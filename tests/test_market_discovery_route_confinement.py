"""Route-level proof that POST /api/discovery/market-discovery cannot read outside the project.

The route is unauthenticated, so ``dataset_paths`` is attacker-controlled. These
tests drive the real FastAPI app through its ASGI interface (no HTTP client
dependency), so routing, body parsing, the handler, the runner, the dataset
loader and response serialisation are all exercised. A canary written to a file
outside the project must never reach the response.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

import pytest

from backend.api import app
from backend.discovery.local_dataset import load_local_evidence_dataset

REPO = Path(__file__).resolve().parents[1]
SEED = "tests/fixtures/market_evidence_seed.json"
CANARY = "zz-canary-route-confinement"
ROUTE = "/api/discovery/market-discovery"


def _dataset(name: str = CANARY) -> str:
    return json.dumps(
        {
            "dataset_id": "route-confinement-dataset",
            "source_name": "local_dataset",
            "provenance": {"type": "synthetic_fixture", "not_real_market_data": True},
            "records": [
                {"entity_type": "category", "entity_name": name, "signal_type": "demand_proxy", "value": 0.5, "weight": 1.0, "confidence": 0.5}
            ],
        }
    )


def _post(payload: dict) -> tuple[int, bytes]:
    body = json.dumps(payload).encode()
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": ROUTE,
        "raw_path": ROUTE.encode(),
        "query_string": b"",
        "headers": [(b"host", b"testserver"), (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    status = next(item["status"] for item in sent if item["type"] == "http.response.start")
    return status, b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")


def _discover(*paths) -> tuple[int, dict, str]:
    status, raw = _post({"dataset_paths": list(paths), "run_validation_services": False})
    return status, json.loads(raw), raw.decode("utf-8", "replace")


@pytest.fixture(autouse=True)
def _from_repo_root(monkeypatch):
    monkeypatch.chdir(REPO)


@pytest.fixture
def inside():
    """A scratch directory inside the project root, removed afterwards."""
    path = Path(tempfile.mkdtemp(dir=REPO, prefix="route_confinement_"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _assert_no_leak(rendered: str, *forbidden: str) -> None:
    assert CANARY not in rendered
    for item in forbidden:
        assert item not in rendered


def test_harness_detects_a_leak_when_the_dataset_is_legitimately_inside_the_root(inside):
    """Positive control: an in-root dataset's content does reach the response."""
    path = inside / "inside.json"
    path.write_text(_dataset(), encoding="utf-8")
    status, body, rendered = _discover(str(path))
    assert status == 200
    assert CANARY in rendered
    assert body["discovery"]["category_opportunities"]


@pytest.mark.parametrize("how", ["absolute", "relative_in_root_fixture", "dot_slash"])
def test_legitimate_in_root_evidence_still_works(how):
    path = {"absolute": str(REPO / SEED), "relative_in_root_fixture": SEED, "dot_slash": "./" + SEED}[how]
    status, body, _ = _discover(path)
    assert status == 200
    assert body["status"] != "blocked"
    assert body["discovery"]["category_opportunities"]


def test_outside_absolute_file_cannot_influence_the_response(tmp_path):
    outside = tmp_path / "outside_dataset.json"
    outside.write_text(_dataset(), encoding="utf-8")
    status, body, rendered = _discover(str(outside))
    assert status == 200
    assert body["status"] == "blocked"
    assert body.get("discovery") in (None, {}) or not body["discovery"].get("category_opportunities")
    _assert_no_leak(rendered, str(tmp_path), str(outside))
    assert any(item.startswith("dataset_failed:") and item.endswith(":ValueError") for item in body["warnings"])


def test_outside_path_gives_no_existence_oracle(tmp_path):
    present = tmp_path / "present.json"
    present.write_text(_dataset(), encoding="utf-8")
    missing = tmp_path / "missing.json"
    _, present_body, _ = _discover(str(present))
    _, missing_body, _ = _discover(str(missing))
    present_types = [item.rsplit(":", 1)[-1] for item in present_body["warnings"]]
    missing_types = [item.rsplit(":", 1)[-1] for item in missing_body["warnings"]]
    assert present_types == missing_types == ["ValueError"]


def test_outside_symlink_inside_the_project_cannot_escape(inside, tmp_path):
    outside = tmp_path / "outside_dataset.json"
    outside.write_text(_dataset(), encoding="utf-8")
    link = inside / "inside_link.json"
    link.symlink_to(outside)
    status, body, rendered = _discover(str(link), str(link.relative_to(REPO)))
    assert status == 200
    assert body["status"] == "blocked"
    _assert_no_leak(rendered, str(tmp_path), str(outside))


def test_outside_directory_symlink_component_cannot_escape(inside, tmp_path):
    (tmp_path / "data.json").write_text(_dataset(), encoding="utf-8")
    (inside / "dir_link").symlink_to(tmp_path, target_is_directory=True)
    status, body, rendered = _discover(str((inside / "dir_link" / "data.json").relative_to(REPO)))
    assert status == 200
    assert body["status"] == "blocked"
    _assert_no_leak(rendered, str(tmp_path))


def test_in_root_symlink_to_an_in_root_file_is_still_allowed(inside):
    link = inside / "seed_link.json"
    link.symlink_to(REPO / SEED)
    status, body, _ = _discover(str(link))
    assert status == 200
    assert body["discovery"]["category_opportunities"]


@pytest.mark.parametrize(
    "path",
    [
        "../outside.json",
        "tests/../../outside.json",
        "tests/fixtures/../../../outside.json",
        "..",
    ],
)
def test_traversal_is_blocked_at_the_route(path):
    status, body, rendered = _discover(path)
    assert status == 200
    assert body["status"] == "blocked"
    _assert_no_leak(rendered)


@pytest.mark.parametrize("path", ["", ".", "tests", "tests/fixtures", "nope\x00evil.json", "x" * 5000, 123, None, ["nested"]])
def test_malformed_paths_fail_closed_without_a_server_error(path):
    status, body, rendered = _discover(path)
    assert status == 200
    assert body["status"] in {"blocked", "error"} or not body["discovery"]["category_opportunities"]
    assert "Traceback" not in rendered
    assert str(REPO) not in rendered


def test_non_list_and_oversized_path_lists_are_blocked():
    for payload in ({"dataset_paths": "tests"}, {"dataset_paths": [SEED] * 11}):
        status, raw = _post(payload)
        assert status == 200
        assert json.loads(raw)["status"] == "blocked"


def test_error_and_blocked_responses_do_not_echo_directories_or_contents(tmp_path):
    outside = tmp_path / "nested" / "dir" / "outside_dataset.json"
    outside.parent.mkdir(parents=True)
    outside.write_text(_dataset(), encoding="utf-8")
    for candidate in (str(outside), str(tmp_path / "nested" / "dir" / "absent.json"), "tests/absent_dataset.json"):
        _, _, rendered = _discover(candidate)
        assert "nested" not in rendered and str(tmp_path) not in rendered and str(REPO) not in rendered
        assert CANARY not in rendered


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX only")
def test_fifo_inside_the_project_is_rejected_without_blocking(inside):
    fifo = inside / "pipe.json"
    os.mkfifo(fifo)
    outcome: list[object] = []

    def attempt() -> None:
        try:
            load_local_evidence_dataset(str(fifo))
        except Exception as exc:  # noqa: BLE001 - only the outcome type matters
            outcome.append(type(exc))

    worker = threading.Thread(target=attempt, daemon=True)
    worker.start()
    worker.join(5)
    assert not worker.is_alive(), "loader blocked on a FIFO"
    assert outcome == [FileNotFoundError]


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
def test_final_component_swapped_to_an_outside_symlink_after_the_check_is_not_followed(inside, tmp_path, monkeypatch):
    """The check/open window: the validated file is replaced by a symlink before it is opened."""
    from backend.discovery import local_dataset

    outside = tmp_path / "outside_dataset.json"
    outside.write_text(_dataset(), encoding="utf-8")
    target = inside / "swapped.json"
    target.write_text(_dataset("harmless"), encoding="utf-8")
    real_confine = local_dataset._confined_dataset_path

    def confine_then_swap(path: str) -> str:
        resolved = real_confine(path)
        os.unlink(resolved)
        os.symlink(outside, resolved)
        return resolved

    monkeypatch.setattr(local_dataset, "_confined_dataset_path", confine_then_swap)
    with pytest.raises(FileNotFoundError) as caught:
        local_dataset.load_local_evidence_dataset(str(target))
    assert CANARY not in str(caught.value)

import json
import os
import tempfile
from pathlib import Path

import pytest

from api.routes.discovery import market_discovery
from backend.discovery.local_dataset import load_local_evidence_dataset, parse_evidence_records

CANARY = "zz-canary-local-dataset-root"
REPO = Path(__file__).resolve().parents[1]


def _symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege unavailable")
        raise


def _canary_payload() -> str:
    return json.dumps({
        "dataset_id": "outside-root-dataset",
        "source_name": "local_dataset",
        "provenance": {"type": "synthetic_fixture", "not_real_market_data": True},
        "records": [{
            "entity_type": "category",
            "entity_name": CANARY,
            "signal_type": "demand_proxy",
            "value": 0.5,
            "weight": 1.0,
            "confidence": 0.5,
        }],
    })


@pytest.fixture(autouse=True)
def _from_repo_root(monkeypatch):
    monkeypatch.chdir(REPO)


def test_seed_fixture_parses():
    path = Path(__file__).resolve().parent / "fixtures" / "market_evidence_seed.json"
    dataset = load_local_evidence_dataset(str(path))
    records = parse_evidence_records(dataset)
    assert records and all(record.provenance.get("not_real_market_data") for record in records)


def test_project_root_itself_is_rejected():
    with pytest.raises(ValueError, match="dataset_path_outside_project_root"):
        load_local_evidence_dataset(str(REPO))
    with pytest.raises(ValueError, match="dataset_path_outside_project_root"):
        load_local_evidence_dataset(".")


def test_in_root_relative_and_absolute_file_loads():
    relative = "tests/fixtures/market_evidence_seed.json"
    absolute = str(REPO / relative)
    for path in (relative, absolute, "./" + relative):
        dataset = load_local_evidence_dataset(path)
        assert dataset["dataset_id"]


def test_missing_provenance_rejected():
    with tempfile.TemporaryDirectory(dir=REPO) as inside:
        path = Path(inside) / "bad.json"
        path.write_text(json.dumps({"dataset_id": "x", "source_name": "local_dataset", "records": []}), encoding="utf-8")
        with pytest.raises(ValueError, match="dataset_provenance_required"):
            load_local_evidence_dataset(str(path.resolve()))


def test_traversal_rejected():
    with pytest.raises(ValueError, match="dataset_path_traversal_blocked"):
        load_local_evidence_dataset("../outside.json")


def test_absolute_outside_root_is_not_read(tmp_path, monkeypatch):
    outside = tmp_path / "outside_dataset.json"
    outside.write_text(_canary_payload(), encoding="utf-8")
    opened: list[str] = []
    real_open = os.open

    def tracking_open(path, flags, *args, dir_fd=None, **kwargs):
        opened.append(os.fspath(path))
        return real_open(path, flags, *args, dir_fd=dir_fd, **kwargs)

    monkeypatch.setattr(os, "open", tracking_open)
    with pytest.raises(ValueError, match="dataset_path_outside_project_root") as caught:
        load_local_evidence_dataset(str(outside))
    assert CANARY not in str(caught.value)
    assert str(outside.resolve()) not in opened
    assert all(not os.path.isabs(item) or os.path.realpath(item) == os.path.realpath(REPO) for item in opened)

    body = market_discovery({"dataset_paths": [str(outside)], "run_validation_services": False})
    rendered = json.dumps(body)
    assert body["status"] == "blocked"
    assert CANARY not in rendered
    assert any(item.endswith(":ValueError") and item.startswith("dataset_failed:") for item in body["warnings"])


def test_sibling_prefix_path_is_rejected(tmp_path, monkeypatch):
    parent = tmp_path / "parents"
    parent.mkdir()
    real_root = parent / "MarketOS"
    sibling = parent / "MarketOS-evil"
    real_root.mkdir()
    sibling.mkdir()
    outside = sibling / "outside_dataset.json"
    outside.write_text(_canary_payload(), encoding="utf-8")
    monkeypatch.chdir(real_root)
    with pytest.raises(ValueError, match="dataset_path_outside_project_root") as caught:
        load_local_evidence_dataset(str(outside))
    assert CANARY not in str(caught.value)


def test_symlink_inside_project_cannot_escape(tmp_path, monkeypatch):
    outside = tmp_path / "outside_dataset.json"
    outside.write_text(_canary_payload(), encoding="utf-8")
    opened: list[str] = []
    real_open = os.open

    def tracking_open(path, flags, *args, dir_fd=None, **kwargs):
        opened.append(os.fspath(path))
        return real_open(path, flags, *args, dir_fd=dir_fd, **kwargs)

    monkeypatch.setattr(os, "open", tracking_open)
    with tempfile.TemporaryDirectory(dir=REPO) as inside:
        link = Path(inside) / "inside_link.json"
        _symlink_or_skip(link, outside)
        with pytest.raises(ValueError, match="dataset_path_outside_project_root") as caught:
            load_local_evidence_dataset(str(link))
        assert CANARY not in str(caught.value)
        assert str(outside.resolve()) not in opened

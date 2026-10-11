"""Mounted discovery import routes. No live providers. No httpx dependency."""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

from fastapi import FastAPI

from api.routes.discovery import router

app = FastAPI()
app.include_router(router)

FIXTURE = "tests/fixtures/evidence_imports/supplier_catalog_sample.csv"
MARKER = "zz-surface-canary-1844"
OPEN_MARKER = "zz-opened-canary-991"


def _call(method: str, path: str, payload: dict | None = None) -> tuple[int, dict, str]:
    body = b"" if payload is None else json.dumps(payload).encode()
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    headers = [(b"host", b"testserver")]
    if payload is not None:
        headers.extend([(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())])
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    status = next(item["status"] for item in sent if item["type"] == "http.response.start")
    raw = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
    text = raw.decode()
    return status, json.loads(text), text


def test_import_api():
    path = str(Path(__file__).parent / "fixtures" / "evidence_imports" / "supplier_catalog_sample.csv")
    status, body, _text = _call(
        "POST",
        "/api/discovery/import-evidence",
        {"input_path": path, "parser_type": "supplier_catalog_csv", "source_name": "supplier"},
    )
    assert status == 200 and body["import_job"]["status"] == "completed"
    quality_status, _quality, _raw = _call("GET", "/api/discovery/source-quality")
    assert quality_status == 200
    blocked_status, blocked, _blocked_text = _call(
        "POST",
        "/api/discovery/import-evidence",
        {"input_path": path, "parser_type": "unknown"},
    )
    assert blocked_status == 200 and blocked["status"] == "blocked"


def _assert_blocked(path: str, reason: str, *hidden: str, route: str = "/api/discovery/import-evidence", payload: dict | None = None) -> None:
    status, body, text = _call("POST", route, payload or {"input_path": path, "parser_type": "supplier_catalog_csv", "source_name": "supplier"})
    assert status == 200
    assert body["status"] == "blocked"
    assert body["blocked_reasons"] == [reason]
    assert "records" not in body
    for item in hidden:
        assert item not in text


def test_import_route_rejects_paths_outside_the_import_surface(tmp_path: Path):
    root = Path.cwd().resolve()
    inside = root / "unintended_surface.csv"
    sibling_root = Path(str(root) + "-sib")
    sibling = sibling_root / "row.csv"
    outside = tmp_path / "outside.csv"
    row = f"category,product,supplier_cost\n{MARKER},item,1\n"
    link = root / "tests" / "fixtures" / "evidence_imports" / "outside-link.csv"
    try:
        inside.write_text(row, encoding="utf-8")
        sibling_root.mkdir(exist_ok=True)
        sibling.write_text(row, encoding="utf-8")
        outside.write_text(row, encoding="utf-8")
        link.symlink_to(outside)

        allowed_status, allowed, allowed_text = _call(
            "POST",
            "/api/discovery/import-evidence",
            {"input_path": FIXTURE, "parser_type": "supplier_catalog_csv", "source_name": "supplier"},
        )
        assert allowed_status == 200
        assert allowed["import_job"]["status"] == "completed"
        assert allowed["import_job"]["records_imported"] > 0
        assert MARKER not in allowed_text
        assert ".opened-" not in allowed_text
        assert "unintended_surface.csv" not in allowed_text

        hidden = (MARKER, inside.name, sibling.name, outside.name, str(outside), str(sibling))
        _assert_blocked(inside.name, "import_path_outside_import_surface", *hidden)
        _assert_blocked(str(sibling), "import_path_outside_import_surface", *hidden)
        _assert_blocked(str(outside), "import_path_outside_import_surface", *hidden)
        _assert_blocked(
            "tests/fixtures/../../unintended_surface.csv",
            "import_path_traversal_blocked",
            *hidden,
        )
        _assert_blocked(
            "tests/fixtures/evidence_imports/missing-no-such.csv",
            "import_path_unavailable",
            "missing-no-such.csv",
            *hidden,
        )
        _assert_blocked(str(link), "import_path_outside_import_surface", *hidden)
        for route in ("/api/discovery/import-and-run", "/api/discovery/import-refine-compare"):
            _assert_blocked(
                inside.name,
                "import_path_outside_import_surface",
                *hidden,
                route=route,
                payload={"imports": [{"input_path": inside.name, "parser_type": "supplier_catalog_csv"}]},
            )
    finally:
        inside.unlink(missing_ok=True)
        link.unlink(missing_ok=True)
        sibling.unlink(missing_ok=True)
        sibling_root.rmdir()


def test_opened_file_stays_confined_when_the_final_component_is_swapped():
    """A resolve-only check can pass, then the loader follows a swapped symlink.

    The canary lives at the repo root, which the CSV loader still allows. The
    route must return bytes from the no-follow open, never that file.
    """
    root = Path.cwd().resolve()
    canary = root / "unintended_open_surface.csv"
    raced = root / "tests" / "fixtures" / "evidence_imports" / "race-open.csv"
    canary.write_text(f"category,product,supplier_cost\n{OPEN_MARKER},item,1\n", encoding="utf-8")
    raced.write_text("category,product,supplier_cost\nhome fitness,recovery accessory,1\n", encoding="utf-8")
    stop = threading.Event()

    def swap() -> None:
        while not stop.is_set():
            try:
                raced.unlink()
            except FileNotFoundError:
                pass
            try:
                raced.symlink_to(canary)
            except FileExistsError:
                pass
            try:
                if raced.is_symlink():
                    raced.unlink()
                raced.write_text(
                    "category,product,supplier_cost\nhome fitness,recovery accessory,1\n",
                    encoding="utf-8",
                )
            except OSError:
                continue

    worker = threading.Thread(target=swap, daemon=True)
    worker.start()
    try:
        for _ in range(30):
            _status, body, text = _call(
                "POST",
                "/api/discovery/import-evidence",
                {"input_path": "tests/fixtures/evidence_imports/race-open.csv", "parser_type": "supplier_catalog_csv", "source_name": "supplier"},
            )
            assert OPEN_MARKER not in text
            assert canary.name not in text
            assert str(canary) not in text
            assert ".opened-" not in text
            if body.get("status") == "blocked":
                assert body["blocked_reasons"] == ["import_path_outside_import_surface"] or body["blocked_reasons"] == ["import_path_unavailable"]
            else:
                assert body["import_job"]["status"] == "completed"
    finally:
        stop.set()
        worker.join(timeout=2)
        if raced.is_symlink() or raced.exists():
            raced.unlink(missing_ok=True)
        canary.unlink(missing_ok=True)

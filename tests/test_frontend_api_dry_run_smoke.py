"""Deterministic dry-run smoke contract for the frontend/API boundary.

Proves the existing FastAPI + React/Vite boundary is alive and fail-closed
without creating a second API, WebSocket protocol, quality gate, event store,
or orchestration loop. No credentials, network providers, payments, ads,
orders, browser automation, or customer messages are activated.
"""
from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
FAKE_SECRET = "sk-live-SMOKE-TEST-SECRET-TOKEN-9f3a2c1b"
FORBIDDEN_ACTIVATION = (
    "allow_public_network",
    "MARKETOS_PUBLIC_COMMERCE_RUNS",
    "puppeteer",
    "shopify.Order.create",
    "openai.OpenAI(",
)


def _npm_executable() -> str:
    """Resolve npm's native Windows launcher for shell-free subprocess calls."""
    if shutil.which("npm.cmd"):
        return "npm.cmd"
    return "npm"


class InertThread:
    """Prevent FastAPI lifespan from starting real background runners."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def start(self):
        return None


def _install_inert_runtime(monkeypatch):
    import backend.api as api

    monkeypatch.setattr(api.threading, "Thread", InertThread)
    monkeypatch.setattr("backend.core.serializer.load", lambda _path: None)
    monkeypatch.setattr("backend.core.serializer.save", lambda *_args: None)
    monkeypatch.setattr(api, "_start_runtime_services", lambda: None)
    monkeypatch.setattr(api, "_stop_runtime_services", lambda: None)
    return api


def _assert_no_secret(payload) -> None:
    blob = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    lowered = blob.lower()
    assert FAKE_SECRET not in blob
    assert "sk-live-smoke-test-secret-token" not in lowered
    assert "bearer " not in lowered
    assert "authorization" not in lowered or "[redacted]" in lowered


@pytest.fixture
def smoke_client(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_SECRET)
    monkeypatch.setenv("CJ_API_KEY", FAKE_SECRET)
    monkeypatch.setenv("CJ_EMAIL", "operator@example.invalid")
    monkeypatch.delenv("MARKETOS_EVENT_READ_JSONL_PATH", raising=False)
    monkeypatch.delenv("MARKETOS_PUBLIC_COMMERCE_RUNS", raising=False)
    monkeypatch.delenv("MEDUSA_REQUIRED_FOR_READY", raising=False)
    api = _install_inert_runtime(monkeypatch)
    from fastapi.testclient import TestClient

    with TestClient(api.app) as client:
        yield client


def test_health_endpoint_is_alive_and_secret_free(smoke_client):
    response = smoke_client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "mvp" in payload
    _assert_no_secret(payload)
    _assert_no_secret(response.text)


def test_ready_endpoint_distinguishes_runtime_initialization(smoke_client):
    response = smoke_client.get("/ready")
    assert response.status_code in {200, 503}
    payload = response.json()
    assert "ready" in payload
    assert "mvp" in payload
    if response.status_code == 200:
        assert payload["ready"] is True
    else:
        assert payload["ready"] is False
        assert payload.get("reason")
    _assert_no_secret(payload)


def test_phase1_readiness_is_read_only(smoke_client):
    response = smoke_client.get("/api/phase1/readiness")
    assert response.status_code == 200
    payload = response.json()
    assert payload["read_only"] is True
    assert payload["mutated"] is False
    assert payload["network_calls"] is False
    _assert_no_secret(payload)


def test_canonical_events_readiness_is_read_only(smoke_client):
    response = smoke_client.get("/api/events/readiness")
    assert response.status_code == 200
    payload = response.json()
    assert payload["read_only"] is True
    assert payload["mutated"] is False
    _assert_no_secret(payload)


def test_canonical_events_timeline_read_is_safe_without_credentials(smoke_client):
    response = smoke_client.get("/api/events/timeline", params={"limit": 5})
    assert response.status_code == 200
    payload = response.json()
    assert "events" in payload
    assert payload.get("read_only") is True or isinstance(payload["events"], list)
    _assert_no_secret(payload)


def test_malformed_event_source_is_rejected(smoke_client):
    response = smoke_client.get("/api/events", params={"source": "live_shopify"})
    assert response.status_code == 400
    _assert_no_secret(response.text)


def test_malformed_query_types_are_rejected_with_safe_errors(smoke_client):
    response = smoke_client.get("/api/events", params={"limit": "not-a-number"})
    assert response.status_code == 422
    _assert_no_secret(response.json())


def test_read_only_readiness_rejects_mutation_methods(smoke_client):
    response = smoke_client.post("/api/phase1/readiness", json={"confirm_live": True})
    assert response.status_code in {405, 422}
    _assert_no_secret(response.text)


def test_missing_cockpit_action_is_safe_not_found(smoke_client):
    response = smoke_client.get("/api/cockpit/actions/missing-smoke-action")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "not_found"
    assert payload["action_id"] == "missing-smoke-action"
    _assert_no_secret(payload)


def test_dry_run_commerce_cycle_remains_offline(smoke_client):
    response = smoke_client.post(
        "/commerce/cycle",
        json={
            "signals": [{"id": "s1", "product": "Widget", "score": 0.9, "engagement": 0.8, "velocity": 0.7}],
            "products": {"Widget": {"product_id": "widget", "name": "Widget", "selling_price": 40}},
            "offers": {},
            "top_k": 1,
            "budget": 10,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    _assert_no_secret(payload)


def test_websocket_replay_schema_boundary(smoke_client, monkeypatch):
    envelope = {
        "type": "runtime.snapshot",
        "event_id": "smoke-replay-1",
        "sequence_id": 1,
        "replay_hash": "smokehash",
        "source": "replay_store",
        "ts": 1.0,
        "payload": {"capital": 0, "phase": "RESEARCH"},
    }

    async def _bounded_event_stream(ws):
        await ws.accept()
        await ws.send_text(json.dumps(envelope))

    monkeypatch.setattr("backend.api._ws_event_stream", _bounded_event_stream)
    with smoke_client.websocket_connect("/ws") as ws:
        raw = ws.receive_text()
        ws.send_text("this is not json {{{")
        ws.close()
    payload = json.loads(raw)
    assert payload["type"] == "runtime.snapshot"
    assert payload["sequence_id"] == 1
    _assert_no_secret(payload)


def test_smoke_client_tears_down_without_leaving_listeners(smoke_client):
    assert smoke_client.get("/health").status_code == 200
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.2)
    try:
        assert sock.connect_ex(("127.0.0.1", 8765)) != 0
    finally:
        sock.close()


def test_frontend_package_contract_and_shared_api_base():
    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["typecheck"] == "tsc --noEmit"
    assert package["scripts"]["test"] == "node --test tests/*.test.mjs"
    assert "lint" not in package["scripts"]
    api_base = (FRONTEND / "src/lib/apiBase.ts").read_text(encoding="utf-8")
    assert "VITE_API_BASE_URL" in api_base
    assert "VITE_API_URL" in api_base


def test_frontend_lint_script_is_unavailable_by_package_contract():
    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    assert "lint" not in package["scripts"]


def test_frontend_build_when_dependencies_installed():
    node_modules = FRONTEND / "node_modules"
    if not node_modules.is_dir():
        pytest.skip("unavailable: frontend/node_modules missing; no npm install attempted in smoke")
    build = subprocess.run(
        [_npm_executable(), "run", "build"],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert build.returncode == 0, build.stdout + "\n" + build.stderr


def test_smoke_suite_does_not_activate_live_side_effects():
    text = Path(__file__).read_text(encoding="utf-8")
    assert "rejects_mutation_methods" in text
    assert ('"npm", "' + "install" + '"') not in text
    pattern = re.compile("|".join(re.escape(token) for token in FORBIDDEN_ACTIVATION))
    for path in (
        ROOT / "docs/FRONTEND_API_DRY_RUN_SMOKE_RUNBOOK.md",
        ROOT / "docs/FRONTEND_API_DRY_RUN_SAFETY_CONTRACT.md",
        ROOT / "docs/plans/active/plan-marketos-frontend-api-boundary-v2.md",
    ):
        if path.exists():
            assert pattern.findall(path.read_text(encoding="utf-8")) == [], path

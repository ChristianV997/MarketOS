"""Deterministic dry-run smoke contract for the frontend/API boundary.

Proves the existing FastAPI + React/Vite boundary is alive and fail-closed
without creating a second API, WebSocket protocol, quality gate, event store,
or orchestration loop. No credentials, network providers, payments, ads,
orders, browser automation, or customer messages are activated.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
CANONICAL_FRONTEND_PATHS = (
    FRONTEND / "package.json",
    FRONTEND / "src" / "hooks" / "useWebSocket.ts",
    FRONTEND / "src" / "hooks" / "useMetrics.ts",
    FRONTEND / "src" / "lib" / "api.ts",
    FRONTEND / "src" / "lib" / "canonicalEventsApi.ts",
    FRONTEND / "src" / "components" / "PhaseHeader.tsx",
)
CANONICAL_API_PATHS = (
    ROOT / "api" / "routes" / "health.py",
    ROOT / "api" / "routes" / "canonical_events.py",
    ROOT / "api" / "routes" / "phase1_readiness.py",
    ROOT / "api" / "routes" / "execution_cockpit.py",
    ROOT / "api" / "ws.py",
    ROOT / "backend" / "ws" / "stream.py",
    ROOT / "backend" / "api.py",
)
FORBIDDEN_ACTIVATION = (
    "allow_public_network",
    "MARKETOS_PUBLIC_COMMERCE_RUNS",
    "puppeteer",
    "shopify.Order.create",
    "openai.OpenAI(",
)
FAKE_SECRET = "sk-live-SMOKE-TEST-SECRET-TOKEN-9f3a2c1b"


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


def test_ready_endpoint_is_a_safe_readiness_boundary(smoke_client):
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


def test_representative_read_only_phase1_readiness_contract(smoke_client):
    response = smoke_client.get("/api/phase1/readiness")
    assert response.status_code == 200
    payload = response.json()
    assert payload["read_only"] is True
    assert payload["mutated"] is False
    assert payload["network_calls"] is False
    assert payload["next_best_action"]
    _assert_no_secret(payload)


def test_representative_read_only_event_readiness_contract(smoke_client):
    response = smoke_client.get("/api/events/readiness")
    assert response.status_code == 200
    payload = response.json()
    assert payload["read_only"] is True
    assert payload["mutated"] is False
    assert payload["jsonl_path_configured"] is False
    _assert_no_secret(payload)


def test_malformed_event_source_is_rejected(smoke_client):
    response = smoke_client.get("/api/events", params={"source": "live_shopify"})
    assert response.status_code == 400
    _assert_no_secret(response.text)
    assert "live_shopify" in response.text or "source must be" in response.text.lower()


def test_malformed_query_types_are_rejected_with_safe_errors(smoke_client):
    response = smoke_client.get("/api/events", params={"limit": "not-a-number"})
    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]
    _assert_no_secret(payload)


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
    monkeypatch.setattr(
        "backend.ws.stream.ws_stream._load_replay_payloads",
        lambda _broker: [json.dumps(envelope)],
    )
    with smoke_client.websocket_connect("/ws") as ws:
        raw = ws.receive_text()
        ws.send_text("this is not json {{{")
        ws.close()
    payload = json.loads(raw)
    assert payload["type"] == "runtime.snapshot"
    assert payload["sequence_id"] == 1
    assert payload["replay_hash"] == "smokehash"
    _assert_no_secret(payload)


def test_frontend_package_manager_contract_is_documented():
    package = json.loads(FRONTEND.joinpath("package.json").read_text(encoding="utf-8"))
    assert package["name"] == "marketos-dashboard"
    assert package["scripts"]["build"] == "tsc && vite build"
    assert package["scripts"]["dev"] == "vite"
    assert "lint" not in package["scripts"]
    assert "test" not in package["scripts"]


def test_frontend_unavailable_backend_behavior_is_encoded():
    header = FRONTEND.joinpath("src/components/PhaseHeader.tsx").read_text(encoding="utf-8")
    ws_hook = FRONTEND.joinpath("src/hooks/useWebSocket.ts").read_text(encoding="utf-8")
    api_client = FRONTEND.joinpath("src/lib/api.ts").read_text(encoding="utf-8")
    events_client = FRONTEND.joinpath("src/lib/canonicalEventsApi.ts").read_text(encoding="utf-8")

    assert "reconnecting" in header
    assert "connected ? \"live\" : \"reconnecting\"" in header
    assert "malformed frames are ignored" in ws_hook
    assert "WS_URL" in ws_hook and "/ws" in ws_hook
    assert "RECONNECT_MS" in ws_hook
    assert "if (!r.ok) throw new Error(`${r.status} ${path}`)" in api_client
    assert "Unable to load operator events" in events_client
    assert "method: \"GET\"" in events_client


def test_frontend_package_checks_report_unavailable_without_faking():
    """Do not claim npm/tsc/vite success when node_modules are absent."""
    node_modules = FRONTEND / "node_modules"
    typescript = node_modules / "typescript"
    vite = node_modules / "vite"
    if not node_modules.is_dir() or not typescript.exists() or not vite.exists():
        pytest.skip(
            "unavailable: frontend Node dependencies are not installed "
            f"(missing {node_modules if not node_modules.is_dir() else 'typescript/vite'}); "
            "no npm install was attempted because this smoke is offline/fail-closed"
        )
    build = subprocess.run(
        ["npm", "run", "build"],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert build.returncode == 0, build.stdout + "\n" + build.stderr


def test_frontend_lint_script_is_unavailable_by_package_contract():
    package = json.loads(FRONTEND.joinpath("package.json").read_text(encoding="utf-8"))
    assert "lint" not in package["scripts"]


def test_smoke_suite_does_not_activate_live_side_effects():
    text = Path(__file__).read_text(encoding="utf-8")
    assert "rejects_mutation_methods" in text
    assert "npm install" not in text
    assert "shopify.Order.create" not in text.split("FORBIDDEN_ACTIVATION", 1)[0]


def test_canonical_owners_remain_the_only_boundary_files():
    for path in (*CANONICAL_FRONTEND_PATHS, *CANONICAL_API_PATHS):
        assert path.is_file(), path
    ws = (ROOT / "api" / "ws.py").read_text(encoding="utf-8")
    assert "backend.ws.stream" in ws
    health = (ROOT / "api" / "routes" / "health.py").read_text(encoding="utf-8")
    assert '@router.get("/health")' in health
    assert '@router.get("/ready")' in health


def test_changed_docs_and_tests_stay_offline():
    scanned = [
        ROOT / "docs" / "FRONTEND_API_DRY_RUN_SMOKE_RUNBOOK.md",
        ROOT / "docs" / "FRONTEND_API_DRY_RUN_SAFETY_CONTRACT.md",
        ROOT / "docs" / "plans" / "active" / "plan-marketos-frontend-api-dry-run-smoke-v1.md",
    ]
    pattern = re.compile("|".join(re.escape(token) for token in FORBIDDEN_ACTIVATION))
    for path in scanned:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        assert "api_key =" not in text.lower()
        assert pattern.findall(text) == [], path

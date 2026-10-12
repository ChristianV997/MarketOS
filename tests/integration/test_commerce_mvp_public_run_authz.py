"""POST /api/commerce-mvp/public-run is operator-only and writes only to the bound workspace.

The public network runner is replaced with a recorder, so no request leaves the process. The JSONL write target is
redirected into ``tmp_path``. Denied calls must never reach the runner or any writer.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import commerce_mvp
from backend.contracts.events import Event
from backend.identity.errors import IdentityError
from backend.identity.http import get_token_verifier, get_workspace_repository
from backend.identity.principal import VerifiedPrincipal
from backend.identity.roles import CLIENT_VIEWER, INTERNAL_OPERATOR
from backend.identity.workspaces import WorkspaceAccess
from backend.security.rate_limit import reset_rate_limits_for_tests

ISSUER = "https://clerk.test"
BOUND = "ws_run_bound_synthetic"
OTHER = "ws_run_other_synthetic"
BODY = {"query": "portable espresso maker", "allow_public_network": True}
OPERATOR = {"Authorization": "Bearer tok-operator"}
VIEWER = {"Authorization": "Bearer tok-viewer"}
MEMBERSHIPS = {
    "user_operator": [(BOUND, "internal", INTERNAL_OPERATOR)],
    "user_viewer": [(BOUND, "internal", CLIENT_VIEWER)],
}
TOKENS = {"tok-operator": "user_operator", "tok-viewer": "user_viewer"}


class FakeVerifier:
    def verify(self, token: str) -> VerifiedPrincipal:
        try:
            return VerifiedPrincipal(ISSUER, TOKENS[token])
        except KeyError:
            raise IdentityError() from None


class FakeRepo:
    def memberships_for(self, principal: VerifiedPrincipal) -> list[WorkspaceAccess]:
        return [
            WorkspaceAccess(ISSUER, principal.subject, ws, kind, "synthetic", role)
            for ws, kind, role in MEMBERSHIPS.get(principal.subject, [])
        ]


def _app(*, identity: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(commerce_mvp.router)
    if identity:
        app.dependency_overrides[get_token_verifier] = lambda: FakeVerifier()
        app.dependency_overrides[get_workspace_repository] = lambda: FakeRepo()
    return app


@pytest.fixture(autouse=True)
def _isolated_rate_limits(monkeypatch):
    monkeypatch.setenv("MARKETOS_EVENT_READ_RATE_LIMIT", "100000")
    monkeypatch.setenv("MARKETOS_PUBLIC_RUN_RATE_LIMIT", "100000")
    reset_rate_limits_for_tests()
    yield
    reset_rate_limits_for_tests()


@pytest.fixture
def runs(monkeypatch) -> list[dict]:
    """Record every network-runner call; the stub returns one synthetic event in the workspace it was given."""
    calls: list[dict] = []

    def fake_runner(**kwargs):
        calls.append(kwargs)
        event = Event(
            "evt_run_1", kwargs["workspace_id"], "commerce", "run_1", "synthetic_probe", 1, 1.0, source="synthetic_test"
        )
        return SimpleNamespace(
            status="succeeded",
            events=(event,),
            to_dict=lambda: {"public_source_status": "succeeded", "warnings": [], "blockers": []},
        )

    monkeypatch.setenv("MARKETOS_PUBLIC_COMMERCE_RUNS", "1")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setattr(commerce_mvp, "run_commerce_mvp_from_public_rss", fake_runner)
    return calls


@pytest.fixture
def artifacts(monkeypatch, tmp_path: Path) -> Path:
    root = (tmp_path / "artifacts").resolve()
    root.mkdir()
    monkeypatch.setattr(commerce_mvp, "ARTIFACTS", root)
    return root


def test_anonymous_run_is_refused_before_any_network_or_write(runs, artifacts, monkeypatch):
    monkeypatch.setenv("MARKETOS_EVENT_WRITE_JSONL_PATH", str(artifacts / "write.jsonl"))

    response = TestClient(_app()).post("/api/commerce-mvp/public-run", json={**BODY, "event_target": "jsonl"})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] in {"missing_credentials", "invalid_credentials"}
    assert runs == []
    assert not (artifacts / "write.jsonl").exists()


def test_unconfigured_identity_provider_fails_closed(runs):
    response = TestClient(_app(identity=False)).post("/api/commerce-mvp/public-run", json=BODY, headers=OPERATOR)

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "identity_provider_unavailable"}}
    assert runs == []


def test_client_viewer_run_is_denied(runs):
    response = TestClient(_app()).post("/api/commerce-mvp/public-run", json=BODY, headers=VIEWER)

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "role_not_authorized"}}
    assert runs == []


def test_foreign_workspace_in_body_is_refused_before_the_run(runs, artifacts, monkeypatch):
    monkeypatch.setenv("MARKETOS_EVENT_WRITE_JSONL_PATH", str(artifacts / "write.jsonl"))

    response = TestClient(_app()).post(
        "/api/commerce-mvp/public-run",
        json={**BODY, "workspace_id": OTHER, "event_target": "jsonl"},
        headers=OPERATOR,
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "workspace_not_authorized"}}
    assert OTHER not in response.text
    assert runs == []
    assert not (artifacts / "write.jsonl").exists()


def test_omitted_workspace_runs_in_the_bound_workspace(runs):
    response = TestClient(_app()).post("/api/commerce-mvp/public-run", json=BODY, headers=OPERATOR)

    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    assert [call["workspace_id"] for call in runs] == [BOUND]


def test_matching_workspace_in_body_is_accepted(runs):
    response = TestClient(_app()).post(
        "/api/commerce-mvp/public-run", json={**BODY, "workspace_id": BOUND}, headers=OPERATOR
    )

    assert response.status_code == 200
    assert [call["workspace_id"] for call in runs] == [BOUND]


def test_operator_jsonl_write_contains_only_the_bound_workspace(runs, artifacts, monkeypatch):
    target = artifacts / "write.jsonl"
    monkeypatch.setenv("MARKETOS_EVENT_WRITE_JSONL_PATH", str(target))

    response = TestClient(_app()).post(
        "/api/commerce-mvp/public-run", json={**BODY, "event_target": "jsonl"}, headers=OPERATOR
    )

    assert response.status_code == 200
    rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows and {row["workspace_id"] for row in rows} == {BOUND}
    assert OTHER not in target.read_text(encoding="utf-8")


def test_request_model_is_not_mutated_by_the_binding(runs):
    model = commerce_mvp.PublicCommerceRunRequest(query="portable espresso maker", allow_public_network=True)
    assert "workspace_id" not in model.model_fields_set

    commerce_mvp.public_run(
        model, access=WorkspaceAccess(ISSUER, "user_operator", BOUND, "internal", "synthetic", INTERNAL_OPERATOR)
    )

    assert model.workspace_id == "commerce-mvp-public"
    assert "workspace_id" not in model.model_fields_set


def test_denied_runs_are_throttled_before_identity(runs, monkeypatch):
    monkeypatch.setenv("MARKETOS_EVENT_READ_RATE_LIMIT", "2")
    reset_rate_limits_for_tests()
    verified: list[str] = []

    class CountingVerifier(FakeVerifier):
        def verify(self, token: str) -> VerifiedPrincipal:
            verified.append(token)
            return super().verify(token)

    app = _app(identity=False)
    app.dependency_overrides[get_token_verifier] = lambda: CountingVerifier()
    app.dependency_overrides[get_workspace_repository] = lambda: FakeRepo()
    client = TestClient(app)

    statuses = [client.post("/api/commerce-mvp/public-run", json=BODY, headers=VIEWER).status_code for _ in range(2)]
    throttled = client.post("/api/commerce-mvp/public-run", json=BODY, headers=VIEWER)

    assert statuses == [403, 403]
    assert throttled.status_code == 429
    assert throttled.headers.get("retry-after")
    assert verified == ["tok-viewer", "tok-viewer"]
    assert runs == []


def test_explicit_default_workspace_is_refused_for_an_operator_bound_elsewhere(runs):
    """Legacy callers that spell out the default workspace are refused once the operator is bound to another one."""
    response = TestClient(_app()).post(
        "/api/commerce-mvp/public-run",
        json={**BODY, "workspace_id": "commerce-mvp-public"},
        headers=OPERATOR,
    )

    assert response.status_code == 403
    assert runs == []


def test_supabase_staging_write_carries_only_the_bound_workspace(runs, monkeypatch):
    written: list = []

    class RecordingRepository:
        def append_many(self, events):
            written.extend(events)

    monkeypatch.setattr(commerce_mvp, "explain_supabase_staging_readiness", lambda: {"configured": True})
    monkeypatch.setattr(commerce_mvp, "build_supabase_staging_repository", lambda: RecordingRepository())
    monkeypatch.setattr(commerce_mvp, "validate_events_for_supabase", lambda events: {"valid": True})

    response = TestClient(_app()).post(
        "/api/commerce-mvp/public-run",
        json={**BODY, "event_target": "supabase_staging"},
        headers=OPERATOR,
    )

    assert response.status_code == 200
    assert response.json()["write_targets"] == ["supabase_staging"]
    assert written and {event.workspace_id for event in written} == {BOUND}

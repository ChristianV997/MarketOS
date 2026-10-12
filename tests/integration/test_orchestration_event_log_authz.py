"""The workflow event-log reads are operator-only; the rate-mesh health view stays open.

The event store is replaced by an in-memory recorder, so nothing is read from or written to disk.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import orchestration
from backend.identity.errors import IdentityError
from backend.identity.http import get_token_verifier, get_workspace_repository
from backend.identity.principal import VerifiedPrincipal
from backend.identity.roles import CLIENT_VIEWER, INTERNAL_OPERATOR
from backend.identity.workspaces import WorkspaceAccess
from backend.security.rate_limit import reset_rate_limits_for_tests

ISSUER = "https://clerk.test"
BOUND = "ws_flow_bound_synthetic"
LOG_PATHS = [
    "/orchestration/workflows",
    "/orchestration/workflows/incomplete",
    "/orchestration/workflows/wf_synthetic_1",
]
OPERATOR = {"Authorization": "Bearer tok-operator"}
VIEWER = {"Authorization": "Bearer tok-viewer"}
MEMBERSHIPS = {
    "user_operator": [(BOUND, "internal", INTERNAL_OPERATOR)],
    "user_viewer": [(BOUND, "internal", CLIENT_VIEWER)],
}
TOKENS = {"tok-operator": "user_operator", "tok-viewer": "user_viewer"}
RECORD = {"workflow_id": "wf_synthetic_1", "event": "synthetic_step", "data": {"workspace_id": BOUND}}


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
    app.include_router(orchestration.router)
    if identity:
        app.dependency_overrides[get_token_verifier] = lambda: FakeVerifier()
        app.dependency_overrides[get_workspace_repository] = lambda: FakeRepo()
    return app


@pytest.fixture(autouse=True)
def _isolated_rate_limits(monkeypatch):
    monkeypatch.setenv("MARKETOS_EVENT_READ_RATE_LIMIT", "100000")
    reset_rate_limits_for_tests()
    yield
    reset_rate_limits_for_tests()


@pytest.fixture
def store(monkeypatch) -> list[str]:
    """Replace the workflow event store's read methods with recorders."""
    from backend.orchestration.event_store import event_store

    touched: list[str] = []

    def record(name, value):
        def read(*args, **kwargs):
            touched.append(name)
            return value

        return read

    monkeypatch.setattr(event_store, "tail", record("tail", [RECORD]))
    monkeypatch.setattr(event_store, "incomplete_workflows", record("incomplete", [{"workflow_id": "wf_synthetic_1"}]))
    monkeypatch.setattr(event_store, "events_for", record("events_for", [RECORD]))
    return touched


@pytest.mark.parametrize("path", LOG_PATHS)
def test_anonymous_workflow_log_reads_are_refused_before_any_read(store, path):
    response = TestClient(_app()).get(path)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] in {"missing_credentials", "invalid_credentials"}
    assert store == []


@pytest.mark.parametrize("path", LOG_PATHS)
def test_unconfigured_identity_provider_fails_closed(store, path):
    response = TestClient(_app(identity=False)).get(path, headers=OPERATOR)

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "identity_provider_unavailable"}}
    assert store == []


@pytest.mark.parametrize("path", LOG_PATHS)
def test_client_viewer_is_denied_without_reading_the_log(store, path):
    response = TestClient(_app()).get(path, headers=VIEWER)

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "role_not_authorized"}}
    assert store == []


def test_operator_reads_the_workflow_log(store):
    client = TestClient(_app())

    assert client.get("/orchestration/workflows", headers=OPERATOR).json() == {"events": [RECORD]}
    assert client.get("/orchestration/workflows/incomplete", headers=OPERATOR).json() == {
        "incomplete": [{"workflow_id": "wf_synthetic_1"}]
    }
    assert (
        client.get("/orchestration/workflows/wf_synthetic_1", headers=OPERATOR).json()["workflow_id"]
        == "wf_synthetic_1"
    )
    assert store == ["tail", "incomplete", "events_for"]


def test_rate_mesh_health_stays_open_and_reads_no_event_log(store):
    response = TestClient(_app()).get("/orchestration/health")

    assert response.status_code == 200
    assert store == []


def test_denied_log_reads_are_throttled_before_identity(store, monkeypatch):
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

    statuses = [client.get("/orchestration/workflows", headers=VIEWER).status_code for _ in range(2)]
    throttled = client.get("/orchestration/workflows", headers=VIEWER)

    assert statuses == [403, 403]
    assert throttled.status_code == 429
    assert verified == ["tok-viewer", "tok-viewer"]
    assert store == []

"""The workflow event-log reads fail closed for every workspace; the rate-mesh health view stays open.

The event store is replaced by in-memory recorders seeded with two synthetic workspaces, so nothing is read from or
written to disk. The store cannot bind its records to a workspace, so no read may return any of them to any caller.
"""

from __future__ import annotations

import os
import tempfile

# Fresh HOME and config path before any backend module is imported. The prior values are restored once the imports
# have run, so no other test in the session inherits this isolation.
_ISOLATED_HOME = tempfile.mkdtemp(prefix="marketos-orchestration-authz-")
_PRIOR_ENV = {key: os.environ.get(key) for key in ("HOME", "USERPROFILE", "MARKETOS_CONFIG_PATH")}
os.environ.update(
    HOME=_ISOLATED_HOME,
    USERPROFILE=_ISOLATED_HOME,
    MARKETOS_CONFIG_PATH=os.path.join(_ISOLATED_HOME, "credentials.json"),
)

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api.routes import orchestration  # noqa: E402
from backend.identity.errors import IdentityError  # noqa: E402
from backend.identity.http import get_token_verifier, get_workspace_repository  # noqa: E402
from backend.identity.principal import VerifiedPrincipal  # noqa: E402
from backend.identity.roles import CLIENT_VIEWER, INTERNAL_OPERATOR  # noqa: E402
from backend.identity.workspaces import WorkspaceAccess  # noqa: E402
from backend.security.rate_limit import reset_rate_limits_for_tests  # noqa: E402

for _key, _value in _PRIOR_ENV.items():
    if _value is None:
        os.environ.pop(_key, None)
    else:
        os.environ[_key] = _value

ISSUER = "https://clerk.test"
WS_A = "ws_flow_bound_synthetic"
WS_B = "ws_flow_other_synthetic"
LOG_PATHS = [
    "/orchestration/workflows",
    "/orchestration/workflows/incomplete",
    "/orchestration/workflows/wf_synthetic_a",
    "/orchestration/workflows/wf_synthetic_b",
]
OPERATOR_A = {"Authorization": "Bearer tok-operator-a"}
OPERATOR_B = {"Authorization": "Bearer tok-operator-b"}
VIEWER_A = {"Authorization": "Bearer tok-viewer-a"}
MEMBERSHIPS = {
    "user_operator_a": [(WS_A, "internal", INTERNAL_OPERATOR)],
    "user_operator_b": [(WS_B, "internal", INTERNAL_OPERATOR)],
    "user_viewer_a": [(WS_A, "internal", CLIENT_VIEWER)],
}
TOKENS = {"tok-operator-a": "user_operator_a", "tok-operator-b": "user_operator_b", "tok-viewer-a": "user_viewer_a"}
# Records carry their workspace only by convention, as the store does today. The route must still refuse to read them.
RECORDS = [
    {"workflow_id": "wf_synthetic_a", "event": "synthetic_step", "data": {"workspace_id": WS_A}},
    {"workflow_id": "wf_synthetic_b", "event": "synthetic_step", "data": {"workspace_id": WS_B}},
]
MARKERS = ("wf_synthetic_a", "wf_synthetic_b", WS_A, WS_B)


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
    """Replace the workflow event store's reads with recorders over the two synthetic workspaces' records."""
    from backend.orchestration.event_store import event_store

    touched: list[str] = []

    def tail(n: int = 50):
        touched.append("tail")
        return RECORDS[-n:]

    def incomplete_workflows():
        touched.append("incomplete")
        return [{"workflow_id": record["workflow_id"]} for record in RECORDS]

    def events_for(workflow_id: str):
        touched.append("events_for")
        return [record for record in RECORDS if record["workflow_id"] == workflow_id]

    monkeypatch.setattr(event_store, "tail", tail)
    monkeypatch.setattr(event_store, "incomplete_workflows", incomplete_workflows)
    monkeypatch.setattr(event_store, "events_for", events_for)
    return touched


@pytest.mark.parametrize("path", LOG_PATHS)
def test_anonymous_workflow_log_reads_are_refused_before_any_read(store, path):
    response = TestClient(_app()).get(path)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] in {"missing_credentials", "invalid_credentials"}
    assert store == []


@pytest.mark.parametrize("path", LOG_PATHS)
def test_unconfigured_identity_provider_fails_closed(store, path):
    response = TestClient(_app(identity=False)).get(path, headers=OPERATOR_A)

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "identity_provider_unavailable"}}
    assert store == []


@pytest.mark.parametrize("path", LOG_PATHS)
def test_client_viewer_is_denied_without_reading_the_log(store, path):
    response = TestClient(_app()).get(path, headers=VIEWER_A)

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "role_not_authorized"}}
    assert store == []


@pytest.mark.parametrize("path", LOG_PATHS)
@pytest.mark.parametrize("headers", [OPERATOR_A, OPERATOR_B], ids=["operator_a", "operator_b"])
def test_workspace_bound_operator_is_refused_without_reading_the_log(store, path, headers):
    response = TestClient(_app()).get(path, headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "workspace_not_authorized"}}
    assert store == []


@pytest.mark.parametrize("path", LOG_PATHS)
@pytest.mark.parametrize("headers", [OPERATOR_A, OPERATOR_B], ids=["operator_a", "operator_b"])
def test_no_workspace_observes_any_event_or_workflow_id(store, path, headers):
    body = TestClient(_app()).get(path, headers=headers).text

    assert not any(marker in body for marker in MARKERS)
    assert store == []


def test_foreign_and_missing_workflow_ids_answer_identically(store):
    client = TestClient(_app())
    foreign = client.get("/orchestration/workflows/wf_synthetic_b", headers=OPERATOR_A)
    missing = client.get("/orchestration/workflows/wf_synthetic_missing", headers=OPERATOR_A)

    assert (foreign.status_code, foreign.json()) == (missing.status_code, missing.json())
    assert store == []


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

    statuses = [client.get("/orchestration/workflows", headers=VIEWER_A).status_code for _ in range(2)]
    throttled = client.get("/orchestration/workflows", headers=VIEWER_A)

    assert statuses == [403, 403]
    assert throttled.status_code == 429
    assert verified == ["tok-viewer-a", "tok-viewer-a"]
    assert store == []

"""The workflow API is operator-only and bound to the verified principal's workspace.

The registry and every runner are in-memory recorders, so nothing is read from or written to disk and no stage runs.
A foreign workflow answers exactly as a missing one does.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import workflows
from backend.identity.errors import IdentityError
from backend.identity.http import get_token_verifier, get_workspace_repository
from backend.identity.principal import VerifiedPrincipal
from backend.identity.roles import CLIENT_VIEWER, INTERNAL_OPERATOR
from backend.identity.workspaces import WorkspaceAccess
from backend.security.rate_limit import reset_rate_limits_for_tests

ISSUER = "https://clerk.test"
BOUND = "ws_flow_bound_synthetic"
OTHER = "ws_flow_other_synthetic"
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


def _record(workflow_id: str, workspace_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        workflow_id=workflow_id,
        workspace_id=workspace_id,
        workflow_type="synthetic_cycle",
        to_dict=lambda: {"workflow_id": workflow_id, "workspace_id": workspace_id},
    )


class FakeRegistry:
    def __init__(self) -> None:
        self.records = {"wf_bound": _record("wf_bound", BOUND), "wf_other": _record("wf_other", OTHER)}
        self.reads: list[str] = []

    def get_workflow(self, workflow_id):
        self.reads.append(workflow_id)
        return self.records.get(workflow_id)

    def list_workflows(self, workspace_id=None, workflow_type=None, status=None, limit=50):
        return [x for x in self.records.values() if workspace_id is None or x.workspace_id == workspace_id]

    def list_checkpoints(self, workflow_id=None, limit=200):
        return [SimpleNamespace(to_dict=lambda: {"checkpoint_for": workflow_id})]

    def list_timeline(self, workflow_id=None, limit=500):
        return [SimpleNamespace(to_dict=lambda: {"timeline_for": workflow_id})]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setenv("MARKETOS_EVENT_READ_RATE_LIMIT", "100000")
    reset_rate_limits_for_tests()
    yield
    reset_rate_limits_for_tests()


@pytest.fixture
def calls(monkeypatch) -> dict[str, list]:
    """Recorders for every runner and the registry: a denied request must leave each list empty."""
    seen: dict[str, list] = {"run": [], "resume": [], "replay": []}
    registry = FakeRegistry()
    monkeypatch.setattr(workflows, "get_workflow_registry", lambda: registry)
    monkeypatch.setattr(
        workflows, "run_workflow", lambda *args, **kwargs: seen["run"].append(args) or {"status": "recorded"}
    )
    monkeypatch.setattr(
        workflows, "resume_workflow", lambda *args, **kwargs: seen["resume"].append(args) or {"status": "recorded"}
    )
    monkeypatch.setattr(
        workflows,
        "replay_workflow_stage",
        lambda *args, **kwargs: seen["replay"].append(args) or {"status": "recorded"},
    )
    monkeypatch.setattr(workflows, "build_workflow_summary", lambda record: {"summary_for": record.workflow_id})
    seen["registry"] = registry
    return seen


def _app(*, identity: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(workflows.router)
    if identity:
        app.dependency_overrides[get_token_verifier] = lambda: FakeVerifier()
        app.dependency_overrides[get_workspace_repository] = lambda: FakeRepo()
    return app


ANON_READS = [
    "/api/workflows",
    "/api/workflows/runbooks",
    "/api/workflows/wf_bound",
    "/api/workflows/wf_bound/checkpoints",
    "/api/workflows/wf_bound/timeline",
    "/api/workflows/wf_bound/summary",
]


@pytest.mark.parametrize("path", ANON_READS)
def test_anonymous_reads_are_refused_before_any_registry_read(calls, path):
    response = TestClient(_app()).get(path)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] in {"missing_credentials", "invalid_credentials"}
    assert calls["registry"].reads == []


def test_anonymous_run_and_resume_are_refused_before_any_stage_runs(calls):
    client = TestClient(_app())

    assert client.post("/api/workflows/run", json={"workspace_id": BOUND}).status_code == 401
    assert client.post("/api/workflows/wf_bound/resume", json={}).status_code == 401
    assert client.post("/api/workflows/wf_bound/replay-stage", json={"stage_name": "x"}).status_code == 401
    assert calls["run"] == calls["resume"] == calls["replay"] == []


def test_unconfigured_identity_provider_fails_closed(calls):
    response = TestClient(_app(identity=False)).get("/api/workflows", headers=OPERATOR)

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "identity_provider_unavailable"}}
    assert calls["registry"].reads == []


def test_client_viewer_cannot_run_a_workflow(calls):
    response = TestClient(_app()).post("/api/workflows/run", json={"workspace_id": BOUND}, headers=VIEWER)

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "role_not_authorized"}}
    assert calls["run"] == []


def test_foreign_workspace_in_run_body_is_refused_before_the_run(calls):
    response = TestClient(_app()).post("/api/workflows/run", json={"workspace_id": OTHER}, headers=OPERATOR)

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "workspace_not_authorized"}}
    assert calls["run"] == []


def test_run_without_a_workspace_runs_in_the_bound_workspace(calls):
    response = TestClient(_app()).post(
        "/api/workflows/run", json={"workflow_type": "synthetic_cycle"}, headers=OPERATOR
    )

    assert response.status_code == 200
    assert calls["run"][0][0] == BOUND


def test_foreign_list_selector_is_refused_and_default_lists_only_the_bound_workspace(calls):
    client = TestClient(_app())

    assert client.get("/api/workflows", params={"workspace_id": OTHER}, headers=OPERATOR).status_code == 403
    listed = client.get("/api/workflows", headers=OPERATOR).json()["workflows"]
    assert [item["workflow_id"] for item in listed] == ["wf_bound"]


def test_foreign_workflow_answers_exactly_like_a_missing_one(calls):
    client = TestClient(_app())

    foreign = client.get("/api/workflows/wf_other", headers=OPERATOR).json()
    missing = client.get("/api/workflows/wf_absent", headers=OPERATOR).json()

    assert foreign == {"status": "not_found", "workflow_id": "wf_other"}
    assert missing == {"status": "not_found", "workflow_id": "wf_absent"}
    assert client.get("/api/workflows/wf_bound", headers=OPERATOR).json() == {
        "workflow": {"workflow_id": "wf_bound", "workspace_id": BOUND}
    }


@pytest.mark.parametrize("suffix", ["checkpoints", "timeline"])
def test_foreign_workflow_sub_reads_are_empty(calls, suffix):
    client = TestClient(_app())

    assert client.get(f"/api/workflows/wf_other/{suffix}", headers=OPERATOR).json() == {suffix: []}
    assert client.get(f"/api/workflows/wf_bound/{suffix}", headers=OPERATOR).json()[suffix]


def test_foreign_summary_is_not_found(calls):
    response = TestClient(_app()).get("/api/workflows/wf_other/summary", headers=OPERATOR)

    assert response.json() == {"status": "not_found", "workflow_id": "wf_other"}


def test_foreign_resume_and_replay_never_reach_the_runner(calls):
    client = TestClient(_app())

    assert client.post("/api/workflows/wf_other/resume", json={}, headers=OPERATOR).json()["status"] == "not_found"
    assert (
        client.post("/api/workflows/wf_other/replay-stage", json={"stage_name": "x"}, headers=OPERATOR).json()["status"]
        == "not_found"
    )
    assert calls["resume"] == calls["replay"] == []


def test_bound_resume_reaches_the_runner(calls):
    response = TestClient(_app()).post("/api/workflows/wf_bound/resume", json={"from_stage": "s"}, headers=OPERATOR)

    assert response.status_code == 200
    assert calls["resume"] == [("wf_bound", "s", None)]


def test_runbooks_are_operator_only_and_static(calls):
    client = TestClient(_app())

    assert client.get("/api/workflows/runbooks", headers=VIEWER).status_code == 403
    assert "runbooks" in client.get("/api/workflows/runbooks", headers=OPERATOR).json()


def test_denied_workflow_reads_are_throttled_before_identity(calls, monkeypatch):
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

    statuses = [client.get("/api/workflows", headers=VIEWER).status_code for _ in range(2)]
    throttled = client.get("/api/workflows", headers=VIEWER)

    assert statuses == [403, 403]
    assert throttled.status_code == 429
    assert verified == ["tok-viewer", "tok-viewer"]
    assert calls["registry"].reads == []

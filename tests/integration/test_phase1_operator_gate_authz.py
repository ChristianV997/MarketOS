"""The phase1 readiness and benchmark readers are operator-only and never disclose server paths.

The report builders are replaced with recorders that return an absolute path, so the test proves the route itself
reduces artifact locations to names. Nothing is read from disk.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import phase1_benchmark_matrix, phase1_readiness
from backend.identity.errors import IdentityError
from backend.identity.http import get_token_verifier, get_workspace_repository
from backend.identity.principal import VerifiedPrincipal
from backend.identity.roles import CLIENT_VIEWER, INTERNAL_OPERATOR
from backend.identity.workspaces import WorkspaceAccess
from backend.security.rate_limit import reset_rate_limits_for_tests

ISSUER = "https://clerk.test"
BOUND = "ws_phase1_bound_synthetic"
ABSOLUTE = "/srv/synthetic-deployment/artifacts/phase1_evaluation.json"
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
    app.include_router(phase1_readiness.router)
    app.include_router(phase1_benchmark_matrix.router)
    if identity:
        app.dependency_overrides[get_token_verifier] = lambda: FakeVerifier()
        app.dependency_overrides[get_workspace_repository] = lambda: FakeRepo()
    return app


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setenv("MARKETOS_EVENT_READ_RATE_LIMIT", "100000")
    reset_rate_limits_for_tests()
    yield
    reset_rate_limits_for_tests()


@pytest.fixture
def builders(monkeypatch) -> dict[str, list]:
    seen: dict[str, list] = {"readiness": [], "matrix": []}

    def readiness_builder(**kwargs):
        seen["readiness"].append(kwargs)
        return SimpleNamespace(to_dict=lambda: {"status": "ready", "source_artifacts": {"evaluation_report": ABSOLUTE}})

    def matrix_builder(**kwargs):
        seen["matrix"].append(kwargs)
        return SimpleNamespace(to_dict=lambda: {"status": "ready", "source_artifacts": {"evaluation_report": ABSOLUTE}})

    monkeypatch.setattr(phase1_readiness, "build_from_paths", readiness_builder)
    monkeypatch.setattr(phase1_benchmark_matrix, "build_benchmark_from_paths", matrix_builder)
    return seen


@pytest.mark.parametrize("path", ["/api/phase1/readiness", "/api/phase1/benchmark-matrix"])
def test_anonymous_phase1_reads_are_refused_before_any_build(builders, path):
    response = TestClient(_app()).get(path)

    assert response.status_code == 401
    assert builders["readiness"] == builders["matrix"] == []


@pytest.mark.parametrize("path", ["/api/phase1/readiness", "/api/phase1/benchmark-matrix"])
def test_client_viewer_is_denied_without_a_build(builders, path):
    response = TestClient(_app()).get(path, headers=VIEWER)

    assert response.status_code == 403
    assert builders["readiness"] == builders["matrix"] == []


def test_unconfigured_identity_provider_fails_closed(builders):
    response = TestClient(_app(identity=False)).get("/api/phase1/readiness", headers=OPERATOR)

    assert response.status_code == 503
    assert builders["readiness"] == []


@pytest.mark.parametrize("path", ["/api/phase1/readiness", "/api/phase1/benchmark-matrix"])
def test_operator_response_names_artifacts_but_never_their_server_paths(builders, path):
    response = TestClient(_app()).get(path, headers=OPERATOR)

    assert response.status_code == 200
    assert response.json()["source_artifacts"] == {"evaluation_report": "phase1_evaluation.json"}
    assert ABSOLUTE not in response.text
    assert "/srv/synthetic-deployment" not in response.text


def test_throttle_runs_before_identity_on_phase1(monkeypatch, builders):
    monkeypatch.setenv("MARKETOS_EVENT_READ_RATE_LIMIT", "2")
    reset_rate_limits_for_tests()

    statuses = [TestClient(_app()).get("/api/phase1/readiness", headers=VIEWER).status_code for _ in range(2)]
    throttled = TestClient(_app()).get("/api/phase1/readiness", headers=VIEWER)

    assert statuses == [403, 403]
    assert throttled.status_code == 429
    assert throttled.headers.get("retry-after")

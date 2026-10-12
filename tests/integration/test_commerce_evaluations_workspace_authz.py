"""Commerce evaluation views are operator-only and evaluate only the bound workspace's canonical events.

Synthetic events and fake identity only. ``ARTIFACTS`` is redirected into ``tmp_path`` so no real artifact or
configuration file is read, and denied requests must never reach the evaluation loader.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import commerce_evaluations
from backend.contracts.events import Event
from backend.identity.errors import IdentityError
from backend.identity.http import get_token_verifier, get_workspace_repository
from backend.identity.principal import VerifiedPrincipal
from backend.identity.roles import CLIENT_VIEWER, INTERNAL_OPERATOR
from backend.identity.workspaces import WorkspaceAccess
from backend.security.rate_limit import reset_rate_limits_for_tests

ISSUER = "https://clerk.test"
BOUND = "ws_eval_bound_synthetic"
OTHER = "ws_eval_other_synthetic"
CANARY = "synthetic-canary-eval-5b2d"
PATHS = ["/api/evaluations", "/api/evaluations/compare", "/api/evaluations/readiness"]
OPERATOR = {"Authorization": "Bearer tok-operator"}
VIEWER = {"Authorization": "Bearer tok-viewer"}
MEMBERSHIPS = {
    "user_operator": [(BOUND, "internal", INTERNAL_OPERATOR)],
    "user_viewer": [(BOUND, "internal", CLIENT_VIEWER)],
}
TOKENS = {"tok-operator": "user_operator", "tok-viewer": "user_viewer"}


class FakeVerifier:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, token: str) -> VerifiedPrincipal:
        self.calls += 1
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


def _event(event_id: str, workspace_id: str | None, occurred_at: float) -> Event:
    return Event(
        event_id,
        workspace_id,
        "synthetic",
        event_id,
        "synthetic_probe",
        1,
        occurred_at,
        source="synthetic_test",
        payload={"secret": CANARY},
    )


def _app(*, identity: bool = True, verifier: FakeVerifier | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(commerce_evaluations.router)
    if identity:
        verifier = verifier or FakeVerifier()
        app.dependency_overrides[get_token_verifier] = lambda: verifier
        app.dependency_overrides[get_workspace_repository] = lambda: FakeRepo()
    return app


@pytest.fixture(autouse=True)
def _isolated_throttle(monkeypatch):
    monkeypatch.setenv("MARKETOS_EVENT_READ_RATE_LIMIT", "100000")
    reset_rate_limits_for_tests()
    yield
    reset_rate_limits_for_tests()


@pytest.fixture
def artifacts(monkeypatch, tmp_path: Path) -> Path:
    root = (tmp_path / "artifacts").resolve()
    root.mkdir()
    monkeypatch.setattr(commerce_evaluations, "ARTIFACTS", root)
    return root


@pytest.fixture
def jsonl(monkeypatch, artifacts: Path) -> Path:
    path = artifacts / "events.jsonl"
    rows = [
        _event("evt_bound_1", BOUND, 1.0),
        _event("evt_other_1", OTHER, 2.0),
        _event("evt_bound_2", BOUND, 3.0),
        _event("evt_unscoped_1", None, 4.0),
    ]
    path.write_text("".join(json.dumps(row.to_dict(), sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(path))
    return path


@pytest.fixture
def loads(monkeypatch) -> list[str]:
    calls: list[str] = []
    original = commerce_evaluations.load_evaluation_input

    def spy(path, **kwargs):
        calls.append(str(path))
        return original(path, **kwargs)

    monkeypatch.setattr(commerce_evaluations, "load_evaluation_input", spy)
    return calls


@pytest.mark.parametrize("path", PATHS)
def test_unauthenticated_evaluation_reads_are_refused_before_any_load(jsonl, loads, path):
    response = TestClient(_app()).get(path)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] in {"missing_credentials", "invalid_credentials"}
    assert loads == []


@pytest.mark.parametrize("path", PATHS)
def test_unconfigured_identity_provider_fails_closed(jsonl, loads, path):
    response = TestClient(_app(identity=False)).get(path, headers=OPERATOR)

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "identity_provider_unavailable"}}
    assert loads == []


def test_client_viewer_is_denied_without_loading_events(jsonl, loads):
    response = TestClient(_app()).get("/api/evaluations", headers=VIEWER)

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "role_not_authorized"}}
    assert loads == []


def test_operator_evaluates_only_the_bound_workspace(jsonl, loads):
    response = TestClient(_app()).get("/api/evaluations", headers=OPERATOR)

    assert response.status_code == 200
    report = response.json()
    assert report["workspace_id"] == BOUND
    assert report["event_count"] == 2
    assert OTHER not in response.text
    assert CANARY not in response.text
    assert str(jsonl) not in response.text
    assert loads == [str(jsonl)]


def test_compare_evaluates_only_the_bound_workspace_on_both_sides(monkeypatch, artifacts, loads):
    baseline = artifacts / "baseline.jsonl"
    current = artifacts / "current.jsonl"
    baseline.write_text(
        json.dumps(_event("evt_b", BOUND, 1.0).to_dict())
        + "\n"
        + json.dumps(_event("evt_o", OTHER, 2.0).to_dict())
        + "\n",
        encoding="utf-8",
    )
    current.write_text(
        "".join(json.dumps(_event(f"evt_c{i}", BOUND, float(i)).to_dict()) + "\n" for i in range(3))
        + json.dumps(_event("evt_x", OTHER, 9.0).to_dict())
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MARKETOS_EVALUATION_BASELINE_JSONL_PATH", str(baseline))
    monkeypatch.setenv("MARKETOS_EVALUATION_CURRENT_JSONL_PATH", str(current))

    response = TestClient(_app()).get("/api/evaluations/compare", headers=OPERATOR)

    assert response.status_code == 200
    body = response.json()
    assert body["baseline"]["event_count"] == 1
    assert body["current"]["event_count"] == 3
    assert OTHER not in response.text


def test_compare_refused_without_identity_loads_nothing(monkeypatch, artifacts, loads):
    baseline = artifacts / "baseline.jsonl"
    current = artifacts / "current.jsonl"
    baseline.write_text(json.dumps(_event("evt_b", BOUND, 1.0).to_dict()) + "\n", encoding="utf-8")
    current.write_text(json.dumps(_event("evt_c", BOUND, 1.0).to_dict()) + "\n", encoding="utf-8")
    monkeypatch.setenv("MARKETOS_EVALUATION_BASELINE_JSONL_PATH", str(baseline))
    monkeypatch.setenv("MARKETOS_EVALUATION_CURRENT_JSONL_PATH", str(current))

    response = TestClient(_app()).get("/api/evaluations/compare")

    assert response.status_code == 401
    assert loads == []


def test_throttle_runs_before_identity(monkeypatch, jsonl):
    monkeypatch.setenv("MARKETOS_EVENT_READ_RATE_LIMIT", "2")
    reset_rate_limits_for_tests()
    verifier = FakeVerifier()
    client = TestClient(_app(verifier=verifier))

    statuses = [client.get("/api/evaluations", headers=VIEWER).status_code for _ in range(2)]
    throttled = client.get("/api/evaluations", headers=VIEWER)

    assert statuses == [403, 403]
    assert throttled.status_code == 429
    assert throttled.headers.get("retry-after")
    assert verifier.calls == 2


def test_evaluation_reads_never_write(jsonl, artifacts):
    def snapshot() -> dict[str, str]:
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(artifacts.rglob("*")) if p.is_file()}

    before = snapshot()
    client = TestClient(_app())
    for path in PATHS:
        client.get(path, headers=OPERATOR)
        client.get(path)

    assert snapshot() == before

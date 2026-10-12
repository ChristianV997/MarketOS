"""Operator gates for runtime control and commerce execution.

Covers the mutating routes that were reachable without caller identity: the manual cycle and background
runner (``api/routes/cycle_control.py``), the global kill-switch (``api/routes/agents_risk.py``), and the
commerce and Postiz execution routes mounted on ``backend.api.app``.

Identity uses the production dependency chain: a fake verifier maps synthetic tokens to principals, and
the workspace repository is the SQLite-backed one from ``tests/identity/conftest.py``. Every side effect and
outbound call sits behind a recorder. A refused request must leave all recorders empty and all state
unchanged. Nothing here reads real credentials, a real database, or the network.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.identity.errors import IdentityError
from backend.identity.http import get_token_verifier, get_workspace_repository
from backend.identity.principal import VerifiedPrincipal
from backend.identity.roles import (
    CLIENT_VIEWER,
    COMMERCE_EXECUTION_WRITE,
    INTERNAL_OPERATOR,
    RUNTIME_CONTROL_WRITE,
    role_grants,
)

from .conftest import ALICE, ISSUER, OWNER_ALICE

VIEWER = VerifiedPrincipal(ISSUER, "user_viewer")
TOKENS = {"tok-operator": ALICE, "tok-viewer": VIEWER}
OPERATOR_HEADERS = {"Authorization": "Bearer tok-operator"}

# (path, JSON body, initial background-runner flag). The flag is set so that the route's authorized call
# would change it; a refused call must leave it as it was.
GATED_ROUTES = [
    pytest.param("/cycle", None, True, id="cycle"),
    pytest.param("/runner/pause", None, True, id="runner-pause"),
    pytest.param("/runner/resume", None, False, id="runner-resume"),
    pytest.param("/risk/killswitch/activate?reason=ops-test", None, True, id="killswitch-activate"),
    pytest.param("/risk/killswitch/deactivate", None, True, id="killswitch-deactivate"),
    pytest.param("/commerce/cycle", {"top_k": 1, "budget": 10}, True, id="commerce-cycle"),
    pytest.param("/commerce/provider-cycle", {"urls": ["https://research.example.test/feed"]}, True, id="commerce-provider-cycle"),
    pytest.param("/commerce/publish", {"product_id": "p-1", "creative_id": "c-1", "hook": "h"}, True, id="commerce-publish"),
    pytest.param("/integrations/postiz/analytics/reconcile", {"post_id": "post-1", "campaign_id": "camp-1"}, True, id="postiz-reconcile"),
]

# (wiring, headers, expected status, expected code). Wiring says which identity providers the app has:
# "wired" both, "no_verifier" only the repository, "no_repository" only the verifier.
REFUSALS = [
    pytest.param("wired", {}, 401, "missing_credentials", id="anonymous"),
    pytest.param("wired", {"Authorization": "Bearer tok-forged"}, 401, "invalid_credentials", id="forged-token"),
    pytest.param("wired", {"Authorization": "Bearer tok-viewer"}, 403, "role_not_authorized", id="client-viewer"),
    pytest.param("no_verifier", OPERATOR_HEADERS, 503, "identity_provider_unavailable", id="unconfigured-verifier"),
    pytest.param("no_repository", OPERATOR_HEADERS, 503, "storage_unavailable", id="unconfigured-repository"),
]


class FakeVerifier:
    def verify(self, token: str) -> VerifiedPrincipal:
        try:
            return TOKENS[token]
        except KeyError:
            raise IdentityError() from None


class Effects:
    """Records each side effect and outbound call that a gated handler would make."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.engine = _FakeRiskEngine(self)

    def record(self, name: str, *args, **kwargs) -> None:
        self.calls.append((name, args, kwargs))

    def names(self) -> list[str]:
        return [name for name, _args, _kwargs in self.calls]


class _FakeRiskEngine:
    def __init__(self, effects: Effects) -> None:
        self._effects = effects
        self.kill_switch_active = False

    def activate_kill_switch(self, reason: str = "manual") -> None:
        self._effects.record("killswitch.activate", reason)
        self.kill_switch_active = True

    def deactivate_kill_switch(self) -> None:
        self._effects.record("killswitch.deactivate")
        self.kill_switch_active = False


class _Report:
    def __init__(self, body: dict) -> None:
        self._body = body

    def to_dict(self) -> dict:
        return dict(self._body)


@pytest.fixture
def store(repo):
    repo.create_workspace(OWNER_ALICE, "internal", "Owner Workspace")
    repo.add_member(OWNER_ALICE, ALICE.issuer, ALICE.subject, INTERNAL_OPERATOR)
    # A client_viewer in the internal workspace: the membership exists, and the role must still refuse.
    repo.add_member(OWNER_ALICE, VIEWER.issuer, VIEWER.subject, CLIENT_VIEWER)
    return repo


@pytest.fixture
def api(monkeypatch):
    import backend.api as module

    # Each test wires its own identity providers; none may leak in from another module.
    monkeypatch.delitem(module.app.dependency_overrides, get_token_verifier, raising=False)
    monkeypatch.delitem(module.app.dependency_overrides, get_workspace_repository, raising=False)
    return module


@pytest.fixture
def effects(api, monkeypatch) -> Effects:
    import api.routes.cycle_control as cycle_control
    import backend.commerce as commerce
    import backend.commerce.feedback as feedback
    import backend.commerce.loop as commerce_loop
    import backend.execution.loop as execution_loop
    from backend.commerce.feedback import webhook_feedback_recorder
    from backend.integrations.postiz import publisher

    rec = Effects()

    # Runtime state the routes mutate; monkeypatch restores each attribute after the test.
    for name in ("_state", "_last_cycle_at", "_bg_running"):
        monkeypatch.setattr(api, name, getattr(api, name))
    monkeypatch.setattr(api, "_global_risk_engine", rec.engine)

    def fake_run_cycle(state):
        rec.record("cycle.run", state)
        return SimpleNamespace(capital=1000.0, total_cycles=7, event_log=SimpleNamespace(rows=[1, 2]), detected_regime="RESEARCH")

    class _RecordingThread:
        def __init__(self, *, target, daemon):
            self._daemon = daemon

        def start(self):
            rec.record("runner.thread_start", daemon=self._daemon)

    def report(name: str):
        def run(*args, **kwargs):
            rec.record(name, *args, **kwargs)
            return _Report({"stub": name})

        return run

    class _RecordingLoop:
        def publish_creatives(self, bundles, *, dry_run, approval_state):
            rec.record("commerce.publish", [bundle.product_id for bundle in bundles], dry_run=dry_run, approval_state=approval_state)
            return [{"record": "stub"}]

    def fake_fetch(post_id, campaign_id, **kwargs):
        rec.record("postiz.fetch_campaign_observation", post_id, campaign_id, **kwargs)
        return SimpleNamespace(post_id=post_id)

    def fake_record_observation(observation):
        rec.record("feedback.record_observation", observation.post_id)
        return {"recorded": True}

    monkeypatch.setattr(execution_loop, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(cycle_control, "threading", SimpleNamespace(Thread=_RecordingThread))
    monkeypatch.setattr(commerce, "run_commerce_cycle", report("commerce.cycle"))
    monkeypatch.setattr(commerce, "run_provider_cycle", report("commerce.provider_cycle"))
    monkeypatch.setattr(commerce_loop, "CommerceLoop", _RecordingLoop)
    monkeypatch.setattr(publisher, "fetch_campaign_observation", fake_fetch)
    monkeypatch.setattr(webhook_feedback_recorder, "record_observation", fake_record_observation)
    monkeypatch.setattr(feedback, "_observation_dict", lambda observation: {"post_id": observation.post_id})
    return rec


def _wire(api, monkeypatch, store, wiring: str) -> None:
    if wiring in ("wired", "no_repository"):
        monkeypatch.setitem(api.app.dependency_overrides, get_token_verifier, lambda: FakeVerifier())
    if wiring in ("wired", "no_verifier"):
        monkeypatch.setitem(api.app.dependency_overrides, get_workspace_repository, lambda: store)


def _state(api, effects: Effects) -> tuple:
    return (api._state, api._last_cycle_at, api._bg_running, effects.engine.kill_switch_active)


@pytest.mark.parametrize("path, body, bg_running", GATED_ROUTES)
@pytest.mark.parametrize("wiring, headers, status, code", REFUSALS)
def test_refused_identity_runs_no_handler_and_changes_nothing(
    api, store, effects, monkeypatch, path, body, bg_running, wiring, headers, status, code
):
    _wire(api, monkeypatch, store, wiring)
    monkeypatch.setattr(api, "_bg_running", bg_running)
    before = _state(api, effects)

    response = TestClient(api.app).post(path, json=body, headers=headers)

    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert effects.calls == []
    assert _state(api, effects) == before


def test_cycle_keeps_response_contract_for_operator(api, store, effects, monkeypatch):
    _wire(api, monkeypatch, store, "wired")
    response = TestClient(api.app).post("/cycle", headers=OPERATOR_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"capital": 1000.0, "total_cycles": 7, "event_count": 2, "detected_regime": "RESEARCH"}
    assert effects.names() == ["cycle.run"]


def test_runner_pause_keeps_response_contract_for_operator(api, store, effects, monkeypatch):
    _wire(api, monkeypatch, store, "wired")
    monkeypatch.setattr(api, "_bg_running", True)
    response = TestClient(api.app).post("/runner/pause", headers=OPERATOR_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"bg_running": False}
    assert api._bg_running is False
    assert effects.calls == []


def test_runner_resume_starts_one_daemon_thread_for_operator(api, store, effects, monkeypatch):
    _wire(api, monkeypatch, store, "wired")
    monkeypatch.setattr(api, "_bg_running", False)
    response = TestClient(api.app).post("/runner/resume", headers=OPERATOR_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"bg_running": True}
    assert api._bg_running is True
    assert effects.calls == [("runner.thread_start", (), {"daemon": True})]


def test_killswitch_activate_keeps_response_contract_for_operator(api, store, effects, monkeypatch):
    _wire(api, monkeypatch, store, "wired")
    response = TestClient(api.app).post("/risk/killswitch/activate?reason=ops-test", headers=OPERATOR_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"kill_switch_active": True, "reason": "ops-test"}
    assert effects.calls == [("killswitch.activate", ("ops-test",), {})]
    assert effects.engine.kill_switch_active is True


def test_killswitch_deactivate_keeps_response_contract_for_operator(api, store, effects, monkeypatch):
    _wire(api, monkeypatch, store, "wired")
    effects.engine.kill_switch_active = True
    response = TestClient(api.app).post("/risk/killswitch/deactivate", headers=OPERATOR_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"kill_switch_active": False}
    assert effects.calls == [("killswitch.deactivate", (), {})]
    assert effects.engine.kill_switch_active is False


def test_commerce_cycle_keeps_response_contract_and_dry_run_default_for_operator(api, store, effects, monkeypatch):
    _wire(api, monkeypatch, store, "wired")
    response = TestClient(api.app).post("/commerce/cycle", json={"top_k": 1, "budget": 10}, headers=OPERATOR_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"stub": "commerce.cycle"}
    assert effects.names() == ["commerce.cycle"]
    assert effects.calls[0][2]["dry_run"] is True


def test_provider_cycle_keeps_response_contract_for_operator(api, store, effects, monkeypatch):
    _wire(api, monkeypatch, store, "wired")
    urls = ["https://research.example.test/feed"]
    response = TestClient(api.app).post("/commerce/provider-cycle", json={"urls": urls}, headers=OPERATOR_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"stub": "commerce.provider_cycle"}
    assert effects.names() == ["commerce.provider_cycle"]
    assert effects.calls[0][1] == (urls,)


def test_publish_keeps_response_contract_and_dry_run_default_for_operator(api, store, effects, monkeypatch):
    _wire(api, monkeypatch, store, "wired")
    response = TestClient(api.app).post(
        "/commerce/publish", json={"product_id": "p-1", "creative_id": "c-1", "hook": "h"}, headers=OPERATOR_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["published"] is True
    assert body["dry_run"] is True
    assert body["records"] == [{"record": "stub"}]
    assert isinstance(body["artifact_id"], str) and body["artifact_id"]
    assert effects.calls == [("commerce.publish", (["p-1"],), {"dry_run": True, "approval_state": "not_required"})]


def test_postiz_reconcile_keeps_response_contract_for_operator(api, store, effects, monkeypatch):
    _wire(api, monkeypatch, store, "wired")
    response = TestClient(api.app).post(
        "/integrations/postiz/analytics/reconcile",
        json={"post_id": "post-1", "campaign_id": "camp-1"},
        headers=OPERATOR_HEADERS,
    )
    assert response.status_code == 200
    assert response.json() == {"reconciled": True, "observation": {"post_id": "post-1"}, "feedback": {"recorded": True}}
    assert effects.names() == ["postiz.fetch_campaign_observation", "feedback.record_observation"]


def test_runtime_and_commerce_permissions_are_granted_to_internal_operator_only():
    assert RUNTIME_CONTROL_WRITE == "runtime_control:write"
    assert COMMERCE_EXECUTION_WRITE == "commerce_execution:write"
    for permission in (RUNTIME_CONTROL_WRITE, COMMERCE_EXECUTION_WRITE):
        assert role_grants(INTERNAL_OPERATOR, permission)
        assert not role_grants(CLIENT_VIEWER, permission)
        assert not role_grants(None, permission)
        assert not role_grants("unknown_role", permission)

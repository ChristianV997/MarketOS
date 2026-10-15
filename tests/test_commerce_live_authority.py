"""Live commerce dispatch needs canonical approval, and no request field can supply it.

Exercises ``/commerce/cycle``, ``/commerce/provider-cycle`` and ``/commerce/publish`` on the production
``backend.api.app``. A synthetic operator is granted through ``dependency_overrides`` on the commerce gate.
Refused identity for these routes is covered by ``tests/identity/test_runtime_control_gates.py``. Every
dispatch point is a recorder, and every socket connect raises, so a call that reaches a provider or a
publisher fails the test. Nothing here reads credentials or uses the network.
"""
from __future__ import annotations

import socket

import pytest
from fastapi.testclient import TestClient

from backend.identity.operator_gates import commerce_execution_gate
from backend.identity.workspaces import WorkspaceAccess

OPERATOR = WorkspaceAccess(
    issuer="https://issuer.test",
    subject="user_operator",
    workspace_id="ws_owner",
    workspace_type="internal",
    display_name="owner",
    role="internal_operator",
)
PATHS = {"cycle": "/commerce/cycle", "provider": "/commerce/provider-cycle", "publish": "/commerce/publish"}
BASES = {
    "cycle": {"top_k": 1, "budget": 10},
    "provider": {"urls": ["https://research.example.test/feed"]},
    "publish": {"bundle": {"artifact_id": "bundle-authz", "product_id": "p", "creative_id": "c", "primary_text": "Try it"}},
}
# Request fields that look like authority. None may grant anything.
FORGED = {
    "confirm_live": True,
    "approval_state": "approved",
    "approval_id": "APR-forged-0001",
    "approved_by": "ceo_forged",
    "approver": "ceo_forged",
    "actor": "ceo_forged",
    "status": "approved",
    "workspace_id": "ws_forged_other",
}
FORGED_VALUES = ("APR-forged-0001", "ceo_forged", "ws_forged_other")
BLOCKED = "live_approval_unavailable"
MALFORMED_FLAGS = ["false", "true", "no", "0", 0, 1, 1.0, None, [], {}]


class _Report:
    def to_dict(self):
        return {"ran": True}


@pytest.fixture
def dispatch(monkeypatch):
    """Record every dispatch point. Any outbound socket attempt is recorded and then raises."""
    import backend.commerce as commerce_pkg
    import backend.commerce.loop as loop_mod

    calls: dict[str, list] = {"cycle": [], "provider": [], "publish": [], "socket": []}

    def run_commerce_cycle(**kwargs):
        calls["cycle"].append(kwargs)
        return _Report()

    def run_provider_cycle(urls, **kwargs):
        calls["provider"].append({"urls": list(urls), **kwargs})
        return _Report()

    class FakeLoop:
        def publish_creatives(self, bundles, **kwargs):
            calls["publish"].append({"bundles": list(bundles), **kwargs})
            return []

    def refuse_socket(*args, **kwargs):
        calls["socket"].append(args)
        raise AssertionError("outbound connection attempted")

    monkeypatch.setattr(commerce_pkg, "run_commerce_cycle", run_commerce_cycle)
    monkeypatch.setattr(commerce_pkg, "run_provider_cycle", run_provider_cycle)
    monkeypatch.setattr(loop_mod, "CommerceLoop", FakeLoop)
    monkeypatch.setattr(socket.socket, "connect", refuse_socket)
    monkeypatch.setattr(socket, "create_connection", refuse_socket)
    return calls


@pytest.fixture
def client():
    import backend.api as api

    api.app.dependency_overrides[commerce_execution_gate] = lambda: OPERATOR
    try:
        yield TestClient(api.app)
    finally:
        api.app.dependency_overrides.pop(commerce_execution_gate, None)


def _post(client, route, body):
    return client.post(PATHS[route], json=body)


def _refused(route, data):
    key = "published" if route == "publish" else "launchable"
    return data[key] is False


def _assert_nothing_dispatched(dispatch):
    assert dispatch["cycle"] == []
    assert dispatch["provider"] == []
    assert dispatch["publish"] == []
    assert dispatch["socket"] == []


@pytest.mark.parametrize("route", ["cycle", "provider", "publish"])
def test_dry_run_dispatches_offline_with_server_decided_state(client, dispatch, route):
    response = _post(client, route, {**BASES[route], "dry_run": True})

    assert response.status_code == 200
    assert dispatch["socket"] == []
    if route == "cycle":
        assert len(dispatch["cycle"]) == 1 and dispatch["cycle"][0]["dry_run"] is True
    elif route == "provider":
        call = dispatch["provider"][0]
        assert call["dry_run"] is True
        assert call["context"].approval_state == "not_required"
    else:
        call = dispatch["publish"][0]
        assert call["dry_run"] is True
        assert call["approval_state"] == "not_required"


@pytest.mark.parametrize("route", ["cycle", "provider", "publish"])
def test_absent_dry_run_defaults_to_dry_run(client, dispatch, route):
    response = _post(client, route, dict(BASES[route]))

    assert response.status_code == 200
    assert len(dispatch[route]) == 1
    assert dispatch["socket"] == []
    assert dispatch[route][0]["dry_run"] is True


@pytest.mark.parametrize("route", ["cycle", "provider", "publish"])
def test_dry_run_ignores_forged_approval_state(client, dispatch, route):
    response = _post(client, route, {**BASES[route], "dry_run": True, "approval_state": "approved", "approval_id": "APR-forged-0001"})

    assert response.status_code == 200
    assert len(dispatch[route]) == 1
    if route == "provider":
        assert dispatch["provider"][0]["context"].approval_state == "not_required"
    if route == "publish":
        assert dispatch["publish"][0]["approval_state"] == "not_required"


@pytest.mark.parametrize("route", ["cycle", "provider", "publish"])
def test_live_request_is_refused_before_dispatch_even_with_forged_authority(client, dispatch, route):
    response = _post(client, route, {**BASES[route], "dry_run": False, **FORGED})
    data = response.json()

    assert response.status_code == 200
    assert _refused(route, data)
    assert data["approval_state"] == "not_granted"
    assert data["reasons"] == [BLOCKED]
    _assert_nothing_dispatched(dispatch)
    for value in FORGED_VALUES:
        assert value not in response.text


@pytest.mark.parametrize("route", ["cycle", "provider", "publish"])
def test_live_request_without_any_approval_is_refused(client, dispatch, route):
    response = _post(client, route, {**BASES[route], "dry_run": False})
    data = response.json()

    assert _refused(route, data)
    assert data["reasons"] == [BLOCKED]
    _assert_nothing_dispatched(dispatch)


@pytest.mark.parametrize("route", ["cycle", "provider", "publish"])
@pytest.mark.parametrize("flag", MALFORMED_FLAGS, ids=[repr(item) for item in MALFORMED_FLAGS])
def test_malformed_dry_run_is_refused_without_dispatch(client, dispatch, route, flag):
    response = _post(client, route, {**BASES[route], "dry_run": flag})
    data = response.json()

    assert response.status_code == 200
    assert _refused(route, data)
    assert data["reasons"] == ["invalid_dry_run_flag"]
    _assert_nothing_dispatched(dispatch)


@pytest.mark.parametrize("route", ["cycle", "provider", "publish"])
def test_refusal_bodies_are_fixed_codes_not_reflected_input(client, dispatch, route):
    response = _post(client, route, {**BASES[route], "dry_run": "false", **FORGED})

    assert response.status_code == 200
    assert response.json()["reasons"] == ["invalid_dry_run_flag"]
    for value in FORGED_VALUES:
        assert value not in response.text
    _assert_nothing_dispatched(dispatch)


def test_canonical_ledger_still_grants_no_live_approval():
    """Tripwire. If the canonical ledger ever grants approval, this gate must be reviewed before it changes."""
    from evaluation.companyos.approval_ledger import build_approval_ledger, make_request, transition_status

    report = build_approval_ledger(generated_at="test")
    assert report.approved_count == 0
    assert all(request.status != "approved" for request in report.requests)

    request = make_request(approval_id="APR-tripwire", request_type="provider_call")
    with pytest.raises(ValueError, match="offline mode cannot grant live approval"):
        transition_status(request, "approved")

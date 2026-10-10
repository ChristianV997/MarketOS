import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import app
from backend.identity.http import get_token_verifier, get_workspace_repository
from backend.identity.principal import VerifiedPrincipal
from backend.identity.workspaces import WorkspaceAccess


OPPORTUNITY_FIXTURES = Path(__file__).parent / "fixtures" / "opportunity_discovery"
ISSUER = "https://marketos.test"
WORKSPACE_ID = "workspace-owner"


class _Verifier:
    def verify(self, token: str) -> VerifiedPrincipal:
        if token == "valid-token":
            return VerifiedPrincipal(ISSUER, "owner")
        if token == "client-token":
            return VerifiedPrincipal(ISSUER, "client")
        raise ValueError("invalid token")


class _Repository:
    def memberships_for(self, principal: VerifiedPrincipal) -> list[WorkspaceAccess]:
        if principal.subject == "owner":
            return [WorkspaceAccess(ISSUER, "owner", WORKSPACE_ID, "internal", "Owner")]
        if principal.subject == "client":
            return [WorkspaceAccess(ISSUER, "client", "workspace-client", "client_service", "Client")]
        return []


@pytest.fixture
def discovery_client():
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_token_verifier] = lambda: _Verifier()
    app.dependency_overrides[get_workspace_repository] = lambda: _Repository()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def _opportunity_fixture(name: str) -> dict:
    return json.loads((OPPORTUNITY_FIXTURES / name).read_text(encoding="utf-8"))


def _ready_opportunity_fixture() -> dict:
    payload = _opportunity_fixture("product_complete.json")
    assumptions = payload["candidates"][0]["economics"]["assumptions"]
    for key in (
        "affiliate_fee_rate",
        "brokerage_fee",
        "cac",
        "domestic_shipping",
        "international_shipping",
        "payment_fee_fixed",
        "platform_fee_fixed",
    ):
        assumptions[key] = {"amount": "0", "currency": "MXN"} if key != "affiliate_fee_rate" else "0"
    return payload


def test_discovery_api_fixture_and_cap():
    client = TestClient(app)
    path = str(Path(__file__).parent / "fixtures" / "market_evidence_seed.json")
    response = client.post("/api/discovery/market-discovery", json={"dataset_paths": [path], "run_validation_services": False})
    assert response.status_code == 200
    assert response.json()["discovery"]["category_opportunities"]
    blocked = client.post("/api/discovery/market-discovery", json={"dataset_paths": ["../outside"]})
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked"


def test_opportunity_discovery_api_preserves_missing_empty_and_nonempty_gaps(discovery_client):
    from services.opportunity_discovery import run_discovery

    client = discovery_client
    headers = {"Authorization": "Bearer valid-token"}

    absent = client.post(
        "/api/discovery/opportunity-discovery",
        params={"mode": "evaluate"},
        json={"candidates": []},
        headers=headers,
    )
    assert absent.status_code == 200
    assert absent.json()["status"] == "unavailable"
    assert absent.json()["decisions"] == []
    assert "evidence_gaps" not in absent.json()

    complete_payload = _ready_opportunity_fixture()
    complete = client.post(
        "/api/discovery/opportunity-discovery",
        params={"mode": "evaluate"},
        json=complete_payload,
        headers=headers,
    )
    assert complete.status_code == 200
    complete_data = complete.json()
    assert complete_data["decisions"][0]["evidence_gaps"] == []

    incomplete_payload = _opportunity_fixture("product_complete.json")
    incomplete_payload["candidates"][0]["economics"]["assumptions"].pop("supplier_shipping")
    incomplete = client.post(
        "/api/discovery/opportunity-discovery",
        params={"mode": "evaluate"},
        json=incomplete_payload,
        headers=headers,
    )
    assert incomplete.status_code == 200
    incomplete_data = incomplete.json()
    assert "shipping" in incomplete_data["decisions"][0]["evidence_gaps"]

    verified_workspace = WorkspaceAccess(ISSUER, "owner", WORKSPACE_ID, "internal", "Owner")
    complete_projection = complete_data.pop("owner_opportunity")
    incomplete_projection = incomplete_data.pop("owner_opportunity")
    assert complete_data == run_discovery("evaluate", complete_payload, workspace=verified_workspace).to_dict()
    assert incomplete_data == run_discovery("evaluate", incomplete_payload, workspace=verified_workspace).to_dict()
    assert complete_projection["safety"]["launch_authorized"] is False
    assert incomplete_projection["snapshot_resolution"]["persisted"] is False


def test_opportunity_discovery_requires_verified_identity(discovery_client):
    response = discovery_client.post("/api/discovery/opportunity-discovery", json={"candidates": []})

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "missing_credentials"}}


def test_opportunity_discovery_rejects_invalid_identity(discovery_client):
    response = discovery_client.post(
        "/api/discovery/opportunity-discovery",
        headers={"Authorization": "Bearer invalid-token"},
        json={"candidates": []},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "invalid_credentials"}}


def test_opportunity_discovery_fails_closed_when_identity_provider_is_unconfigured():
    previous = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    try:
        response = TestClient(app).post(
            "/api/discovery/opportunity-discovery",
            headers={"Authorization": "Bearer valid-token"},
            json={"candidates": []},
        )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "identity_provider_unavailable"}}


def test_opportunity_discovery_denies_workspace_mismatch_and_client_workspace(discovery_client):
    mismatch = discovery_client.post(
        "/api/discovery/opportunity-discovery",
        headers={"Authorization": "Bearer valid-token", "X-MarketOS-Workspace": "workspace-other"},
        json={"candidates": []},
    )
    client_workspace = discovery_client.post(
        "/api/discovery/opportunity-discovery",
        headers={"Authorization": "Bearer client-token"},
        json={"candidates": []},
    )

    assert mismatch.status_code == 403
    assert mismatch.json() == {"detail": {"code": "workspace_not_authorized"}}
    assert client_workspace.status_code == 403
    assert client_workspace.json() == {"detail": {"code": "workspace_type_mismatch"}}


@pytest.mark.parametrize("location", ["query", "body"])
def test_opportunity_discovery_rejects_spoofed_workspace_selectors(discovery_client, location):
    kwargs = {"headers": {"Authorization": "Bearer valid-token"}, "json": {"candidates": []}}
    if location == "query":
        kwargs["params"] = {"mode": "evaluate", "workspace_id": "workspace-other"}
    else:
        kwargs["json"] = {"candidates": [], "workspace_id": "workspace-other"}

    response = discovery_client.post("/api/discovery/opportunity-discovery", **kwargs)

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "workspace_selector_rejected"}}


def test_opportunity_discovery_rejects_query_workspace_override(discovery_client):
    payload = _ready_opportunity_fixture()

    response = discovery_client.post(
        "/api/discovery/opportunity-discovery",
        params={"mode": "evaluate", "workspace_id": WORKSPACE_ID},
        headers={"Authorization": "Bearer valid-token"},
        json=payload,
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "workspace_selector_rejected"}}


def test_opportunity_discovery_adds_owner_projection_without_replacing_raw_run(discovery_client):
    from services.opportunity_discovery import run_discovery

    headers = {"Authorization": "Bearer valid-token"}
    payload = {"candidates": []}
    response = discovery_client.post("/api/discovery/opportunity-discovery", params={"mode": "evaluate"}, json=payload, headers=headers)
    assert response.status_code == 200
    body = response.json()
    raw = run_discovery("evaluate", payload, workspace=WorkspaceAccess(ISSUER, "owner", WORKSPACE_ID, "internal", "Owner")).to_dict()
    projection = body.pop("owner_opportunity")
    assert body == raw
    assert projection["snapshot_resolution"]["persisted"] is False
    assert projection["snapshot_resolution"]["resolver"] == "unavailable"
    assert projection["safety"]["ads_launched"] is False
    assert projection["safety"]["publishing"] is False
    assert projection["safety"]["launch_authorized"] is False
    assert projection["workspace_id"] == WORKSPACE_ID
    assert projection["workspace_binding"] == "injected"
    assert projection["authorized_workspace_id"] == WORKSPACE_ID
    denied = discovery_client.post("/api/discovery/opportunity-discovery", json=payload)
    assert denied.status_code == 401

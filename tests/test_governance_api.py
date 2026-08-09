from fastapi.testclient import TestClient


def test_governance_routes_return_safe_json(monkeypatch, tmp_path):
    from backend import api as backend_api
    from backend.organization import org_registry
    from backend.governance import registry as governance_registry
    from backend.organization.org_registry import OrganizationRegistry
    from backend.governance.registry import GovernanceRegistry
    monkeypatch.setattr(org_registry, "_singleton", OrganizationRegistry(tmp_path / "org.json"))
    monkeypatch.setattr(governance_registry, "_singleton", GovernanceRegistry(tmp_path / "gov.json"))
    with TestClient(backend_api.app) as client:
        assert client.post("/api/organization/bootstrap-defaults").status_code == 200
        response = client.post("/api/governance/run-loop", json={"objective": "x", "department": "product", "service": "unknown", "workspace_id": "w"})
        assert response.status_code == 200
        assert response.json()["status"] == "blocked"
        assert client.get("/api/governance/service-contracts").status_code == 200
        assert client.get("/api/governance/proposals/nope/decisions").json()["decisions"] == []
        assert client.get("/api/organization/defaults").status_code == 200
        proposal_id = response.json()["proposal"]["proposal_id"]
        transition = client.post(f"/api/governance/proposals/{proposal_id}/transition", json={"status": "completed"})
        assert transition.status_code == 200
        assert transition.json()["status"] == "invalid_transition"

from fastapi.testclient import TestClient


def test_governance_report_endpoints(monkeypatch, tmp_path):
    from backend import api as backend_api
    from backend.organization import org_registry, report_registry
    from backend.governance import registry as governance_registry
    from backend.organization.org_registry import OrganizationRegistry
    from backend.organization.report_registry import ReportRegistry
    from backend.governance.registry import GovernanceRegistry
    monkeypatch.setattr(org_registry, "_singleton", OrganizationRegistry(tmp_path / "org.json"))
    monkeypatch.setattr(governance_registry, "_singleton", GovernanceRegistry(tmp_path / "gov.json"))
    monkeypatch.setattr(report_registry, "_singleton", ReportRegistry(tmp_path / "reports.json"))
    with TestClient(backend_api.app) as client:
        result = client.post("/api/governance/run-loop", json={"objective": "Research bottle", "workspace_id": "w", "department": "product", "service": "product_research", "inputs": {"product_name": "Bottle", "category": "home"}}).json()
        report_id = result["report_id"]
        assert client.get("/api/governance/reports").json()["count"] >= 1
        assert client.get(f"/api/governance/reports/{report_id}").json()["report"]["report_id"] == report_id
        portfolio = client.post("/api/governance/portfolio-report", json={"workspace_id": "w"}).json()
        portfolio_id = portfolio["portfolio_report_id"]
        assert client.get(f"/api/governance/portfolio-reports/{portfolio_id}").json()["portfolio_report"]["report_ids"]
        assert client.get("/api/governance/reports/missing").json()["status"] == "not_found"


def test_empty_portfolio_api(monkeypatch, tmp_path):
    from backend import api as backend_api
    from backend.organization import report_registry
    from backend.organization.report_registry import ReportRegistry
    monkeypatch.setattr(report_registry, "_singleton", ReportRegistry(tmp_path / "reports.json"))
    with TestClient(backend_api.app) as client:
        result = client.post("/api/governance/portfolio-report", json={"workspace_id": "empty"}).json()
        assert result["portfolio_report"]["metadata"]["status"] == "empty"

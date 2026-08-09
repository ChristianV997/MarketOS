from backend.governance import registry as governance_registry
from backend.organization import org_registry, report_registry
from backend.organization.org_registry import OrganizationRegistry
from backend.organization.report_registry import ReportRegistry
from backend.organization.planner_executor_reviewer import run_planner_executor_reviewer


def test_planner_registers_report_and_returns_id(monkeypatch, tmp_path):
    monkeypatch.setattr(org_registry, "_singleton", OrganizationRegistry(tmp_path / "org.json"))
    monkeypatch.setattr(governance_registry, "_singleton", governance_registry.GovernanceRegistry(tmp_path / "gov.json"))
    monkeypatch.setattr(report_registry, "_singleton", ReportRegistry(tmp_path / "reports.json"))
    result = run_planner_executor_reviewer("Research", "w", "product", "product_research", {"product_name": "Bottle", "category": "home"})
    assert result["report_id"] == result["report"]["report_id"]
    assert report_registry.get_report_registry().get(result["report_id"]) is not None


def test_report_persistence_warning_does_not_change_execution(monkeypatch, tmp_path):
    monkeypatch.setattr(org_registry, "_singleton", OrganizationRegistry(tmp_path / "org.json"))
    monkeypatch.setattr(governance_registry, "_singleton", governance_registry.GovernanceRegistry(tmp_path / "gov.json"))
    class Broken:
        def register(self, report): raise OSError("read-only")
    monkeypatch.setattr("backend.organization.planner_executor_reviewer.get_report_registry", lambda: Broken())
    result = run_planner_executor_reviewer("Research", "w", "product", "product_research", {"product_name": "Bottle", "category": "home"})
    assert result["report_persistence"]["status"] == "warning"
    assert result["execution"]["dry_run"] is True

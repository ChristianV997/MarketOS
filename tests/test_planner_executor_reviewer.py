from backend.organization.org_registry import OrganizationRegistry
from backend.organization import org_registry
from backend.governance import registry as governance_registry
from backend.organization.planner_executor_reviewer import run_planner_executor_reviewer


def test_loop_blocks_live_action(monkeypatch, tmp_path):
    monkeypatch.setattr(org_registry, "_singleton", OrganizationRegistry(tmp_path / "org.json"))
    monkeypatch.setattr(governance_registry, "_singleton", governance_registry.GovernanceRegistry(tmp_path / "gov.json"))
    result = run_planner_executor_reviewer("research", "w", "product", "product_research", {}, live_action_requested=True)
    assert result["status"] == "blocked"
    assert result["approval"]["dry_run_safe"] is False


def test_loop_unknown_service_is_structured(monkeypatch, tmp_path):
    monkeypatch.setattr(org_registry, "_singleton", OrganizationRegistry(tmp_path / "org.json"))
    monkeypatch.setattr(governance_registry, "_singleton", governance_registry.GovernanceRegistry(tmp_path / "gov.json"))
    result = run_planner_executor_reviewer("x", "w", "product", "unknown", {})
    assert result["status"] in {"blocked", "completed"}
    assert isinstance(result["proposal"], dict)


def test_loop_rejects_live_input_even_without_top_level_flag(monkeypatch, tmp_path):
    monkeypatch.setattr(org_registry, "_singleton", OrganizationRegistry(tmp_path / "org.json"))
    monkeypatch.setattr(governance_registry, "_singleton", governance_registry.GovernanceRegistry(tmp_path / "gov.json"))
    result = run_planner_executor_reviewer("x", "w", "product", "product_research", {"confirm_live": True})
    assert result["status"] == "blocked"
    assert "live_execution_forbidden_in_governance_loop" in result["approval"]["blocked_reasons"]


def test_unavailable_service_is_not_completed(monkeypatch, tmp_path):
    monkeypatch.setattr(org_registry, "_singleton", OrganizationRegistry(tmp_path / "org.json"))
    monkeypatch.setattr(governance_registry, "_singleton", governance_registry.GovernanceRegistry(tmp_path / "gov.json"))
    result = run_planner_executor_reviewer("x", "w", "product", "product_research", {})
    assert result["status"] == "blocked"
    assert result["execution"]["status"] == "service_module_unavailable"

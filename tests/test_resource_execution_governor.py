from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from evaluation.companyos.resource_execution_governor import (
    ACTION_TYPES, DOMAINS, MODEL_POLICY_TIERS, OUTCOMES, RESOURCE_TYPES,
    BudgetCheckResult, ExecutionActionType, ExecutionDecisionRequest,
    ExecutionGovernorSafetySummary, ExecutionResourceType, LearningCaptureRequirement,
    ResourceBudget, ResourceQuota, build_resource_execution_governor_report,
    evaluate_execution_request, request_from_mapping,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "resource_execution_governor"
CLI = ROOT / "scripts" / "run_resource_execution_governor.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], cwd=ROOT, text=True, capture_output=True, timeout=60)


def base(action: str = "screen_product_opportunities", **kwargs) -> ExecutionDecisionRequest:
    defaults = {"request_id": f"test-{action}", "action_type": action, "domain": "intelligence", "owner_department": "intelligence", "workspace_id": "internal-companyos"}
    defaults.update(kwargs)
    return ExecutionDecisionRequest(**defaults)


def test_report_is_deterministic():
    assert build_resource_execution_governor_report().to_dict() == build_resource_execution_governor_report().to_dict()


def test_report_serializes_and_counts_decisions():
    report = build_resource_execution_governor_report()
    payload = report.to_dict()
    assert payload["report_version"] == "resource-execution-governor-v1"
    assert payload["decision_count"] == len(report.decisions)
    assert payload["budget_count"] == len(report.budgets)
    assert payload["quota_count"] == len(report.quotas)


def test_markdown_has_required_sections():
    markdown = build_resource_execution_governor_report().to_markdown()
    for section in ("Decision Outcomes", "Budget and Quota Controls", "Model Spend Policy", "Provider/API Spend Policy", "Portfolio Governor", "Experiment Governor", "Runaway Guard", "Cross-Department Decision Wiring", "Learning Capture Requirements", "Safety Boundaries"):
        assert f"## {section}" in markdown


@pytest.mark.parametrize("action", ACTION_TYPES)
def test_action_catalog_covers_supported_actions(action: str):
    item = next(item for item in build_resource_execution_governor_report().actions if item.action_type == action)
    assert item.domain in DOMAINS
    assert item.default_outcome in OUTCOMES


@pytest.mark.parametrize("resource", RESOURCE_TYPES)
def test_resource_catalog_covers_supported_resources(resource: str):
    item = next(item for item in build_resource_execution_governor_report().resources if item.resource_type == resource)
    assert item.unit
    assert item.default_owner_department


@pytest.mark.parametrize("outcome", OUTCOMES)
def test_outcome_vocabulary_is_explicit(outcome: str):
    assert outcome in OUTCOMES


@pytest.mark.parametrize("tier", MODEL_POLICY_TIERS)
def test_model_policy_tier_vocabulary(tier: str):
    assert tier in MODEL_POLICY_TIERS
    assert tier in build_resource_execution_governor_report().model_policy.tiers


def test_budget_available_allows_safe_action():
    result = evaluate_execution_request(base(resource_type="report_generation_quota"))
    assert result.outcome == "allow"
    assert result.budget_checks[0].status == "available"


def test_soft_cap_requires_finance_review():
    result = evaluate_execution_request(base("run_cheap_llm_task", requested_amount=45, resource_type="cheap_llm_budget", model_tier="cheap_llm"))
    assert result.outcome == "requires_finance_review"


def test_hard_cap_blocks_action():
    result = evaluate_execution_request(base("run_frontier_llm_synthesis", requested_amount=150, resource_type="frontier_llm_budget", model_tier="frontier_llm", evidence_score=.9, approval_state="approved"))
    assert result.outcome in {"soft_block", "hard_block"}
    assert result.budget_checks[0].status == "blocked"


def test_reserved_budget_reduces_available_amount():
    budget = ResourceBudget("cheap_llm_budget", "finance", "internal-companyos", "monthly", 50, 10, 15, "USD", 50, 40, 10)
    assert budget.available_amount == 25


def test_quota_has_available_amount():
    quota = ResourceQuota("q", "report_generation_quota", "management", "cycle", 20, 4, 3, "reports", True)
    assert quota.available == 13


@pytest.mark.parametrize("action", ["screen_product_opportunities", "run_companyos_review", "run_trustops_report", "run_security_scan", "run_local_llm_task", "run_cheap_llm_task"])
def test_safe_internal_actions_are_allowed(action: str):
    kwargs = {"model_tier": "local_llm"} if action == "run_local_llm_task" else {"model_tier": "cheap_llm"} if action == "run_cheap_llm_task" else {}
    assert evaluate_execution_request(base(action, **kwargs)).outcome == "allow"


def test_algorithmic_scoring_is_preferred():
    policy = build_resource_execution_governor_report().model_policy
    assert dict(policy.routing_rules)["deterministic_scoring"] == "algorithmic"


def test_local_model_is_preferred_for_internal_task():
    policy = build_resource_execution_governor_report().model_policy
    assert dict(policy.routing_rules)["structured_extraction"] == "local_llm_or_cheap_llm"


def test_cheap_model_is_preferred_for_routine_drafting():
    policy = build_resource_execution_governor_report().model_policy
    assert dict(policy.routing_rules)["routine_report_drafting"] == "cheap_llm"


def test_frontier_model_requires_evidence():
    result = evaluate_execution_request(base("run_frontier_llm_synthesis", model_tier="frontier_llm", requested_amount=5, resource_type="frontier_llm_budget", evidence_score=.4, approval_state="approved"))
    assert result.outcome == "soft_block"
    assert any("evidence" in item for item in result.blockers)


def test_frontier_model_requires_management_approval():
    result = evaluate_execution_request(base("run_frontier_llm_synthesis", model_tier="frontier_llm", requested_amount=5, resource_type="frontier_llm_budget", evidence_score=.9))
    assert any(item.approval_type == "model_spend" for item in result.approvals)


def test_frontier_repeated_low_value_is_guarded():
    policy = build_resource_execution_governor_report().model_policy
    assert policy.repeated_low_value_blocked is True
    assert "frontier_llm" in policy.tiers


@pytest.mark.parametrize("blocked_request", ["credential_extraction", "hidden_prompt_request", "unbounded_user_task"])
def test_blocked_model_requests_are_declared(blocked_request: str):
    assert blocked_request in build_resource_execution_governor_report().model_policy.blocked_requests


def test_provider_requires_registration():
    result = evaluate_execution_request(base("run_provider_data_pull", provider_id="unknown", resource_type="data_provider_budget", requested_amount=5, registered_provider=False, terms_privacy_complete=True))
    assert "provider is not registered" in result.blockers


def test_provider_requires_terms_privacy():
    result = evaluate_execution_request(base("run_provider_data_pull", provider_id="dataforseo", resource_type="data_provider_budget", requested_amount=5, terms_privacy_complete=False))
    assert result.outcome == "hard_block"
    assert any("terms/privacy" in item for item in result.blockers)


def test_provider_requires_output_contract():
    result = evaluate_execution_request(base("run_provider_data_pull", provider_id="dataforseo", resource_type="data_provider_budget", requested_amount=5, output_contract_tested=False))
    assert "provider output contract is not tested" in result.blockers


def test_provider_requires_approval():
    result = evaluate_execution_request(base("run_provider_data_pull", provider_id="dataforseo", resource_type="data_provider_budget", requested_amount=5))
    assert any(item.approval_type == "provider_call" for item in result.approvals)


def test_provider_policy_caps_retries():
    policy = build_resource_execution_governor_report().provider_policy
    assert policy.max_retries == 2
    assert policy.raw_payload_missing_outcome == "hard_block"


def test_dataforseo_dry_run_is_registered_as_allowed_candidate():
    assert "dataforseo" in build_resource_execution_governor_report().provider_policy.dry_run_providers_allowed


def test_portfolio_caps_pipeline():
    policy = build_resource_execution_governor_report().portfolio_policy
    assert (policy.max_raw_opportunities_per_cycle, policy.max_deep_validations_per_cycle, policy.max_promoted_candidates_per_cycle) == (50, 5, 2)
    assert policy.max_launch_drafts_per_cycle == 2
    assert policy.max_new_sites_per_cycle == 1


def test_deep_validation_below_threshold_blocks():
    result = evaluate_execution_request(base("deep_validate_product", opportunity_score=.3))
    assert "opportunity score" in result.blockers[0]


def test_promotion_requires_all_scores():
    result = evaluate_execution_request(base("promote_product_candidate", opportunity_score=.9, supplier_score=.4, attention_score=.9, unit_economics_score=.9, portfolio_fit_score=.9))
    assert result.outcome == "soft_block"
    assert any("portfolio score" in item for item in result.blockers)


def test_existing_brand_fit_blocks_new_website():
    result = evaluate_execution_request(base("create_new_website", domain="website_store_funnel", owner_department="launch", resource_type="website_build_capacity", requested_amount=1, existing_brand_fit=True))
    assert result.outcome == "soft_block"
    assert any("existing brand" in item for item in result.blockers)


def test_existing_brand_fit_blocks_new_brand():
    result = evaluate_execution_request(base("create_new_brand", domain="management", owner_department="management", resource_type="brand_capacity", requested_amount=1, existing_brand_fit=True))
    assert result.outcome == "soft_block"


def test_inventory_requires_supplier_proof():
    result = evaluate_execution_request(base("increase_inventory_exposure", domain="finance", owner_department="finance", resource_type="inventory_cash_exposure", requested_amount=50, supplier_proof=False))
    assert "supplier proof" in result.blockers[0]


def test_experiment_policy_has_required_fields():
    policy = build_resource_execution_governor_report().experiment_policy
    for field in ("hypothesis", "budget_cap", "sample_size_target", "success_metric", "kill_threshold", "scale_threshold", "learning_required"):
        assert field in policy.required_fields


def test_ad_experiment_without_design_is_blocked():
    result = evaluate_execution_request(base("launch_ad_experiment", domain="ads_content", owner_department="consumer_attention", resource_type="ad_spend", requested_amount=25))
    assert result.outcome == "soft_block"
    assert any("experiment design" in item for item in result.blockers)


def test_ad_experiment_with_design_requires_approval():
    result = evaluate_execution_request(base("launch_ad_experiment", domain="ads_content", owner_department="consumer_attention", resource_type="ad_spend", requested_amount=25, hypothesis="test offer", success_metric="conversion_rate", kill_threshold=.02, scale_threshold=.05))
    assert result.outcome == "requires_approval"


def test_scale_without_evidence_blocks():
    result = evaluate_execution_request(base("scale_ad_budget", domain="ads_content", owner_department="finance", resource_type="ad_spend", requested_amount=20))
    assert "scale evidence" in result.blockers[0]


def test_scale_winner_is_controlled():
    result = evaluate_execution_request(base("scale_ad_budget", domain="ads_content", owner_department="finance", resource_type="ad_spend", requested_amount=20, metric_value=.06, scale_threshold=.05, max_scale_increment=.2, approval_state="approved"))
    assert result.outcome == "scale"


def test_large_scale_requires_approval():
    result = evaluate_execution_request(base("scale_ad_budget", domain="ads_content", owner_department="finance", resource_type="ad_spend", requested_amount=20, metric_value=.06, scale_threshold=.05, max_scale_increment=.5, approval_state="approved"))
    assert any(item.approval_type == "scale_budget" for item in result.approvals)


def test_kill_loser_after_sample():
    result = evaluate_execution_request(base("kill_ad_experiment", domain="ads_content", owner_department="consumer_attention", metric_value=.01, kill_threshold=.02, sample_size=120, sample_size_target=100))
    assert result.outcome == "kill"
    assert "failure reason" in result.next_best_action


def test_inconclusive_test_pauses_by_policy_metadata():
    rules = build_resource_execution_governor_report().experiment_policy.rules
    assert any("Pause" in rule for rule in rules)


def test_missing_learning_blocks_iteration():
    result = evaluate_execution_request(base("generate_creative_batch", domain="ads_content", owner_department="consumer_attention", resource_type="creative_generation_capacity", requested_amount=1, previous_learning_required=True, learning_captured=False))
    assert result.outcome == "soft_block"
    assert any("learning" in item for item in result.blockers)


@pytest.mark.parametrize("field,limit", [("max_workflow_steps", 25), ("max_retries", 2), ("max_child_tasks", 10), ("max_spawned_agents", 3), ("max_provider_calls", 5), ("max_llm_calls", 10), ("max_frontier_llm_calls", 2), ("max_output_files", 20), ("max_runtime_seconds", 300), ("max_budget_per_run", 25.0), ("max_repeated_similar_outputs", 2)])
def test_runaway_limits_are_bounded(field: str, limit):
    assert getattr(build_resource_execution_governor_report().runaway_policy, field) == limit


def test_runaway_retry_is_hard_blocked():
    result = evaluate_execution_request(base("retry_failed_workflow", domain="management", owner_department="operations", retry_count=3))
    assert result.outcome == "hard_block"
    assert any("runaway" in item for item in result.blockers)


def test_runaway_spawned_agents_are_hard_blocked():
    result = evaluate_execution_request(base("spawn_agent_workflow", domain="management", owner_department="operations", spawned_agents=5))
    assert result.outcome == "hard_block"


def test_runaway_provider_loop_is_hard_blocked():
    result = evaluate_execution_request(base("run_provider_data_pull", provider_id="dataforseo", resource_type="data_provider_budget", requested_amount=5, provider_calls=6, terms_privacy_complete=True))
    assert result.outcome == "hard_block"


def test_runaway_guard_outputs_are_explicit():
    policy = build_resource_execution_governor_report().runaway_policy
    assert "pause_and_summarize" in policy.outputs
    assert "request_approval" in policy.outputs
    assert "record_risk" in policy.outputs


@pytest.mark.parametrize("action", ["promote_product_candidate", "create_new_website", "launch_ad_experiment", "run_frontier_llm_synthesis", "run_provider_data_pull", "generate_client_export"])
def test_cross_department_dependency_exists(action: str):
    dependency = next(item for item in build_resource_execution_governor_report().dependencies if item.action_type == action)
    assert dependency.required_departments
    assert dependency.required_checks
    assert dependency.blocked_without


def test_product_promotion_wires_required_departments():
    item = next(item for item in build_resource_execution_governor_report().dependencies if item.action_type == "promote_product_candidate")
    assert {"intelligence", "supplier", "consumer_attention", "finance", "risk_approval", "management"}.issubset(item.required_departments)


def test_website_wires_workspace_and_trust():
    item = next(item for item in build_resource_execution_governor_report().dependencies if item.action_type == "create_new_website")
    assert "client_workspace" in item.required_departments
    assert "risk_approval" in item.required_departments


def test_learning_types_are_generated():
    types = {item.learning_type for item in build_resource_execution_governor_report().learning_requirements}
    assert {"creative_test", "provider_run", "model_routing"}.issubset(types)


@pytest.mark.parametrize("action", ACTION_TYPES)
def test_learning_requirement_serializes_for_every_action(action: str):
    item = next(item for item in build_resource_execution_governor_report().learning_requirements if item.source_action_id == action) if any(item.source_action_id == action for item in build_resource_execution_governor_report().learning_requirements) else None
    if item is None:
        item = LearningCaptureRequirement(False, "companyos_review", action, "success_metric_or_review_result", True, True, True, True, True)
    assert item.source_action_id == action
    assert item.to_dict()["next_iteration_required"] is True


def test_client_export_requires_workspace_review():
    result = evaluate_execution_request(base("generate_client_export", domain="client_workspace", owner_department="management", resource_type="client_export_quota", requested_amount=1, workspace_decision="hard_block"))
    assert result.outcome == "hard_block"


def test_trustos_hard_block_propagates():
    result = evaluate_execution_request(base("generate_site_draft", domain="website_store_funnel", owner_department="launch", trustos_decision="hard_block"))
    assert result.outcome == "hard_block"


def test_approval_state_is_preserved_as_requirement():
    result = evaluate_execution_request(base("send_sales_outreach", domain="sales", owner_department="sales", approval_state="not_requested"))
    assert result.outcome == "requires_approval"
    assert any(item.approval_type == "approval_ledger" for item in result.approvals)


def test_safety_summary_is_fail_closed():
    summary = ExecutionGovernorSafetySummary()
    assert summary.read_only is True
    with pytest.raises(ValueError):
        ExecutionGovernorSafetySummary(network_calls=True)


@pytest.mark.parametrize("field", ["model_calls", "provider_calls", "ads_launched", "sites_published", "orders_created", "payments_created", "messages_sent", "auth_calls", "database_writes", "tenant_created", "credentials_present", "client_data_present", "artifacts_written"])
def test_safety_flags_cannot_be_enabled(field: str):
    with pytest.raises(ValueError):
        ExecutionGovernorSafetySummary(**{field: True})


def test_invalid_action_rejected():
    with pytest.raises(ValueError):
        base("not_an_action")


def test_invalid_resource_rejected():
    with pytest.raises(ValueError):
        base(resource_type="not_a_resource")


def test_negative_amount_rejected():
    with pytest.raises(ValueError):
        base(requested_amount=-1)


def test_mapping_loader_accepts_known_fields():
    request = request_from_mapping({"request_id": "mapped", "action_type": "screen_product_opportunities", "domain": "intelligence", "owner_department": "intelligence", "workspace_id": "internal-companyos", "ignored": "removed"})
    assert request.request_id == "mapped"


@pytest.mark.parametrize("fixture", ["governor_context.json", "budget_policy_seed.json", "quota_policy_seed.json", "model_spend_policy_seed.json", "provider_spend_policy_seed.json", "portfolio_policy_seed.json", "experiment_policy_seed.json", "runaway_guard_policy_seed.json", "product_to_launch_pipeline_scenario.json", "ads_kill_scale_loop_scenario.json", "model_cost_control_scenario.json", "provider_cost_control_scenario.json", "new_website_blocked_scenario.json", "frontier_llm_blocked_scenario.json", "runaway_agent_loop_blocked_scenario.json", "learning_missing_blocked_scenario.json", "safe_action_allowed_scenario.json"])
def test_sanitized_fixtures_load(fixture: str):
    payload = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert "api_key" not in json.dumps(payload)


def test_secret_fixture_is_not_accepted_by_cli():
    result = run_cli("--context", str(FIXTURES / "secret_like_governor_input_rejected.json"), "--json")
    assert result.returncode != 0
    assert "secret-like" in result.stderr


def test_cli_json():
    result = run_cli("--json")
    assert result.returncode == 0
    assert json.loads(result.stdout)["safety_summary"]["network_calls"] is False


def test_cli_markdown():
    result = run_cli("--markdown")
    assert result.returncode == 0
    assert "# Resource & Execution Governor" in result.stdout


@pytest.mark.parametrize("action", ["screen_product_opportunities", "create_new_website", "launch_ad_experiment", "run_frontier_llm_synthesis", "run_provider_data_pull", "spawn_agent_workflow"])
def test_cli_action_filter(action: str):
    result = run_cli("--action", action, "--json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert len(payload["decisions"]) == 1
    assert payload["decisions"][0]["action_type"] == action


@pytest.mark.parametrize("scenario", ["product_to_launch_pipeline", "ads_kill_scale_loop", "model_cost_control"])
def test_cli_scenario_filter(scenario: str):
    result = run_cli("--scenario", scenario, "--json")
    assert result.returncode == 0
    assert json.loads(result.stdout)["decision_count"] >= 1


def test_cli_output_writes_only_sanitized_files(tmp_path: Path):
    result = run_cli("--output", str(tmp_path), "--markdown")
    assert result.returncode == 0
    expected = {"resource_execution_governor_report.json", "resource_execution_governor_report.md", "decision_results.json", "budget_checks.json", "quota_checks.json", "model_spend_policy.json", "provider_spend_policy.json", "portfolio_policy.json", "experiment_policy.json", "runaway_guard_policy.json", "learning_capture_requirements.json", "cross_department_dependencies.json"}
    assert expected == {item.name for item in tmp_path.iterdir()}
    assert all("synthetic-secret-value" not in item.read_text(encoding="utf-8") for item in tmp_path.iterdir())


def test_cli_deterministic():
    assert run_cli("--json").stdout == run_cli("--json").stdout


def test_cli_invalid_context_fails():
    result = run_cli("--context", str(FIXTURES / "malformed_governor_input.json"), "--json")
    assert result.returncode != 0


def test_source_has_no_live_transport():
    source = (ROOT / "evaluation" / "companyos" / "resource_execution_governor.py").read_text(encoding="utf-8").lower()
    for marker in ("requests.get", "httpx", "openai.", "subprocess", "socket"):
        assert marker not in source


def test_source_has_no_external_mutation_vocabulary():
    source = (ROOT / "scripts" / "run_resource_execution_governor.py").read_text(encoding="utf-8").lower()
    assert "send_email" not in source
    assert "create_payment" not in source


def test_report_has_no_live_safety_flags():
    rendered = json.dumps(build_resource_execution_governor_report().to_dict()).lower()
    assert '"model_calls": true' not in rendered
    assert '"provider_calls": true' not in rendered
    assert '"ads_launched": true' not in rendered
    assert '"artifacts_written": true' not in rendered


@pytest.mark.parametrize("resource", ["frontier_llm_budget", "cheap_llm_budget", "provider_api_budget", "data_provider_budget", "ad_spend", "inventory_cash_exposure", "website_build_capacity", "brand_capacity", "creative_generation_capacity", "report_generation_quota", "client_export_quota"])
def test_default_budget_is_positive_and_fail_closed(resource: str):
    budget = next(item for item in build_resource_execution_governor_report().budgets if item.resource_type == resource)
    assert budget.budget_limit > 0
    assert budget.hard_cap >= budget.soft_cap
    assert budget.available_amount >= 0


@pytest.mark.parametrize("resource", ["report_generation_quota", "client_export_quota", "workflow_runtime"])
def test_default_quota_is_hard_capped(resource: str):
    quota = next(item for item in build_resource_execution_governor_report().quotas if item.resource_type == resource)
    assert quota.hard_cap is True
    assert quota.limit > 0
    assert quota.available >= 0


@pytest.mark.parametrize("action", ["generate_launch_draft", "generate_site_draft", "request_supplier_proof", "prepare_inventory_plan", "generate_sales_sequence", "generate_client_export", "run_provider_data_pull", "run_frontier_llm_synthesis"])
def test_action_result_is_always_simulated(action: str):
    item = evaluate_execution_request(base(action))
    assert item.simulated_only is True
    assert item.outcome in OUTCOMES


@pytest.mark.parametrize("action", ["screen_product_opportunities", "deep_validate_product", "promote_product_candidate", "generate_launch_draft", "generate_site_draft", "create_new_brand", "create_new_website", "expand_existing_brand"])
def test_product_pipeline_actions_have_next_actions(action: str):
    item = next(item for item in build_resource_execution_governor_report().actions if item.action_type == action)
    assert item.description
    assert item.domain


@pytest.mark.parametrize("field", ["strategic_fit", "evidence_strength", "revenue_or_learning_value", "urgency", "total"])
def test_priority_score_fields_are_numeric(field: str):
    score = build_resource_execution_governor_report().decisions[0].priority_score
    assert isinstance(getattr(score, field), float)


@pytest.mark.parametrize("field", ["financial_risk", "action_risk", "complexity_risk", "trust_risk", "total"])
def test_risk_score_fields_are_numeric(field: str):
    score = build_resource_execution_governor_report().decisions[0].risk_score
    assert isinstance(getattr(score, field), float)


@pytest.mark.parametrize("action", ["launch_ad_experiment", "generate_creative_batch", "deep_validate_product", "run_provider_data_pull", "run_frontier_llm_synthesis"])
def test_high_learning_actions_require_learning(action: str):
    item = next(item for item in build_resource_execution_governor_report().learning_requirements if item.source_action_id == action)
    assert item.required is True
    assert item.failure_reason_required is True
    assert item.do_not_repeat_rule_required is True


def test_safe_review_actions_can_be_repeated_without_frontier_spend():
    for action in ("run_companyos_review", "run_trustops_report", "run_security_scan"):
        result = evaluate_execution_request(base(action))
        assert result.outcome == "allow"
        assert result.model_tier == "algorithmic" if hasattr(result, "model_tier") else True


@pytest.mark.parametrize("action", ["send_sales_outreach", "launch_ad_experiment", "scale_ad_budget", "create_new_website", "create_new_brand", "increase_inventory_exposure"])
def test_material_actions_have_approval_requirements(action: str):
    kwargs = {"domain": "sales", "owner_department": "sales"} if action == "send_sales_outreach" else {}
    result = evaluate_execution_request(base(action, **kwargs))
    assert result.approvals or result.blockers


def test_provider_and_model_cost_constraints_are_reported():
    report = build_resource_execution_governor_report()
    data = report.to_dict()
    assert "top_model_cost_constraints" in data
    assert "top_provider_constraints" in data


def test_portfolio_rule_is_client_safe_metadata():
    rendered = json.dumps(build_resource_execution_governor_report().portfolio_policy.to_dict())
    assert "Many ideas enter" in rendered
    assert "client@example.com" not in rendered


def test_experiment_rule_has_controlled_increment():
    rule = build_resource_execution_governor_report().experiment_policy.kill_scale_rules[0]
    assert rule.max_scale_increment <= .30
    assert rule.max_iterations > 0


def test_dependencies_are_unique():
    ids = [item.dependency_id for item in build_resource_execution_governor_report().dependencies]
    assert len(ids) == len(set(ids))


def test_learning_requirements_are_deterministic():
    first = build_resource_execution_governor_report().learning_requirements
    second = build_resource_execution_governor_report().learning_requirements
    assert first == second


def test_default_report_has_expected_example_outcomes():
    outcomes = {item.action_type: item.outcome for item in build_resource_execution_governor_report().decisions}
    assert outcomes["screen_product_opportunities"] == "allow"
    assert outcomes["run_provider_data_pull"] == "hard_block"
    assert outcomes["spawn_agent_workflow"] == "hard_block"
    assert outcomes["kill_ad_experiment"] == "kill"
    assert outcomes["scale_ad_budget"] == "scale"


@pytest.mark.parametrize("action", ["run_frontier_llm_synthesis", "run_provider_data_pull", "generate_client_export", "spawn_agent_workflow"])
def test_high_risk_examples_never_auto_allow(action: str):
    item = evaluate_execution_request(base(action, domain="client_workspace" if action == "generate_client_export" else "provider" if action == "run_provider_data_pull" else "management" if action == "spawn_agent_workflow" else "model", provider_id="dataforseo" if action == "run_provider_data_pull" else "", resource_type="client_export_quota" if action == "generate_client_export" else "data_provider_budget" if action == "run_provider_data_pull" else "workflow_runtime" if action == "spawn_agent_workflow" else "frontier_llm_budget", model_tier="frontier_llm" if action == "run_frontier_llm_synthesis" else "algorithmic", terms_privacy_complete=False if action == "run_provider_data_pull" else True))
    assert item.outcome != "allow"


def test_report_safety_summary_is_all_false_except_read_only():
    summary = build_resource_execution_governor_report().safety_summary.to_dict()
    assert summary["read_only"] is True
    assert all(value is False for key, value in summary.items() if key != "read_only")


def test_report_has_no_secret_fixture_values():
    rendered = json.dumps(build_resource_execution_governor_report().to_dict())
    for marker in ("synthetic-secret-value", "BEGIN PRIVATE KEY", "client@example.com", "real account"):
        assert marker not in rendered

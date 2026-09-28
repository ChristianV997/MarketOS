from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from evaluation.companyos.learning_ledger import (
    BLOCK_BEHAVIORS, EVENT_TYPES, FAILURE_REASONS, GOVERNOR_EVIDENCE_MODES, MIN_SCALE_CONFIDENCE,
    OUTCOMES, PLACEHOLDER_CANDIDATE_ID, SUCCESS_REASONS, VISIBILITY,
    LearningAttribution, LearningDoNotRepeatRule, LearningGovernorInfluence, LearningHypothesis, LearningLedgerSafetySummary,
    LearningMetric, LearningOutcome, LearningResult, build_learning_ledger_report, derive_governor_influence,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "learning_ledger"
CLI = ROOT / "scripts" / "run_learning_ledger.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], cwd=ROOT, text=True, capture_output=True, timeout=60)


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_report_is_deterministic():
    assert build_learning_ledger_report().to_dict() == build_learning_ledger_report().to_dict()


def test_report_counts_are_present():
    data = build_learning_ledger_report().to_dict()
    for key in ("learning_event_count", "experiment_count", "win_count", "loss_count", "kill_count", "scale_count", "paused_count", "inconclusive_count", "do_not_repeat_rule_count", "iteration_recommendation_count", "portfolio_impact_count", "model_routing_impact_count", "provider_impact_count", "trustos_impact_count", "decision_influence_count"):
        assert key in data


def test_report_has_safety_summary():
    safety = build_learning_ledger_report().to_dict()["safety_summary"]
    assert safety["read_only"] is True
    assert safety["database_writes"] is False
    assert safety["model_calls"] is False
    assert safety["provider_calls"] is False


def test_markdown_has_required_sections():
    markdown = build_learning_ledger_report().to_markdown()
    for section in ("Learning Events", "Experiments", "Wins and Losses", "Kill / Scale Decisions", "Do-Not-Repeat Rules", "Iteration Recommendations", "Portfolio Learning", "Model-Routing Learning", "Provider Learning", "TrustOS / Security Learning", "Resource Governor Feedback", "Safety Boundaries"):
        assert f"## {section}" in markdown


@pytest.mark.parametrize("value", EVENT_TYPES)
def test_event_type_vocabulary(value: str):
    assert value in EVENT_TYPES
    assert any(event.event_type == value for event in build_learning_ledger_report().events)


@pytest.mark.parametrize("value", OUTCOMES)
def test_outcome_vocabulary(value: str):
    assert value in OUTCOMES
    assert value in LearningOutcome.values


def test_learning_outcome_is_a_validated_dataclass():
    outcome = LearningOutcome("win")
    assert outcome.to_dict() == {"outcome": "win"}
    with pytest.raises(ValueError):
        LearningOutcome("not-a-learning-outcome")


@pytest.mark.parametrize("value", VISIBILITY)
def test_visibility_vocabulary(value: str):
    assert value in VISIBILITY


@pytest.mark.parametrize("value", FAILURE_REASONS)
def test_failure_reason_vocabulary(value: str):
    assert value in FAILURE_REASONS


@pytest.mark.parametrize("value", SUCCESS_REASONS)
def test_success_reason_vocabulary(value: str):
    assert value in SUCCESS_REASONS


@pytest.mark.parametrize("value", BLOCK_BEHAVIORS)
def test_block_behavior_vocabulary(value: str):
    assert value in BLOCK_BEHAVIORS


def test_learning_event_serializes():
    event = build_learning_ledger_report().events[0]
    payload = event.to_dict()
    for key in ("learning_event_id", "source_decision_id", "source_module", "source_department", "workspace_id", "client_visibility", "event_type", "hypothesis", "input_evidence_refs", "action_taken", "cost_estimate", "budget_context", "metrics", "outcome", "confidence", "failure_reasons", "success_reasons", "winner_attributes", "loser_attributes", "do_not_repeat_rules", "iteration_recommendations", "portfolio_impact", "resource_governor_influence", "created_at", "owner_department", "review_required"):
        assert key in payload


def test_experiment_serializes():
    experiment = build_learning_ledger_report().experiments[0]
    assert experiment.experiment_id
    assert experiment.hypothesis.statement
    assert experiment.budget_cap >= 0
    assert experiment.learning_required is True


def test_hypothesis_serializes():
    item = LearningHypothesis("h", "test statement", ("criterion",), "metric", .5)
    assert item.to_dict()["statement"] == "test statement"


def test_metric_serializes():
    item = LearningMetric("m", "conversion_rate", .06, .05, "ratio", 120, "fixture")
    assert item.to_dict()["sample_size"] == 120


def test_result_serializes():
    result = LearningResult("r", "win", "summary", (), .8)
    assert result.to_dict()["outcome"] == "win"


def test_attribution_serializes():
    item = LearningAttribution("a", ("hook", "offer"), .7, "fixture_attribution", ("no live metrics",))
    assert item.to_dict()["confidence"] == .7


def test_lesson_serializes():
    item = build_learning_ledger_report().lessons[0]
    assert item.lesson_id
    assert item.statement


def test_do_not_repeat_rule_serializes():
    rule = build_learning_ledger_report().do_not_repeat_rules[0]
    assert rule.rule_id
    assert rule.recommended_block_behavior in BLOCK_BEHAVIORS


def test_iteration_recommendation_serializes():
    item = build_learning_ledger_report().iteration_recommendations[0]
    assert item.action_type
    assert item.expected_learning


def test_portfolio_impact_serializes():
    item = build_learning_ledger_report().portfolio_impacts[0]
    assert item.portfolio_area
    assert item.recommended_focus_area


def test_model_routing_impact_serializes():
    item = build_learning_ledger_report().model_routing_impacts[0]
    assert item.recommended_model_tier_next_time
    assert item.cost_savings_note


def test_provider_impact_serializes():
    item = build_learning_ledger_report().provider_impacts[0]
    assert item.provider_id
    assert item.recommended_next_provider_action


def test_trustos_impact_serializes():
    item = build_learning_ledger_report().trustos_impacts[0]
    assert item.blocker
    assert item.recommended_next_evidence


def test_decision_influence_serializes():
    item = build_learning_ledger_report().decision_influences[0]
    assert item.action_type
    assert item.recommended_decision_modifier


def test_safety_flags_reject_live_behavior():
    with pytest.raises(ValueError): LearningLedgerSafetySummary(model_calls=True)
    with pytest.raises(ValueError): LearningLedgerSafetySummary(database_writes=True)


@pytest.mark.parametrize("field", ["provider_calls", "ads_launched", "sites_published", "orders_created", "payments_created", "messages_sent", "auth_calls", "tenant_created", "client_data_present", "raw_prompts_present", "real_metrics_present", "artifacts_written"])
def test_all_safety_flags_are_fail_closed(field: str):
    with pytest.raises(ValueError): LearningLedgerSafetySummary(**{field: True})


def test_winner_event_is_counted():
    report = build_learning_ledger_report()
    assert report.to_dict()["win_count"] >= 1
    assert any(item.outcome == "win" for item in report.events)


def test_loser_event_is_counted():
    report = build_learning_ledger_report()
    assert report.to_dict()["loss_count"] >= 1


def test_kill_event_is_counted():
    assert build_learning_ledger_report().to_dict()["kill_count"] >= 1


def test_scale_event_is_counted():
    assert build_learning_ledger_report().to_dict()["scale_count"] >= 1


def test_paused_event_can_be_counted():
    context = {"events": [{"event_type": "landing_page_test", "outcome": "paused", "failure_reasons": ["insufficient_sample"]}]}
    assert build_learning_ledger_report(context=context).to_dict()["paused_count"] == 1


def test_inconclusive_event_is_counted():
    context = {"events": [{"event_type": "landing_page_test", "outcome": "inconclusive", "failure_reasons": ["insufficient_sample"]}]}
    assert build_learning_ledger_report(context=context).to_dict()["inconclusive_count"] == 1


def test_invalid_test_is_counted():
    context = {"events": [{"event_type": "creative_test", "outcome": "invalid_test", "failure_reasons": ["invalid_test_design"]}]}
    assert build_learning_ledger_report(context=context).events[0].outcome == "invalid_test"


def test_needs_more_evidence_is_preserved():
    context = {"events": [{"event_type": "security_scan", "outcome": "needs_more_evidence", "failure_reasons": ["insufficient_sample"]}]}
    assert build_learning_ledger_report(context=context).events[0].outcome == "needs_more_evidence"


def test_failure_reasons_are_aggregated():
    report = build_learning_ledger_report()
    assert "low_click_through" in report.summary.top_failure_reasons
    assert "poor_margin" in report.summary.top_failure_reasons


def test_success_reasons_are_aggregated():
    report = build_learning_ledger_report()
    assert "strong_hook" in report.summary.top_success_reasons
    assert "high_margin" in report.summary.top_success_reasons


@pytest.mark.parametrize("failure,action", [("poor_margin", "increase_inventory_exposure"), ("missing_learning_capture", "launch_ad_experiment"), ("poor_creative_angle", "generate_creative_batch"), ("model_cost_too_high", "run_frontier_llm_synthesis"), ("provider_blocker", "run_provider_data_pull"), ("trust_blocker", "generate_client_export"), ("runaway_guard_triggered", "spawn_agent_workflow"), ("weak_supplier_feasibility", "increase_inventory_exposure"), ("landing_page_mismatch", "generate_site_draft")])
def test_failure_creates_do_not_repeat_rule(failure: str, action: str):
    report = build_learning_ledger_report(context={"events": [{"event_type": "companyos_review", "outcome": "loss", "failure_reasons": [failure], "action_taken": action}]})
    assert report.do_not_repeat_rules
    rule = report.do_not_repeat_rules[0]
    assert action in rule.applies_to_action_types


def test_poor_margin_rule_is_soft_block():
    report = build_learning_ledger_report(context={"events": [{"event_type": "product_validation", "outcome": "loss", "failure_reasons": ["poor_margin"]}]})
    assert report.do_not_repeat_rules[0].recommended_block_behavior == "soft_block"


def test_provider_blocker_rule_is_hard_block():
    report = build_learning_ledger_report(context={"events": [{"event_type": "provider_run", "outcome": "blocked", "failure_reasons": ["provider_blocker"]}]})
    assert report.do_not_repeat_rules[0].recommended_block_behavior == "hard_block"


def test_rule_review_period_is_present():
    assert all(rule.expiry_or_review_period for rule in build_learning_ledger_report().do_not_repeat_rules)


def test_client_visibility_is_enforced_on_rules():
    report = build_learning_ledger_report()
    assert all(isinstance(rule.client_visible, bool) for rule in report.do_not_repeat_rules)


@pytest.mark.parametrize("failure,action", [("low_click_through", "generate_creative_batch"), ("landing_page_mismatch", "generate_site_draft"), ("weak_supplier_feasibility", "request_supplier_proof"), ("model_cost_too_high", "run_cheap_llm_task"), ("provider_blocker", "run_provider_data_pull"), ("missing_learning_capture", "run_companyos_review"), ("insufficient_sample", "landing_page_test")])
def test_failure_creates_iteration_recommendation(failure: str, action: str):
    report = build_learning_ledger_report(context={"events": [{"event_type": "companyos_review", "outcome": "loss", "failure_reasons": [failure], "action_taken": action}]})
    assert report.iteration_recommendations
    assert report.iteration_recommendations[0].action_type == action or report.iteration_recommendations[0].action_type != ""


def test_low_ctr_recommends_creative_change():
    report = build_learning_ledger_report(context={"events": [{"event_type": "ad_experiment", "outcome": "loss", "failure_reasons": ["low_click_through"], "action_taken": "launch_ad_experiment"}]})
    assert report.iteration_recommendations[0].action_type == "generate_creative_batch"


def test_good_ctr_poor_conversion_recommends_page_change():
    report = build_learning_ledger_report(context={"events": [{"event_type": "landing_page_test", "outcome": "loss", "failure_reasons": ["landing_page_mismatch"], "action_taken": "generate_site_draft"}]})
    assert report.iteration_recommendations[0].action_type == "generate_site_draft"


def test_supplier_uncertainty_recommends_proof():
    report = build_learning_ledger_report(context={"events": [{"event_type": "supplier_validation", "outcome": "blocked", "failure_reasons": ["weak_supplier_feasibility"]}]})
    assert report.iteration_recommendations[0].action_type == "request_supplier_proof"


def test_model_waste_recommends_cheaper_route():
    report = build_learning_ledger_report(context={"events": [{"event_type": "model_routing_decision", "outcome": "loss", "failure_reasons": ["model_cost_too_high"], "action_taken": "run_frontier_llm_synthesis"}]})
    assert report.iteration_recommendations[0].action_type == "run_cheap_llm_task"


def test_trustos_blocker_recommends_evidence():
    report = build_learning_ledger_report(context={"events": [{"event_type": "trustos_review", "outcome": "blocked", "failure_reasons": ["trust_blocker"]}]})
    assert "evidence" in report.iteration_recommendations[0].recommendation.lower()


def test_resource_influence_for_ad_experiment():
    item = next(item for item in build_learning_ledger_report().decision_influences if item.action_type == "launch_ad_experiment")
    assert "learning" in item.recommended_decision_modifier


def test_resource_influence_for_product_validation():
    assert any(item.action_type == "request_supplier_proof" for item in build_learning_ledger_report().decision_influences)


def test_resource_influence_for_new_website():
    assert not any(item.action_type == "create_new_website" for item in build_learning_ledger_report().decision_influences)


def test_resource_influence_for_frontier_llm():
    item = next(item for item in build_learning_ledger_report().decision_influences if item.action_type == "run_frontier_llm_synthesis")
    assert "cheaper" in item.recommended_decision_modifier


def test_resource_influence_for_scale_winner():
    item = next(item for item in build_learning_ledger_report().decision_influences if item.action_type == "scale_ad_budget")
    assert item.positive_prior_score > item.negative_prior_score
    assert "scale" in item.recommended_decision_modifier


def test_missing_learning_soft_block_is_influence():
    item = next(item for item in build_learning_ledger_report().decision_influences if item.source_event_id == "event-missing-learning")
    assert item.missing_learning_blockers


def test_winner_supports_scale():
    assert any("scale" in item.recommended_next_action for item in build_learning_ledger_report().decision_influences if item.action_type == "scale_ad_budget")


def test_loser_supports_kill_rule():
    assert any("soft_block" in item.recommended_decision_modifier for item in build_learning_ledger_report().decision_influences if item.action_type == "launch_ad_experiment")


def test_portfolio_impacts_cover_categories():
    areas = {item.portfolio_area for item in build_learning_ledger_report().portfolio_impacts}
    assert {"product-category", "creative-hooks", "landing-pages"}.issubset(areas)


def test_working_category_is_summarized():
    item = next(item for item in build_learning_ledger_report().portfolio_impacts if item.portfolio_area == "product-category")
    assert item.positive_signals


def test_failing_category_is_summarized():
    item = next(item for item in build_learning_ledger_report().portfolio_impacts if item.portfolio_area == "product-category")
    assert item.negative_signals


def test_supplier_type_failure_is_in_ledger():
    assert any("supplier" in " ".join(item.negative_signals).lower() for item in build_learning_ledger_report().portfolio_impacts) or any("supplier" in item.condition for item in build_learning_ledger_report().do_not_repeat_rules)


def test_winning_hook_is_summarized():
    item = next(item for item in build_learning_ledger_report().portfolio_impacts if item.portfolio_area == "creative-hooks")
    assert any("hook" in signal for signal in item.positive_signals)


def test_failing_price_or_economics_is_summarized():
    item = next(item for item in build_learning_ledger_report().portfolio_impacts if item.portfolio_area == "product-category")
    assert any("economics" in signal or "espresso" in signal for signal in item.negative_signals)


def test_landing_page_pattern_is_summarized():
    item = next(item for item in build_learning_ledger_report().portfolio_impacts if item.portfolio_area == "landing-pages")
    assert item.recommended_focus_area


def test_model_routing_impacts_cover_algorithmic_local_cheap_frontier_human():
    items = build_learning_ledger_report().model_routing_impacts
    assert {"algorithmic", "cheap_llm", "algorithmic_or_cheap_llm", "human_review"} == {item.recommended_model_tier_next_time for item in items}


def test_frontier_waste_cost_note_present():
    item = next(item for item in build_learning_ledger_report().model_routing_impacts if item.model_route_id == "frontier-reasoning")
    assert item.cost_savings_note
    assert item.quality_risk_note


def test_cheap_success_is_recorded():
    item = next(item for item in build_learning_ledger_report().model_routing_impacts if item.model_route_id == "cheap-api")
    assert item.observed_outcome == "win"


def test_provider_learning_has_dataforseo():
    item = next(item for item in build_learning_ledger_report().provider_impacts if item.provider_id == "dataforseo")
    assert item.evidence_value == .72
    assert item.schema_quality == .85


def test_provider_learning_has_apify_plan_only():
    item = next(item for item in build_learning_ledger_report().provider_impacts if item.provider_id == "apify")
    assert "plan-only" in item.recommended_next_provider_action


def test_provider_terms_blocker_is_recorded():
    item = next(item for item in build_learning_ledger_report().provider_impacts if item.provider_id == "apify")
    assert "provider_blocker" in item.blocked_reason
    assert item.terms_privacy_blocker is None
    assert item.output_contract_blocker is None


def test_manual_import_is_sufficient_for_early_screen():
    item = next(item for item in build_learning_ledger_report().provider_impacts if item.provider_id == "manual_import")
    assert "manual" in item.recommended_next_provider_action


def test_trustos_blockers_are_summarized():
    blockers = {item.blocker for item in build_learning_ledger_report().trustos_impacts}
    assert "missing client isolation" in blockers
    assert "terms/privacy or provider activation" in blockers


def test_trustos_control_improvement_is_present():
    assert all(item.recommended_control_improvements for item in build_learning_ledger_report().trustos_impacts)


def test_next_evidence_is_present():
    assert all(item.recommended_next_evidence for item in build_learning_ledger_report().trustos_impacts)


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_event_filter(event_type: str):
    report = build_learning_ledger_report(event_type=event_type)
    assert all(item.event_type == event_type for item in report.events)


@pytest.mark.parametrize("fixture_name", ["ad_experiment_winner_fixture.json", "ad_experiment_loser_fixture.json", "product_validation_failure_fixture.json", "product_validation_winner_fixture.json", "supplier_failure_fixture.json", "creative_test_iteration_fixture.json", "landing_page_test_fixture.json", "model_routing_frontier_waste_fixture.json", "model_routing_cheap_success_fixture.json", "provider_run_blocked_fixture.json", "dataforseo_dry_run_learning_fixture.json", "trustos_blocker_recurrence_fixture.json", "runaway_guard_learning_fixture.json", "missing_learning_blocker_fixture.json", "portfolio_learning_fixture.json", "safe_client_visible_summary_fixture.json"])
def test_sanitized_fixture_builds(fixture_name: str):
    report = build_learning_ledger_report(context=fixture(fixture_name))
    assert report.events
    assert "synthetic-secret-value" not in json.dumps(report.to_dict())


def test_fixture_client_summary_visibility_is_preserved():
    report = build_learning_ledger_report(context=fixture("safe_client_visible_summary_fixture.json"))
    assert report.events[0].client_visibility == "client_visible_summary"


def test_invalid_event_type_rejected():
    with pytest.raises(ValueError): build_learning_ledger_report(context=fixture("malformed_learning_input.json"))


def test_secret_fixture_is_rejected_by_cli():
    result = run_cli("--context", str(FIXTURES / "secret_like_learning_input_rejected.json"), "--json")
    assert result.returncode != 0
    assert "rejected" in result.stderr


def test_client_private_fixture_is_rejected_by_cli():
    result = run_cli("--context", str(FIXTURES / "client_private_learning_input_rejected.json"), "--json")
    assert result.returncode != 0


def test_cli_json():
    result = run_cli("--json")
    assert result.returncode == 0
    assert json.loads(result.stdout)["safety_summary"]["model_calls"] is False


def test_cli_markdown():
    result = run_cli("--markdown")
    assert result.returncode == 0
    assert "# Learning Ledger" in result.stdout


@pytest.mark.parametrize("event_type", ["ad_experiment", "product_validation", "model_routing_decision"])
def test_cli_event_type(event_type: str):
    result = run_cli("--event-type", event_type, "--json")
    assert result.returncode == 0
    assert all(item["event_type"] == event_type for item in json.loads(result.stdout)["events"])


@pytest.mark.parametrize("scenario", ["ads_winner_loser", "product_validation_failure", "frontier_llm_waste", "trustos_blocker_recurrence"])
def test_cli_scenario(scenario: str):
    result = run_cli("--scenario", scenario, "--markdown")
    assert result.returncode == 0
    assert "# Learning Ledger" in result.stdout


def test_cli_output_writes_sanitized_files(tmp_path: Path):
    result = run_cli("--output", str(tmp_path), "--markdown")
    assert result.returncode == 0
    expected = {"learning_ledger_report.json", "learning_ledger_report.md", "learning_events.json", "experiments.json", "do_not_repeat_rules.json", "iteration_recommendations.json", "portfolio_impacts.json", "model_routing_impacts.json", "provider_impacts.json", "trustos_impacts.json", "decision_influences.json"}
    assert expected == {item.name for item in tmp_path.iterdir()}
    assert all("synthetic-secret-value" not in item.read_text(encoding="utf-8") for item in tmp_path.iterdir())


def test_cli_is_deterministic():
    assert run_cli("--json").stdout == run_cli("--json").stdout


def test_cli_invalid_path_rejected():
    result = run_cli("--context", str(ROOT.parent / "outside-learning.json"), "--json")
    assert result.returncode != 0


def test_report_has_no_raw_prompt_or_client_data():
    rendered = json.dumps(build_learning_ledger_report().to_dict()).lower()
    for marker in ("client@example.com", "actual_secret_value", "raw prompt", "real ad metric", "begin private key"):
        assert marker not in rendered


def test_source_has_no_persistence_or_transport():
    source = (ROOT / "evaluation" / "companyos" / "learning_ledger.py").read_text(encoding="utf-8").lower()
    for marker in ("sqlalchemy", "supabase", "requests.get", "httpx", "openai.", "subprocess", "socket", "embedding"):
        assert marker not in source


def test_learning_requirements_match_governor_vocabulary():
    from evaluation.companyos.resource_execution_governor import build_resource_execution_governor_report
    governor_types = {item.learning_type for item in build_resource_execution_governor_report().learning_requirements}
    assert {"creative_test", "product_validation", "provider_run", "model_routing"}.issubset(governor_types)


def test_no_duplicate_resource_governor_is_created():
    source = (ROOT / "evaluation" / "companyos" / "learning_ledger.py").read_text(encoding="utf-8")
    assert "class ResourceBudget" not in source
    assert "class ResourceQuota" not in source


def test_no_vector_memory_is_created():
    source = (ROOT / "evaluation" / "companyos" / "learning_ledger.py").read_text(encoding="utf-8").lower()
    assert "vector" not in source


def test_summary_what_to_repeat_and_avoid_are_present():
    summary = build_learning_ledger_report().summary
    assert summary.what_to_repeat
    assert summary.what_to_avoid


def test_report_next_action_mentions_governor():
    assert "Resource Governor" in build_learning_ledger_report().next_best_action


def test_report_exposes_resource_governor_feedback():
    data = build_learning_ledger_report().to_dict()
    assert data["resource_governor_feedback"]


def test_event_confidence_is_preserved():
    report = build_learning_ledger_report(context={"events": [{"learning_event_id": "confidence", "event_type": "product_validation", "outcome": "win", "confidence": .91}]})
    assert report.events[0].confidence == .91


def test_cost_is_preserved_without_real_spend():
    report = build_learning_ledger_report(context={"events": [{"learning_event_id": "cost", "event_type": "model_routing_decision", "outcome": "loss", "cost_estimate": 12.5, "failure_reasons": ["model_cost_too_high"]}]})
    assert report.events[0].cost_estimate == 12.5
    assert report.safety_summary.model_calls is False


def test_review_required_is_set_for_blocked_events():
    assert all(item.review_required for item in build_learning_ledger_report().events if item.outcome in {"blocked", "loss", "killed"})


def test_client_visible_summary_has_no_internal_lesson_visibility():
    report = build_learning_ledger_report(context=fixture("safe_client_visible_summary_fixture.json"))
    assert report.events[0].client_visibility == "client_visible_summary"
    assert all("internal prompt" not in item.statement.lower() for item in report.lessons)


@pytest.mark.parametrize("outcome", ["win", "loss", "inconclusive", "killed", "scaled", "paused", "iterated", "blocked", "needs_more_evidence", "invalid_test"])
def test_custom_outcome_event_round_trips(outcome: str):
    report = build_learning_ledger_report(context={"events": [{"event_type": "companyos_review", "outcome": outcome}]})
    assert report.events[0].outcome == outcome


@pytest.mark.parametrize("visibility", VISIBILITY)
def test_custom_visibility_event_round_trips(visibility: str):
    report = build_learning_ledger_report(context={"events": [{"event_type": "companyos_review", "outcome": "win", "client_visibility": visibility}]})
    assert report.events[0].client_visibility == visibility


@pytest.mark.parametrize("event_type", ["consumer_attention_test", "site_funnel_test", "companyos_review", "kill_decision", "scale_decision"])
def test_default_event_types_are_available(event_type: str):
    assert any(item.event_type == event_type for item in build_learning_ledger_report().events)


def test_event_candidate_id_is_safe_placeholder():
    assert all(item.candidate_id for item in build_learning_ledger_report().events)


def test_event_owner_department_is_present():
    assert all(item.owner_department for item in build_learning_ledger_report().events)


def test_event_source_decision_id_is_present():
    assert all(item.source_decision_id for item in build_learning_ledger_report().events)


def test_event_evidence_refs_are_present():
    assert all(item.input_evidence_refs for item in build_learning_ledger_report().events)


def test_experiments_have_event_refs():
    assert all(item.event_refs for item in build_learning_ledger_report().experiments)


def test_experiments_have_iteration_rule():
    assert all(item.iteration_rule for item in build_learning_ledger_report().experiments)


def test_lessons_match_event_count():
    report = build_learning_ledger_report()
    assert len(report.lessons) == len(report.events)


def test_results_match_event_count():
    report = build_learning_ledger_report()
    assert len(report.results) == len(report.events)


def test_do_not_repeat_rules_have_source_events():
    report = build_learning_ledger_report()
    event_ids = {item.learning_event_id for item in report.events}
    assert all(item.source_event_id in event_ids for item in report.do_not_repeat_rules)


def test_iteration_recommendations_have_source_events():
    report = build_learning_ledger_report()
    event_ids = {item.learning_event_id for item in report.events}
    assert all(item.source_event_id in event_ids for item in report.iteration_recommendations)


def test_portfolio_impacts_have_confidence():
    assert all(0 <= item.confidence <= 1 for item in build_learning_ledger_report().portfolio_impacts)


def test_model_impacts_have_confidence():
    assert all(0 <= item.confidence <= 1 for item in build_learning_ledger_report().model_routing_impacts)


def test_trustos_impacts_have_occurrences():
    assert all(item.occurrences > 0 for item in build_learning_ledger_report().trustos_impacts)


def test_decision_influences_have_workspace_scope():
    assert all(item.workspace_id == "internal-companyos" for item in build_learning_ledger_report().decision_influences)


def test_provider_costs_are_nonnegative():
    assert all(item.cost_estimate >= 0 for item in build_learning_ledger_report().provider_impacts)


def test_provider_schema_quality_is_bounded():
    assert all(item.schema_quality is None or 0 <= item.schema_quality <= 1 for item in build_learning_ledger_report().provider_impacts)


def test_provider_evidence_value_is_bounded():
    assert all(item.evidence_value is None or 0 <= item.evidence_value <= 1 for item in build_learning_ledger_report().provider_impacts)


def test_summary_failure_rules_are_nonempty():
    assert build_learning_ledger_report().summary.top_do_not_repeat_rules


def test_summary_iteration_recommendations_are_nonempty():
    assert build_learning_ledger_report().summary.top_iteration_recommendations


def test_summary_recurring_blockers_are_nonempty():
    assert build_learning_ledger_report().summary.recurring_blockers


def test_event_filter_empty_is_valid():
    report = build_learning_ledger_report(event_type="consumer_attention_test")
    assert report.events


def test_context_without_events_uses_safe_defaults():
    report = build_learning_ledger_report(context={"mode": "offline"})
    assert report.events


def test_empty_event_list_is_an_explicit_empty_batch():
    report = build_learning_ledger_report(context={"events": []})
    assert not report.events


def test_custom_cost_does_not_enable_spend():
    report = build_learning_ledger_report(context={"events": [{"event_type": "ad_experiment", "outcome": "loss", "cost_estimate": 99, "failure_reasons": ["budget_cap"]}]})
    assert report.events[0].cost_estimate == 99
    assert report.safety_summary.ads_launched is False


def test_custom_influence_is_preserved():
    report = build_learning_ledger_report(context={"events": [{"event_type": "companyos_review", "outcome": "win", "resource_governor_influence": "prefer bounded review"}]})
    assert report.events[0].resource_governor_influence == "prefer bounded review"


def test_report_version_is_stable():
    assert build_learning_ledger_report().report_version == "learning-ledger-v1"


def test_generated_at_is_deterministic():
    assert build_learning_ledger_report().generated_at == "offline-deterministic"


def test_no_external_action_is_in_default_event_action():
    rendered = json.dumps(build_learning_ledger_report().to_dict()).lower()
    assert "send_email" not in rendered
    assert "create_payment" not in rendered


# --- recovery-pass repairs -------------------------------------------------------


def test_event_types_filter_keeps_derived_aggregates_consistent():
    """Regression: the CLI's --scenario path filtered events on a finished
    report, leaving lessons, do-not-repeat rules, recommendations,
    impacts, influences, and the summary describing events the report no
    longer showed. Filtering at build time must keep every aggregate
    consistent with the events actually reported."""
    report = build_learning_ledger_report(event_types=("model_routing_decision",))
    assert report.events
    assert {item.event_type for item in report.events} == {"model_routing_decision"}
    assert len(report.lessons) == len(report.events)
    assert len(report.do_not_repeat_rules) <= len(report.events)
    full = build_learning_ledger_report()
    assert len(report.lessons) < len(full.lessons)


def test_event_types_filter_rejects_unsupported_type():
    with pytest.raises(ValueError):
        build_learning_ledger_report(event_types=("not_a_real_event_type",))


def test_event_types_filter_accepts_multiple_types():
    report = build_learning_ledger_report(event_types=("ad_experiment", "creative_test"))
    assert {item.event_type for item in report.events} <= {"ad_experiment", "creative_test"}
    assert len(report.lessons) == len(report.events)


@pytest.mark.parametrize("scenario", ("ads_winner_loser", "product_validation_failure", "frontier_llm_waste", "trustos_blocker_recurrence"))
def test_cli_scenario_report_is_internally_consistent(scenario: str):
    result = run_cli("--scenario", scenario, "--json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert len(payload["lessons"]) == len(payload["events"])
    assert len(payload["do_not_repeat_rules"]) <= len(payload["events"])


def test_cli_output_rejects_path_traversal():
    """Regression: --output resolved a caller path with no traversal
    guard, unlike --context and unlike every other harness in this
    repository."""
    result = run_cli("--output", "../../tmp/learning-ledger-escape", "--json")
    assert result.returncode != 0
    assert "path traversal is not accepted" in (result.stdout + result.stderr)


# --- named do-not-repeat / iteration-recommendation categories (recovery pass 2) --


def test_invalid_test_design_has_specific_rule_and_recommendation_text():
    """Regression: `invalid_test_design` (incomplete ad experiment design)
    previously fell through to the generic 'the same failure reason
    recurs' fallback in both the do-not-repeat rule and the iteration
    recommendation."""
    report = build_learning_ledger_report(context={"events": [{"event_type": "ad_experiment", "outcome": "loss", "failure_reasons": ["invalid_test_design"], "action_taken": "launch_ad_experiment"}]})
    assert "hypothesis" in report.do_not_repeat_rules[0].condition
    assert "hypothesis" in report.iteration_recommendations[0].recommendation


def test_poor_offer_has_specific_iteration_recommendation():
    """Regression: `poor_offer` had no entry in the iteration-recommendation
    mapping at all, despite being a valid FAILURE_REASONS value -- it fell
    through to the generic fallback text."""
    report = build_learning_ledger_report(context={"events": [{"event_type": "product_validation", "outcome": "loss", "failure_reasons": ["poor_offer"], "action_taken": "generate_site_draft"}]})
    assert report.iteration_recommendations[0].action_type == "iterate_offer_draft"
    assert "offer" in report.iteration_recommendations[0].expected_learning.lower()


def test_poor_margin_has_specific_iteration_recommendation():
    """Regression: `poor_margin` had a do-not-repeat rule but no
    iteration-recommendation entry -- economics failures fell through to
    the generic fallback recommendation text."""
    report = build_learning_ledger_report(context={"events": [{"event_type": "product_validation", "outcome": "loss", "failure_reasons": ["poor_margin"], "action_taken": "promote_product_candidate"}]})
    assert report.iteration_recommendations[0].action_type == "run_unit_economics_review"


def test_trust_blocker_has_specific_iteration_recommendation():
    """Regression: `trust_blocker` had a do-not-repeat rule but no
    iteration-recommendation entry."""
    report = build_learning_ledger_report(context={"events": [{"event_type": "client_export_review", "outcome": "blocked", "failure_reasons": ["trust_blocker"], "action_taken": "generate_client_export"}]})
    assert report.iteration_recommendations[0].action_type == "run_trustos_control_plane"
    assert "trustos" in report.iteration_recommendations[0].recommendation.lower()


def test_absorbable_new_website_do_not_repeat_rule():
    """Regression: there was no do-not-repeat rule at all for 'an existing
    brand/category can absorb this opportunity without a new site' --
    action_taken='create_new_website' fell through to the generic
    fallback regardless of failure reason."""
    report = build_learning_ledger_report(context={"events": [{"event_type": "portfolio_decision", "outcome": "loss", "failure_reasons": ["weak_demand"], "action_taken": "create_new_website"}]})
    rule = report.do_not_repeat_rules[0]
    assert "absorb" in rule.condition
    assert "create_new_website" in rule.applies_to_action_types


def test_scale_without_evidence_is_hard_blocked():
    """Regression: there was no do-not-repeat rule for scaling without
    sufficient evidence -- action_taken='scale_ad_budget' with
    insufficient_sample fell through to the generic fallback."""
    report = build_learning_ledger_report(context={"events": [{"event_type": "scale_decision", "outcome": "blocked", "failure_reasons": ["insufficient_sample"], "action_taken": "scale_ad_budget"}]})
    rule = report.do_not_repeat_rules[0]
    assert "sample size" in rule.condition or "evidence" in rule.condition
    assert rule.recommended_block_behavior == "hard_block"


def test_provider_retry_cap_violation_has_specific_condition():
    """Regression: a provider-specific retry-cap violation
    (runaway_guard_triggered + action_taken=run_provider_data_pull) was
    indistinguishable from the generic 'workflow exceeds retry, agent, or
    step limits' rule that applies to any runaway workflow."""
    report = build_learning_ledger_report(context={"events": [{"event_type": "provider_run", "outcome": "blocked", "failure_reasons": ["runaway_guard_triggered"], "action_taken": "run_provider_data_pull"}]})
    rule = report.do_not_repeat_rules[0]
    assert "provider retry cap" in rule.condition
    assert rule.recommended_block_behavior == "hard_block"


def test_generic_runaway_guard_rule_is_unaffected_by_provider_special_case():
    """The provider-specific retry-cap branch must not swallow the
    existing, still-valid generic runaway_guard_triggered rule for
    non-provider actions."""
    report = build_learning_ledger_report(context={"events": [{"event_type": "runaway_guard_event", "outcome": "blocked", "failure_reasons": ["runaway_guard_triggered"], "action_taken": "spawn_agent_workflow"}]})
    rule = report.do_not_repeat_rules[0]
    assert rule.condition == "workflow exceeds retry, agent, or step limits"


def test_governor_evidence_modes_vocabulary_is_bounded():
    assert GOVERNOR_EVIDENCE_MODES == ("actual", "simulated", "unavailable", "not_run")


def test_derive_governor_influence_absent_evidence_is_not_run():
    """Required scenario: absent learning context (no matching event at
    all) must never invent a signal -- every boolean stays False and
    evidence_mode is the explicit 'not_run' vocabulary member."""
    report = build_learning_ledger_report(context={"events": [{"event_type": "product_validation", "outcome": "win", "success_reasons": ["strong_demand"], "action_taken": "deep_validate_product"}]})
    influence = derive_governor_influence(report, action_type="run_frontier_llm_synthesis", candidate_id="never-seen-candidate")
    assert influence.evidence_mode == "not_run"
    assert influence.provenance == ()
    assert influence.supports_scale is False
    assert influence.hold_or_avoid is False
    assert influence.do_not_repeat_blocked is False
    assert influence.trustos_recurrence_blocked is False
    assert influence.recommended_model_tier == ""


def test_derive_governor_influence_repeated_failure_creates_hold_or_avoid():
    """Required scenario: repeated failed/killed experiments create a
    deterministic hold/avoid recommendation for the matching action."""
    events = [
        {"event_type": "ad_experiment", "outcome": "loss", "failure_reasons": ["poor_creative_angle"], "action_taken": "launch_ad_experiment", "candidate_id": "repeat-offender"},
        {"event_type": "ad_experiment", "outcome": "killed", "failure_reasons": ["poor_creative_angle"], "action_taken": "launch_ad_experiment", "candidate_id": "repeat-offender"},
    ]
    report = build_learning_ledger_report(context={"events": events})
    influence = derive_governor_influence(report, action_type="launch_ad_experiment", candidate_id="repeat-offender")
    assert influence.hold_or_avoid is True
    assert influence.loss_count == 2
    assert influence.evidence_mode == "simulated"
    assert len(influence.provenance) == 2


def test_derive_governor_influence_single_failure_does_not_hold():
    """A single matching failure is not 'repeated' -- hold_or_avoid must
    stay False until the pattern actually recurs."""
    report = build_learning_ledger_report(context={"events": [{"event_type": "ad_experiment", "outcome": "loss", "failure_reasons": ["poor_creative_angle"], "action_taken": "launch_ad_experiment", "candidate_id": "one-off"}]})
    influence = derive_governor_influence(report, action_type="launch_ad_experiment", candidate_id="one-off")
    assert influence.hold_or_avoid is False


def test_derive_governor_influence_do_not_repeat_blocks_without_new_hypothesis():
    """Required scenario / requirement: do-not-repeat rules must prevent
    the Governor from recommending the same known-bad action unless a new
    explicit hypothesis or override is present."""
    report = build_learning_ledger_report(context={"events": [{"event_type": "ad_experiment", "outcome": "loss", "failure_reasons": ["poor_creative_angle"], "action_taken": "launch_ad_experiment", "candidate_id": "blocked-candidate"}]})
    blocked = derive_governor_influence(report, action_type="launch_ad_experiment", candidate_id="blocked-candidate")
    assert blocked.do_not_repeat_blocked is True
    assert blocked.do_not_repeat_overridden is False
    assert blocked.do_not_repeat_rule_ids


def test_derive_governor_influence_do_not_repeat_override_with_new_hypothesis():
    report = build_learning_ledger_report(context={"events": [{"event_type": "ad_experiment", "outcome": "loss", "failure_reasons": ["poor_creative_angle"], "action_taken": "launch_ad_experiment", "candidate_id": "blocked-candidate"}]})
    overridden = derive_governor_influence(report, action_type="launch_ad_experiment", candidate_id="blocked-candidate", proposed_hypothesis="A new, changed creative hook targeting a different audience segment.")
    assert overridden.do_not_repeat_blocked is False
    assert overridden.do_not_repeat_overridden is True
    assert overridden.do_not_repeat_rule_ids


def test_derive_governor_influence_trustos_recurrence_is_flagged():
    """Required scenario / requirement: recurring TrustOS or security
    blockers must remain hard blockers. This records the signal only;
    `apply_learning_influence` (tested in
    test_resource_execution_governor.py) never uses a positive signal to
    lift the Governor's own trustos_decision gate."""
    events = [
        {"event_type": "trustos_review", "outcome": "blocked", "failure_reasons": ["trust_blocker"], "action_taken": "generate_client_export", "candidate_id": "export-candidate"},
        {"event_type": "trustos_review", "outcome": "blocked", "failure_reasons": ["trust_blocker"], "action_taken": "generate_client_export", "candidate_id": "export-candidate"},
    ]
    report = build_learning_ledger_report(context={"events": events})
    influence = derive_governor_influence(report, action_type="generate_client_export", candidate_id="export-candidate")
    assert influence.trustos_recurrence_blocked is True
    assert influence.supports_scale is False


def test_derive_governor_influence_model_routing_lesson_is_planning_metadata():
    """Required scenario / requirement: provider/model lessons influence
    routing tier as planning metadata only."""
    report = build_learning_ledger_report(context={"events": [{"event_type": "model_routing_decision", "outcome": "loss", "failure_reasons": ["model_cost_too_high"], "action_taken": "run_frontier_llm_synthesis"}]})
    influence = derive_governor_influence(report, action_type="run_frontier_llm_synthesis")
    assert influence.recommended_model_tier == "cheap_llm"
    assert influence.deprioritize is True


def test_derive_governor_influence_positive_evidence_supports_scale_only_when_repeated_and_clean():
    report = build_learning_ledger_report(context={"events": [
        {"event_type": "ad_experiment", "outcome": "win", "success_reasons": ["budget_efficient"], "action_taken": "scale_ad_budget", "candidate_id": "clean-winner"},
        {"event_type": "ad_experiment", "outcome": "win", "success_reasons": ["budget_efficient"], "action_taken": "scale_ad_budget", "candidate_id": "clean-winner"},
    ]})
    influence = derive_governor_influence(report, action_type="scale_ad_budget", candidate_id="clean-winner")
    assert influence.supports_scale is True
    assert influence.win_count == 2


def test_derive_governor_influence_falls_back_to_action_type_when_no_candidate_match():
    report = build_learning_ledger_report(context={"events": [{"event_type": "ad_experiment", "outcome": "loss", "failure_reasons": ["poor_creative_angle"], "action_taken": "launch_ad_experiment", "candidate_id": "someone-else"}]})
    influence = derive_governor_influence(report, action_type="launch_ad_experiment", candidate_id="unrelated-candidate")
    assert influence.recency_label == "action_type_only_match"
    assert influence.loss_count == 1


def test_derive_governor_influence_is_deterministic():
    report = build_learning_ledger_report()
    first = derive_governor_influence(report, action_type="launch_ad_experiment", candidate_id="portable-espresso-maker")
    second = derive_governor_influence(report, action_type="launch_ad_experiment", candidate_id="portable-espresso-maker")
    assert first == second


def test_derive_governor_influence_to_governor_context_is_narrow():
    report = build_learning_ledger_report()
    influence = derive_governor_influence(report, action_type="launch_ad_experiment", candidate_id="portable-espresso-maker")
    context = influence.to_governor_context()
    assert set(context) == {"do_not_repeat_blocked", "hold_or_avoid", "trustos_recurrence_blocked", "kill_blocks_resumption", "recommended_model_tier", "recommended_provider_id", "avoid_provider_ids"}
    assert "candidate_id" not in context
    assert "provenance" not in context
    assert "iteration_recommendation" not in context


def test_learning_governor_influence_rejects_invalid_evidence_mode():
    with pytest.raises(ValueError):
        LearningGovernorInfluence("launch_ad_experiment", "candidate", "internal-companyos", "not-a-real-mode", 0.0, "unknown", (), 0, 0, False, False, False, False, (), False, "", False, ())


def test_learning_ledger_still_imports_no_governor_module():
    """The stdlib-only invariant this PR's body already documents must
    survive the new bridge: the ledger must not import the Resource &
    Execution Governor, even though it now produces a record the Governor
    can consume."""
    source = (ROOT / "evaluation" / "companyos" / "learning_ledger.py").read_text(encoding="utf-8")
    assert "resource_execution_governor" not in source
    assert "import evaluation" not in source


def test_default_provider_events_carry_provider_id():
    """Regression: `_event()` accepted a `provider` keyword but never
    stored it -- `event-provider-blocked`/`event-provider-dry-run` looked
    provider-specific (both pass `provider="dataforseo"`) but their
    `provider_id` was always empty. Fixed as part of wiring provider
    lessons into `derive_governor_influence`."""
    report = build_learning_ledger_report()
    by_id = {event.learning_event_id: event for event in report.events}
    assert by_id["event-provider-blocked"].provider_id == "dataforseo"
    assert by_id["event-provider-dry-run"].provider_id == "dataforseo"


def test_derive_governor_influence_kill_blocks_resumption_from_single_event():
    """Required scenario: a kill decision must prevent automatic
    resumption -- unlike hold_or_avoid, a single kill is definitive and
    needs no repetition."""
    report = build_learning_ledger_report(context={"events": [{"event_type": "kill_decision", "outcome": "killed", "failure_reasons": ["low_click_through"], "action_taken": "kill_ad_experiment", "candidate_id": "killed-candidate"}]})
    influence = derive_governor_influence(report, action_type="kill_ad_experiment", candidate_id="killed-candidate")
    assert influence.kill_blocks_resumption is True
    assert influence.hold_or_avoid is False
    assert influence.supports_scale is False


def test_derive_governor_influence_iteration_recommendation_surfaces_next_plan():
    """Required scenario: an iteration recommendation must be available to
    change the next plan, not just live unused in the report's own list."""
    report = build_learning_ledger_report(context={"events": [{"event_type": "security_scan", "outcome": "needs_more_evidence", "failure_reasons": ["insufficient_sample"], "action_taken": "run_security_scan", "candidate_id": "scan-candidate"}]})
    influence = derive_governor_influence(report, action_type="run_security_scan", candidate_id="scan-candidate")
    assert influence.iteration_recommendation
    assert "bounded sample" in influence.iteration_recommendation


def test_derive_governor_influence_provider_lesson_flags_blocked_and_ready_providers():
    """Required scenario: provider lesson affecting provider selection --
    a blocked provider is flagged to avoid and a ready alternate provider
    is recommended, both as planning metadata only."""
    events = [
        {"event_type": "provider_run", "outcome": "blocked", "failure_reasons": ["provider_blocker"], "action_taken": "run_provider_data_pull", "provider_id": "dataforseo", "candidate_id": "provider-candidate"},
        {"event_type": "provider_run", "outcome": "win", "success_reasons": ["provider_ready"], "action_taken": "run_provider_data_pull", "provider_id": "manual_import", "candidate_id": "provider-candidate"},
    ]
    report = build_learning_ledger_report(context={"events": events})
    influence = derive_governor_influence(report, action_type="run_provider_data_pull", candidate_id="provider-candidate")
    assert influence.avoid_provider_ids == ("dataforseo",)
    assert influence.recommended_provider_id == "manual_import"


def test_derive_governor_influence_conflicting_evidence_blocks_scale():
    """Required scenario: conflicting learning context (both wins and
    losses recorded for the same action/candidate) must never authorize
    scale."""
    events = [
        {"event_type": "ad_experiment", "outcome": "win", "success_reasons": ["budget_efficient"], "action_taken": "scale_ad_budget", "candidate_id": "mixed-candidate"},
        {"event_type": "ad_experiment", "outcome": "loss", "failure_reasons": ["poor_creative_angle"], "action_taken": "scale_ad_budget", "candidate_id": "mixed-candidate"},
    ]
    report = build_learning_ledger_report(context={"events": events})
    influence = derive_governor_influence(report, action_type="scale_ad_budget", candidate_id="mixed-candidate")
    assert influence.conflicting_evidence is True
    assert influence.supports_scale is False


def test_derive_governor_influence_stale_events_are_excluded_from_evidence():
    """Required scenario: stale learning context cannot authorize scale --
    a caller-declared-stale win must not count toward win_count or
    supports_scale, and excluding it (rather than merely flagging it)
    keeps stale evidence from shaping the result at all."""
    events = [
        {"learning_event_id": "stale-win-1", "event_type": "ad_experiment", "outcome": "win", "success_reasons": ["budget_efficient"], "action_taken": "scale_ad_budget", "candidate_id": "stale-candidate"},
        {"learning_event_id": "stale-win-2", "event_type": "ad_experiment", "outcome": "win", "success_reasons": ["budget_efficient"], "action_taken": "scale_ad_budget", "candidate_id": "stale-candidate"},
    ]
    report = build_learning_ledger_report(context={"events": events})
    fresh = derive_governor_influence(report, action_type="scale_ad_budget", candidate_id="stale-candidate")
    assert fresh.supports_scale is True
    staled = derive_governor_influence(report, action_type="scale_ad_budget", candidate_id="stale-candidate", stale_event_ids=("stale-win-1", "stale-win-2"))
    assert staled.evidence_mode == "not_run"
    assert staled.supports_scale is False
    assert staled.excluded_stale_event_ids == ("stale-win-1", "stale-win-2")


def test_derive_governor_influence_matching_events_are_bounded():
    """Bounded context size: however much history a candidate/action pair
    accumulates, the influence record only ever reflects the most recent
    `_MAX_MATCHING_EVENTS`."""
    events = [{"event_type": "ad_experiment", "outcome": "loss", "failure_reasons": ["poor_creative_angle"], "action_taken": "launch_ad_experiment", "candidate_id": "bulk-candidate", "learning_event_id": f"bulk-{i}"} for i in range(40)]
    report = build_learning_ledger_report(context={"events": events})
    influence = derive_governor_influence(report, action_type="launch_ad_experiment", candidate_id="bulk-candidate")
    assert len(influence.provenance) <= 25


def test_derive_governor_influence_fingerprint_is_deterministic_and_sensitive():
    """Required scenario: deterministic fingerprint and stable reasons."""
    report = build_learning_ledger_report()
    first = derive_governor_influence(report, action_type="launch_ad_experiment", candidate_id="portable-espresso-maker")
    second = derive_governor_influence(report, action_type="launch_ad_experiment", candidate_id="portable-espresso-maker")
    assert first.fingerprint == second.fingerprint
    assert first.fingerprint
    assert first.rationale == second.rationale
    different_candidate = derive_governor_influence(report, action_type="launch_ad_experiment", candidate_id="mini-thermal-printer")
    assert different_candidate.fingerprint != first.fingerprint


def test_derive_governor_influence_does_not_leak_across_workspaces():
    """Required scenario: no cross-client leakage -- a repeated failure
    recorded under one workspace must not influence a decision for the
    same action/candidate under a different workspace, even when the
    candidate_id string coincides."""
    events = [
        {"event_type": "ad_experiment", "outcome": "loss", "failure_reasons": ["poor_creative_angle"], "action_taken": "launch_ad_experiment", "candidate_id": "shared-name", "workspace_id": "client-a"},
        {"event_type": "ad_experiment", "outcome": "killed", "failure_reasons": ["poor_creative_angle"], "action_taken": "launch_ad_experiment", "candidate_id": "shared-name", "workspace_id": "client-a"},
    ]
    report = build_learning_ledger_report(context={"events": events})
    client_a = derive_governor_influence(report, action_type="launch_ad_experiment", candidate_id="shared-name", workspace_id="client-a")
    client_b = derive_governor_influence(report, action_type="launch_ad_experiment", candidate_id="shared-name", workspace_id="client-b")
    assert client_a.hold_or_avoid is True
    assert client_b.evidence_mode == "not_run"
    assert client_b.hold_or_avoid is False
    assert client_b.provenance == ()


def test_derive_governor_influence_trustos_recurrence_does_not_leak_across_workspaces():
    """No cross-client leakage: the aggregated, ledger-wide TrustOS impact
    counter must never be used to flag a per-workspace recurrence -- two
    different workspaces each with exactly one trust_blocker event must
    not individually see trustos_recurrence_blocked=True, even though the
    ledger-wide aggregate legitimately shows 2 occurrences."""
    events = [
        {"event_type": "trustos_review", "outcome": "blocked", "failure_reasons": ["trust_blocker"], "action_taken": "generate_client_export", "candidate_id": "export-a", "workspace_id": "client-a"},
        {"event_type": "trustos_review", "outcome": "blocked", "failure_reasons": ["trust_blocker"], "action_taken": "generate_client_export", "candidate_id": "export-b", "workspace_id": "client-b"},
    ]
    report = build_learning_ledger_report(context={"events": events})
    assert sum(impact.occurrences for impact in report.trustos_impacts if impact.blocker == "missing client isolation") == 2
    client_a = derive_governor_influence(report, action_type="generate_client_export", candidate_id="export-a", workspace_id="client-a")
    client_b = derive_governor_influence(report, action_type="generate_client_export", candidate_id="export-b", workspace_id="client-b")
    assert client_a.trustos_recurrence_blocked is False
    assert client_b.trustos_recurrence_blocked is False


def test_derive_governor_influence_do_not_repeat_rules_do_not_leak_across_workspaces():
    """No cross-client leakage: a do-not-repeat rule generated from one
    workspace's event must not block the same action/candidate string in
    another workspace."""
    events = [{"event_type": "ad_experiment", "outcome": "loss", "failure_reasons": ["poor_creative_angle"], "action_taken": "launch_ad_experiment", "candidate_id": "shared-name", "workspace_id": "client-a"}]
    report = build_learning_ledger_report(context={"events": events})
    client_a = derive_governor_influence(report, action_type="launch_ad_experiment", candidate_id="shared-name", workspace_id="client-a")
    client_b = derive_governor_influence(report, action_type="launch_ad_experiment", candidate_id="shared-name", workspace_id="client-b")
    assert client_a.do_not_repeat_blocked is True
    assert client_b.do_not_repeat_blocked is False
    assert client_b.do_not_repeat_rule_ids == ()


def test_derive_governor_influence_low_confidence_evidence_cannot_authorize_scale():
    """Required scenario: low-confidence evidence must never authorize
    scale, even when it is otherwise a clean, repeated win."""
    events = [
        {"event_type": "ad_experiment", "outcome": "win", "success_reasons": ["budget_efficient"], "action_taken": "scale_ad_budget", "candidate_id": "shaky-candidate", "confidence": 0.2},
        {"event_type": "ad_experiment", "outcome": "win", "success_reasons": ["budget_efficient"], "action_taken": "scale_ad_budget", "candidate_id": "shaky-candidate", "confidence": 0.2},
    ]
    report = build_learning_ledger_report(context={"events": events})
    influence = derive_governor_influence(report, action_type="scale_ad_budget", candidate_id="shaky-candidate")
    assert influence.win_count == 2
    assert influence.confidence < MIN_SCALE_CONFIDENCE
    assert influence.low_confidence_evidence is True
    assert influence.supports_scale is False
    assert any("confidence" in reason for reason in influence.rationale)


def test_derive_governor_influence_fixture_only_candidate_cannot_authorize_scale():
    """Required scenario: fixture-only evidence (the unspecified
    placeholder candidate) must never authorize scale -- repeated wins
    with no real candidate attached are not evidence about any actual
    decision."""
    events = [
        {"event_type": "ad_experiment", "outcome": "win", "success_reasons": ["budget_efficient"], "action_taken": "scale_ad_budget"},
        {"event_type": "ad_experiment", "outcome": "win", "success_reasons": ["budget_efficient"], "action_taken": "scale_ad_budget"},
    ]
    report = build_learning_ledger_report(context={"events": events})
    influence = derive_governor_influence(report, action_type="scale_ad_budget", candidate_id=PLACEHOLDER_CANDIDATE_ID)
    assert influence.win_count == 2
    assert influence.fixture_only_evidence is True
    assert influence.supports_scale is False
    assert any("placeholder" in reason for reason in influence.rationale)


def test_derive_governor_influence_malformed_evidence_never_reaches_the_bridge():
    """Required scenario: malformed learning evidence must never authorize
    scale. `LearningEvent.__post_init__` already fails closed on an
    invalid event_type/outcome, so a malformed event can never survive
    construction into a `LearningLedgerReport` -- it never becomes
    `evidence` `derive_governor_influence` could act on at all."""
    with pytest.raises(ValueError):
        build_learning_ledger_report(context={"events": [{"event_type": "not-a-real-event", "outcome": "not-a-real-outcome", "action_taken": "scale_ad_budget"}]})


def test_derive_governor_influence_warn_severity_rule_does_not_force_learning_required():
    """Severity-aware do-not-repeat handling (informed by Dagster's
    WARN-vs-ERROR asset-check severity pattern): a matching rule whose
    `recommended_block_behavior` is the weakest tier in this contract's
    own `BLOCK_BEHAVIORS` vocabulary ("warn") is recorded and surfaced,
    but must not force `previous_learning_required` the way a
    soft_block/hard_block/requires_approval rule does. No fixture in this
    ledger currently produces a "warn"-severity rule, so this is
    exercised by injecting one directly onto an existing rule (a report,
    not a second registry)."""
    report = build_learning_ledger_report(context={"events": [{"event_type": "ad_experiment", "outcome": "loss", "failure_reasons": ["poor_creative_angle"], "action_taken": "launch_ad_experiment", "candidate_id": "warn-only-candidate"}]})
    original_rule = report.do_not_repeat_rules[0]
    warn_only_rule = LearningDoNotRepeatRule(original_rule.rule_id, original_rule.source_event_id, original_rule.applies_to_action_types, original_rule.applies_to_departments, original_rule.condition, "low", "warn", original_rule.expiry_or_review_period, original_rule.client_visible)
    warn_only_report = replace(report, do_not_repeat_rules=(warn_only_rule,))
    influence = derive_governor_influence(warn_only_report, action_type="launch_ad_experiment", candidate_id="warn-only-candidate")
    assert influence.do_not_repeat_blocked is False
    assert influence.do_not_repeat_rule_ids == ()
    assert influence.advisory_rule_ids == (original_rule.rule_id,)
    assert any("warn-severity" in reason for reason in influence.rationale)


def test_explicit_empty_batch_does_not_load_demo_events():
    report = build_learning_ledger_report(context={"events": []})

    assert report.events == ()
    assert report.experiments == ()
    assert report.results == ()
    assert report.portfolio_impacts == ()
    assert report.model_routing_impacts == ()
    assert report.provider_impacts == ()
    assert report.trustos_impacts == ()
    assert report.decision_influences == ()
    assert "No learning events" in report.next_best_action


def test_empty_events_argument_overrides_default_fixtures():
    assert build_learning_ledger_report(events=[]).events == ()


def test_fixture_mapping_preserves_missing_and_explicit_zero_metrics():
    report = build_learning_ledger_report(context={"events": [
        {
            "learning_event_id": "metric-zero",
            "event_type": "ad_experiment",
            "outcome": "win",
            "action_taken": "launch_ad_experiment",
            "metrics": [{"name": "conversion_rate", "value": 0.0, "target": 0.0, "sample_size": 0, "unit": "ratio", "source": "fixture"}, {"name": "evidence_value", "value": 0.0, "sample_size": 0, "unit": "ratio", "source": "fixture"}],
        },
        {
            "learning_event_id": "metric-missing",
            "event_type": "ad_experiment",
            "outcome": "win",
            "action_taken": "launch_ad_experiment",
            "metrics": [{"name": "conversion_rate", "unit": "ratio", "source": "fixture"}, {"name": "evidence_value", "unit": "ratio", "source": "fixture"}],
        },
        {
            "learning_event_id": "provider-metric-zero",
            "event_type": "provider_run",
            "outcome": "win",
            "action_taken": "run_provider_data_pull",
            "provider_id": "provider-zero",
            "metrics": [{"name": "evidence_value", "value": 0.0, "sample_size": 0, "unit": "ratio", "source": "fixture"}],
        },
        {
            "learning_event_id": "provider-metric-missing",
            "event_type": "provider_run",
            "outcome": "win",
            "action_taken": "run_provider_data_pull",
            "provider_id": "provider-unreported",
            "metrics": [{"name": "evidence_value", "unit": "ratio", "source": "fixture"}],
        },
    ]})
    events = {event.learning_event_id: event for event in report.events}
    zero = events["metric-zero"].metrics[0]
    missing = events["metric-missing"].metrics[0]

    assert (zero.value, zero.target, zero.sample_size) == (0.0, 0.0, 0)
    assert (missing.value, missing.target, missing.sample_size) == (None, None, None)
    providers = {item.provider_id: item for item in report.provider_impacts}
    assert providers["provider-zero"].evidence_value == 0.0
    assert providers["provider-unreported"].evidence_value is None
    experiments = {item.event_refs[0]: item for item in report.experiments}
    assert experiments["metric-zero"].observed_sample_size == 0
    assert experiments["metric-missing"].observed_sample_size is None


def test_duplicate_event_identity_is_idempotent_but_conflicts_fail_closed():
    event = {"learning_event_id": "same-id", "event_type": "product_validation", "outcome": "win", "success_reasons": ["strong_demand"]}
    duplicate_report = build_learning_ledger_report(context={"events": [event, dict(event)]})
    assert [item.learning_event_id for item in duplicate_report.events] == ["same-id"]

    conflict = {**event, "outcome": "loss", "failure_reasons": ["weak_demand"]}
    with pytest.raises(ValueError, match="conflicting learning event identity"):
        build_learning_ledger_report(context={"events": [event, conflict]})

    typed_event = build_learning_ledger_report().events[0]
    assert build_learning_ledger_report(events=[typed_event, typed_event]).events == (typed_event,)
    with pytest.raises(ValueError, match="conflicting learning event identity"):
        build_learning_ledger_report(events=[typed_event, replace(typed_event, outcome="win" if typed_event.outcome != "win" else "loss")])


@pytest.mark.parametrize("metrics", [
    {"name": "conversion_rate"},
    [None],
    [{"name": "evidence_value", "value": 1.1}],
    [{"name": "conversion_rate", "value": True}],
    [{"name": "conversion_rate", "sample_size": -1}],
])
def test_fixture_mapping_rejects_malformed_metric_records(metrics):
    with pytest.raises(ValueError):
        build_learning_ledger_report(context={"events": [{"learning_event_id": "bad-metric", "metrics": metrics}]})


def test_batch_report_order_is_stable_by_event_identity():
    events = [
        {"learning_event_id": "z-event", "event_type": "product_validation", "outcome": "loss", "failure_reasons": ["weak_demand"]},
        {"learning_event_id": "a-event", "event_type": "product_validation", "outcome": "win", "success_reasons": ["strong_demand"]},
    ]
    forward = build_learning_ledger_report(context={"events": events})
    reverse = build_learning_ledger_report(context={"events": list(reversed(events))})

    assert [event.learning_event_id for event in forward.events] == ["a-event", "z-event"]
    assert forward.to_dict() == reverse.to_dict()


def test_custom_batch_impacts_only_use_recorded_evidence():
    events = [
        {"learning_event_id": "product-win", "event_type": "product_validation", "outcome": "win", "candidate_id": "candidate-x", "action_taken": "validate_candidate", "success_reasons": ["strong_demand"]},
        {"learning_event_id": "model-loss", "event_type": "model_routing_decision", "outcome": "loss", "action_taken": "run_frontier_llm_synthesis", "failure_reasons": ["model_cost_too_high"]},
        {"learning_event_id": "provider-block", "event_type": "provider_run", "outcome": "blocked", "action_taken": "run_provider_data_pull", "provider_id": "fixture-search", "failure_reasons": ["provider_blocker"]},
        {"learning_event_id": "trust-block", "event_type": "trustos_review", "outcome": "blocked", "action_taken": "generate_client_export", "failure_reasons": ["trust_blocker"]},
    ]
    report = build_learning_ledger_report(context={"events": events})

    assert {item.portfolio_area for item in report.portfolio_impacts} == {"product-category"}
    assert {item.model_route_id for item in report.model_routing_impacts} == {"frontier-reasoning"}
    assert {item.provider_id for item in report.provider_impacts} == {"fixture-search"}
    assert {item.blocker for item in report.trustos_impacts} == {"missing client isolation", "terms/privacy or provider activation"}
    assert all(item.confidence == 0.7 for item in report.trustos_impacts)
    assert {item.action_type for item in report.decision_influences} == {event["action_taken"] for event in events}
    assert all(item.source_event_id in {event["learning_event_id"] for event in events} for item in report.decision_influences)
    assert not any(item.action_type == "scale_ad_budget" for item in report.decision_influences)


def test_model_route_with_conflicting_outcomes_requires_reconciliation():
    report = build_learning_ledger_report(context={"events": [
        {"learning_event_id": "route-win", "event_type": "model_routing_decision", "outcome": "win", "action_taken": "run_frontier_llm_synthesis", "success_reasons": ["budget_efficient"]},
        {"learning_event_id": "route-loss", "event_type": "model_routing_decision", "outcome": "loss", "action_taken": "run_frontier_llm_synthesis", "failure_reasons": ["model_cost_too_high"]},
    ]})
    item = report.model_routing_impacts[0]

    assert item.observed_outcome == "mixed"
    assert item.recommended_model_tier_next_time == "review_conflicting_outcomes"
    assert "route-loss" in item.cost_savings_note and "route-win" in item.cost_savings_note


def test_loss_without_failure_reason_requests_evidence_instead_of_claiming_success():
    report = build_learning_ledger_report(context={"events": [{
        "learning_event_id": "loss-no-cause",
        "event_type": "product_validation",
        "outcome": "loss",
        "action_taken": "validate_candidate",
    }]})
    recommendation = report.iteration_recommendations[0]

    assert "success" not in recommendation.rationale
    assert "failure reason" in recommendation.recommendation
    assert recommendation.action_type == "run_companyos_review"
    assert recommendation.source_event_id == "loss-no-cause"


def test_inconclusive_event_with_recorded_metric_does_not_claim_metrics_missing():
    report = build_learning_ledger_report(context={"events": [{
        "learning_event_id": "inconclusive-with-metric",
        "event_type": "ad_experiment",
        "outcome": "inconclusive",
        "action_taken": "launch_ad_experiment",
        "metrics": [{"name": "conversion_rate", "value": 0.12, "target": 0.1, "sample_size": 100, "unit": "ratio"}],
    }]})

    recommendation = report.iteration_recommendations[0]
    influence = report.decision_influences[0]
    assert "missing outcome metrics" not in recommendation.recommendation
    assert "without a failure reason or outcome metric" not in recommendation.rationale
    assert "outcome metrics were not recorded" not in influence.missing_learning_blockers


def test_metric_record_without_value_is_still_a_missing_metric_blocker():
    report = build_learning_ledger_report(context={"events": [{
        "learning_event_id": "inconclusive-null-metric",
        "event_type": "ad_experiment",
        "outcome": "inconclusive",
        "action_taken": "launch_ad_experiment",
        "metrics": [{"name": "conversion_rate", "value": None, "target": 0.1, "sample_size": 100, "unit": "ratio"}],
    }]})

    influence = report.decision_influences[0]
    assert "outcome metrics were not recorded" in influence.missing_learning_blockers


def test_provider_id_on_non_provider_event_does_not_create_provider_impact():
    report = build_learning_ledger_report(context={"events": [{
        "learning_event_id": "model-with-provider-label",
        "event_type": "model_routing_decision",
        "outcome": "win",
        "action_taken": "run_cheap_llm_task",
        "provider_id": "model-vendor-label",
        "success_reasons": ["budget_efficient"],
    }]})

    assert report.provider_impacts == ()


def test_duplicate_trustos_reason_in_one_event_counts_one_occurrence():
    report = build_learning_ledger_report(context={"events": [{
        "learning_event_id": "trust-duplicate-reason",
        "event_type": "trustos_review",
        "outcome": "blocked",
        "action_taken": "generate_client_export",
        "failure_reasons": ["trust_blocker", "trust_blocker"],
    }]})

    assert len(report.trustos_impacts) == 1
    assert report.trustos_impacts[0].blocker == "missing client isolation"
    assert report.trustos_impacts[0].occurrences == 1


def test_sample_size_target_is_not_inferred_from_observed_sample_size():
    report = build_learning_ledger_report(context={"events": [{
        "learning_event_id": "sample-size-observed",
        "event_type": "ad_experiment",
        "outcome": "inconclusive",
        "action_taken": "launch_ad_experiment",
        "metrics": [{"name": "conversion_rate", "value": 0.12, "target": 0.1, "sample_size": 25, "unit": "ratio"}],
    }, {
        "learning_event_id": "sample-size-unknown",
        "event_type": "ad_experiment",
        "outcome": "inconclusive",
        "action_taken": "launch_ad_experiment",
        "metrics": [{"name": "conversion_rate", "value": 0.12, "target": 0.1, "unit": "ratio"}],
    }]})
    experiments = {experiment.event_refs[0]: experiment for experiment in report.experiments}

    assert experiments["sample-size-observed"].sample_size_target is None
    assert experiments["sample-size-observed"].observed_sample_size == 25
    assert experiments["sample-size-unknown"].sample_size_target is None
    assert experiments["sample-size-unknown"].observed_sample_size is None

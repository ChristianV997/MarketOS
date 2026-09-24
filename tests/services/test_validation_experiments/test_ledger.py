from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.validation_experiments import (
    NormalizedOpportunityInput,
    ValidationExperimentInputError,
    build_validation_experiment_ledger,
    normalize_opportunity_inputs,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "validation_experiments"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_strong_demand_without_reachable_buyer_holds():
    ledger = build_validation_experiment_ledger(load("strong_demand_no_buyer.json"))
    assert ledger.decision == "hold_unreachable_buyer"
    assert "reachable_buyer" in ledger.blockers
    assert ledger.opportunity_summary["scoring_authority"].endswith("build_product_opportunity_synthesis")


def test_negative_unit_economics_kills_even_with_demand():
    ledger = build_validation_experiment_ledger(load("negative_economics.json"))
    assert ledger.decision == "kill_negative_unit_economics"
    assert ledger.economics["scenarios"]["base"]["contribution_after_cac"]["amount"] == "-5.00"


def test_missing_supplier_and_budget_fail_closed():
    ledger = build_validation_experiment_ledger(load("missing_supplier_budget.json"))
    assert ledger.decision == "blocked_missing_budget"
    assert "supplier_evidence" in ledger.evidence_gaps
    assert "experiment_budget" in ledger.blockers
    assert ledger.approval_state == "blocked_by_policy"


def test_fixture_evidence_is_not_live_evidence():
    ledger = build_validation_experiment_ledger(load("fixture_evidence.json"))
    assert ledger.evidence_summary["mode"] == "fixture"
    assert ledger.evidence_summary["live_validated"] is False
    assert "fixture_evidence_not_live" in ledger.limitations
    assert ledger.decision == "blocked_evidence_integrity"


def test_stale_and_conflicting_evidence_blocks_decision():
    ledger = build_validation_experiment_ledger(load("stale_future_conflict.json"))
    assert ledger.decision == "blocked_evidence_integrity"
    assert "evidence_integrity" in ledger.blockers
    assert ledger.validation_pipeline["next_action"] == "repair_evidence_provenance"


def test_explicit_zero_cost_is_distinct_from_missing_cost():
    zero = build_validation_experiment_ledger(load("explicit_zero_cost.json"))
    missing = build_validation_experiment_ledger(load("missing_cost.json"))
    assert zero.economics["base_cost_state"] == "explicit_zero"
    assert missing.economics["base_cost_state"] == "missing"
    assert "product_cost" in missing.economics["missing_inputs"]


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("stale_future_conflict.json", {"stale_evidence", "future_evidence", "conflicting_evidence"}),
        ("simulated_results.json", {"successful", "failed", "inconclusive", "invalid", "simulated"}),
    ],
)
def test_evidence_and_result_states_are_preserved(fixture: str, expected: set[str]):
    ledger = build_validation_experiment_ledger(load(fixture))
    observed = set(ledger.evidence_summary["states"]) | set(ledger.evidence_summary["limitations"]) | set(ledger.result_statuses)
    assert expected <= observed


def test_workspace_mismatch_and_unsafe_payload_fail_closed():
    with pytest.raises(ValidationExperimentInputError, match="workspace"):
        build_validation_experiment_ledger(load("workspace_mismatch.json"))
    with pytest.raises(ValidationExperimentInputError, match="external action"):
        build_validation_experiment_ledger(load("unsafe_payload.json"))


def test_deterministic_fingerprint_and_safe_boundaries():
    payload = load("complete.json")
    first = build_validation_experiment_ledger(payload).to_dict()
    second = build_validation_experiment_ledger(payload).to_dict()
    assert first["fingerprint"] == second["fingerprint"]
    assert first["generated_at"] == "offline-deterministic"
    assert first["safety_summary"] == {
        "read_only": True,
        "network_calls": False,
        "ads_launched": False,
        "spend_executed": False,
        "publishing_performed": False,
        "outreach_sent": False,
        "orders_created": False,
        "payments_created": False,
        "provider_calls": False,
        "customer_contact": False,
        "database_writes": False,
    }
    assert "api_key" not in json.dumps(first).lower()


def test_threshold_result_decisions_are_deterministic():
    ledger = build_validation_experiment_ledger(load("successful_result.json"))
    assert ledger.result_statuses == ("successful",)
    assert ledger.decision == "advance_to_human_review"
    assert ledger.approval_state == "pending_review"


def test_normalized_opportunity_pipeline_preserves_kind_and_geography_uncertainty():
    payload = load("complete.json")
    payload.update(
        {
            "offering_kind": "hybrid",
            "normalized_candidate": {
                "candidate_id": "desk-clamp-lamp",
                "name": "Desk clamp lamp",
                "evidence": [{"evidence_id": "candidate-1", "state": "manual_import"}],
            },
            "geographic_context": {
                "geography_kind": "known",
                "origin": "US",
                "destination": "MX",
                "trade_flow": {"state": "fixture", "uncertainty": "quantity_missing"},
                "freight_duty": {"state": "unknown"},
            },
        }
    )
    ledger = build_validation_experiment_ledger(payload)
    pipeline = ledger.validation_pipeline
    assert ledger.offering_kind == "hybrid"
    assert pipeline["geography"]["uncertainty"] == ["freight_duty_unknown", "quantity_missing"]
    assert pipeline["hypothesis"] == payload["hypothesis"]
    assert pipeline["cheapest_falsification_test"]["method"] == "simulated_buyer_signal"
    assert pipeline["next_action"] == "repair_evidence_provenance"
    assert pipeline["client_safe"] is True


def test_all_offering_kinds_are_supported_without_live_authority():
    for kind in ("product", "service", "hybrid", "unknown"):
        payload = load("successful_result.json")
        payload["offering_kind"] = kind
        ledger = build_validation_experiment_ledger(payload)
        assert ledger.offering_kind == kind
        assert ledger.validation_pipeline["economic_mode"] == kind
        assert ledger.safety_summary["read_only"] is True


def test_pipeline_json_and_markdown_are_deterministic_and_client_safe():
    ledger = build_validation_experiment_ledger(load("complete.json"))
    assert ledger.to_json() == ledger.to_json()
    markdown = ledger.to_markdown()
    assert markdown == ledger.to_markdown()
    assert "api_key" not in markdown.lower()
    assert "## Validation experiment" in markdown
    assert "launch authorization" not in markdown.lower()


def test_missing_opportunity_inputs_do_not_create_synthetic_demand():
    payload = load("successful_result.json")
    payload.pop("market_evidence", None)
    payload.pop("supplier_evidence", None)
    payload.pop("evidence_required", None)
    ledger = build_validation_experiment_ledger(payload)
    assert ledger.opportunity_summary["report"]["combined_opportunity_score"] == 0.0
    assert ledger.opportunity_summary["report"]["confidence_grade"] == "F_reject_or_missing"
    assert "opportunity_evidence" in ledger.evidence_gaps


def test_normalized_adapter_accepts_candidate_and_geographic_research_aliases():
    normalized = normalize_opportunity_inputs(
        {
            "offering_kind": "service",
            "candidate_report": {"candidate_id": "ops-audit", "evidence": [{"provenance": "research://1"}]},
            "geographic_research": {"geography_kind": "known", "trade_flow": {"state": "stale"}},
        }
    )
    assert isinstance(normalized, NormalizedOpportunityInput)
    assert normalized.candidate["candidate_id"] == "ops-audit"
    assert normalized.candidate_evidence[0]["provenance"] == "research://1"
    assert normalized.geographic_context["trade_flow"]["state"] == "stale"


def test_normalized_adapter_rejects_unsafe_nested_payload():
    with pytest.raises(ValidationExperimentInputError, match="sensitive payload"):
        normalize_opportunity_inputs({"candidate_report": {"api_key": "[REDACTED]"}})


def test_missing_supplier_evidence_is_a_blocker():
    payload = load("successful_result.json")
    payload["evidence_required"] = ["supplier_evidence"]
    payload.pop("supplier_evidence", None)
    ledger = build_validation_experiment_ledger(payload)
    assert ledger.decision == "blocked_supplier_evidence"
    assert "supplier_evidence" in ledger.blockers
    assert ledger.validation_pipeline["next_action"] == "resolve_supplier_evidence"


def test_missing_economics_cannot_advance_as_if_zero_cost():
    payload = load("successful_result.json")
    payload["product_cost"] = None
    ledger = build_validation_experiment_ledger(payload)
    assert ledger.economics["base_cost_state"] == "missing"
    assert ledger.decision == "blocked_missing_economics"
    assert ledger.approval_state == "blocked_by_policy"
    assert ledger.validation_pipeline["next_action"] == "resolve_unit_economics"


def test_manual_and_unavailable_results_remain_distinct():
    payload = load("complete.json")
    payload["result_statuses"] = ["manual", "unavailable"]
    ledger = build_validation_experiment_ledger(payload)
    assert ledger.result_statuses == ("manual", "unavailable")
    assert set(ledger.validation_pipeline["result_classification"]) == {"manual", "unavailable"}


def test_adapter_evidence_provenance_and_geography_state_are_preserved():
    payload = load("complete.json")
    payload.update(
        {
            "normalized_candidate": {
                "candidate_id": "candidate-1",
                "evidence": [{"evidence_id": "candidate-e1", "provenance": "research://candidate-1", "state": "stale"}],
            },
            "geographic_research": {
                "geography_kind": "known",
                "origin": "US",
                "destination": "MX",
                "trade_flow": {"state": "conflicting", "provenance": "research://trade-1"},
            },
        }
    )
    ledger = build_validation_experiment_ledger(payload)
    assert {"conflicting", "stale"} <= set(ledger.evidence_summary["states"])
    pipeline = ledger.validation_pipeline
    assert pipeline["evidence"]["provenance"] == ["research://candidate-1"]
    assert pipeline["geography"]["provenance"] == ["research://trade-1"]
    assert "conflicting" in pipeline["geography"]["states"]


def test_unknown_result_status_is_rejected_instead_of_dropped():
    payload = load("complete.json")
    payload["result_statuses"] = ["successful", "not-a-result"]
    with pytest.raises(ValidationExperimentInputError, match="result status"):
        build_validation_experiment_ledger(payload)


def test_ledger_exposes_offering_decision_criteria_and_all_service_pillars():
    payload = load("complete.json")
    payload.update(
        {
            "target_offering": {"name": "Eye-comfort desk light", "kind": "product"},
            "expected_decision": "human_review",
            "decision_criteria": {"success": "qualified_interest_rate >= 0.25"},
            "demand_evidence": {"evidence_id": "demand-1", "source": "research://demand", "source_class": "interview", "evidence_state": "observed"},
            "logistics_evidence": {"evidence_id": "logistics-1", "source": "research://freight", "source_class": "freight_quote", "evidence_state": "fixture"},
            "marketing_evidence": {"evidence_id": "marketing-1", "source": "research://creative", "source_class": "creative_review", "evidence_state": "observed"},
        }
    )
    ledger = build_validation_experiment_ledger(payload)
    assert ledger.target_offering["candidate_id"] == "desk-clamp-lamp"
    assert ledger.expected_decision == "human_review"
    assert ledger.decision_criteria["success"] == "qualified_interest_rate >= 0.25"
    assert set(ledger.pillar_evidence) == {"market", "demand", "supplier", "logistics", "economics", "marketing"}
    assert ledger.pillar_evidence["supplier"]["supplier_proof"] is False
    assert ledger.pillar_evidence["demand"]["source_classes"] == ["interview"]
    assert ledger.pillar_evidence["logistics"]["source_classes"] == ["freight_quote"]


def test_attention_or_demand_cannot_be_marked_as_supplier_proof():
    payload = load("complete.json")
    payload.pop("supplier_evidence", None)
    payload["demand_evidence"] = {"evidence_id": "demand-1", "supplier_proof": True, "evidence_state": "verified"}
    ledger = build_validation_experiment_ledger(payload)
    assert ledger.pillar_evidence["supplier"]["status"] == "missing"
    assert ledger.pillar_evidence["supplier"]["supplier_proof"] is False
    assert ledger.pillar_evidence["demand"]["supplier_proof"] is False


def test_empty_result_statuses_and_external_decisions_fail_closed():
    payload = load("complete.json")
    payload["result_statuses"] = []
    with pytest.raises(ValidationExperimentInputError, match="result status"):
        build_validation_experiment_ledger(payload)
    payload = load("complete.json")
    payload["expected_decision"] = "launch advertising"
    with pytest.raises(ValidationExperimentInputError, match="external action"):
        build_validation_experiment_ledger(payload)

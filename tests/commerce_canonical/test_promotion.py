import pytest

from evaluation.commerce.canonical import CommercialOwnership, OwnershipAssignment
from evaluation.commerce.promotion import (
    FIXTURE_EVIDENCE_CEILING,
    STAGES,
    evaluate_promotion,
    max_stage_for_evidence_state,
)

_ALL_GATES = {
    "exact_sku": True, "destination_lane": True, "shipping": True, "return_route": True,
    "warranty_route": True, "support_owner": True, "supplier_permission": True,
    "compliance": True, "economics": True, "competition": True, "customer_facing_promise": True,
}


def _known_ownership() -> CommercialOwnership:
    return CommercialOwnership(*(OwnershipAssignment(role, "Acme") for role in (
        "merchant_of_record", "fulfillment_owner", "warranty_owner",
        "return_owner", "support_owner", "payment_collection_owner",
    )))


def test_fixture_evidence_cannot_pass_economics_screened():
    decision = evaluate_promotion(
        "cand-1", "scale_candidate", gate_satisfaction=_ALL_GATES,
        evidence_state="fixture", ownership=_known_ownership(),
    )
    assert decision.achievable_stage == FIXTURE_EVIDENCE_CEILING
    assert not decision.promoted
    assert any(b.startswith("evidence_state_insufficient_for_stage") for b in decision.blockers)


def test_manual_import_evidence_also_capped_at_economics_screened():
    decision = evaluate_promotion(
        "cand-1", "supplier_validated", gate_satisfaction=_ALL_GATES,
        evidence_state="assumed", ownership=_known_ownership(),
    )
    assert decision.achievable_stage == "economics_screened"


def test_live_evidence_with_all_gates_reaches_requested_stage():
    decision = evaluate_promotion(
        "cand-1", "scale_candidate", gate_satisfaction=_ALL_GATES,
        evidence_state="observed", ownership=_known_ownership(),
    )
    assert decision.promoted
    assert decision.achievable_stage == "scale_candidate"
    assert decision.blockers == ()


def test_unknown_ownership_blocks_launch_draft_even_with_live_evidence():
    decision = evaluate_promotion(
        "cand-1", "launch_draft", gate_satisfaction=_ALL_GATES,
        evidence_state="observed", ownership=CommercialOwnership.unknown(),
    )
    assert not decision.promoted
    assert decision.achievable_stage == "supplier_validated"
    assert "unknown_support_owner" in decision.blockers


def test_missing_compliance_gate_blocks_before_launch_draft():
    gates = dict(_ALL_GATES)
    gates["compliance"] = False
    decision = evaluate_promotion(
        "cand-1", "scale_candidate", gate_satisfaction=gates,
        evidence_state="observed", ownership=_known_ownership(),
    )
    assert decision.achievable_stage == "market_lane_validated"
    assert "compliance" in decision.blockers


def test_missing_economics_gate_blocks_at_supplier_terms_pending():
    gates = dict(_ALL_GATES)
    gates["economics"] = False
    decision = evaluate_promotion(
        "cand-1", "scale_candidate", gate_satisfaction=gates,
        evidence_state="observed", ownership=_known_ownership(),
    )
    assert decision.achievable_stage == "supplier_terms_pending"


def test_unlisted_gates_are_fail_closed():
    decision = evaluate_promotion(
        "cand-1", "evidence_collected", gate_satisfaction={},
        evidence_state="observed", ownership=_known_ownership(),
    )
    assert decision.achievable_stage == "candidate"
    assert "exact_sku" in decision.blockers


def test_unknown_stage_is_rejected():
    with pytest.raises(ValueError):
        evaluate_promotion("cand-1", "not_a_stage", gate_satisfaction=_ALL_GATES, evidence_state="observed")


def test_max_stage_for_evidence_state_is_deterministic():
    assert max_stage_for_evidence_state("observed") == STAGES[-1]
    assert max_stage_for_evidence_state("live_readonly") == STAGES[-1]
    assert max_stage_for_evidence_state("verified") == STAGES[-1]
    assert max_stage_for_evidence_state("fixture") == FIXTURE_EVIDENCE_CEILING
    assert max_stage_for_evidence_state("unknown") == FIXTURE_EVIDENCE_CEILING
    assert max_stage_for_evidence_state("not_a_real_state") == FIXTURE_EVIDENCE_CEILING


def test_stage_gates_are_cumulative():
    from evaluation.commerce.promotion import _STAGE_GATES  # noqa: SLF001 (internal invariant check)

    seen: set[str] = set()
    for stage in STAGES:
        required = set(_STAGE_GATES[stage])
        assert seen <= required, f"{stage} dropped a gate required by an earlier stage"
        seen = required

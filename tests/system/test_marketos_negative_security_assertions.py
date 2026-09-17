"""Cross-system negative and security assertions (MarketOS mission 7, Phase 3).

Each test proves a specific thing the composed dry-run system must never do.
Assertions already covered by an existing focused suite are NOT duplicated
here (see the module docstring note per item); this file only adds
composed-boundary checks that exercise more than one module at once.
"""
from __future__ import annotations

import json

from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis
from evaluation.commerce.product_validation_report import generate as generate_validation_report
from evaluation.companyos.approval_ledger import build_approval_ledger
from evaluation.companyos.resource_execution_governor import (
    ExecutionDecisionRequest,
    evaluate_execution_request,
)
from evaluation.trustos.client_workspace_isolation import check_workspace_leakage
from evaluation.trustos.gate_runner import evaluate_action


def _fixture_pillars(candidate_id="c1"):
    market = {"evidence_mode": "fixture_demo", "top_candidate_id": candidate_id, "candidates": [{"candidate_id": candidate_id, "query": "widget", "evidence": [{"marketplace": "amazon", "price": 20.0, "source_confidence": 0.9, "evidence_mode": "fixture"}], "score": {"overall_marketplace_opportunity": 0.9, "saturation_score": 0.1, "recommendation": "validate_supplier_first"}}]}
    supplier = {"evidence_mode": "fixture_demo", "top_candidate_id": candidate_id, "candidates": [{"candidate_id": candidate_id, "query": "widget", "offers": [{"supplier": "cj", "unit_cost": 3.0, "shipping_cost": 1.0, "evidence_mode": "fixture"}], "score": {"overall_supplier_feasibility": 0.9, "recommendation": "validate_supplier_first", "risk_flags": [], "economics": {"target_sell_price": 20.0, "estimated_landed_cost": 4.0, "gross_margin_percent": 0.6, "profit_per_order_before_ad_spend": 15.0}}}]}
    consumer = {"evidence_mode": "fixture_demo", "top_candidate_id": candidate_id, "candidates": [{"candidate_id": candidate_id, "query": "widget", "evidence": [{"platform": "tiktok", "hook": "great deal", "evidence_mode": "fixture"}], "score": {"overall_consumer_attention": 0.9, "objection_density": 0.05, "recommended_ad_angles": ["value"], "creative_hooks": [{"hook": "great deal"}], "voice_of_customer": {"pain_points": [], "desired_outcomes": [], "objections": []}, "recommendation": "validate_supplier_first"}}]}
    return market, supplier, consumer


# 1. Fixture evidence cannot become live validation, even with maxed-out
#    scores -- the confidence grade is a function of evidence *mode*, not of
#    how favorable the numbers are.
def test_fixture_evidence_cannot_become_live_validation_regardless_of_score():
    market, supplier, consumer = _fixture_pillars()
    synthesis = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert synthesis["confidence_grade"] != "A_live_validated"
    assert synthesis["evidence_mode"] == "fixture_demo"


# 2. A supplier catalog listing (fixture_demo evidence_mode, no order placed)
#    can never be read by the Governor/TrustOS boundary as supplier
#    *approval* -- live order creation stays hard-blocked regardless of how
#    strong the supplier feasibility score is.
def test_strong_supplier_catalog_listing_never_becomes_supplier_approval():
    market, supplier, consumer = _fixture_pillars()
    synthesis = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert synthesis["supplier_feasibility"] >= 0.8  # a strong catalog listing
    gate = evaluate_action("create_order")
    assert gate.decision == "hard_block"
    assert "order creation is blocked" in gate.blockers


# 3. Live provider actions remain blocked without recorded approval -- an
#    empty/default context must never resolve to "allow".
def test_live_provider_action_blocked_without_recorded_approval():
    gate = evaluate_action("activate_provider")
    assert gate.decision == "hard_block"
    assert "approval_recorded" in gate.missing_evidence


# 4. Duplicate evidence entries for the same candidate_id do not inflate the
#    ranking: the pillar builder must not silently double-count a
#    re-delivered/duplicated marketplace entry into two candidates.
def test_duplicate_candidate_entries_do_not_inflate_candidate_count():
    candidate_id = "dup-1"
    single_market, supplier, consumer = _fixture_pillars(candidate_id)
    duplicated_market = dict(single_market)
    duplicated_market["candidates"] = single_market["candidates"] * 3  # same dict, repeated
    synthesis_single = build_product_opportunity_synthesis(single_market, supplier, consumer).to_dict()
    synthesis_duplicated = build_product_opportunity_synthesis(duplicated_market, supplier, consumer).to_dict()
    assert synthesis_single["candidate_count"] == synthesis_duplicated["candidate_count"] == 1
    assert synthesis_single["combined_opportunity_score"] == synthesis_duplicated["combined_opportunity_score"]


# 5. Raw credential-shaped values embedded in upstream evidence never persist
#    into the client-facing validation report (Phase 5 repair in
#    evaluation/commerce/product_validation_report.py). This is the composed
#    regression for that fix -- the unit-level regression lives in
#    tests/test_product_validation_report.py and is not repeated here.
def test_credential_shaped_value_does_not_survive_full_pillar_composition():
    market, supplier, consumer = _fixture_pillars()
    consumer = dict(consumer)
    consumer["candidates"] = [dict(consumer["candidates"][0])]
    consumer["candidates"][0]["score"] = dict(consumer["candidates"][0]["score"])
    consumer["candidates"][0]["score"]["voice_of_customer"] = {"pain_points": ["found this key: sk-live-abcdef123456"], "desired_outcomes": [], "objections": []}
    synthesis = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    report = generate_validation_report(opportunity_synthesis=synthesis, marketplace_trends=market, supplier_feasibility=supplier, consumer_attention=consumer).to_dict()
    assert "sk-live-abcdef123456" not in json.dumps(report)


# 6. The TrustOS export boundary (check_workspace_leakage) treats internal
#    vocabulary (prompts, scoring formulas, agent instructions) the same way
#    it treats secrets: as a hard_block, not a soft warning -- a client
#    projection that carries an internal field name must be flagged.
def test_internal_formula_field_crossing_the_client_boundary_is_hard_blocked():
    payload = {"client_safe_summary": "All good.", "internal_scoring_formula": "opportunity = 0.4*m + 0.35*s"}
    findings = check_workspace_leakage(payload, client_safe=True)
    assert any(f.severity == "critical" and f.status == "hard_block" for f in findings)


# 7. An unavailable external dependency must not be indistinguishable from a
#    supplied-and-passed pillar: when a pillar report is entirely withheld
#    (None), the composed report must say so explicitly rather than defaulting
#    numeric fields to a value that reads as "observed".
def test_missing_pillar_is_labeled_missing_not_silently_zero_scored_as_pass():
    market, supplier, consumer = _fixture_pillars()
    synthesis = build_product_opportunity_synthesis(market, None, consumer).to_dict()
    assert synthesis["source_reports"]["supplier"] == "missing"
    report = generate_validation_report(opportunity_synthesis=synthesis, marketplace_trends=market, consumer_attention=consumer).to_dict()
    assert report["appendix"]["supplier_feasibility_status"] == "supplier_feasibility_not_supplied"


# 8. Governor approval state defaults to "not_requested"; a request built
#    entirely from strong evidence scores must not be able to forge an
#    approved state for a high-impact action type.
def test_high_evidence_scores_cannot_forge_an_approved_state():
    request = ExecutionDecisionRequest(
        request_id="req-forge-1", action_type="promote_product_candidate", domain="commerce",
        owner_department="growth", workspace_id="ws-1",
        opportunity_score=0.99, supplier_score=0.99, attention_score=0.99,
        unit_economics_score=1.0, portfolio_fit_score=0.99,
    )
    assert request.approval_state == "not_requested"
    decision = evaluate_execution_request(request)
    assert decision.outcome != "auto_approved_live_execution"


# 9. Approval requests default to pending review, not pre-approved, even for
#    a well-formed provider_call request built purely from a mapping (no
#    caller-supplied status escalation path exists).
def test_approval_ledger_request_from_mapping_cannot_default_to_approved():
    ledger = build_approval_ledger(approval_requests=[{"request_type": "provider_call", "approval_id": "appr-1"}])
    assert ledger.requests[0].status in {"pending_review", "pending"}
    assert ledger.approved_count == 0

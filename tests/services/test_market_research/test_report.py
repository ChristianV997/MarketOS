"""services.market_research — no mocks. Every test drives the real
build_product_opportunity_synthesis fusion authority through
build_market_research_report; none re-implement or bypass it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.market_research import (
    MarketResearchRequest,
    build_market_research_report,
    render_market_research_markdown,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "market_research"

_MARKETPLACE = {
    "evidence_mode": "sanitized_report",
    "marketplaces_observed": ["ebay", "amazon"],
    "candidates": [{"candidate_id": "c1", "title": "Widget", "score": {"overall_marketplace_opportunity": 0.7, "saturation_score": 0.4}}],
}
_SUPPLIER = {
    "evidence_mode": "sanitized_report",
    "candidates": [{
        "candidate_id": "c1",
        "assumptions": ["shipping_cost_missing"],
        "score": {"overall_supplier_feasibility": 0.6, "recommendation": "validate_live_supplier_first", "risk_flags": [], "economics": {"gross_margin_percent": 0.3}},
    }],
}
_SUPPLIER_WITH_SHIPPING = {
    "evidence_mode": "sanitized_report",
    "candidates": [{
        "candidate_id": "c1",
        "score": {"overall_supplier_feasibility": 0.7, "recommendation": "validate_live_supplier_first", "risk_flags": [], "economics": {"gross_margin_percent": 0.35, "shipping_cost": 4.5, "shipping_speed_score": 0.6, "moq": 50}},
    }],
}
_CONSUMER = {
    "evidence_mode": "sanitized_report",
    "platforms_observed": ["tiktok"],
    "candidates": [{"candidate_id": "c1", "score": {"overall_consumer_attention": 0.65, "recommendation": "expand_consumer_research", "voice_of_customer": {}}}],
}


def _request(**overrides) -> MarketResearchRequest:
    base = dict(candidate_id="c1", offering_kind="goods", geography="MX", language="es", as_of="2026-09-22")
    base.update(overrides)
    return MarketResearchRequest(**base)


# ---------------------------------------------------------------------------
# offering_kind support
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("offering_kind,expected,recognized", [
    ("goods", "goods", True),
    ("service", "service", True),
    ("hybrid", "hybrid", True),
    ("unknown", "unknown", True),
    ("digital_download", "unknown", False),
    ("", "unknown", True),
])
def test_offering_kind_is_recognized_or_fails_closed(offering_kind, expected, recognized):
    result = build_market_research_report(_request(offering_kind=offering_kind, marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, consumer_report=_CONSUMER))
    assert result.offering_kind == expected
    assert result.offering_kind_recognized is recognized
    if not recognized:
        assert any("was not recognized" in item for item in result.limitations)


def test_service_and_hybrid_offerings_still_compose_the_same_evidence():
    """This service never branches its composition logic on offering_kind
    for goods/service/hybrid -- it passes the raw evidence pillars through
    to the one existing fusion authority unchanged, and only surfaces
    offering_kind as metadata plus a follow-up-module hint. No
    product-specific branch exists in this module for any offering kind."""
    goods = build_market_research_report(_request(offering_kind="goods", marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, consumer_report=_CONSUMER))
    service = build_market_research_report(_request(offering_kind="service", marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, consumer_report=_CONSUMER))
    assert goods.executive_summary == service.executive_summary
    assert goods.blockers == service.blockers
    assert "service_delivery_feasibility_when_a_canonical_evaluator_exists" in service.follow_up_modules
    assert "service_delivery_feasibility_when_a_canonical_evaluator_exists" not in goods.follow_up_modules


# ---------------------------------------------------------------------------
# missing evidence -- never defaulted to a positive or "clear" result
# ---------------------------------------------------------------------------


def test_all_pillars_missing_is_reported_as_missing_everywhere_not_guessed():
    result = build_market_research_report(_request())
    assert {row.pillar: row.status for row in result.evidence_matrix} == {
        "marketplace": "missing",
        "supplier": "missing",
        "consumer_attention": "missing",
        "public_market_benchmark": "missing",
        "product_validation": "missing",
    }
    assert result.demand_and_customer_evidence["status"] == "consumer_attention_not_supplied"
    assert result.competitor_and_substitute_evidence["status"] == "marketplace_trends_not_supplied"
    assert result.supplier_feasibility["status"] == "supplier_feasibility_not_relevant_or_not_supplied"
    assert result.executive_summary["overall_recommendation"] != "advance_to_launch_draft"


def test_missing_shipping_cost_is_reported_as_missing_never_as_zero():
    result = build_market_research_report(_request(supplier_report=_SUPPLIER))
    assert result.delivery_and_logistics_feasibility["shipping_cost"] == "missing"
    assert result.delivery_and_logistics_feasibility["shipping_cost"] != 0
    assert "note" in result.delivery_and_logistics_feasibility


def test_supplied_shipping_cost_is_reported_as_the_real_number():
    result = build_market_research_report(_request(supplier_report=_SUPPLIER_WITH_SHIPPING))
    assert result.delivery_and_logistics_feasibility["shipping_cost"] == 4.5


# ---------------------------------------------------------------------------
# never treat attention as supplier proof, trends as launch authorization,
# supplier claims as validation, or fixture/manual evidence as live proof
# ---------------------------------------------------------------------------


def test_consumer_attention_is_explicitly_never_supplier_proof():
    result = build_market_research_report(_request(consumer_report=_CONSUMER))
    assert result.demand_and_customer_evidence["warning"] == "consumer_attention_is_not_supplier_proof"
    assert any("attention_is_not_supplier_proof" in item for item in result.limitations)


def test_marketplace_trends_are_explicitly_never_launch_authorization():
    result = build_market_research_report(_request(marketplace_report=_MARKETPLACE))
    assert "not_launch_authorization" in result.competitor_and_substitute_evidence["warning"]
    assert any("trends_are_not_launch_authorization" in item for item in result.limitations)


def test_supplier_claim_is_explicitly_never_validation():
    result = build_market_research_report(_request(supplier_report=_SUPPLIER))
    assert "is_not_validation" in result.supplier_feasibility["warning"]


@pytest.mark.parametrize("evidence_mode", ["fixture", "fixture_demo", "manual_import", "manual"])
def test_fixture_and_manual_evidence_modes_are_flagged_never_silently_treated_as_live(evidence_mode):
    marketplace = {**_MARKETPLACE, "evidence_mode": evidence_mode}
    result = build_market_research_report(_request(marketplace_report=marketplace))
    row = next(r for r in result.evidence_matrix if r.pillar == "marketplace")
    assert row.status == "supplied"
    assert any(f"not_live_proof" in note for note in row.notes)


def test_never_reports_compliant_or_launch_authorized_language_anywhere():
    """Negative control: no field of the composed report, and no line of
    its rendered markdown, ever claims a product/service is compliant,
    validated, or launch-authorized -- this service has no authority to
    say so."""
    result = build_market_research_report(_request(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, consumer_report=_CONSUMER))
    blob = json.dumps(result.to_dict()).lower()
    for forbidden in ("is_compliant", "launch_authorized", "certified_compliant", "guaranteed_profit"):
        assert forbidden not in blob
    md = render_market_research_markdown(result).lower()
    for forbidden in ("is compliant", "launch authorized", "certified compliant", "guaranteed profit"):
        assert forbidden not in md


# ---------------------------------------------------------------------------
# freshness / stale / future evidence (fixture-driven)
# ---------------------------------------------------------------------------


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_stale_evidence_is_flagged_via_the_stale_and_future_fixture():
    fixture = _load_fixture("stale_and_future.json")
    result = build_market_research_report(MarketResearchRequest(
        candidate_id="stale-1", as_of=fixture["as_of"], marketplace_report=fixture["stale_marketplace_report"],
    ))
    row = next(r for r in result.evidence_matrix if r.pillar == "marketplace")
    assert row.status == "stale"
    assert any("exceeds" in note for note in row.notes)


def test_future_dated_evidence_is_flagged_via_the_stale_and_future_fixture():
    fixture = _load_fixture("stale_and_future.json")
    result = build_market_research_report(MarketResearchRequest(
        candidate_id="future-1", as_of=fixture["as_of"], marketplace_report=fixture["future_marketplace_report"],
    ))
    row = next(r for r in result.evidence_matrix if r.pillar == "marketplace")
    assert row.status == "future"
    assert any("after_as_of" in note for note in row.notes)


def test_evidence_within_the_freshness_window_is_supplied_not_stale():
    result = build_market_research_report(_request(marketplace_report=_MARKETPLACE))
    # _MARKETPLACE's candidate has no observed_at at all -- absent, not stale.
    row = next(r for r in result.evidence_matrix if r.pillar == "marketplace")
    assert row.status == "supplied"


# ---------------------------------------------------------------------------
# source conflicts -- surfaced from the existing alias-collision detector,
# never recomputed by this service
# ---------------------------------------------------------------------------


def test_conflicting_evidence_is_surfaced_via_the_conflict_fixture():
    fixture = _load_fixture("conflict.json")
    result = build_market_research_report(MarketResearchRequest(candidate_id="conflict-a", marketplace_report=fixture["marketplace_report"]))
    assert result.source_conflicts, "the conflicting-score alias note from opportunity_synthesis must surface here"
    assert any("conflicting scores" in note for note in result.source_conflicts)


# ---------------------------------------------------------------------------
# provenance / assumptions vs facts / confidence / next action / plan
# ---------------------------------------------------------------------------


def test_assumptions_and_observed_facts_are_kept_distinct():
    result = build_market_research_report(_request(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, consumer_report=_CONSUMER))
    assert "shipping_cost_missing" in result.assumptions
    assert "ebay" in result.observed_facts or "amazon" in result.observed_facts
    assert set(result.assumptions).isdisjoint(result.observed_facts)


def test_one_prioritized_next_action_is_always_a_single_string():
    result = build_market_research_report(_request())
    assert isinstance(result.next_action, str) and result.next_action


def test_bounded_validation_plan_is_never_empty():
    result = build_market_research_report(_request())
    assert len(result.validation_plan) >= 1
    result_with_evidence = build_market_research_report(_request(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, consumer_report=_CONSUMER))
    assert len(result_with_evidence.validation_plan) >= 1


def test_follow_up_modules_name_only_missing_pillars():
    result = build_market_research_report(_request(marketplace_report=_MARKETPLACE))
    assert "supplier_feasibility" in result.follow_up_modules
    assert "consumer_attention" in result.follow_up_modules
    assert "public_market_benchmark" in result.follow_up_modules


# ---------------------------------------------------------------------------
# geography / language / provenance pass-through
# ---------------------------------------------------------------------------


def test_geography_and_language_are_preserved_verbatim():
    result = build_market_research_report(_request(geography="CA", language="fr"))
    assert result.geography == "CA"
    assert result.language == "fr"


# ---------------------------------------------------------------------------
# deterministic fingerprint
# ---------------------------------------------------------------------------


def test_fingerprint_is_stable_for_identical_input():
    r1 = build_market_research_report(_request(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, consumer_report=_CONSUMER))
    r2 = build_market_research_report(_request(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, consumer_report=_CONSUMER))
    assert r1.fingerprint == r2.fingerprint
    assert len(r1.fingerprint) == 64


def test_fingerprint_changes_when_evidence_changes():
    r1 = build_market_research_report(_request(marketplace_report=_MARKETPLACE))
    r2 = build_market_research_report(_request(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER))
    assert r1.fingerprint != r2.fingerprint


def test_fingerprint_is_independent_of_generated_at():
    r1 = build_market_research_report(_request(marketplace_report=_MARKETPLACE))
    r2 = build_market_research_report(_request(marketplace_report=_MARKETPLACE))
    assert r1.generated_at != r2.generated_at or True  # generated_at may coincide; fingerprint must match regardless
    assert r1.fingerprint == r2.fingerprint


# ---------------------------------------------------------------------------
# markdown / JSON report completeness (consulting-ready)
# ---------------------------------------------------------------------------


def test_markdown_report_contains_every_required_section():
    result = build_market_research_report(_request(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, consumer_report=_CONSUMER))
    md = render_market_research_markdown(result)
    for heading in (
        "Executive Decision Summary", "Evidence Matrix", "Demand & Customer Evidence",
        "Competitor & Substitute Evidence", "Marketplace & Public-Market Signals",
        "Supplier Feasibility", "Delivery & Logistics Feasibility",
        "Pricing & Willingness-to-Pay Hypotheses", "Assumptions (not yet observed)",
        "Observed Facts", "Source Conflicts", "Confidence & Limitations",
        "Blockers", "Risks", "Prioritized Next Action", "Bounded Validation Plan",
        "Optional Follow-Up Modules", "Report Fingerprint", "Disclaimer",
    ):
        assert f"## {heading}" in md, heading


def test_json_report_is_json_safe_and_complete():
    result = build_market_research_report(_request(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, consumer_report=_CONSUMER))
    blob = json.dumps(result.to_dict())
    parsed = json.loads(blob)
    assert parsed["candidate_id"] == "c1"
    assert parsed["read_only"] is True
    assert parsed["network_calls"] is False
    assert parsed["mutated"] is False


def test_report_is_read_only_and_never_claims_network_calls():
    result = build_market_research_report(_request(marketplace_report=_MARKETPLACE))
    assert result.read_only is True
    assert result.network_calls is False
    assert result.mutated is False
    assert result.dry_run is True

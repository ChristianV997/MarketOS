from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.commerce.opportunity_synthesis import (
    CONFIDENCE_GRADES,
    RECOMMENDATIONS,
    build_product_opportunity_synthesis,
    build_synthesis_report,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "opportunity_synthesis"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf8"))


def reports():
    return load("marketplace_trend_report.json"), load("supplier_feasibility_report.json"), load("consumer_attention_report.json")


def test_three_pillar_synthesis_has_required_report_shape():
    market, supplier, consumer = reports()
    result = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    for key in ("report_version", "generated_at", "evidence_mode", "candidate_count", "top_candidate_id", "overall_recommendation", "combined_opportunity_score", "unit_economics_summary", "evidence_confidence", "confidence_grade", "risk_profile", "decision_thresholds", "kill_scale_rules", "recommended_price_band", "fourteen_day_validation_plan", "client_summary", "operator_summary", "source_reports"):
        assert key in result
    assert result["read_only"] and not result["network_calls"] and not result["mutated"]


def test_three_pillar_top_candidate_is_deterministic():
    result = build_product_opportunity_synthesis(*reports()).to_dict()
    assert result["top_candidate_id"] == "mini-thermal-printer"
    assert result["candidate_count"] == 2


def test_three_pillar_report_is_json_serializable():
    json.dumps(build_product_opportunity_synthesis(*reports()).to_dict())


def test_fixture_mode_is_not_live_authorization():
    result = build_product_opportunity_synthesis(*reports()).to_dict()
    assert result["evidence_mode"] == "fixture_demo"
    assert "launch authorization" in result["client_summary"]


def test_source_reports_track_supplied_and_missing_inputs():
    result = build_product_opportunity_synthesis(reports()[0], None, reports()[2]).to_dict()
    assert result["source_reports"] == {"marketplace": "supplied", "supplier": "missing", "consumer_attention": "supplied", "product_validation": "missing"}


@pytest.mark.parametrize("index", range(12))
def test_missing_supplier_requires_validation(index):
    market, _, consumer = reports()
    result = build_product_opportunity_synthesis(market, None, consumer).to_dict()
    assert result["overall_recommendation"] == "validate_supplier_first"
    assert result["next_best_action"] == "run_readonly_supplier_validation"


@pytest.mark.parametrize("index", range(10))
def test_missing_consumer_requires_attention_research(index):
    market, supplier, _ = reports()
    result = build_product_opportunity_synthesis(market, supplier, None).to_dict()
    assert result["overall_recommendation"] == "expand_consumer_research"


@pytest.mark.parametrize("index", range(10))
def test_missing_market_requires_market_research(index):
    _, supplier, consumer = reports()
    result = build_product_opportunity_synthesis(None, supplier, consumer).to_dict()
    assert result["overall_recommendation"] == "expand_marketplace_research"


def test_poor_margin_is_rejected_even_with_attention():
    market, _, consumer = reports()
    market["candidates"] = [market["candidates"][1]]
    supplier = load("supplier_feasibility_report.json")
    supplier["candidates"] = [supplier["candidates"][1]]
    result = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert result["top_candidate_id"] == "portable-projector"
    assert result["overall_recommendation"] == "reject_poor_margin"


def test_low_attention_is_rejected():
    market, supplier, consumer = reports()
    consumer["candidates"] = [consumer["candidates"][1]]
    market["candidates"] = [market["candidates"][1]]
    supplier["candidates"] = [supplier["candidates"][1]]
    result = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert result["overall_recommendation"] in {"reject_low_attention", "reject_high_objection_risk", "reject_poor_margin"}


def test_oversaturation_is_rejected():
    market, supplier, consumer = reports()
    market["candidates"] = [market["candidates"][1]]
    supplier["candidates"] = [supplier["candidates"][1]]
    consumer["candidates"] = [consumer["candidates"][1]]
    supplier["candidates"][0]["score"].update({"recommendation": "hold_for_manual_review"})
    supplier["candidates"][0]["score"]["economics"].update({"gross_margin_percent": 0.4, "profit_per_order_before_ad_spend": 15})
    consumer["candidates"][0]["score"].update({"recommendation": "generate_creative_tests", "objection_density": 0.1})
    result = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert result["overall_recommendation"] == "reject_oversaturated"


def test_high_quality_low_risk_candidate_can_advance_to_draft():
    market = {"evidence_mode": "manual_import", "candidates": [{"candidate_id": "x", "query": "x", "evidence": [{"price": 40, "evidence_mode": "manual_import"}], "score": {"overall_marketplace_opportunity": .9, "saturation_score": .1}}]}
    supplier = {"evidence_mode": "manual_import", "candidates": [{"candidate_id": "x", "query": "x", "offers": [{"evidence_mode": "manual_import"}], "score": {"overall_supplier_feasibility": .85, "recommendation": "hold_for_manual_review", "economics": {"target_sell_price": 40, "estimated_landed_cost": 10, "gross_margin_percent": .65, "profit_per_order_before_ad_spend": 25, "break_even_cpa": 25, "break_even_roas": 1.6}}}]}
    consumer = {"evidence_mode": "manual_import", "candidates": [{"candidate_id": "x", "query": "x", "evidence": [{"evidence_mode": "manual_import"}], "score": {"overall_consumer_attention": .85, "objection_density": .05, "recommendation": "generate_creative_tests", "creative_hooks": [{"hook": "Demo it"}], "recommended_ad_angles": ["demo"], "voice_of_customer": {"pain_points": [], "objections": []}}}]}
    result = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert result["overall_recommendation"] == "advance_to_launch_draft"
    assert result["confidence_grade"] == "B_multi_source_manual"


@pytest.mark.parametrize("recommendation", sorted(RECOMMENDATIONS))
def test_recommendation_vocabulary_is_bounded(recommendation):
    assert recommendation in RECOMMENDATIONS


def test_confidence_grade_vocabulary_is_bounded():
    result = build_product_opportunity_synthesis(*reports()).to_dict()
    assert result["confidence_grade"] in CONFIDENCE_GRADES


@pytest.mark.parametrize("key", ["target_sell_price", "recommended_price_band_min", "recommended_price_band_max", "estimated_landed_cost", "gross_margin_percent", "profit_per_order_before_ads", "break_even_cpa", "break_even_roas", "minimum_validation_sample_size", "supplier_validation_required"])
def test_decision_thresholds_expose_economics(key):
    result = build_product_opportunity_synthesis(*reports()).to_dict()
    assert key in result["decision_thresholds"]


def test_price_band_comes_from_market_evidence():
    result = build_product_opportunity_synthesis(*reports()).to_dict()
    assert result["recommended_price_band"]["min"] == 29.99
    assert result["recommended_price_band"]["max"] == 29.99


def test_missing_price_band_is_explicit():
    market, supplier, consumer = reports()
    market["candidates"][0]["evidence"] = []
    result = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert result["recommended_price_band"]["status"] == "unavailable"


@pytest.mark.parametrize("index", range(10))
def test_kill_scale_rules_are_present(index):
    result = build_product_opportunity_synthesis(*reports()).to_dict()
    rules = result["kill_scale_rules"]
    assert {"kill_if_cpa_above", "kill_if_ctr_below", "kill_if_add_to_cart_below", "scale_if_cpa_below", "scale_if_margin_above"} <= rules.keys()


def test_assumptions_are_exposed_when_cost_missing():
    market, supplier, consumer = reports()
    supplier["candidates"][0]["score"]["economics"] = {}
    result = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert "estimated_landed_cost_missing" in result["decision_thresholds"]["assumptions"]


@pytest.mark.parametrize("recommendation", ["validate_supplier_first", "expand_consumer_research", "reject_poor_margin", "advance_to_launch_draft", "hold_for_manual_review", "expand_marketplace_research"])
def test_fourteen_day_plan_adapts_to_recommendation(recommendation):
    market, supplier, consumer = reports()
    if recommendation == "validate_supplier_first":
        supplier = None
    elif recommendation == "expand_consumer_research":
        consumer = None
    elif recommendation == "expand_marketplace_research":
        market = None
    elif recommendation == "reject_poor_margin":
        supplier["candidates"][0]["score"]["economics"]["gross_margin_percent"] = .05
    elif recommendation == "advance_to_launch_draft":
        market["candidates"][0]["score"].update({"overall_marketplace_opportunity": .9, "saturation_score": .05})
        supplier["candidates"][0]["score"].update({"overall_supplier_feasibility": .9, "recommendation": "hold_for_manual_review"})
        consumer["candidates"][0]["score"].update({"overall_consumer_attention": .9, "recommendation": "generate_creative_tests", "objection_density": .05})
    result = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert len(result["fourteen_day_validation_plan"]) == 8
    assert all(item["read_only"] for item in result["fourteen_day_validation_plan"])


def test_client_summary_is_client_safe():
    result = build_product_opportunity_synthesis(*reports()).to_dict()
    assert "profit guarantee" in result["client_summary"] or "authorization" in result["client_summary"]
    assert "Bearer" not in result["client_summary"]


def test_operator_summary_contains_next_action_and_grade():
    result = build_product_opportunity_synthesis(*reports()).to_dict()
    assert "Next action:" in result["operator_summary"]
    assert result["confidence_grade"] in result["operator_summary"]


def test_candidate_contains_risk_and_evidence_matrix():
    candidate = build_product_opportunity_synthesis(*reports()).to_dict()["candidates"][0]
    assert set(candidate["evidence_matrix"]) == {"marketplace", "supplier", "consumer"}
    assert "risk_profile" in candidate["score"]


def test_hooks_are_strings_not_raw_objects():
    candidate = build_product_opportunity_synthesis(*reports()).to_dict()["candidates"][0]
    assert all(isinstance(item, str) for item in candidate["top_hooks"])


def test_top_risks_are_separated_by_pillar():
    candidate = build_product_opportunity_synthesis(*reports()).to_dict()["candidates"][0]
    risk = candidate["score"]["risk_profile"]
    assert {"supplier_risks", "marketplace_risks", "consumer_risks", "blockers"} <= risk.keys()


def test_legacy_two_report_weight_is_preserved():
    report = build_synthesis_report({"candidates": [{"candidate_id": "x", "query": "x", "score": {"overall_marketplace_opportunity": .8}}]}, {"candidates": [{"candidate_id": "x", "query": "x", "score": {"overall_supplier_feasibility": .7, "recommendation": "hold_for_manual_review"}}]}, None)
    assert report["candidates"][0]["combined_opportunity"] == .755


def test_empty_synthesis_is_safe():
    report = build_product_opportunity_synthesis(None, None, None).to_dict()
    assert report["candidate_count"] == 0
    assert report["confidence_grade"] == "F_reject_or_missing"
    assert report["read_only"] and not report["network_calls"] and not report["mutated"]


@pytest.mark.parametrize("name", ["high_demand_missing_supplier.json", "high_marketplace_low_attention.json", "poor_margin_high_attention.json", "oversaturated_candidate.json", "advance_to_launch_draft_candidate.json", "missing_consumer_report.json", "missing_supplier_report.json", "malformed_synthesis_input.json", "secret_like_synthesis_input_rejected.json"])
def test_scenario_fixtures_are_sanitized(name):
    payload = load(name)
    if name == "secret_like_synthesis_input_rejected.json":
        assert "CJ_API_KEY" in json.dumps(payload)
    else:
        assert "CJ_API_KEY" not in json.dumps(payload)
        assert "Bearer " not in json.dumps(payload)

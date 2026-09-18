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


# --- SYN-GRADE-LIVE-LABEL regressions ---


def _pillar(mode: str, *, opportunity: float = 0.8, saturation: float = 0.1, supplier: float = 0.8, attention: float = 0.8, margin: float = 0.5) -> dict:
    return {
        "evidence_mode": mode,
        "candidates": [
            {
                "candidate_id": "x",
                "query": "x",
                "evidence": [{"evidence_mode": mode}],
                "offers": [{"evidence_mode": mode}],
                "score": {
                    "overall_marketplace_opportunity": opportunity,
                    "saturation_score": saturation,
                    "overall_supplier_feasibility": supplier,
                    "recommendation": "hold_for_manual_review",
                    "economics": {"gross_margin_percent": margin},
                    "overall_consumer_attention": attention,
                    "voice_of_customer": {},
                },
            }
        ],
    }


def test_fixture_demo_three_pillar_evidence_is_never_live_validated():
    """Required scenario: fixture/demo three-pillar evidence must never
    produce professional live authorization, even with all three pillars
    supplied."""
    market, supplier, consumer = _pillar("fixture_demo"), _pillar("fixture_demo"), _pillar("fixture_demo")
    result = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert result["confidence_grade"] != "A_live_validated"


def test_mixing_one_live_pillar_with_fixture_pillars_is_never_live_validated():
    """The exact SYN-GRADE-LIVE-LABEL reproduction: one live_readonly
    pillar mixed with fixture pillars must not be graded as live-validated
    -- three populated pillars alone (or a single live-looking one) is
    never sufficient."""
    market = _pillar("live_readonly")
    _, supplier, consumer = reports()
    result = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert result["confidence_grade"] != "A_live_validated"


def test_valid_live_attestation_on_every_pillar_reaches_live_validated():
    """Required scenario: a valid live attestation. A_live_validated must
    remain reachable when every supplied pillar carries an explicit,
    consistent live evidence_mode -- the fix tightens the check, it does
    not make the grade permanently unreachable."""
    market, supplier, consumer = _pillar("live_readonly"), _pillar("authenticated_live"), _pillar("public_live")
    result = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert result["confidence_grade"] == "A_live_validated"


def test_internally_inconsistent_evidence_labels_are_never_live_validated():
    """Evidence labels must remain internally consistent: a pillar report
    that labels itself fixture_demo at the top level while an embedded
    evidence/offer item claims live_readonly (or the reverse) is a
    mislabeled report, not a live attestation, and must never reach
    A_live_validated."""
    def mismatched(top_level_mode: str, item_mode: str) -> dict:
        return {
            "evidence_mode": top_level_mode,
            "candidates": [
                {
                    "candidate_id": "x",
                    "query": "x",
                    "evidence": [{"evidence_mode": item_mode}],
                    "offers": [{"evidence_mode": item_mode}],
                    "score": {"overall_marketplace_opportunity": .8, "overall_supplier_feasibility": .8, "overall_consumer_attention": .8, "saturation_score": .1, "recommendation": "hold_for_manual_review", "economics": {"gross_margin_percent": .5}, "voice_of_customer": {}},
                }
            ],
        }
    top_says_fixture_item_says_live = mismatched("fixture_demo", "live_readonly")
    result = build_product_opportunity_synthesis(top_says_fixture_item_says_live, top_says_fixture_item_says_live, top_says_fixture_item_says_live).to_dict()
    assert result["confidence_grade"] != "A_live_validated"
    top_says_live_item_says_fixture = mismatched("live_readonly", "fixture")
    result2 = build_product_opportunity_synthesis(top_says_live_item_says_fixture, top_says_live_item_says_fixture, top_says_live_item_says_fixture).to_dict()
    assert result2["confidence_grade"] != "A_live_validated"


def test_stale_evidence_mode_from_sibling_adapters_cannot_promote_grade():
    """Forward-compatibility regression: a sibling adapter (the supplier
    feasibility importer) can pass an explicit `evidence_mode: "stale"`
    value through unmodified, rather than always overwriting it with the
    import mode. `"stale"` is not in `LIVE_EVIDENCE_MODES` and not
    `"manual_import"`, so it must fall through to the same
    C_fixture_or_partial treatment as any other unlabeled evidence --
    never A_live_validated or B_multi_source_manual."""
    def stale_pillar() -> dict:
        return {
            "evidence_mode": "stale",
            "candidates": [
                {
                    "candidate_id": "x",
                    "query": "x",
                    "evidence": [{"evidence_mode": "stale"}],
                    "offers": [{"evidence_mode": "stale"}],
                    "score": {"overall_marketplace_opportunity": .8, "overall_supplier_feasibility": .8, "overall_consumer_attention": .8, "saturation_score": .1, "recommendation": "hold_for_manual_review", "economics": {"gross_margin_percent": .5}, "voice_of_customer": {}},
                }
            ],
        }
    market, supplier, consumer = stale_pillar(), stale_pillar(), stale_pillar()
    result = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert result["confidence_grade"] not in {"A_live_validated", "B_multi_source_manual"}


def test_alias_collapse_does_not_leak_a_discarded_aliass_live_label_into_the_kept_grade():
    """Interaction check between the two fixes: when a correlated alias
    that gets discarded during collapse happens to carry a live-looking
    evidence_mode while the kept candidate is fixture-labeled, the
    discarded alias's label must never leak into the kept candidate's
    grade -- collapse must happen before grading, on the kept candidate's
    own evidence only."""
    market = {
        "evidence_mode": "fixture_demo",
        "candidates": [
            {"candidate_id": "kept-fixture", "query": "desk clamp lamp", "evidence": [{"price": 29.99, "evidence_mode": "fixture", "source_family": "amazon_serp"}], "score": {"overall_marketplace_opportunity": .7, "saturation_score": .3}},
            {"candidate_id": "alias-claims-live", "query": "desk clamp lamp", "evidence": [{"price": 29.99, "evidence_mode": "live_readonly", "source_family": "amazon_serp"}], "score": {"overall_marketplace_opportunity": .7, "saturation_score": .3}},
        ],
    }
    supplier = {"evidence_mode": "fixture_demo", "candidates": [{"candidate_id": "kept-fixture", "query": "desk clamp lamp", "offers": [{"evidence_mode": "fixture"}], "score": {"overall_supplier_feasibility": .71, "recommendation": "validate_live_supplier_first", "economics": {"gross_margin_percent": .57}}}]}
    consumer = {"evidence_mode": "fixture_demo", "candidates": [{"candidate_id": "kept-fixture", "query": "desk clamp lamp", "evidence": [{"evidence_mode": "fixture"}], "score": {"overall_consumer_attention": .64, "recommendation": "test_creative_offline", "voice_of_customer": {}}}]}
    result = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert result["candidate_count"] == 1
    assert result["candidates"][0]["candidate_id"] == "kept-fixture"
    assert result["confidence_grade"] != "A_live_validated"


def test_stale_evidence_is_not_live_validated():
    market, supplier, consumer = reports()
    market["generated_at"] = "2019-01-01T00:00:00Z"
    market["candidates"][0]["evidence_class"] = "stale"
    result = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert result["confidence_grade"] != "A_live_validated"
    assert result["evidence_mode"] == "fixture_demo"


# --- SYN-ALIAS-NO-COLLAPSE regressions ---


def _aligned_pillar_candidate(candidate_id: str, source_family: str | None) -> dict:
    evidence = {"price": 29.99, "evidence_mode": "fixture"}
    if source_family:
        evidence["source_family"] = source_family
    return {"candidate_id": candidate_id, "query": "desk clamp lamp", "evidence": [evidence], "score": {"overall_marketplace_opportunity": 0.7, "saturation_score": 0.3}}


def _aligned_supplier_consumer() -> tuple[dict, dict]:
    supplier = {"evidence_mode": "fixture_demo", "candidates": [{"candidate_id": "desk-clamp-lamp", "query": "desk clamp lamp", "offers": [{"evidence_mode": "fixture"}], "score": {"overall_supplier_feasibility": 0.71, "recommendation": "validate_live_supplier_first", "economics": {"gross_margin_percent": 0.57}}}]}
    consumer = {"evidence_mode": "fixture_demo", "candidates": [{"candidate_id": "desk-clamp-lamp", "query": "desk clamp lamp", "evidence": [{"evidence_mode": "fixture"}], "score": {"overall_consumer_attention": 0.64, "recommendation": "test_creative_offline", "voice_of_customer": {}}}]}
    return supplier, consumer


def test_correlated_alias_same_query_and_source_family_collapses_to_one_candidate():
    """Required scenario: correlated aliases. Two marketplace candidates
    sharing query and source_family but different candidate_id must not
    be scored and ranked twice."""
    market = {"evidence_mode": "fixture_demo", "candidates": [_aligned_pillar_candidate("desk-clamp-lamp", "amazon_serp"), _aligned_pillar_candidate("desk-clamp-lamp-amazon-mirror", "amazon_serp")]}
    supplier, consumer = _aligned_supplier_consumer()
    result = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert result["candidate_count"] == 1
    assert [item["candidate_id"] for item in result["candidates"]] == ["desk-clamp-lamp"]
    assert result["alias_notes"]
    assert "desk-clamp-lamp-amazon-mirror" in result["alias_notes"][0]


def test_correlated_alias_with_conflicting_scores_is_flagged_not_silently_picked():
    market = {
        "evidence_mode": "fixture_demo",
        "candidates": [
            _aligned_pillar_candidate("desk-clamp-lamp", "amazon_serp"),
            {**_aligned_pillar_candidate("desk-clamp-lamp-amazon-mirror", "amazon_serp"), "score": {"overall_marketplace_opportunity": 0.95, "saturation_score": 0.05}},
        ],
    }
    supplier, consumer = _aligned_supplier_consumer()
    result = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert result["candidate_count"] == 1
    assert any("conflicting scores" in note for note in result["alias_notes"])


def test_distinct_legitimate_products_sharing_only_a_query_are_not_collapsed():
    """Required scenario: distinct legitimate products. A shared, generic
    query with no matching source_family provenance must never collapse
    two genuinely different products."""
    market = {
        "evidence_mode": "fixture_demo",
        "candidates": [
            {"candidate_id": "product-a", "query": "desk lamp", "evidence": [{"price": 19.99, "evidence_mode": "fixture"}], "score": {"overall_marketplace_opportunity": 0.5, "saturation_score": 0.2}},
            {"candidate_id": "product-b", "query": "desk lamp", "evidence": [{"price": 39.99, "evidence_mode": "fixture"}], "score": {"overall_marketplace_opportunity": 0.6, "saturation_score": 0.3}},
        ],
    }
    result = build_product_opportunity_synthesis(market, None, None).to_dict()
    assert result["candidate_count"] == 2
    assert result["alias_notes"] == []


def test_distinct_legitimate_products_with_different_source_families_are_not_collapsed():
    market = {
        "evidence_mode": "fixture_demo",
        "candidates": [
            _aligned_pillar_candidate("product-c", "amazon_serp"),
            _aligned_pillar_candidate("product-d", "ebay_serp"),
        ],
    }
    result = build_product_opportunity_synthesis(market, None, None).to_dict()
    assert result["candidate_count"] == 2


def test_alias_collapse_does_not_create_a_second_identity_or_scoring_authority():
    """Do not create a second identity registry, second scorer, or new
    independent source-family authority: the fix must stay inside this
    module's existing per-pillar candidate map."""
    source = (Path(__file__).resolve().parents[1] / "evaluation" / "commerce" / "opportunity_synthesis.py").read_text(encoding="utf-8")
    assert "class " not in source.split("def _identity_key")[1].split("def _candidate_map")[0]
    for forbidden in ("sqlite3", "requests", "httpx", "socket"):
        assert forbidden not in source


# --- deterministic ordering / fingerprint ---


def test_synthesis_report_fingerprint_is_stable_across_repeated_runs():
    """Required scenario: deterministic ordering and fingerprint."""
    market = {"evidence_mode": "fixture_demo", "candidates": [_aligned_pillar_candidate("desk-clamp-lamp", "amazon_serp"), _aligned_pillar_candidate("desk-clamp-lamp-amazon-mirror", "amazon_serp")]}
    supplier, consumer = _aligned_supplier_consumer()
    first = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    second = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    third = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    blob_first, blob_second, blob_third = (json.dumps(item, sort_keys=True, default=str) for item in (first, second, third))
    assert blob_first == blob_second == blob_third
    assert first["generated_at"] == "deterministic"


def test_no_credential_provider_or_network_behavior_after_fixes():
    result = build_product_opportunity_synthesis(*reports()).to_dict()
    assert result["read_only"] is True
    assert result["network_calls"] is False
    assert result["mutated"] is False
    blob = json.dumps(result).lower()
    assert "sk-" not in blob
    assert "bearer " not in blob

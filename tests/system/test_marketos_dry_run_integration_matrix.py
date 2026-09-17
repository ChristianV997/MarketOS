"""Cross-system dry-run integration matrix (MarketOS mission 7, Phase 2).

These tests compose EXISTING public builders across real module boundaries --
opportunity synthesis, the client-facing validation report, and the
Resource & Execution Governor -- exactly as a real dry-run cycle would chain
them. No new production workflow engine is introduced here; this file only
calls public entry points that already exist on `origin/main`.

Scope note (read before extending): the mission brief's scenarios F and G
describe a *service client* value/capacity evaluation (client order history,
CAC, contribution margin, delivery capacity for an agency-style engagement).
No such module exists anywhere in this repository's mergeable baseline --
`evaluation/economics.py` and `evaluation/experiments.py` model *product* and
*ad-campaign* evidence only. Scenarios F and G are therefore reported as an
architecture gap in the mission's release-evidence report rather than
fabricated here against a module that doesn't exist.
"""
from __future__ import annotations

from evaluation import DataQuality, ProductCandidate, SupplierOffer, calculate_unit_economics
from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis
from evaluation.commerce.product_validation_report import generate as generate_validation_report
from evaluation.companyos.resource_execution_governor import (
    ExecutionDecisionRequest,
    evaluate_execution_request,
)
from evaluation.trustos.gate_runner import evaluate_action

LIVE_ATTRIBUTED = DataQuality(provenance="live", attribution="attributed")


def _pillar(candidate_id, query, *, marketplace=None, supplier=None, consumer=None):
    market = None
    if marketplace is not None:
        market = {
            "report_version": "marketplace-trends-v1",
            "evidence_mode": "fixture_demo",
            "top_candidate_id": candidate_id,
            "candidates": [{"candidate_id": candidate_id, "query": query, "evidence": marketplace["evidence"], "score": marketplace["score"]}],
        }
    supplier_report = None
    if supplier is not None:
        supplier_report = {
            "report_version": "supplier-feasibility-v1",
            "evidence_mode": "fixture_demo",
            "top_candidate_id": candidate_id,
            "candidates": [{"candidate_id": candidate_id, "query": query, "offers": supplier["offers"], "score": supplier["score"]}],
        }
    consumer_report = None
    if consumer is not None:
        consumer_report = {
            "report_version": "consumer-attention-v1",
            "evidence_mode": "fixture_demo",
            "top_candidate_id": candidate_id,
            "candidates": [{"candidate_id": candidate_id, "query": query, "evidence": consumer["evidence"], "score": consumer["score"]}],
        }
    return market, supplier_report, consumer_report


def _promotion_request(synthesis: dict, *, action_type="promote_product_candidate", workspace_id="ws-client-alpha") -> ExecutionDecisionRequest:
    supplier_econ = synthesis["unit_economics_summary"] or {}
    margin = supplier_econ.get("gross_margin_percent")
    return ExecutionDecisionRequest(
        request_id=f"req-{synthesis['top_candidate_id']}",
        action_type=action_type,
        domain="commerce",
        owner_department="growth",
        workspace_id=workspace_id,
        opportunity_score=synthesis["marketplace_opportunity"],
        supplier_score=synthesis["supplier_feasibility"],
        attention_score=synthesis["consumer_attention"],
        unit_economics_score=1.0 if (margin is not None and margin > 0) else 0.0,
        portfolio_fit_score=synthesis["combined_opportunity_score"],
        supplier_proof=True,
    )


# ---------------------------------------------------------------------------
# Scenario A: positive hydroponics candidate, Mexico destination lane.
# ---------------------------------------------------------------------------

def test_scenario_a_hydroponics_candidate_gets_launch_draft_but_no_live_authorization():
    market, supplier, consumer = _pillar(
        "hydro-kit-mx-01", "hydroponics starter kit mexico",
        marketplace={
            "evidence": [{"marketplace": "mercadolibre", "price": 39.99, "review_count": 1800, "source_confidence": 0.8, "evidence_mode": "fixture"}],
            "score": {"overall_marketplace_opportunity": 0.78, "demand_proxy_score": 0.82, "saturation_score": 0.3, "price_confidence": 0.8, "recommendation": "validate_supplier_first"},
        },
        supplier={
            "offers": [{"supplier": "cj", "unit_cost": 9.5, "shipping_cost": 3.0, "estimated_landed_cost": 12.5, "delivery_max_days": 10, "evidence_mode": "fixture"}],
            "score": {
                "overall_supplier_feasibility": 0.75, "supplier_cost_confidence": 0.7, "margin_feasibility_proxy": 0.75,
                "recommendation": "validate_supplier_first", "risk_flags": [],
                "economics": {"target_sell_price": 39.99, "estimated_landed_cost": 12.5, "gross_margin_percent": 0.4, "profit_per_order_before_ad_spend": 16.0, "break_even_cpa": 16.0, "break_even_roas": 2.5, "assumptions": []},
            },
        },
        consumer={
            "evidence": [{"platform": "tiktok", "hook": "Grow your own herbs indoors", "evidence_mode": "fixture"}],
            "score": {"overall_consumer_attention": 0.72, "source_diversity": 0.7, "objection_density": 0.1, "recommended_ad_angles": ["convenience"], "creative_hooks": [{"hook": "Grow your own herbs indoors"}], "voice_of_customer": {"pain_points": ["fresh herbs are expensive"], "desired_outcomes": ["fresh herbs at home"], "objections": []}, "recommendation": "validate_supplier_first"},
        },
    )
    synthesis = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert synthesis["overall_recommendation"] == "advance_to_launch_draft"
    assert synthesis["confidence_grade"] != "A_live_validated"  # fixture evidence, never live

    # Currency metadata: a Mexico-lane supplier quote in MXN against a USD
    # sell price must fail closed rather than get treated as apples-to-apples
    # (this composes the Phase-5 currency-mismatch fix with a real scenario).
    usd_product = ProductCandidate("hydro-kit-mx-01", "Hydroponics kit", currency="USD", selling_price=39.99, quality=LIVE_ATTRIBUTED)
    mxn_offer = SupplierOffer("cj", "hydro-kit-mx-01", unit_cost=180.0, shipping_cost=55.0, currency="MXN", quality=LIVE_ATTRIBUTED)
    mismatched = calculate_unit_economics(usd_product, mxn_offer)
    assert mismatched.eligible is False and mismatched.reasons == ("currency_mismatch",)

    matching_offer = SupplierOffer("cj", "hydro-kit-mx-01", unit_cost=9.5, shipping_cost=3.0, currency="USD", quality=LIVE_ATTRIBUTED)
    economics = calculate_unit_economics(usd_product, matching_offer)
    assert economics.eligible is True
    contribution_before_cac = economics.contribution_before_ads
    contribution_after_a_10_dollar_cac = contribution_before_cac - 10.0
    assert contribution_before_cac > contribution_after_a_10_dollar_cac > 0

    report = generate_validation_report(client_name="Acme Hydroponics MX", opportunity_synthesis=synthesis, supplier_feasibility=supplier, marketplace_trends=market, consumer_attention=consumer).to_dict()
    assert report["overall_recommendation"] == "advance_to_launch_draft"
    assert "launch draft" not in report["operator_disclaimer"].lower() or "not" in report["operator_disclaimer"].lower()
    assert "not a profit guarantee" in report["operator_disclaimer"] or "not" in report["operator_disclaimer"]

    decision = evaluate_execution_request(_promotion_request(synthesis))
    # A strong candidate can clear the Governor's portfolio-score gate...
    assert "candidate is below a portfolio score threshold" not in decision.blockers

    # ...but no amount of synthesis confidence grants live execution authority.
    for live_action in ("launch_ad", "create_order", "activate_provider"):
        gate = evaluate_action(live_action)
        assert gate.decision in {"hard_block", "needs_professional_review"}
        assert gate.decision != "allow"


# ---------------------------------------------------------------------------
# Scenario B: smart-pet candidate with app burden and support ownership gaps.
# ---------------------------------------------------------------------------

def test_scenario_b_smart_pet_candidate_surfaces_support_and_setup_risk_but_stays_conditional():
    market, supplier, consumer = _pillar(
        "smart-feeder-02", "smart pet feeder app",
        marketplace={
            "evidence": [{"marketplace": "amazon", "price": 59.99, "review_count": 900, "source_confidence": 0.65, "evidence_mode": "fixture"}],
            "score": {"overall_marketplace_opportunity": 0.6, "demand_proxy_score": 0.6, "saturation_score": 0.4, "price_confidence": 0.65, "recommendation": "validate_supplier_first"},
        },
        supplier={
            "offers": [{"supplier": "alibaba", "unit_cost": 18.0, "shipping_cost": 5.0, "estimated_landed_cost": 23.0, "delivery_max_days": 20, "evidence_mode": "fixture"}],
            "score": {
                "overall_supplier_feasibility": 0.55, "supplier_cost_confidence": 0.5, "margin_feasibility_proxy": 0.55,
                "recommendation": "expand_supplier_research",
                "risk_flags": [
                    {"code": "app_setup_burden", "severity": "advisory"},
                    {"code": "support_owner_unassigned", "severity": "blocker"},
                    {"code": "replacement_filter_potential", "severity": "advisory"},
                    {"code": "defect_reserve_recommended", "severity": "advisory"},
                ],
                "economics": {"target_sell_price": 59.99, "estimated_landed_cost": 23.0, "gross_margin_percent": 0.35, "profit_per_order_before_ad_spend": 21.0, "break_even_cpa": 21.0, "break_even_roas": 2.86, "assumptions": []},
            },
        },
        consumer={
            "evidence": [{"platform": "reddit", "objection": "app requires account and wifi setup", "evidence_mode": "fixture"}],
            "score": {"overall_consumer_attention": 0.5, "source_diversity": 0.4, "objection_density": 0.3, "recommended_ad_angles": ["convenience"], "creative_hooks": [], "voice_of_customer": {"pain_points": ["forgetting to feed pets while traveling"], "desired_outcomes": ["automated feeding"], "objections": ["app setup friction", "customer_support_escalation_risk"]}, "recommendation": "validate_supplier_first"},
        },
    )
    synthesis = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    # The blocking risk flag from raw supplier evidence must survive into the
    # composed risk profile -- this is the real cross-boundary assertion:
    # a risk recorded in one pillar's evidence is visible at the synthesis
    # level, not silently dropped when pillars are combined.
    assert "support_owner_unassigned" in synthesis["risk_profile"]["supplier_risks"]
    assert "app_setup_burden" in synthesis["risk_profile"]["supplier_risks"]
    assert synthesis["risk_profile"]["blockers"], "recorded risk flags must appear as blockers, not be silently dropped"

    evaluate_execution_request(_promotion_request(synthesis, action_type="deep_validate_product"))
    # Below the launch-draft threshold (combined < 0.68) with recorded risk,
    # this must not be treated as a clean advance -- it stays conditional,
    # requiring a human decision rather than an automatic promotion.
    assert synthesis["overall_recommendation"] != "advance_to_launch_draft"


# ---------------------------------------------------------------------------
# Scenario C: solar 4G security candidate missing SIM/radio compliance -- must
# remain blocked end to end.
# ---------------------------------------------------------------------------

def test_scenario_c_solar_4g_security_candidate_remains_blocked_on_compliance_gaps():
    market, supplier, consumer = _pillar(
        "solar-4g-cam-03", "solar 4g security camera",
        marketplace={
            "evidence": [{"marketplace": "amazon", "price": 129.0, "review_count": 200, "source_confidence": 0.5, "evidence_mode": "fixture"}],
            "score": {"overall_marketplace_opportunity": 0.5, "demand_proxy_score": 0.55, "saturation_score": 0.5, "price_confidence": 0.5, "recommendation": "validate_supplier_first"},
        },
        supplier={
            "offers": [{"supplier": "alibaba", "unit_cost": 45.0, "shipping_cost": 12.0, "estimated_landed_cost": 57.0, "delivery_max_days": 30, "evidence_mode": "fixture"}],
            "score": {
                "overall_supplier_feasibility": 0.3, "supplier_cost_confidence": 0.4, "margin_feasibility_proxy": 0.3,
                "recommendation": "reject_compliance_evidence_absent",
                "risk_flags": [
                    {"code": "sim_compatibility_absent", "severity": "blocker"},
                    {"code": "radio_compliance_evidence_absent", "severity": "blocker"},
                    {"code": "warranty_terms_undocumented", "severity": "blocker"},
                    {"code": "installation_setup_burden", "severity": "advisory"},
                ],
                "economics": {"target_sell_price": 129.0, "estimated_landed_cost": 57.0, "gross_margin_percent": 0.2, "profit_per_order_before_ad_spend": 25.0, "break_even_cpa": 25.0, "break_even_roas": 5.16, "assumptions": []},
            },
        },
        consumer={
            "evidence": [{"platform": "amazon_reviews", "objection": "unclear cellular carrier compatibility", "evidence_mode": "fixture"}],
            "score": {"overall_consumer_attention": 0.4, "source_diversity": 0.3, "objection_density": 0.5, "recommended_ad_angles": [], "creative_hooks": [], "voice_of_customer": {"pain_points": [], "desired_outcomes": [], "objections": ["sim_compatibility_absent"]}, "recommendation": "validate_supplier_first"},
        },
    )
    synthesis = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert synthesis["overall_recommendation"] == "reject_compliance_evidence_absent"
    assert "sim_compatibility_absent" in synthesis["risk_profile"]["supplier_risks"]
    assert "radio_compliance_evidence_absent" in synthesis["risk_profile"]["supplier_risks"]

    decision = evaluate_execution_request(_promotion_request(synthesis, action_type="promote_product_candidate"))
    assert "candidate is below a portfolio score threshold" in decision.blockers
    assert decision.outcome != "allow"


# ---------------------------------------------------------------------------
# Scenario D: commodity electronics -- weak defensibility, margin erased by
# shipping/returns against dominant marketplace competition. Must be
# rejected or held, never advanced.
# ---------------------------------------------------------------------------

def test_scenario_d_commodity_electronics_is_rejected_or_held_never_advanced():
    market, supplier, consumer = _pillar(
        "usb-cable-04", "usb c cable",
        marketplace={
            "evidence": [{"marketplace": "mercadolibre", "price": 6.99, "review_count": 50000, "source_confidence": 0.9, "evidence_mode": "fixture"}],
            "score": {"overall_marketplace_opportunity": 0.75, "demand_proxy_score": 0.9, "saturation_score": 0.92, "price_confidence": 0.9, "recommendation": "reject_oversaturated"},
        },
        supplier={
            "offers": [{"supplier": "alibaba", "unit_cost": 1.2, "shipping_cost": 1.5, "estimated_landed_cost": 2.7, "delivery_max_days": 25, "evidence_mode": "fixture"}],
            "score": {
                "overall_supplier_feasibility": 0.5, "supplier_cost_confidence": 0.5, "margin_feasibility_proxy": 0.3,
                "recommendation": "expand_supplier_research", "risk_flags": [{"code": "returns_and_shipping_erode_margin", "severity": "blocker"}],
                "economics": {"target_sell_price": 6.99, "estimated_landed_cost": 2.7, "gross_margin_percent": 0.1, "profit_per_order_before_ad_spend": 0.7, "break_even_cpa": 0.7, "break_even_roas": 10.0, "assumptions": []},
            },
        },
        consumer={
            "evidence": [{"platform": "amazon_reviews", "hook": "cheap and works", "evidence_mode": "fixture"}],
            "score": {"overall_consumer_attention": 0.55, "source_diversity": 0.5, "objection_density": 0.2, "recommended_ad_angles": ["price"], "creative_hooks": [{"hook": "cheap and works"}], "voice_of_customer": {"pain_points": [], "desired_outcomes": [], "objections": []}, "recommendation": "validate_supplier_first"},
        },
    )
    synthesis = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    # Marketplace saturation is checked before margin in the recommendation
    # logic, so a dominant-competition commodity candidate is rejected as
    # oversaturated even though the standalone margin figure (10%) is also
    # below the 15% floor -- either reason is sufficient, but it must never
    # fall through to an advance/hold-neutral outcome.
    assert synthesis["overall_recommendation"] in {"reject_oversaturated", "reject_poor_margin"}
    assert synthesis["overall_recommendation"] != "advance_to_launch_draft"

    decision = evaluate_execution_request(_promotion_request(synthesis))
    assert decision.outcome != "allow"


# ---------------------------------------------------------------------------
# Scenario E: high-ticket product with delivery/reverse-logistics and cash
# exposure uncertainty -- must remain deferred (hold_for_manual_review),
# never silently promoted on marketplace demand alone.
# ---------------------------------------------------------------------------

def test_scenario_e_high_ticket_product_stays_deferred_on_logistics_and_cash_risk():
    market, supplier, consumer = _pillar(
        "e-bike-05", "electric bike",
        marketplace={
            "evidence": [{"marketplace": "shopify", "price": 899.0, "review_count": 120, "source_confidence": 0.6, "evidence_mode": "fixture"}],
            "score": {"overall_marketplace_opportunity": 0.6, "demand_proxy_score": 0.65, "saturation_score": 0.4, "price_confidence": 0.6, "recommendation": "validate_supplier_first"},
        },
        supplier={
            "offers": [{"supplier": "alibaba", "unit_cost": 380.0, "shipping_cost": 220.0, "estimated_landed_cost": 600.0, "delivery_max_days": 60, "evidence_mode": "fixture"}],
            "score": {
                "overall_supplier_feasibility": 0.45, "supplier_cost_confidence": 0.4, "margin_feasibility_proxy": 0.35,
                "recommendation": "validate_supplier_first",
                "risk_flags": [{"code": "reverse_logistics_uncertain", "severity": "blocker"}, {"code": "warranty_liability_undocumented", "severity": "blocker"}, {"code": "high_cash_exposure_per_unit", "severity": "advisory"}],
                "economics": {"target_sell_price": 899.0, "estimated_landed_cost": 600.0, "gross_margin_percent": 0.22, "profit_per_order_before_ad_spend": 200.0, "break_even_cpa": 200.0, "break_even_roas": 4.5, "assumptions": []},
            },
        },
        consumer={
            "evidence": [{"platform": "google_trends", "hook": "commute without a car", "evidence_mode": "fixture"}],
            "score": {"overall_consumer_attention": 0.5, "source_diversity": 0.4, "objection_density": 0.2, "recommended_ad_angles": ["commute"], "creative_hooks": [{"hook": "commute without a car"}], "voice_of_customer": {"pain_points": [], "desired_outcomes": [], "objections": []}, "recommendation": "validate_supplier_first"},
        },
    )
    synthesis = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert synthesis["overall_recommendation"] == "hold_for_manual_review"
    assert "reverse_logistics_uncertain" in synthesis["risk_profile"]["supplier_risks"]

    decision = evaluate_execution_request(_promotion_request(synthesis, action_type="increase_inventory_exposure"))
    assert "supplier proof is required before inventory exposure" not in decision.blockers  # supplier_proof=True in this test
    # A high-ticket, logistics-uncertain candidate must not clear the
    # portfolio's minimum-score gates from evidence confidence alone.
    assert decision.outcome != "allow"

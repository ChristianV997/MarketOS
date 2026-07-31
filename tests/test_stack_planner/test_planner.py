from __future__ import annotations

from backend.stack_planner.planner import recommend_stack
from backend.stack_planner.schemas import BusinessStackRequest


def test_defaults_to_hostinger_woocommerce():
    request = BusinessStackRequest(business_model="own_ecommerce", supplier_cost=10.0, retail_price=35.0)
    rec = recommend_stack(request)
    assert rec.status == "recommended"
    assert rec.commerce_provider_recommendation.provider_id == "woocommerce"


def test_shopify_only_when_justified():
    low_cost_request = BusinessStackRequest(
        business_model="client_ecommerce_shopify_premium", margin_sensitivity="low_cost_validation",
        supplier_cost=10.0, retail_price=35.0,
    )
    rec = recommend_stack(low_cost_request)
    assert rec.commerce_provider_recommendation.provider_id == "woocommerce"

    premium_request = BusinessStackRequest(
        business_model="client_ecommerce_shopify_premium", margin_sensitivity="premium_brand",
        supplier_cost=10.0, retail_price=35.0,
    )
    rec = recommend_stack(premium_request)
    assert rec.commerce_provider_recommendation.provider_id == "shopify"


def test_gohighlevel_blocked_below_threshold():
    request = BusinessStackRequest(business_model="own_ecommerce", expected_monthly_revenue_usd=500.0)
    rec = recommend_stack(request)
    ghl = next(r for r in rec.automation_recommendations if r.provider_id == "gohighlevel")
    assert ghl.blocked is True
    assert ghl.blocked_reason


def test_gohighlevel_allowed_above_threshold():
    request = BusinessStackRequest(business_model="own_ecommerce", expected_monthly_revenue_usd=20000.0)
    rec = recommend_stack(request)
    ghl = next(r for r in rec.automation_recommendations if r.provider_id == "gohighlevel")
    assert ghl.blocked is False


def test_n8n_never_recommended_when_white_labeled():
    request = BusinessStackRequest(business_model="own_ecommerce", is_white_labeled_client_facing=True)
    rec = recommend_stack(request)
    n8n = next(r for r in rec.automation_recommendations if r.provider_id == "n8n")
    assert n8n.blocked is True


def test_postiz_blocked_without_legal_approval():
    request = BusinessStackRequest(business_model="own_ecommerce", postiz_legal_approval=False)
    rec = recommend_stack(request)
    postiz = next(r for r in rec.automation_recommendations if r.provider_id == "postiz")
    assert postiz.blocked is True

    approved_request = BusinessStackRequest(business_model="own_ecommerce", postiz_legal_approval=True)
    rec = recommend_stack(approved_request)
    postiz = next(r for r in rec.automation_recommendations if r.provider_id == "postiz")
    assert postiz.blocked is False


def test_deferred_strategies_return_explicit_stub_never_raise():
    for strategy in ("high_ticket_lead_gen_low_cost", "high_ticket_lead_gen_gohighlevel_fast", "agency_white_label_fast"):
        request = BusinessStackRequest(business_model=strategy)
        rec = recommend_stack(request)
        assert rec.status == "not_yet_supported"
        assert rec.strategy_id == strategy
        assert rec.warnings


def test_mx_geo_defaults_to_mercado_pago():
    request = BusinessStackRequest(business_model="own_ecommerce", target_geo="MX")
    rec = recommend_stack(request)
    assert rec.payment_provider_recommendation.provider_id == "mercado_pago_mx"


def test_recommendation_includes_cost_estimate():
    request = BusinessStackRequest(business_model="own_ecommerce", supplier_cost=10.0, retail_price=35.0, expected_monthly_orders=100)
    rec = recommend_stack(request)
    assert rec.monthly_cost_estimate is not None
    assert rec.monthly_cost_estimate.fixed_monthly_cost > 0
    assert rec.break_even_client_price > 0

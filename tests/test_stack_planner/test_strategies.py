from __future__ import annotations

from dataclasses import dataclass

from backend.stack_planner.strategies import (
    ALL_STRATEGIES,
    DEFERRED_STRATEGIES,
    ECOMMERCE_STRATEGIES,
    LEAD_GEN_STRATEGIES,
    is_deferred_strategy,
    is_lead_gen_strategy,
    select_strategy,
)


@dataclass
class _Req:
    business_model: str = "own_ecommerce"
    margin_sensitivity: str = "standard"
    expected_monthly_revenue_usd: float = 5000.0


def test_seven_presets_accounted_for():
    assert len(ALL_STRATEGIES) == 7
    assert len(ECOMMERCE_STRATEGIES) == 4
    assert len(LEAD_GEN_STRATEGIES) == 3
    assert len(DEFERRED_STRATEGIES) == 0


def test_select_strategy_defaults_to_low_cost():
    assert select_strategy(_Req(business_model="something_unrecognized")) == "own_ecommerce_low_cost"


def test_select_strategy_own_ecommerce():
    assert select_strategy(_Req(business_model="own_ecommerce")) == "own_ecommerce_low_cost"


def test_select_strategy_client_ecommerce_premium_brand():
    assert select_strategy(_Req(business_model="client_ecommerce", margin_sensitivity="premium_brand")) == "client_ecommerce_shopify_premium"


def test_select_strategy_client_ecommerce_default():
    assert select_strategy(_Req(business_model="client_ecommerce")) == "client_ecommerce_low_cost"


def test_select_strategy_explicit_strategy_id_passthrough():
    assert select_strategy(_Req(business_model="marketos_owned_stack")) == "marketos_owned_stack"


def test_select_strategy_lead_gen_picks_gohighlevel_when_revenue_justifies_it():
    assert select_strategy(_Req(business_model="lead_gen", expected_monthly_revenue_usd=20000.0)) == "high_ticket_lead_gen_gohighlevel_fast"


def test_select_strategy_lead_gen_picks_low_cost_below_threshold():
    assert select_strategy(_Req(business_model="lead_gen", expected_monthly_revenue_usd=500.0)) == "high_ticket_lead_gen_low_cost"


def test_no_strategies_are_deferred():
    for strategy in ALL_STRATEGIES:
        assert not is_deferred_strategy(strategy)


def test_lead_gen_strategies_flagged():
    for strategy in LEAD_GEN_STRATEGIES:
        assert is_lead_gen_strategy(strategy)
    for strategy in ECOMMERCE_STRATEGIES:
        assert not is_lead_gen_strategy(strategy)

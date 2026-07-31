from __future__ import annotations

from dataclasses import dataclass

from backend.stack_planner.strategies import (
    ALL_STRATEGIES,
    DEFERRED_STRATEGIES,
    REACHABLE_STRATEGIES,
    is_deferred_strategy,
    select_strategy,
)


@dataclass
class _Req:
    business_model: str = "own_ecommerce"
    margin_sensitivity: str = "standard"


def test_seven_presets_accounted_for():
    assert len(ALL_STRATEGIES) == 7
    assert len(REACHABLE_STRATEGIES) == 4
    assert len(DEFERRED_STRATEGIES) == 3


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


def test_deferred_strategies_flagged():
    for strategy in DEFERRED_STRATEGIES:
        assert is_deferred_strategy(strategy)
    for strategy in REACHABLE_STRATEGIES:
        assert not is_deferred_strategy(strategy)

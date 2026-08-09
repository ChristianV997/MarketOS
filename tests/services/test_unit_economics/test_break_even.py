"""Tests for services.unit_economics.break_even — exact formula + verdict-
threshold boundary correctness."""
from backend.validation.margin_calculator import (
    _BREAKEVEN_PCT,
    _PROFITABLE_PCT,
    calculate_margin,
)
from services.unit_economics.break_even import (
    break_even_cac,
    required_roas,
    verdict_from_margin,
)


def test_break_even_cac_matches_hand_computed_margin_at_zero_cac():
    supplier_cost, retail_price, shipping = 10.0, 40.0, 2.0
    expected = calculate_margin(
        supplier_cost=supplier_cost, retail_price=retail_price, shipping_cost=shipping,
        monthly_ad_spend=0.0, expected_monthly_revenue=5000.0, category="general",
    )["net_margin"]

    assert break_even_cac(supplier_cost, retail_price, shipping) == round(expected, 2)


def test_required_roas_equals_price_over_break_even_cac():
    cac = break_even_cac(10.0, 40.0, 2.0)
    assert required_roas(10.0, 40.0, 2.0) == round(40.0 / cac, 4)


def test_required_roas_is_inf_when_break_even_cac_is_zero():
    # A retail price barely above landed cost, with a huge shipping cost,
    # drives net_margin (at cac=0) negative -> break_even_cac clamps to 0.
    assert break_even_cac(90.0, 100.0, shipping_cost=50.0) == 0.0
    assert required_roas(90.0, 100.0, shipping_cost=50.0) == float("inf")


def test_break_even_cac_never_negative():
    assert break_even_cac(1000.0, 10.0) == 0.0


def test_verdict_from_margin_profitable_boundary():
    # net_margin_pct strictly greater than _PROFITABLE_PCT -> "profitable"
    margin = {"margin_status": "profitable"}
    assert verdict_from_margin(margin) == "profitable"


def test_verdict_from_margin_matches_calculate_margin_thresholds():
    # High-margin, low-cost product should clear _PROFITABLE_PCT and read "profitable".
    profitable = calculate_margin(supplier_cost=5.0, retail_price=100.0, shipping_cost=1.0)
    assert profitable["net_margin_pct"] > _PROFITABLE_PCT
    assert verdict_from_margin(profitable) == "profitable"

    # Thin-margin product priced just above cost should read "loss".
    loss = calculate_margin(supplier_cost=38.0, retail_price=40.0, shipping_cost=2.0)
    assert loss["net_margin_pct"] <= _BREAKEVEN_PCT
    assert verdict_from_margin(loss) == "loss"


def test_verdict_from_margin_unknown_status_defaults_safely():
    assert verdict_from_margin({}) == "unknown"

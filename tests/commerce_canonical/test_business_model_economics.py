from decimal import Decimal

import pytest

from backend.economics.kernel import CurrencyMismatchError, EconomicsError, Money

from evaluation.commerce.business_model_economics import (
    assert_no_shared_retail_formula,
    calculate_offer_economics,
)
from evaluation.commerce.canonical import BusinessModel


def test_retail_margin_uses_full_landed_cost_waterfall():
    price = Money("50.00", "USD")
    cost = Money("20.00", "USD")
    result = calculate_offer_economics(BusinessModel.RETAIL_MARGIN, price=price, product_cost=cost)
    assert result.product_cost.amount == Decimal("20.00")
    assert result.net_sales.amount == Decimal("50.00")


def test_retail_margin_requires_product_cost():
    with pytest.raises(EconomicsError):
        calculate_offer_economics(BusinessModel.RETAIL_MARGIN, price=Money("50.00", "USD"))


def test_commission_model_never_carries_landed_cost():
    price = Money("100.00", "USD")
    result = calculate_offer_economics(BusinessModel.COMMISSION, price=price, commission_rate=Decimal("0.20"))
    # Revenue basis is the commission slice, not the full sale price, and
    # product_cost is exactly zero -- commission offers never own inventory.
    assert result.net_sales.amount == Decimal("20.00")
    assert result.product_cost.amount == Decimal("0")


def test_affiliate_model_never_carries_landed_cost():
    price = Money("200.00", "USD")
    result = calculate_offer_economics(BusinessModel.AFFILIATE, price=price, affiliate_rate=Decimal("0.10"))
    assert result.net_sales.amount == Decimal("20.00")
    assert result.product_cost.amount == Decimal("0")


def test_lead_generation_model_revenue_is_the_payout_not_a_sale_price():
    payout = Money("35.00", "USD")
    result = calculate_offer_economics(BusinessModel.LEAD_GENERATION, price=payout, lead_payout=payout)
    assert result.net_sales.amount == Decimal("35.00")
    assert result.product_cost.amount == Decimal("0")


def test_commission_without_rate_is_rejected():
    with pytest.raises(EconomicsError):
        calculate_offer_economics(BusinessModel.COMMISSION, price=Money("100.00", "USD"))


def test_lead_generation_without_payout_is_rejected():
    with pytest.raises(EconomicsError):
        calculate_offer_economics(BusinessModel.LEAD_GENERATION, price=Money("100.00", "USD"))


def test_guard_rejects_nonzero_product_cost_on_non_retail_models():
    with pytest.raises(EconomicsError):
        assert_no_shared_retail_formula(BusinessModel.COMMISSION, Money("5.00", "USD"))
    with pytest.raises(EconomicsError):
        assert_no_shared_retail_formula(BusinessModel.LEAD_GENERATION, Money("1.00", "USD"))
    # Zero cost, or no cost at all, is fine for a non-retail model.
    assert_no_shared_retail_formula(BusinessModel.COMMISSION, Money("0", "USD"))
    assert_no_shared_retail_formula(BusinessModel.COMMISSION, None)
    # Any nonzero product cost is fine for the retail model.
    assert_no_shared_retail_formula(BusinessModel.RETAIL_MARGIN, Money("20.00", "USD"))


def test_currency_mismatch_between_price_and_cost_is_rejected():
    price = Money("50.00", "USD")
    cost = Money("300.00", "MXN")
    with pytest.raises(CurrencyMismatchError):
        calculate_offer_economics(BusinessModel.RETAIL_MARGIN, price=price, product_cost=cost)


def test_no_currency_is_ever_silently_treated_as_another():
    # A USD price and an MXN lane must not combine without explicit FX.
    from backend.economics.kernel import MarketLane

    price = Money("50.00", "USD")
    cost = Money("20.00", "USD")
    mxn_lane = MarketLane(
        lane_id="mx-lane", origin="MX", ship_from="MX", warehouse="MX-CDMX",
        destination_country="MX", currency="MXN",
    )
    with pytest.raises(CurrencyMismatchError):
        calculate_offer_economics(BusinessModel.RETAIL_MARGIN, price=price, product_cost=cost, lane=mxn_lane)


def test_explicit_fx_conversion_is_required_and_recorded():
    usd = Money("10.00", "USD")
    with pytest.raises(EconomicsError):
        usd.convert("MXN", exchange_rate=None, exchange_rate_timestamp="", uncertainty=0, source="")  # type: ignore[arg-type]
    converted = usd.convert(
        "MXN", exchange_rate=Decimal("18.50"), exchange_rate_timestamp="2026-09-17T00:00:00Z",
        uncertainty=Decimal("0.02"), source="test-fixture-fx",
    )
    assert converted.currency == "MXN"
    assert converted.amount == Decimal("185.00")
    assert converted.exchange_rate_timestamp == "2026-09-17T00:00:00Z"

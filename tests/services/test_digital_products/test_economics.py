"""Tests for services.digital_products.economics.estimate_digital_product_margin
— wraps backend.validation.margin_calculator.calculate_margin with
supplier_cost=0.0 rather than a second margin formula."""
from backend.validation.margin_calculator import calculate_margin
from services.digital_products.economics import estimate_digital_product_margin


def test_matches_calculate_margin_with_zero_supplier_cost():
    result = estimate_digital_product_margin(99.0)
    expected = calculate_margin(
        supplier_cost=0.0, retail_price=99.0, shipping_cost=0.0,
        monthly_ad_spend=0.0, expected_monthly_revenue=990.0, category="general",
    )
    assert result == expected


def test_zero_price_yields_loss_status_not_a_crash():
    result = estimate_digital_product_margin(0.0)
    assert result["margin_status"] == "loss"


def test_expected_monthly_revenue_override_is_honored():
    result = estimate_digital_product_margin(50.0, expected_monthly_revenue=5000.0)
    expected = calculate_margin(
        supplier_cost=0.0, retail_price=50.0,
        monthly_ad_spend=0.0, expected_monthly_revenue=5000.0, category="general",
    )
    assert result == expected


def test_never_raises_on_backend_failure(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr("backend.validation.margin_calculator.calculate_margin", _boom)
    assert estimate_digital_product_margin(99.0) == {}

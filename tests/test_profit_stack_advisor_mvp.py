import pytest

from backend.commercial.profit_stack_advisor import run_profit_stack_advisor


def test_profit_stack_low_cost_and_high_simplicity_cases():
    low = run_profit_stack_advisor("Small shop", expected_monthly_revenue=1000, margin_sensitivity="high")
    high = run_profit_stack_advisor("Large shop", expected_monthly_revenue=50000, expected_monthly_orders=800)
    assert "low_cost" in low["recommended_stack"]["commerce"]
    assert "shopify" in high["recommended_stack"]["commerce"]
    assert low["blocked_providers"] and low["provenance"]["provider_prices"] == "static_estimates_or_not_connected"


def test_profit_stack_rejects_unsafe_mode():
    with pytest.raises(PermissionError): run_profit_stack_advisor("x", read_only=False)

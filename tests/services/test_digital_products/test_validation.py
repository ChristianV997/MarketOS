"""Tests for services.digital_products.validation.validate_digital_product."""
from services.digital_products.offer import create_digital_offer
from services.digital_products.validation import validate_digital_product


class TestValidateDigitalProduct:
    def test_zero_price_is_unsafe(self):
        offer = create_digital_offer("Free thing", price=0.0)
        result = validate_digital_product(offer)
        assert result.verdict == "unsafe"

    def test_low_target_buyers_and_warm_audience_is_strong(self):
        offer = create_digital_offer("Thing", price=99.0)
        result = validate_digital_product(offer, target_buyers=5, has_existing_audience=True)
        assert result.verdict == "strong"

    def test_high_target_buyers_cold_traffic_is_fragile_or_unsafe(self):
        offer = create_digital_offer("Thing", price=99.0)
        result = validate_digital_product(offer, target_buyers=500, has_existing_audience=False)
        assert result.verdict in ("fragile", "unsafe")

    def test_required_traffic_matches_formula(self):
        offer = create_digital_offer("Thing", price=99.0)
        result = validate_digital_product(offer, target_buyers=15, assumed_conversion_rate_pct=1.5)
        assert result.required_traffic_estimate == 1000  # ceil(15 / 0.015)

    def test_custom_conversion_rate_overrides_default(self):
        offer = create_digital_offer("Thing", price=99.0)
        result = validate_digital_product(offer, target_buyers=10, assumed_conversion_rate_pct=10.0)
        assert result.required_conversion_rate_pct == 10.0
        assert result.required_traffic_estimate == 100

    def test_never_raises_with_negative_target_buyers(self):
        offer = create_digital_offer("Thing", price=99.0)
        result = validate_digital_product(offer, target_buyers=-5)
        assert result.verdict == "unsafe"

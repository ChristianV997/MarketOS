"""services.digital_products.validation — validate_digital_product.

A low-budget/organic validation test before building the full product:
how much traffic does this offer realistically need to hit a target
number of buyers, given a conservative conversion-rate assumption? These
assumptions are explicitly labeled as assumptions (not fabricated "real"
data) — override assumed_conversion_rate_pct with your own funnel data
once you have it.

This is a traffic/conversion-funnel estimate, deliberately distinct from
services.digital_products.economics (unit-economics/margin, wrapping
backend.validation.margin_calculator) and from backend/validation itself
(product-opportunity validation) — a required_traffic_estimate is not a
margin and shouldn't be computed alongside one in the same function.
"""
from __future__ import annotations

import math

from .schemas import DigitalOffer, DigitalProductValidation

_COLD_TRAFFIC_CONVERSION_PCT = 1.5   # conservative assumption, cold/paid traffic
_WARM_AUDIENCE_CONVERSION_PCT = 5.0  # conservative assumption, existing owned audience


def validate_digital_product(
    offer: DigitalOffer,
    *,
    target_buyers: int = 10,
    assumed_conversion_rate_pct: float | None = None,
    has_existing_audience: bool = False,
) -> DigitalProductValidation:
    """Never raises."""
    if assumed_conversion_rate_pct is None:
        assumed_conversion_rate_pct = _WARM_AUDIENCE_CONVERSION_PCT if has_existing_audience else _COLD_TRAFFIC_CONVERSION_PCT

    if offer.price <= 0 or target_buyers <= 0:
        return DigitalProductValidation(
            validation_test="pre-launch traffic/conversion estimate",
            verdict="unsafe",
            reasoning="price must be > 0 and target_buyers must be > 0 to validate an offer",
        )

    if assumed_conversion_rate_pct <= 0:
        required_traffic = 0
    else:
        required_traffic = math.ceil(target_buyers / (assumed_conversion_rate_pct / 100.0))

    if has_existing_audience and required_traffic <= 2000:
        verdict = "strong"
        reasoning = f"only {required_traffic} visitors needed against an existing audience — low-risk validation"
    elif required_traffic <= 500:
        verdict = "strong"
        reasoning = f"only {required_traffic} visitors needed at {assumed_conversion_rate_pct}% conversion — cheap to test organically"
    elif required_traffic <= 2000:
        verdict = "viable"
        reasoning = f"{required_traffic} visitors needed — realistic with a modest organic/low-paid-budget test"
    elif required_traffic <= 10000:
        verdict = "fragile"
        reasoning = f"{required_traffic} visitors needed — validate the offer with a smaller target_buyers count or an owned audience first"
    else:
        verdict = "unsafe"
        reasoning = f"{required_traffic} visitors needed — this offer/price/target combination isn't realistically testable without paid traffic budget most operators shouldn't risk pre-validation"

    return DigitalProductValidation(
        validation_test="pre-launch traffic/conversion estimate",
        required_traffic_estimate=required_traffic,
        required_conversion_rate_pct=assumed_conversion_rate_pct,
        verdict=verdict,
        reasoning=reasoning,
    )

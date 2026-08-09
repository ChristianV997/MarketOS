"""services.digital_products.economics — estimate_digital_product_margin.

Before this, services.digital_products.plan set an offer's price with no
unit-economics check at all: create_digital_offer just clamped price to
>= 0 and nothing downstream ever asked "does this price actually leave a
margin after payment processing, platform fees, and refunds?"

A digital product has no supplier/landed cost (nothing physical ships),
but it does carry the same payment-processing fee, platform-fee
amortization, and refund-loss economics as a physical dropship sale — so
this wraps the existing backend.validation.margin_calculator.
calculate_margin with supplier_cost=0.0 rather than inventing a second
margin formula. This is a genuine, correct reuse, not a coincidental
naming collision: calculate_margin's cost model (payment_fee +
platform_fee + return_loss) already generalizes to zero-COGS products.

services.digital_products.validation (the traffic/conversion funnel
estimator) is intentionally a separate, distinct calculation from this
module and from backend/validation — a required_traffic_estimate is not
a margin, and conflating the two into one file would be the real naming
confusion the audit flagged, not the module split itself.
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

# Digital products are typically sold via a platform (Gumroad, Teachable,
# a course host) with materially different processing/refund economics
# than a Shopify dropship storefront — "digital" isn't in
# CATEGORY_RETURN_RATES, so it falls back to margin_calculator's
# "general" 12% return rate unless a caller supplies a more specific one.
_DEFAULT_CATEGORY = "general"


def estimate_digital_product_margin(
    price: float,
    *,
    category: str = _DEFAULT_CATEGORY,
    monthly_ad_spend: float = 0.0,
    expected_monthly_revenue: float | None = None,
) -> dict:
    """Never raises: calculate_margin is already never-raise; this wraps it
    anyway so a surprise failure degrades to an empty dict rather than
    aborting the caller's plan.

    ``expected_monthly_revenue`` defaults to 10x price (a conservative
    "sell at least 10 units this month" assumption for amortizing the
    platform's fixed monthly fee) when not supplied — override with a
    real sales-volume estimate once you have one.
    """
    try:
        from backend.validation.margin_calculator import calculate_margin
        return calculate_margin(
            supplier_cost=0.0,
            retail_price=price,
            shipping_cost=0.0,
            monthly_ad_spend=monthly_ad_spend,
            expected_monthly_revenue=expected_monthly_revenue if expected_monthly_revenue is not None else max(price * 10, 1.0),
            category=category,
        )
    except Exception as exc:  # noqa: BLE001
        _log.debug("digital_product_margin_estimate_failed price=%s error=%s", price, exc)
        return {}

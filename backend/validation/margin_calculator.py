"""backend.validation.margin_calculator — dropship unit economics.

Pure math, stdlib only.  Computes net margin per unit after every real cost a
dropship order carries:

  supplier cost + shipping        (landed cost)
  payment processing              (pct + fixed, Stripe/Shopify Payments style)
  platform subscription           (amortized over expected monthly revenue)
  returns/refunds                 (expected loss rate on gross margin)
  customer acquisition            (ad spend / expected orders)

Thresholds are deliberately conservative: a product only reads "profitable"
when net margin clears 15% — below that, ad-cost variance eats the spread.
"""
from __future__ import annotations

import os

# Platform fee model (Shopify Basic defaults; env-tunable per deployment)
_PAYMENT_FEE_PCT   = float(os.getenv("MARGIN_PAYMENT_FEE_PCT", "0.029"))
_PAYMENT_FEE_FIXED = float(os.getenv("MARGIN_PAYMENT_FEE_FIXED", "0.30"))
_PLATFORM_MONTHLY  = float(os.getenv("MARGIN_PLATFORM_MONTHLY", "29.0"))

# Verdict thresholds on net margin percentage
_PROFITABLE_PCT = float(os.getenv("MARGIN_PROFITABLE_PCT", "15.0"))
_BREAKEVEN_PCT  = float(os.getenv("MARGIN_BREAKEVEN_PCT", "5.0"))


def calculate_margin(
    supplier_cost: float,
    retail_price: float,
    shipping_cost: float = 0.0,
    monthly_ad_spend: float = 500.0,
    expected_monthly_revenue: float = 5000.0,
    return_rate: float = 0.12,
) -> dict:
    """Return the full unit-economics breakdown for one sale.

    All percentages are relative to retail_price.  Never raises: a zero or
    negative retail price returns a "loss" verdict with zeroed ratios.
    """
    if retail_price <= 0:
        return {
            "supplier_cost": round(supplier_cost, 2),
            "retail_price": round(retail_price, 2),
            "landed_cost": round(supplier_cost + shipping_cost, 2),
            "gross_margin": 0.0, "gross_margin_pct": 0.0,
            "payment_fee": 0.0, "platform_fee": 0.0,
            "return_loss": 0.0, "cac": 0.0,
            "net_margin": 0.0, "net_margin_pct": 0.0,
            "margin_status": "loss",
        }

    landed_cost  = supplier_cost + shipping_cost
    gross_margin = retail_price - landed_cost

    payment_fee = retail_price * _PAYMENT_FEE_PCT + _PAYMENT_FEE_FIXED

    # Subscription amortized per order: monthly fee spread over expected orders
    expected_orders = max(expected_monthly_revenue / retail_price, 1.0)
    platform_fee    = _PLATFORM_MONTHLY / expected_orders

    # Expected loss from returns: refunded revenue minus recovered nothing
    # (dropship returns are rarely restocked) → lose the gross margin on
    # return_rate of orders, plus the payment fee is not refunded by Stripe.
    return_loss = gross_margin * return_rate

    cac = monthly_ad_spend / expected_orders

    net_margin     = gross_margin - payment_fee - platform_fee - return_loss - cac
    net_margin_pct = net_margin / retail_price * 100

    if net_margin_pct > _PROFITABLE_PCT:
        status = "profitable"
    elif net_margin_pct > _BREAKEVEN_PCT:
        status = "breakeven"
    else:
        status = "loss"

    return {
        "supplier_cost":     round(supplier_cost, 2),
        "retail_price":      round(retail_price, 2),
        "landed_cost":       round(landed_cost, 2),
        "gross_margin":      round(gross_margin, 2),
        "gross_margin_pct":  round(gross_margin / retail_price * 100, 1),
        "payment_fee":       round(payment_fee, 2),
        "platform_fee":      round(platform_fee, 2),
        "return_loss":       round(return_loss, 2),
        "cac":               round(cac, 2),
        "net_margin":        round(net_margin, 2),
        "net_margin_pct":    round(net_margin_pct, 1),
        "margin_status":     status,
    }


def suggest_retail_price(
    landed_cost: float,
    target_net_margin_pct: float = 20.0,
    monthly_ad_spend: float = 500.0,
    expected_monthly_revenue: float = 5000.0,
    return_rate: float = 0.12,
) -> float:
    """Find the lowest retail price hitting the target net margin (bisection).

    Searches between 1x and 10x landed cost; returns the 10x cap if even that
    can't reach the target (caller should treat the product as unviable).
    """
    if landed_cost <= 0:
        return 0.0
    lo, hi = landed_cost, landed_cost * 10.0
    for _ in range(40):
        mid = (lo + hi) / 2
        result = calculate_margin(
            supplier_cost=landed_cost, retail_price=mid,
            monthly_ad_spend=monthly_ad_spend,
            expected_monthly_revenue=expected_monthly_revenue,
            return_rate=return_rate,
        )
        if result["net_margin_pct"] < target_net_margin_pct:
            lo = mid
        else:
            hi = mid
    return round(hi, 2)

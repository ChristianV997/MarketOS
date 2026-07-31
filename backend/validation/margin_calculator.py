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

Phase 6 additions (all opt-in, zero effect on ``calculate_margin``'s default
behavior unless a caller explicitly supplies the new parameters):

  * category-aware return rates (``CATEGORY_RETURN_RATES``) replace the
    single global 12% constant — electronics/apparel/beauty have very
    different real-world return profiles; ``category`` defaults to
    "general" (12%, byte-identical to the old constant).
  * ``calculate_margin_geo`` layers per-destination shipping bands, a
    cross-border customs/duty line item, and a COD-vs-card payment split
    on top of the base model — a product that looks profitable on raw
    ad-platform ROAS can be a loser once COD refusal rates or import duty
    in a given geo are counted.
  * ``calculate_ltv_adjusted_margin`` recomputes net margin against
    LTV-adjusted CAC (``backend.economics.ltv.effective_cac``) instead of
    single-order CAC, so a consumable with real repeat-purchase potential
    correctly outranks a one-off novelty item with identical first-order
    margin.

Cost Engine additions (``backend/costs``, all opt-in): ``calculate_margin``
and ``suggest_retail_price`` accept optional ``payment_fee_pct``,
``payment_fee_fixed``, and ``platform_monthly_fee`` overrides so a caller
modeling a specific provider stack (e.g. WooCommerce + Mercado Pago MX) can
drive this same math with that stack's real fees instead of the global
env-tunable defaults. Omitting all three is byte-identical to pre-existing
behavior.
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

# ── Phase 6a: category-aware return rates ──────────────────────────────────
# Seeded from public dropshipping-industry benchmarks; "general" (12%)
# matches the pre-Phase-6 global constant exactly, so any caller that omits
# ``category`` sees byte-identical behavior to before this phase.
CATEGORY_RETURN_RATES = {
    "general":     0.12,
    "electronics": 0.15,
    "apparel":     0.20,
    "beauty":      0.10,
    "consumables": 0.08,
    "jewelry":     0.18,
    "home":        0.10,
    "pets":        0.08,   # low returns — impulse/gift-driven, rarely fit-dependent
    "baby":        0.14,   # moderate — safety/fit concerns push slightly above general
}

# Supplier-selection risk adjustment (see suppliers.py::find_best_supplier):
# lower-reliability suppliers get a return-rate markup on top of the
# category baseline — worse quality control plausibly correlates with more
# returns/complaints, independent of category. Increased from 0.3 to 0.5 to
# make risk-adjusted ranking more aggressive (0.15 unreliability gap = 7.5%
# cost markup vs 4.5% before).
RETURN_RELIABILITY_SENSITIVITY = 0.5


def category_return_rate(category: str = "general") -> float:
    """Category-specific return/chargeback rate; unknown categories fall
    back to the "general" (12%) rate, matching the pre-Phase-6 default.

    Consults backend.data.category_priors (Phase I) for a dataset-derived
    return_proxy first — a no-op today (returns *legacy* unchanged) until
    both CATEGORY_PRIORS_LIVE is set and scripts/ingest_category_priors.py
    has actually populated real data for *category*.
    """
    legacy = CATEGORY_RETURN_RATES.get(category, CATEGORY_RETURN_RATES["general"])
    try:
        from backend.data.category_priors import category_prior
        return category_prior(category, "return_proxy", legacy)
    except Exception:
        return legacy


def calculate_margin(
    supplier_cost: float,
    retail_price: float,
    shipping_cost: float = 0.0,
    monthly_ad_spend: float = 500.0,
    expected_monthly_revenue: float = 5000.0,
    return_rate: float | None = None,
    category: str = "general",
    payment_fee_pct: float | None = None,
    payment_fee_fixed: float | None = None,
    platform_monthly_fee: float | None = None,
) -> dict:
    """Return the full unit-economics breakdown for one sale.

    All percentages are relative to retail_price.  Never raises: a zero or
    negative retail price returns a "loss" verdict with zeroed ratios.

    ``return_rate``, when omitted (``None``), is derived from ``category``
    via ``category_return_rate`` — callers that pass neither see exactly
    today's 12% default; callers that pass ``return_rate`` explicitly keep
    that exact value regardless of category (unchanged legacy override
    behavior).

    ``payment_fee_pct``/``payment_fee_fixed``/``platform_monthly_fee``, when
    omitted (``None``), fall back to the module's env-tunable defaults
    (``_PAYMENT_FEE_PCT``/``_PAYMENT_FEE_FIXED``/``_PLATFORM_MONTHLY``) —
    byte-identical to pre-existing behavior. Pass them explicitly to model a
    specific provider stack's real fees (see ``backend/costs``).
    """
    if return_rate is None:
        return_rate = category_return_rate(category)
    if payment_fee_pct is None:
        payment_fee_pct = _PAYMENT_FEE_PCT
    if payment_fee_fixed is None:
        payment_fee_fixed = _PAYMENT_FEE_FIXED
    if platform_monthly_fee is None:
        platform_monthly_fee = _PLATFORM_MONTHLY

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

    payment_fee = retail_price * payment_fee_pct + payment_fee_fixed

    # Subscription amortized per order: monthly fee spread over expected orders
    expected_orders = max(expected_monthly_revenue / retail_price, 1.0)
    platform_fee    = platform_monthly_fee / expected_orders

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


# ── Phase 6b: geo-aware economics ──────────────────────────────────────────
# Per-destination shipping multiplier on top of a supplier's base shipping
# quote (which is typically priced for domestic/US delivery).
GEO_SHIPPING_MULTIPLIERS = {
    "US":   1.0,
    "CA":   1.3,
    "UK":   1.5,
    "EU":   1.6,
    "AU":   2.0,
    "INTL": 2.5,   # catch-all cross-border default
}

# Customs/duty: cross-border orders above this dutiable value incur a flat
# rate on the excess. US (domestic) never incurs duty.
GEO_CUSTOMS_THRESHOLD_USD = 800.0
GEO_CUSTOMS_RATE = 0.15

# COD vs. card payment-method economics. COD refusal (buyer declines at the
# door) is a real, materially large loss in COD-heavy geos and was entirely
# absent from the pre-Phase-6 margin model.
COD_REFUSAL_RATE = 0.10
CARD_REFUSAL_RATE = 0.025
COD_HANDLING_FEE_PCT = 0.02   # courier cash-collection/remittance fee


def geo_adjusted_shipping(base_shipping: float, geo: str = "US") -> float:
    """Scale a supplier's (typically domestic-priced) shipping quote for
    the destination geo; unknown geos fall back to the cross-border rate."""
    mult = GEO_SHIPPING_MULTIPLIERS.get(geo, GEO_SHIPPING_MULTIPLIERS["INTL"])
    return round(base_shipping * mult, 2)


def customs_duty(landed_cost: float, retail_price: float, geo: str = "US") -> float:
    """Flat-rate duty on the portion of dutiable value above the threshold;
    zero for domestic (US) orders."""
    if geo == "US":
        return 0.0
    dutiable_value = max(retail_price, landed_cost)
    if dutiable_value <= GEO_CUSTOMS_THRESHOLD_USD:
        return 0.0
    return round((dutiable_value - GEO_CUSTOMS_THRESHOLD_USD) * GEO_CUSTOMS_RATE, 2)


def payment_method_economics(retail_price: float, payment_method: str = "card") -> dict:
    """Refusal-rate-driven expected loss and handling fee for the chosen
    payment method. COD refusal (order fulfilled and shipped, then declined
    at delivery) is a full-order loss, not a partial one — the whole
    landed-cost + shipping investment is stranded."""
    if payment_method == "cod":
        refusal_rate = COD_REFUSAL_RATE
        handling_fee = round(retail_price * COD_HANDLING_FEE_PCT, 2)
    else:
        refusal_rate = CARD_REFUSAL_RATE
        handling_fee = 0.0
    expected_refusal_loss = round(retail_price * refusal_rate, 2)
    return {
        "payment_method": payment_method,
        "refusal_rate": refusal_rate,
        "handling_fee": handling_fee,
        "expected_refusal_loss": expected_refusal_loss,
    }


def calculate_margin_geo(
    supplier_cost: float,
    retail_price: float,
    shipping_cost: float = 0.0,
    monthly_ad_spend: float = 500.0,
    expected_monthly_revenue: float = 5000.0,
    return_rate: float | None = None,
    category: str = "general",
    geo: str = "US",
    payment_method: str = "card",
) -> dict:
    """Geo-aware unit economics: layers destination shipping, cross-border
    customs, and COD-vs-card payment economics on top of ``calculate_margin``.

    A new, opt-in function (rather than extending ``calculate_margin``
    itself) so existing callers/tests of the base function see zero change
    in behavior — this is where GeoAgent-facing callers should compute
    net-margin-adjusted ROAS instead of trusting raw ad-platform ROAS.
    """
    adjusted_shipping = geo_adjusted_shipping(shipping_cost, geo)
    base = calculate_margin(
        supplier_cost=supplier_cost,
        retail_price=retail_price,
        shipping_cost=adjusted_shipping,
        monthly_ad_spend=monthly_ad_spend,
        expected_monthly_revenue=expected_monthly_revenue,
        return_rate=return_rate,
        category=category,
    )

    if retail_price <= 0:
        base.update({"geo": geo, "customs_duty": 0.0, "payment_economics": None})
        return base

    duty = customs_duty(supplier_cost + adjusted_shipping, retail_price, geo)
    payment_econ = payment_method_economics(retail_price, payment_method)

    net_margin = base["net_margin"] - duty - payment_econ["handling_fee"] - payment_econ["expected_refusal_loss"]
    net_margin_pct = net_margin / retail_price * 100

    if net_margin_pct > _PROFITABLE_PCT:
        status = "profitable"
    elif net_margin_pct > _BREAKEVEN_PCT:
        status = "breakeven"
    else:
        status = "loss"

    result = dict(base)
    result.update({
        "geo": geo,
        "customs_duty": round(duty, 2),
        "payment_economics": payment_econ,
        "net_margin": round(net_margin, 2),
        "net_margin_pct": round(net_margin_pct, 1),
        "margin_status": status,
    })
    return result


def geo_margin_adjusted_roas(platform_roas: float, geo_margin_pct: float,
                              base_margin_pct: float = _PROFITABLE_PCT) -> float:
    """Scale raw ad-platform ROAS by how the geo's net margin compares to
    the baseline profitable-margin threshold.

    A pure ratio: ``platform_roas * (geo_margin_pct / base_margin_pct)``,
    clipped to non-negative. When ``geo_margin_pct`` matches the baseline
    threshold exactly, this is a no-op; a geo with materially thinner
    margin (COD-heavy, high-duty) pulls the effective ROAS down even if
    the raw platform-reported ROAS looks identical to a cleaner geo's.
    """
    if base_margin_pct <= 0:
        return max(0.0, platform_roas)
    frac = geo_margin_pct / base_margin_pct
    return max(0.0, platform_roas * frac)


# ── Phase 6d: LTV-adjusted margin ──────────────────────────────────────────


def calculate_ltv_adjusted_margin(
    supplier_cost: float,
    retail_price: float,
    shipping_cost: float = 0.0,
    monthly_ad_spend: float = 500.0,
    expected_monthly_revenue: float = 5000.0,
    return_rate: float | None = None,
    category: str = "general",
) -> dict:
    """Net margin recomputed against LTV-adjusted CAC instead of
    single-order CAC.

    New, opt-in function — ``calculate_margin`` itself is untouched. A
    consumable with a real repeat-purchase rate earns back a fraction of
    its acquisition cost on later orders at near-zero incremental spend;
    single-order economics (the base ``calculate_margin``) can't see that
    and scores it identically to a one-off novelty item with the same
    first-order margin. This is the correction.
    """
    from backend.economics.ltv import effective_cac

    base = calculate_margin(
        supplier_cost=supplier_cost, retail_price=retail_price,
        shipping_cost=shipping_cost, monthly_ad_spend=monthly_ad_spend,
        expected_monthly_revenue=expected_monthly_revenue,
        return_rate=return_rate, category=category,
    )
    if retail_price <= 0:
        result = dict(base)
        result["effective_cac"] = 0.0
        return result

    ltv_cac = effective_cac(base["cac"], category=category)
    cac_savings = base["cac"] - ltv_cac
    net_margin = base["net_margin"] + cac_savings
    net_margin_pct = net_margin / retail_price * 100

    if net_margin_pct > _PROFITABLE_PCT:
        status = "profitable"
    elif net_margin_pct > _BREAKEVEN_PCT:
        status = "breakeven"
    else:
        status = "loss"

    result = dict(base)
    result.update({
        "effective_cac":  round(ltv_cac, 2),
        "net_margin":     round(net_margin, 2),
        "net_margin_pct": round(net_margin_pct, 1),
        "margin_status":  status,
    })
    return result


def suggest_retail_price(
    landed_cost: float,
    target_net_margin_pct: float = 20.0,
    monthly_ad_spend: float = 500.0,
    expected_monthly_revenue: float = 5000.0,
    return_rate: float = 0.12,
    payment_fee_pct: float | None = None,
    payment_fee_fixed: float | None = None,
    platform_monthly_fee: float | None = None,
) -> float:
    """Find the lowest retail price hitting the target net margin (bisection).

    Searches between 1x and 10x landed cost; returns the 10x cap if even that
    can't reach the target (caller should treat the product as unviable).

    ``payment_fee_pct``/``payment_fee_fixed``/``platform_monthly_fee`` are
    forwarded to ``calculate_margin`` unchanged (see its docstring); omitting
    all three is byte-identical to pre-existing behavior.
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
            payment_fee_pct=payment_fee_pct,
            payment_fee_fixed=payment_fee_fixed,
            platform_monthly_fee=platform_monthly_fee,
        )
        if result["net_margin_pct"] < target_net_margin_pct:
            lo = mid
        else:
            hi = mid
    return round(hi, 2)

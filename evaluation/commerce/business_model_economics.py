"""Business-model-aware economics dispatch.

Consumes the canonical financial kernel (``backend.economics.kernel`` —
PR #248's financial-evidence-kernel lane) rather than duplicating its
formulas. The one thing that kernel does not decide on its own is *which*
revenue/cost basis applies: a retail_margin offer owns landed cost against
the full sale price, but a commission, affiliate, or lead_generation offer
never does — MarketOS (or the operator) is paid a fraction of, or a flat fee
against, someone else's sale. Silently running every offer through the same
full-margin waterfall would overstate commission/affiliate/lead-gen economics
by counting costs the business model never actually bears.

This module is the single place that decides the revenue/cost basis per
``BusinessModel`` and then calls straight into the kernel's
``calculate_unit_economics`` — it never reimplements fee/contribution math.
"""
from __future__ import annotations

from decimal import Decimal

from backend.economics.kernel import (
    EconomicsError,
    MarketLane,
    Money,
    UnitEconomicsAssumptions,
    UnitEconomicsResult,
    calculate_unit_economics,
)

from .canonical import BusinessModel


def calculate_offer_economics(
    business_model: BusinessModel,
    *,
    price: Money,
    product_cost: Money | None = None,
    commission_rate: Decimal | None = None,
    affiliate_rate: Decimal | None = None,
    lead_payout: Money | None = None,
    lane: MarketLane | None = None,
    assumptions: UnitEconomicsAssumptions | None = None,
) -> UnitEconomicsResult:
    """Route to the revenue/cost basis that matches ``business_model``.

    Each branch fixes the inputs the kernel receives so that a business
    model that never touches landed cost (commission/affiliate/lead_gen)
    cannot be handed a nonzero ``product_cost`` by mistake — the caller
    would have to explicitly misuse ``RETAIL_MARGIN`` to do that, which this
    function refuses.
    """
    if business_model == BusinessModel.RETAIL_MARGIN:
        if product_cost is None:
            raise EconomicsError("retail_margin business model requires product_cost")
        return calculate_unit_economics(price, product_cost, lane=lane, assumptions=assumptions, scenario="retail_margin")

    if business_model == BusinessModel.COMMISSION:
        if commission_rate is None:
            raise EconomicsError("commission business model requires commission_rate")
        if not (Decimal("0") <= commission_rate <= Decimal("1")):
            raise EconomicsError("invalid commission_rate")
        commission_revenue = price.multiply(commission_rate)
        zero_cost = Money.zero(price.currency, source="commission_model_no_inventory")
        return calculate_unit_economics(
            commission_revenue, zero_cost, lane=lane, assumptions=assumptions, scenario="commission",
        )

    if business_model == BusinessModel.AFFILIATE:
        if affiliate_rate is None:
            raise EconomicsError("affiliate business model requires affiliate_rate")
        if not (Decimal("0") <= affiliate_rate <= Decimal("1")):
            raise EconomicsError("invalid affiliate_rate")
        affiliate_revenue = price.multiply(affiliate_rate)
        zero_cost = Money.zero(price.currency, source="affiliate_model_no_inventory")
        return calculate_unit_economics(
            affiliate_revenue, zero_cost, lane=lane, assumptions=assumptions, scenario="affiliate",
        )

    if business_model == BusinessModel.LEAD_GENERATION:
        if lead_payout is None:
            raise EconomicsError("lead_generation business model requires lead_payout")
        zero_cost = Money.zero(lead_payout.currency, source="lead_generation_no_inventory")
        return calculate_unit_economics(
            lead_payout, zero_cost, lane=lane, assumptions=assumptions, scenario="lead_generation",
        )

    raise EconomicsError(f"unsupported business model: {business_model!r}")


def assert_no_shared_retail_formula(business_model: BusinessModel, product_cost: Money | None) -> None:
    """Defense-in-depth: reject an explicit landed-cost input on a non-retail model.

    ``calculate_offer_economics`` already ignores ``product_cost`` for
    commission/affiliate/lead_generation by construction (it never reads the
    parameter for those branches); this guard exists for callers assembling
    kernel inputs directly instead of going through
    ``calculate_offer_economics``, so a copy-paste from a retail_margin
    offer can't silently reintroduce a landed-cost assumption a commission
    or lead-gen deal never bears.
    """
    if business_model != BusinessModel.RETAIL_MARGIN and product_cost is not None and product_cost.amount != Decimal("0"):
        raise EconomicsError(
            f"{business_model.value} business model must not carry a nonzero product_cost "
            "(retail-margin landed-cost formula does not apply)"
        )


__all__ = ["calculate_offer_economics", "assert_no_shared_retail_formula"]

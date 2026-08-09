"""backend.costs.payment_cost — extract and apply a payment provider plan's
processing-fee rate. Pure extraction of catalog data, not a fee-formula
invention — the actual per-order math is one line, delegated identically to
how backend.validation.margin_calculator already computes payment_fee."""
from __future__ import annotations

from backend.providers.schemas import Provider, ProviderPlan


def payment_fee_rate(payment_provider: Provider, plan: ProviderPlan) -> tuple[float, float]:
    """Return (pct, fixed) extracted from the plan's payment_pct/payment_fixed
    cost components. Missing components default to 0.0 — a provider plan
    with no payment fee (e.g. WooCommerce itself, which has none — the
    payment processor is a separate provider) is a valid zero-fee reading,
    not an error."""
    pct = 0.0
    fixed = 0.0
    for component in plan.cost_components:
        if component.kind == "payment_pct":
            pct = component.amount
        elif component.kind == "payment_fixed":
            fixed = component.amount
    return pct, fixed


def payment_processing_cost_per_order(payment_provider: Provider, plan: ProviderPlan, order_value: float) -> float:
    pct, fixed = payment_fee_rate(payment_provider, plan)
    return round(order_value * pct + fixed, 2)

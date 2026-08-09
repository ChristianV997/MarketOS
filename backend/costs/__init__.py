"""backend.costs — the Cost Engine.

Composes backend.validation.margin_calculator and backend.providers rather
than reimplementing fee/margin math. See docs/COST_AWARE_INTEGRATION_AUDIT.md.
"""
from __future__ import annotations

from .compare import compare_stacks
from .fixed_cost import stack_fixed_monthly_cost
from .payment_cost import payment_fee_rate, payment_processing_cost_per_order
from .schemas import CostComparisonResult, StackCostEstimate
from .stack_total import break_even_client_price, margin_after_stack_cost, stack_total_monthly_cost

__all__ = [
    "StackCostEstimate",
    "CostComparisonResult",
    "stack_fixed_monthly_cost",
    "payment_fee_rate",
    "payment_processing_cost_per_order",
    "stack_total_monthly_cost",
    "margin_after_stack_cost",
    "break_even_client_price",
    "compare_stacks",
]

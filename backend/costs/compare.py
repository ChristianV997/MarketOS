"""backend.costs.compare — compare_stacks, pure sort/selection over already-
computed StackCostEstimates. No external calls."""
from __future__ import annotations

from .schemas import CostComparisonResult, StackCostEstimate


def compare_stacks(stack_estimates: list[StackCostEstimate]) -> CostComparisonResult:
    """Never raises: an empty list returns a CostComparisonResult with empty
    id fields rather than raising on max()/min() of an empty sequence."""
    if not stack_estimates:
        return CostComparisonResult(stacks=[])

    cheapest = min(stack_estimates, key=lambda s: s.monthly_total_cost_at_volume)
    highest_margin = max(
        stack_estimates,
        key=lambda s: s.margin_after_stack_cost.get("net_margin_pct", float("-inf")),
    )
    return CostComparisonResult(
        stacks=list(stack_estimates),
        cheapest_stack_id=cheapest.stack_id,
        highest_margin_stack_id=highest_margin.stack_id,
    )

"""backend.costs.fixed_cost — sum of a stack's fixed_monthly cost components."""
from __future__ import annotations

from typing import Sequence

from backend.providers.schemas import Provider, ProviderPlan


def stack_fixed_monthly_cost(selections: Sequence[tuple[Provider, ProviderPlan]]) -> float:
    """Sum every ``kind="fixed_monthly"`` cost component across the given
    (provider, plan) selections. Never raises; an empty selection is $0."""
    total = 0.0
    for _provider, plan in selections:
        for component in plan.cost_components:
            if component.kind == "fixed_monthly":
                total += component.amount
    return round(total, 2)

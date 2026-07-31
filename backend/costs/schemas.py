"""backend.costs.schemas — Cost Engine result dataclasses."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StackCostEstimate:
    stack_id: str
    fixed_monthly_cost: float = 0.0
    payment_fee_pct: float = 0.0
    payment_fee_fixed: float = 0.0
    estimated_monthly_orders: float = 0.0
    estimated_avg_order_value: float = 0.0
    margin_after_stack_cost: dict[str, Any] = field(default_factory=dict)
    break_even_client_price: float = 0.0
    monthly_total_cost_at_volume: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stack_id": self.stack_id,
            "fixed_monthly_cost": self.fixed_monthly_cost,
            "payment_fee_pct": self.payment_fee_pct,
            "payment_fee_fixed": self.payment_fee_fixed,
            "estimated_monthly_orders": self.estimated_monthly_orders,
            "estimated_avg_order_value": self.estimated_avg_order_value,
            "margin_after_stack_cost": self.margin_after_stack_cost,
            "break_even_client_price": self.break_even_client_price,
            "monthly_total_cost_at_volume": self.monthly_total_cost_at_volume,
            "notes": self.notes,
        }


@dataclass
class CostComparisonResult:
    stacks: list[StackCostEstimate] = field(default_factory=list)
    cheapest_stack_id: str = ""
    highest_margin_stack_id: str = ""
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stacks": [s.to_dict() for s in self.stacks],
            "cheapest_stack_id": self.cheapest_stack_id,
            "highest_margin_stack_id": self.highest_margin_stack_id,
            "generated_at": self.generated_at,
        }

"""services.ecommerce_operator.schemas — LaunchReadiness, ContributionProfitResult,
ScaleDecision."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

DECISIONS = (
    "kill", "iterate_offer", "iterate_creative", "continue_test",
    "scale_cautiously", "scale_approved", "blocked",
)


@dataclass
class LaunchReadiness:
    ready: bool
    blocked_reasons: list[str] = field(default_factory=list)
    checklist: dict[str, bool] = field(default_factory=dict)
    live_mode_checklist: dict[str, Any] | None = None
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "blocked_reasons": list(self.blocked_reasons),
            "checklist": dict(self.checklist),
            "live_mode_checklist": self.live_mode_checklist,
            "generated_at": self.generated_at,
        }


@dataclass
class ContributionProfitResult:
    product_name: str
    actual_spend: float = 0.0
    actual_revenue_raw: float = 0.0
    actual_revenue_reconciled: float = 0.0
    actual_orders: int = 0
    refunds: float = 0.0
    supplier_costs: float = 0.0
    payment_fees: float = 0.0
    contribution_profit: float = 0.0
    contribution_margin: float = 0.0
    reconciliation: dict[str, Any] = field(default_factory=dict)
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_name": self.product_name,
            "actual_spend": round(self.actual_spend, 2),
            "actual_revenue_raw": round(self.actual_revenue_raw, 2),
            "actual_revenue_reconciled": round(self.actual_revenue_reconciled, 2),
            "actual_orders": self.actual_orders,
            "refunds": round(self.refunds, 2),
            "supplier_costs": round(self.supplier_costs, 2),
            "payment_fees": round(self.payment_fees, 2),
            "contribution_profit": round(self.contribution_profit, 2),
            "contribution_margin": round(self.contribution_margin, 4),
            "reconciliation": self.reconciliation,
            "generated_at": self.generated_at,
        }


@dataclass
class ScaleDecision:
    decision: str
    decision_reason: str
    next_action: str
    contribution_profit: float = 0.0
    contribution_margin: float = 0.0
    roas: float = 0.0
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "decision_reason": self.decision_reason,
            "next_action": self.next_action,
            "contribution_profit": round(self.contribution_profit, 2),
            "contribution_margin": round(self.contribution_margin, 4),
            "roas": round(self.roas, 4),
            "generated_at": self.generated_at,
        }

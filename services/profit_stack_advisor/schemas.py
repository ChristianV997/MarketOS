"""services.profit_stack_advisor.schemas — ProfitStackAdvisorResult."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProfitStackAdvisorResult:
    business_name: str
    business_model: str = "own_ecommerce"
    recommendation: dict[str, Any] = field(default_factory=dict)
    cost_comparison: dict[str, Any] | None = None
    dry_run: bool = True
    status: str = "ready_for_client_service"
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "business_name": self.business_name,
            "business_model": self.business_model,
            "recommendation": self.recommendation,
            "cost_comparison": self.cost_comparison,
            "dry_run": self.dry_run,
            "status": self.status,
            "generated_at": self.generated_at,
        }

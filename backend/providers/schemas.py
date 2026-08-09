"""backend.providers.schemas — Provider Registry dataclasses.

Static catalog data describing third-party commerce/payment/automation
providers and their pricing shape, used by backend.costs and
backend.stack_planner to compute and compare stacks. No credentials, no
live pricing lookups — every dollar figure here is a documented,
env-overridable estimate (see provider_catalog.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProviderCostComponent:
    """One line item in a provider plan's cost structure.

    kind: "fixed_monthly" | "payment_pct" | "payment_fixed" | "per_order" | "usage_overage"
    amount: the numeric value (currency units for fixed/per_order/payment_fixed,
      a fraction like 0.029 for payment_pct).
    """
    kind: str
    amount: float
    unit: str = ""
    notes: str = ""


@dataclass(frozen=True)
class ProviderPlan:
    plan_id: str
    display_name: str
    cost_components: tuple[ProviderCostComponent, ...] = ()
    min_monthly_revenue_usd: float = 0.0
    notes: str = ""


@dataclass(frozen=True)
class ProviderRisk:
    level: str = "low"  # low | medium | high
    reasons: tuple[str, ...] = ()
    requires_legal_approval: bool = False
    internal_only: bool = False


@dataclass(frozen=True)
class Provider:
    provider_id: str
    name: str
    category: str
    capabilities: tuple[str, ...] = ()
    integration_status: str = "catalog_only"  # catalog_only | adapter_available
    plans: tuple[ProviderPlan, ...] = ()
    risk: ProviderRisk = field(default_factory=ProviderRisk)
    license: str = "proprietary"
    oss_inventory_ref: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class ProviderIntegrationStatus:
    """Computed (not catalog data): how usable a provider is for a specific
    workspace right now, composing backend.workspaces.credential_scope."""
    provider_id: str
    catalog_state: str
    credential_status: str
    dry_run: bool
    usable_now: bool


@dataclass
class ProviderRecommendation:
    provider_id: str
    category: str
    selected_plan_id: str = ""
    monthly_cost_estimate: float = 0.0
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False
    blocked_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "category": self.category,
            "selected_plan_id": self.selected_plan_id,
            "monthly_cost_estimate": self.monthly_cost_estimate,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "blocked": self.blocked,
            "blocked_reason": self.blocked_reason,
        }

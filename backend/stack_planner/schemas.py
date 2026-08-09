"""backend.stack_planner.schemas — BusinessStackRequest / BusinessStackRecommendation."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from backend.costs.schemas import StackCostEstimate
from backend.providers.schemas import ProviderRecommendation


@dataclass
class BusinessStackRequest:
    business_model: str = "own_ecommerce"
    target_geo: str = "MX"
    expected_monthly_revenue_usd: float = 5000.0
    expected_monthly_orders: float = 0.0
    margin_sensitivity: str = "standard"  # low_cost_validation | standard | premium_brand
    is_white_labeled_client_facing: bool = False
    postiz_legal_approval: bool = False
    category: str = "general"
    supplier_cost: float = 0.0
    retail_price: float = 0.0
    workspace: Any = None  # ClientWorkspace, not serialized


@dataclass
class BusinessStackRecommendation:
    strategy_id: str = ""
    commerce_provider_recommendation: ProviderRecommendation | None = None
    payment_provider_recommendation: ProviderRecommendation | None = None
    # Only populated for lead-gen/agency strategies (no checkout involved).
    crm_provider_recommendation: ProviderRecommendation | None = None
    automation_recommendations: list[ProviderRecommendation] = field(default_factory=list)
    monthly_cost_estimate: StackCostEstimate | None = None
    margin_after_stack_cost: dict[str, Any] = field(default_factory=dict)
    break_even_client_price: float = 0.0
    rules_applied: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = "recommended"  # recommended | not_yet_supported
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "commerce_provider_recommendation": self.commerce_provider_recommendation.to_dict() if self.commerce_provider_recommendation else None,
            "payment_provider_recommendation": self.payment_provider_recommendation.to_dict() if self.payment_provider_recommendation else None,
            "crm_provider_recommendation": self.crm_provider_recommendation.to_dict() if self.crm_provider_recommendation else None,
            "automation_recommendations": [r.to_dict() for r in self.automation_recommendations],
            "monthly_cost_estimate": self.monthly_cost_estimate.to_dict() if self.monthly_cost_estimate else None,
            "margin_after_stack_cost": self.margin_after_stack_cost,
            "break_even_client_price": self.break_even_client_price,
            "rules_applied": self.rules_applied,
            "warnings": self.warnings,
            "status": self.status,
            "generated_at": self.generated_at,
        }

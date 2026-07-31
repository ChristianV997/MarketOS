"""services.digital_products.schemas."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

PRODUCT_TYPES = (
    "template", "playbook", "course", "cohort", "ebook", "paid_report",
    "prompt_pack", "calculator", "dashboard_access", "mentorship",
)

VALIDATION_VERDICTS = ("unsafe", "fragile", "viable", "strong")


@dataclass
class DigitalOffer:
    offer_name: str
    product_type: str
    target_customer: str
    transformation_promised: str
    price: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "offer_name": self.offer_name, "product_type": self.product_type,
            "target_customer": self.target_customer,
            "transformation_promised": self.transformation_promised, "price": self.price,
        }


@dataclass
class FunnelPlan:
    lead_magnet: str
    funnel_steps: list[str] = field(default_factory=list)
    sales_page_structure: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"lead_magnet": self.lead_magnet, "funnel_steps": self.funnel_steps, "sales_page_structure": self.sales_page_structure}


@dataclass
class DigitalProductValidation:
    validation_test: str
    required_traffic_estimate: int = 0
    required_conversion_rate_pct: float = 0.0
    verdict: str = "unsafe"
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "validation_test": self.validation_test,
            "required_traffic_estimate": self.required_traffic_estimate,
            "required_conversion_rate_pct": self.required_conversion_rate_pct,
            "verdict": self.verdict, "reasoning": self.reasoning,
        }


@dataclass
class DigitalProductPlan:
    offer: dict[str, Any] = field(default_factory=dict)
    funnel: dict[str, Any] = field(default_factory=dict)
    content_plan: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    launch_checklist: list[dict[str, Any]] = field(default_factory=list)
    metrics_to_track: list[str] = field(default_factory=list)
    decision_criteria: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = True
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "offer": self.offer, "funnel": self.funnel, "content_plan": self.content_plan,
            "validation": self.validation, "launch_checklist": self.launch_checklist,
            "metrics_to_track": self.metrics_to_track, "decision_criteria": self.decision_criteria,
            "dry_run": self.dry_run, "generated_at": self.generated_at,
        }

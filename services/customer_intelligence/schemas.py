"""services.customer_intelligence.schemas."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

VERTICALS = (
    "real_estate", "car_sales", "ecommerce_brand", "clinic_wellness",
    "home_services", "coaching_consulting", "luxury_products",
)


@dataclass
class ICPResult:
    business_type: str
    target_geo: str = "MX"
    buyer_profile: dict[str, Any] = field(default_factory=dict)
    pain_points: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    data_sources: list[str] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "business_type": self.business_type, "target_geo": self.target_geo,
            "buyer_profile": self.buyer_profile, "pain_points": self.pain_points,
            "triggers": self.triggers, "data_sources": self.data_sources,
            "generated_at": self.generated_at,
        }


@dataclass
class CustomerSegmentsResult:
    business_type: str
    segments: list[dict[str, Any]] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {"business_type": self.business_type, "segments": self.segments, "generated_at": self.generated_at}


@dataclass
class LeadStrategyResult:
    business_type: str
    lead_sources: list[str] = field(default_factory=list)
    outreach_channels: list[str] = field(default_factory=list)
    qualification_questions: list[str] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "business_type": self.business_type, "lead_sources": self.lead_sources,
            "outreach_channels": self.outreach_channels,
            "qualification_questions": self.qualification_questions,
            "generated_at": self.generated_at,
        }


@dataclass
class PublicityStrategyResult:
    business_type: str
    ad_angles: list[str] = field(default_factory=list)
    pr_angles: list[str] = field(default_factory=list)
    content_pillars: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "business_type": self.business_type, "ad_angles": self.ad_angles,
            "pr_angles": self.pr_angles, "content_pillars": self.content_pillars,
            "channels": self.channels, "generated_at": self.generated_at,
        }


@dataclass
class VerticalPlaybook:
    vertical: str
    buyer_profile: dict[str, Any] = field(default_factory=dict)
    pain_points: list[str] = field(default_factory=list)
    high_value_triggers: list[str] = field(default_factory=list)
    offer_angles: list[str] = field(default_factory=list)
    lead_sources: list[str] = field(default_factory=list)
    outreach_channels: list[str] = field(default_factory=list)
    ad_angles: list[str] = field(default_factory=list)
    landing_page_structure: list[str] = field(default_factory=list)
    qualification_questions: list[str] = field(default_factory=list)
    appointment_setting_logic: dict[str, Any] = field(default_factory=dict)
    monetization_model: dict[str, Any] = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "vertical": self.vertical, "buyer_profile": self.buyer_profile,
            "pain_points": self.pain_points, "high_value_triggers": self.high_value_triggers,
            "offer_angles": self.offer_angles, "lead_sources": self.lead_sources,
            "outreach_channels": self.outreach_channels, "ad_angles": self.ad_angles,
            "landing_page_structure": self.landing_page_structure,
            "qualification_questions": self.qualification_questions,
            "appointment_setting_logic": self.appointment_setting_logic,
            "monetization_model": self.monetization_model, "risks": self.risks,
            "generated_at": self.generated_at,
        }

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


def bound(value: Any, low: float = 0, high: float = 100) -> float:
    try:
        return max(low, min(float(value), high))
    except (TypeError, ValueError):
        return low


class ModelMixin:
    def to_dict(self) -> dict[str, Any]: return asdict(self)
    @classmethod
    def from_dict(cls, data: dict[str, Any]): return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})
    def to_markdown(self) -> str:
        title = getattr(self, "title", self.__class__.__name__)
        return f"# {title}\n\n```json\n{self.to_dict()}\n```\n\nAll creative material is a local, evidence-constrained draft. No ad was launched and no performance is predicted.\n"


@dataclass
class BuyerPsychologyMap(ModelMixin):
    map_id: str; workspace_id: str; product_name: str; category_name: str; opportunity_id: str = ""
    likely_buyer_segments: list[dict[str, Any]] = field(default_factory=list); primary_jobs_to_be_done: list[str] = field(default_factory=list); pain_points: list[str] = field(default_factory=list); desired_outcomes: list[str] = field(default_factory=list); anxieties: list[str] = field(default_factory=list); objections: list[str] = field(default_factory=list); buying_triggers: list[str] = field(default_factory=list); emotional_drivers: list[str] = field(default_factory=list); rational_drivers: list[str] = field(default_factory=list); trust_requirements: list[str] = field(default_factory=list); evidence_basis: list[dict[str, Any]] = field(default_factory=list); limitations: list[str] = field(default_factory=list); created_at: float = field(default_factory=time.time); metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CreativeAngle(ModelMixin):
    angle_id: str; workspace_id: str; product_name: str; category_name: str; opportunity_id: str; angle_type: str; title: str; premise: str; target_segment: str; buyer_motivation: str; primary_objection: str
    evidence_basis: list[dict[str, Any]] = field(default_factory=list); substantiation_level: str = "unsupported_hypothesis"; risk_level: str = "low"; prohibited_claims: list[str] = field(default_factory=list); safe_claims: list[str] = field(default_factory=list); recommended_formats: list[str] = field(default_factory=list); score: float = 0; confidence: float = 0; limitations: list[str] = field(default_factory=list); created_at: float = field(default_factory=time.time); metadata: dict[str, Any] = field(default_factory=dict)
    def __post_init__(self): self.score = bound(self.score); self.confidence = bound(self.confidence, 0, 1)


@dataclass
class CreativeHook(ModelMixin):
    hook_id: str; workspace_id: str; angle_id: str; hook_type: str; text: str; opening_visual: str; first_three_seconds: str
    claim_safety_status: str = "safe"; blocked_reasons: list[str] = field(default_factory=list); evidence_basis: list[dict[str, Any]] = field(default_factory=list); score: float = 0; confidence: float = 0; limitations: list[str] = field(default_factory=list); metadata: dict[str, Any] = field(default_factory=dict)
    def __post_init__(self): self.score = bound(self.score); self.confidence = bound(self.confidence, 0, 1)


@dataclass
class UGCBrief(ModelMixin):
    brief_id: str; workspace_id: str; product_name: str; category_name: str; opportunity_id: str; angle_id: str; title: str; creator_profile: str; scene_setup: str
    talking_points: list[str] = field(default_factory=list); visual_beats: list[str] = field(default_factory=list); demonstration_steps: list[str] = field(default_factory=list); do_say: list[str] = field(default_factory=list); do_not_say: list[str] = field(default_factory=list); required_disclosures: list[str] = field(default_factory=list); evidence_basis: list[dict[str, Any]] = field(default_factory=list); safety_notes: list[str] = field(default_factory=list); created_at: float = field(default_factory=time.time); metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StoryboardOutline(ModelMixin):
    storyboard_id: str; workspace_id: str; angle_id: str; hook_id: str; title: str; format: str
    beats: list[dict[str, Any]] = field(default_factory=list); primary_claims: list[str] = field(default_factory=list); proof_requirements: list[str] = field(default_factory=list); call_to_action: str = "Review this draft and collect substantiation before use."; safety_notes: list[str] = field(default_factory=list); evidence_basis: list[dict[str, Any]] = field(default_factory=list); created_at: float = field(default_factory=time.time); metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LandingPageClaimMap(ModelMixin):
    claim_map_id: str; workspace_id: str; product_name: str; category_name: str; opportunity_id: str
    hero_claims: list[dict[str, Any]] = field(default_factory=list); benefit_claims: list[dict[str, Any]] = field(default_factory=list); proof_blocks: list[dict[str, Any]] = field(default_factory=list); objection_blocks: list[dict[str, Any]] = field(default_factory=list); faq_blocks: list[dict[str, Any]] = field(default_factory=list); blocked_claims: list[dict[str, Any]] = field(default_factory=list); required_evidence: list[str] = field(default_factory=list); safety_notes: list[str] = field(default_factory=list); created_at: float = field(default_factory=time.time); metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CreativeTestMatrix(ModelMixin):
    matrix_id: str; workspace_id: str; product_name: str; category_name: str; opportunity_id: str
    hypotheses: list[dict[str, Any]] = field(default_factory=list); variants: list[dict[str, Any]] = field(default_factory=list); test_plan: list[dict[str, Any]] = field(default_factory=list); success_metrics: list[str] = field(default_factory=list); guardrail_metrics: list[str] = field(default_factory=list); minimum_evidence_needed: list[str] = field(default_factory=list); safety_notes: list[str] = field(default_factory=list); created_at: float = field(default_factory=time.time); metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CreativeIntelligenceReport(ModelMixin):
    report_id: str; workspace_id: str; product_name: str; category_name: str; opportunity_id: str; title: str; buyer_psychology_map_id: str
    angle_ids: list[str] = field(default_factory=list); hook_ids: list[str] = field(default_factory=list); ugc_brief_ids: list[str] = field(default_factory=list); storyboard_ids: list[str] = field(default_factory=list); landing_page_claim_map_id: str = ""; test_matrix_id: str = ""; summary: str = ""; top_angles: list[dict[str, Any]] = field(default_factory=list); top_hooks: list[dict[str, Any]] = field(default_factory=list); top_ugc_briefs: list[dict[str, Any]] = field(default_factory=list); major_risks: list[str] = field(default_factory=list); blocked_claims: list[str] = field(default_factory=list); missing_evidence: list[str] = field(default_factory=list); recommended_next_actions: list[str] = field(default_factory=list); confidence_score: float = 0; created_at: float = field(default_factory=time.time); metadata: dict[str, Any] = field(default_factory=dict)
    def __post_init__(self): self.confidence_score = bound(self.confidence_score, 0, 1)
    def to_markdown(self) -> str:
        return f"# {self.title}\n\n**Confidence:** `{self.confidence_score:.2f}`\n\n## Top angles\n\n" + "\n".join(f"- {x.get('title', x)}" for x in self.top_angles) + "\n\n## Missing proof\n\n" + "\n".join(f"- {x}" for x in self.missing_evidence) + "\n\nSafety: all creative artifacts are hypotheses/drafts. No ad was launched and no performance is predicted.\n"

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

STAGES = {"discovered", "evidence_requested", "evidence_enriched", "validation_ready", "launch_candidate", "rejected", "archived"}
RECOMMENDATIONS = {"prioritize", "investigate", "hold", "reject"}
TRANSITIONS = {"discovered": {"evidence_requested", "rejected", "archived"}, "evidence_requested": {"evidence_enriched", "rejected", "archived"}, "evidence_enriched": {"validation_ready", "rejected", "archived"}, "validation_ready": {"launch_candidate", "rejected", "archived"}, "launch_candidate": {"rejected", "archived"}, "rejected": {"archived"}, "archived": set()}

def _bound(value, low, high):
    try: return max(low, min(float(value), high))
    except (TypeError, ValueError): return low

@dataclass
class Opportunity:
    opportunity_id: str
    workspace_id: str
    opportunity_type: str
    name: str
    category_name: str
    stage: str = "discovered"
    recommendation: str = "investigate"
    score: float = 0.0
    confidence: float = 0.0
    evidence_ids: list[str] = field(default_factory=list)
    report_ids: list[str] = field(default_factory=list)
    gap_ids: list[str] = field(default_factory=list)
    acquisition_plan_ids: list[str] = field(default_factory=list)
    calibration_profile_ids: list[str] = field(default_factory=list)
    source_discovery_id: str = ""
    source_hypothesis_run_id: str = ""
    source_hypothesis_id: str = ""
    risk_flags: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    def __post_init__(self):
        if self.stage not in STAGES: self.stage = "discovered"
        if self.recommendation not in RECOMMENDATIONS: self.recommendation = "investigate"
        self.score, self.confidence = _bound(self.score, 0, 100), _bound(self.confidence, 0, 1)
    def to_dict(self): return {k: getattr(self, k) for k in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data): return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})
    def to_markdown(self):
        return f"# {self.name}\n\n**Stage:** `{self.stage}`  \n**Recommendation:** `{self.recommendation}`  \n**Score:** `{self.score:.1f}`  \n**Confidence:** `{self.confidence:.2f}`\n\n## Evidence\n\n- Evidence IDs: {', '.join(self.evidence_ids) or 'none'}\n- Missing: {', '.join(self.missing_evidence) or 'none'}\n\n## Next actions\n\n" + "\n".join(f"- {x}" for x in self.next_actions) + "\n\nThis is a read-only research/planning opportunity. `launch_candidate` never authorizes live execution.\n"

@dataclass
class OpportunityStageTransition:
    transition_id: str
    opportunity_id: str
    workspace_id: str
    from_stage: str
    to_stage: str
    decision: str
    reason: str
    gate_results: dict[str, Any] = field(default_factory=dict)
    evidence_ids: list[str] = field(default_factory=list)
    report_ids: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self): return {k: getattr(self, k) for k in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data): return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})

@dataclass
class OpportunityPipelineSnapshot:
    snapshot_id: str
    workspace_id: str
    title: str
    opportunities: list[Opportunity] = field(default_factory=list)
    stage_counts: dict[str, int] = field(default_factory=dict)
    top_opportunities: list[dict[str, Any]] = field(default_factory=list)
    blocked_opportunities: list[dict[str, Any]] = field(default_factory=list)
    rejected_opportunities: list[dict[str, Any]] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self): return {k: [x.to_dict() for x in v] if k == "opportunities" else v for k, v in ((k, getattr(self, k)) for k in self.__dataclass_fields__)}
    @classmethod
    def from_dict(cls, data):
        data = dict(data); data["opportunities"] = [Opportunity.from_dict(x) for x in data.get("opportunities", [])]
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})
    def to_markdown(self):
        rows = "\n".join(f"- **{x.get('name')}** — `{x.get('stage')}` — {x.get('score', 0):.1f}" for x in self.top_opportunities) or "- No opportunities."
        return f"# {self.title}\n\n## Stage counts\n\n```json\n{self.stage_counts}\n```\n\n## Top opportunities\n\n{rows}\n\n## Next actions\n\n" + "\n".join(f"- {x}" for x in self.next_actions) + "\n\n`launch_candidate` is planning-only and never authorizes live execution.\n"

def stable_opportunity_id(workspace_id, kind, name, source=""):
    return "opportunity_" + uuid.uuid5(uuid.NAMESPACE_URL, f"{workspace_id}:{kind}:{name.strip().lower()}:{source}").hex[:16]

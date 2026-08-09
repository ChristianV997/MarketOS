from __future__ import annotations
import time, uuid
from dataclasses import dataclass, field
from typing import Any

def _b(v, lo, hi):
    try: return max(lo, min(float(v), hi))
    except (TypeError, ValueError): return lo

@dataclass
class ValidationSprintTarget:
    target_id: str; opportunity_id: str; opportunity_type: str; name: str; category_name: str; starting_stage: str
    service_plan: list[str] = field(default_factory=list); evidence_ids: list[str] = field(default_factory=list); report_ids: list[str] = field(default_factory=list); metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self): return {k:getattr(self,k) for k in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls,d): return cls(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})

@dataclass
class ValidationServiceResult:
    result_id: str; opportunity_id: str; service_name: str; status: str = "skipped"; report_id: str = ""; score_contribution: float = 0.0
    findings: list[dict[str, Any]] = field(default_factory=list); recommendations: list[str] = field(default_factory=list); risk_flags: list[str] = field(default_factory=list); missing_evidence: list[str] = field(default_factory=list); blocked_reasons: list[str] = field(default_factory=list); metadata: dict[str, Any] = field(default_factory=dict)
    def __post_init__(self): self.score_contribution=_b(self.score_contribution,-100,100)
    def to_dict(self): return {k:getattr(self,k) for k in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls,d): return cls(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})

@dataclass
class ValidationScorecard:
    scorecard_id: str; opportunity_id: str; opportunity_name: str; category_name: str; validation_score: float = 0.0; confidence: float = 0.0; recommendation: str = "keep_validating"
    service_results: list[ValidationServiceResult] = field(default_factory=list); passed_checks: list[str] = field(default_factory=list); failed_checks: list[str] = field(default_factory=list); risk_flags: list[str] = field(default_factory=list); missing_evidence: list[str] = field(default_factory=list); next_actions: list[str] = field(default_factory=list); transition_recommendation: str = "validation_ready"; metadata: dict[str, Any] = field(default_factory=dict)
    def __post_init__(self): self.validation_score=_b(self.validation_score,0,100); self.confidence=_b(self.confidence,0,1)
    def to_dict(self): return {k:[x.to_dict() for x in v] if k=="service_results" else v for k,v in ((k,getattr(self,k)) for k in self.__dataclass_fields__)}
    @classmethod
    def from_dict(cls,d):
        d=dict(d); d["service_results"]=[ValidationServiceResult.from_dict(x) for x in d.get("service_results",[])]; return cls(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})
    def to_markdown(self): return f"# Validation scorecard: {self.opportunity_name}\n\n**Score:** `{self.validation_score:.1f}`  \n**Confidence:** `{self.confidence:.2f}`  \n**Recommendation:** `{self.recommendation}`  \n**Transition:** `{self.transition_recommendation}`\n\n## Passed checks\n\n"+"\n".join(f"- {x}" for x in self.passed_checks)+"\n\n## Failed checks\n\n"+"\n".join(f"- {x}" for x in self.failed_checks)+"\n\nThis is a dry-run planning artifact. It never authorizes live launch or external mutation.\n"

@dataclass
class ValidationSprint:
    sprint_id: str; workspace_id: str; title: str; objective: str; status: str = "created"; targets: list[ValidationSprintTarget] = field(default_factory=list); scorecards: list[ValidationScorecard] = field(default_factory=list); report_ids: list[str] = field(default_factory=list); portfolio_report_id: str = ""; created_at: float = field(default_factory=time.time); finished_at: float|None = None; blocked_reasons: list[str] = field(default_factory=list); metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self): return {k:[x.to_dict() for x in v] if k in {"targets","scorecards"} else v for k,v in ((k,getattr(self,k)) for k in self.__dataclass_fields__)}
    @classmethod
    def from_dict(cls,d):
        d=dict(d); d["targets"]=[ValidationSprintTarget.from_dict(x) for x in d.get("targets",[])]; d["scorecards"]=[ValidationScorecard.from_dict(x) for x in d.get("scorecards",[])]; return cls(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})
    def to_markdown(self): return f"# {self.title}\n\n**Status:** `{self.status}`  \n**Objective:** {self.objective}\n\n## Targets\n\n"+"\n".join(f"- **{x.name}**: {', '.join(x.service_plan)}" for x in self.targets)+"\n\n## Scorecards\n\n"+"\n".join(f"- {x.opportunity_name}: `{x.validation_score:.1f}` — `{x.recommendation}`" for x in self.scorecards)+"\n\nThis sprint is dry-run and planning-only. No live ads, orders, messages, payments, publishing, or commerce mutation are performed.\n"

def stable_sprint_id(workspace_id, title): return "sprint_"+uuid.uuid5(uuid.NAMESPACE_URL,f"{workspace_id}:{title}:{time.time_ns()}").hex[:16]

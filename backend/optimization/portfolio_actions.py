from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

ACTION_TYPES = {"acquire_evidence", "run_refinement_cycle", "refresh_pipeline", "run_validation_sprint", "generate_deliverable", "run_source_calibration", "resolve_risk", "hold_opportunity", "reject_opportunity", "advance_planning", "run_executive_cycle"}
ACTION_STATUSES = {"candidate", "recommended", "blocked", "selected", "simulated", "completed", "dismissed"}


def _bound(value: Any, low: float, high: float) -> float:
    try:
        return max(low, min(float(value), high))
    except (TypeError, ValueError):
        return low


@dataclass
class PortfolioAction:
    action_id: str
    workspace_id: str
    action_type: str
    title: str
    description: str
    related_opportunity_ids: list[str] = field(default_factory=list)
    related_gap_ids: list[str] = field(default_factory=list)
    related_acquisition_plan_ids: list[str] = field(default_factory=list)
    related_priority_ids: list[str] = field(default_factory=list)
    related_workflow_ids: list[str] = field(default_factory=list)
    estimated_cost: float = 0.0
    estimated_hours: float = 0.0
    expected_information_gain: float = 0.0
    expected_confidence_delta: float = 0.0
    expected_risk_reduction: float = 0.0
    expected_portfolio_value_delta: float = 0.0
    feasibility_score: float = 0.0
    risk_score: float = 0.0
    urgency_score: float = 0.0
    leverage_score: float = 0.0
    confidence_score: float = 0.0
    total_action_score: float = 0.0
    blocked_reasons: list[str] = field(default_factory=list)
    required_inputs: list[str] = field(default_factory=list)
    safe_endpoint: str = ""
    safe_payload: dict[str, Any] = field(default_factory=dict)
    status: str = "candidate"
    rationale: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.action_type not in ACTION_TYPES:
            self.action_type = "resolve_risk"
        if self.status not in ACTION_STATUSES:
            self.status = "candidate"
        for field_name in ("expected_information_gain", "expected_confidence_delta", "expected_risk_reduction", "expected_portfolio_value_delta", "feasibility_score", "risk_score", "urgency_score", "leverage_score", "confidence_score", "total_action_score"):
            setattr(self, field_name, _bound(getattr(self, field_name), 0, 100))
        self.estimated_cost = max(0.0, _bound(self.estimated_cost, 0, 1_000_000))
        self.estimated_hours = max(0.0, _bound(self.estimated_hours, 0, 10_000))

    def to_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PortfolioAction":
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass
class PortfolioActionSet:
    action_set_id: str
    workspace_id: str
    title: str
    objective: str
    actions: list[PortfolioAction] = field(default_factory=list)
    blocked_actions: list[PortfolioAction] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {key: [item.to_dict() for item in value] if key in {"actions", "blocked_actions"} else value for key, value in ((key, getattr(self, key)) for key in self.__dataclass_fields__)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PortfolioActionSet":
        data = dict(data)
        data["actions"] = [PortfolioAction.from_dict(item) for item in data.get("actions", [])]
        data["blocked_actions"] = [PortfolioAction.from_dict(item) for item in data.get("blocked_actions", [])]
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})

    def to_markdown(self) -> str:
        rows = "\n".join(f"- **{item.title}** — `{item.action_type}` — score `{item.total_action_score:.1f}` — simulated cost `${item.estimated_cost:.2f}`, `{item.estimated_hours:.1f}h`" for item in self.actions) or "- No unblocked actions."
        blocked = "\n".join(f"- **{item.title}** — {', '.join(item.blocked_reasons)}" for item in self.blocked_actions) or "- None."
        return f"# {self.title}\n\n{self.objective}\n\n## Actions\n\n{rows}\n\n## Blocked actions\n\n{blocked}\n\nAll costs and actions are simulated planning assumptions. No live budget is allocated.\n"

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .portfolio_actions import PortfolioAction

OBJECTIVES = {"maximize_information_gain", "maximize_confidence", "minimize_cost", "reduce_risk", "prepare_deliverables", "balanced"}
RISK_TOLERANCES = {"low", "medium", "high"}


def _bound(value: Any, low: float, high: float) -> float:
    try:
        return max(low, min(float(value), high))
    except (TypeError, ValueError):
        return low


@dataclass
class ResourceConstraint:
    constraint_id: str
    budget: float
    hours: float
    max_actions: int
    objective: str = "balanced"
    risk_tolerance: str = "medium"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.budget = max(0.0, _bound(self.budget, 0, 1_000_000_000))
        self.hours = max(0.0, _bound(self.hours, 0, 100_000))
        self.max_actions = max(0, min(int(self.max_actions), 200))
        if self.objective not in OBJECTIVES:
            self.objective = "balanced"
        if self.risk_tolerance not in RISK_TOLERANCES:
            self.risk_tolerance = "medium"

    def to_dict(self):
        return {key: getattr(self, key) for key in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data):
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass
class OptimizationScenario:
    scenario_id: str
    workspace_id: str
    title: str
    constraint: ResourceConstraint
    selected_action_ids: list[str] = field(default_factory=list)
    rejected_action_ids: list[str] = field(default_factory=list)
    blocked_action_ids: list[str] = field(default_factory=list)
    total_simulated_cost: float = 0.0
    total_estimated_hours: float = 0.0
    total_expected_information_gain: float = 0.0
    total_expected_confidence_delta: float = 0.0
    total_expected_risk_reduction: float = 0.0
    portfolio_projection: dict[str, Any] = field(default_factory=dict)
    rationale: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {key: value.to_dict() if key == "constraint" else value for key, value in ((key, getattr(self, key)) for key in self.__dataclass_fields__)}

    @classmethod
    def from_dict(cls, data):
        data = dict(data); data["constraint"] = ResourceConstraint.from_dict(data.get("constraint", {}))
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass
class PortfolioOptimizationPlan:
    optimization_id: str
    workspace_id: str
    title: str
    objective: str
    action_set_id: str
    scenarios: list[OptimizationScenario] = field(default_factory=list)
    recommended_scenario_id: str = ""
    recommended_actions: list[PortfolioAction] = field(default_factory=list)
    blocked_actions: list[PortfolioAction] = field(default_factory=list)
    summary: str = ""
    next_actions: list[str] = field(default_factory=list)
    safety_notes: list[str] = field(default_factory=lambda: ["Simulated-only planning; no real budget or capital is allocated."])
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {key: [item.to_dict() for item in value] if key == "scenarios" else [item.to_dict() for item in value] if key in {"recommended_actions", "blocked_actions"} else value for key, value in ((key, getattr(self, key)) for key in self.__dataclass_fields__)}

    @classmethod
    def from_dict(cls, data):
        data = dict(data); data["scenarios"] = [OptimizationScenario.from_dict(item) for item in data.get("scenarios", [])]; data["recommended_actions"] = [PortfolioAction.from_dict(item) for item in data.get("recommended_actions", [])]; data["blocked_actions"] = [PortfolioAction.from_dict(item) for item in data.get("blocked_actions", [])]
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})

    def to_markdown(self):
        scenarios = "\n".join(f"- **{item.title}** — `${item.total_simulated_cost:.2f}`, `{item.total_estimated_hours:.1f}h`, information gain `{item.total_expected_information_gain:.1f}`" for item in self.scenarios) or "- None."
        actions = "\n".join(f"- {item.title}: {item.description}" for item in self.recommended_actions) or "- None."
        return f"# {self.title}\n\n{self.summary}\n\n## Simulated scenarios\n\n{scenarios}\n\n## Recommended actions\n\n{actions}\n\n## Safety\n\n" + "\n".join(f"- {note}" for note in self.safety_notes) + "\n"

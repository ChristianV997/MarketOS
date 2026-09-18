"""Simulation report record."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class SimulationReport:
    schema: str
    experiment_id: str
    classification: str
    lifecycle_state: str
    input_valid: bool
    scenario_assumptions: tuple[str, ...]
    metric_definitions: Mapping[str, str]
    stop_condition_evaluation: str
    blocked_reasons: tuple[str, ...]
    next_action: str
    replay_hash: str
    live_action_allowed: bool
    planning_currency: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "experiment_id": self.experiment_id,
            "classification": self.classification,
            "lifecycle_state": self.lifecycle_state,
            "input_valid": self.input_valid,
            "scenario_assumptions": list(self.scenario_assumptions),
            "metric_definitions": dict(self.metric_definitions),
            "stop_condition_evaluation": self.stop_condition_evaluation,
            "blocked_reasons": list(self.blocked_reasons),
            "next_action": self.next_action,
            "replay_hash": self.replay_hash,
            "live_action_allowed": False,
            "planning_currency": self.planning_currency,
            "claimed_real_performance": False,
        }

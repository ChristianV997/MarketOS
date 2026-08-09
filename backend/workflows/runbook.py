from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowRunbook:
    runbook_id: str
    workflow_type: str
    title: str
    purpose: str
    stages: list[str]
    required_inputs: list[str] = field(default_factory=list)
    optional_inputs: list[str] = field(default_factory=list)
    safety_constraints: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    failure_modes: list[str] = field(default_factory=list)
    recovery_steps: list[str] = field(default_factory=list)
    created_at: float = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {key: getattr(self, key) for key in self.__dataclass_fields__}

    def to_markdown(self):
        return (
            f"# {self.title}\n\n{self.purpose}\n\n"
            "## Stages\n\n"
            + "\n".join(f"- {stage}" for stage in self.stages)
            + "\n\n## Safety\n\n"
            + "\n".join(f"- {item}" for item in self.safety_constraints)
            + "\n\n## Recovery\n\n"
            + "\n".join(f"- {item}" for item in self.recovery_steps)
        )


_STAGES = {
    "full_market_cycle": ["import_evidence", "market_discovery", "refinement_cycle", "acquisition_planning", "opportunity_pipeline_refresh", "source_calibration", "validation_sprint", "deliverable_package", "executive_intelligence", "portfolio_optimization", "final_summary"],
    "import_discovery_cycle": ["import_evidence", "market_discovery", "final_summary"],
    "discovery_refinement_cycle": ["market_discovery", "refinement_cycle", "acquisition_planning", "final_summary"],
    "validation_deliverable_cycle": ["opportunity_pipeline_refresh", "validation_sprint", "deliverable_package", "final_summary"],
    "executive_intelligence_cycle": ["executive_intelligence", "final_summary"],
    "portfolio_optimization_cycle": ["opportunity_pipeline_refresh", "source_calibration", "portfolio_optimization", "executive_intelligence", "final_summary"],
}


def get_workflow_runbook(workflow_type: str) -> WorkflowRunbook:
    if workflow_type not in _STAGES:
        raise ValueError("unsupported_workflow_type")
    return WorkflowRunbook(
        f"runbook_{workflow_type}",
        workflow_type,
        workflow_type.replace("_", " ").title(),
        "Run safe local/cache-only MarketOS stages.",
        list(_STAGES[workflow_type]),
        optional_inputs=["local dataset paths", "manual export paths"],
        safety_constraints=["No live flags, external URLs, or mutation payloads."],
        expected_outputs=["persisted registry IDs", "checkpoints", "summary"],
        failure_modes=["missing evidence", "unavailable service", "blocked safety"],
        recovery_steps=["Resume from a recoverable checkpoint.", "Replay only a safe replayable stage."],
    )


def list_workflow_runbooks():
    return [get_workflow_runbook(workflow_type) for workflow_type in _STAGES]

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .source_playbooks import get_source_playbook


@dataclass
class EvidenceAcquisitionStep:
    step_id: str
    order: int
    title: str
    instruction: str
    expected_output: str
    parser_type: str
    required_fields: list[str] = field(default_factory=list)
    optional_fields: list[str] = field(default_factory=list)
    safety_notes: list[str] = field(default_factory=list)
    verification_checks: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self): return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data): return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass
class EvidenceAcquisitionPlan:
    plan_id: str
    workspace_id: str
    source_name: str
    parser_type: str
    title: str
    objective: str
    priority_score: float
    expected_signal_types: list[str] = field(default_factory=list)
    related_gap_ids: list[str] = field(default_factory=list)
    related_recommendation_ids: list[str] = field(default_factory=list)
    steps: list[EvidenceAcquisitionStep] = field(default_factory=list)
    template_paths: list[str] = field(default_factory=list)
    connector_stub_name: str = ""
    current_mode: str = "manual_export_only"
    status: str = "drafted"
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    def __post_init__(self): self.priority_score = max(0.0, min(float(self.priority_score), 100.0))
    def to_dict(self): return {key: [step.to_dict() for step in value] if key == "steps" else value for key, value in ((key, getattr(self, key)) for key in self.__dataclass_fields__)}
    @classmethod
    def from_dict(cls, data):
        data = dict(data); data["steps"] = [EvidenceAcquisitionStep.from_dict(x) for x in data.get("steps", [])]; return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})
    def to_markdown(self):
        steps = "\n".join(f"{step.order}. **{step.title}** — {step.instruction}\n   - Expected: {step.expected_output}\n   - Verify: {'; '.join(step.verification_checks)}" for step in self.steps)
        return f"# {self.title}\n\n**Mode:** `{self.current_mode}`  \n**Status:** `{self.status}`  \n**Parser:** `{self.parser_type}`  \n**Priority:** `{self.priority_score:.1f}`\n\n{self.objective}\n\n## Expected signals\n\n{', '.join(self.expected_signal_types)}\n\n## Manual acquisition steps\n\n{steps}\n\n## Schema\n\nRequired: `{', '.join(self.steps[0].required_fields if self.steps else [])}`  \nOptional: `{', '.join(self.steps[0].optional_fields if self.steps else [])}`\n\n## Template paths\n\n{', '.join(self.template_paths) or 'No template generated.'}\n\n## Safety\n\nThis plan is manual/cache-only. The connector stub is disabled and non-executable.\n"


def build_acquisition_plan_from_recommendation(recommendation, workspace_id: str = "default") -> EvidenceAcquisitionPlan:
    playbook = get_source_playbook(recommendation.parser_type); stub = recommendation.parser_type.replace("_csv", "") + "_export_connector"
    steps = [EvidenceAcquisitionStep(f"step_{uuid.uuid5(uuid.NAMESPACE_URL, recommendation.parser_type).hex[:12]}", 1, "Prepare an authorized local export", "Use the source-specific manual instructions and place the completed CSV under the approved project data/imports path.", "A documented local CSV with provenance", recommendation.parser_type, playbook["required_fields"], playbook["optional_fields"], playbook["safety_notes"], playbook["verification_checks"]), EvidenceAcquisitionStep(f"step_{uuid.uuid5(uuid.NAMESPACE_URL, recommendation.parser_type + ':import').hex[:12]}", 2, "Verify and import", "Check required columns, remove secrets/PII, record provenance, then run the cache-only import endpoint.", "Normalized EvidenceRecord objects", recommendation.parser_type, playbook["required_fields"], playbook["optional_fields"], playbook["safety_notes"], playbook["verification_checks"])]
    return EvidenceAcquisitionPlan("acquisition_" + uuid.uuid5(uuid.NAMESPACE_URL, f"{workspace_id}:{recommendation.parser_type}").hex[:16], workspace_id, recommendation.source_name_suggestion, recommendation.parser_type, playbook["title"], recommendation.reason, recommendation.priority_score, playbook["expected_signal_types"], recommendation.related_gap_ids, [recommendation.recommendation_id], steps, [recommendation.template_path], stub, "manual_export_only", "ready_for_manual_export", metadata={"invalid_claims": playbook["invalid_claims"], "no_live_calls": True})


def build_acquisition_plans_from_import_plan(import_plan, workspace_id: str = "default") -> list[EvidenceAcquisitionPlan]:
    return [build_acquisition_plan_from_recommendation(item, workspace_id) for item in import_plan.recommendations]

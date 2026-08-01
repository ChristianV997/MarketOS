"""backend.experiments.envelope — CommercialRunEnvelope, the durable
run/experiment record for every commercial action a service module takes.

Subclasses BaseArtifact (backend/contracts/base.py) rather than inventing a
parallel artifact system — it gets artifact_id/workspace/parent_ids/
replay_hash/.to_dict()/.from_dict() for free and can register into the
existing ArtifactRegistry (backend/contracts/registry.py) instead of a
second in-memory store. `workspace` (BaseArtifact's lineage-namespace field,
default "default") is set equal to `workspace_id` at construction so other
artifact types' existing default usage is unaffected while this one also
carries real tenant meaning.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from backend.contracts.base import BaseArtifact

ARTIFACT_TYPE = "commercial_run_envelope"

STATUSES = ("created", "running", "completed", "blocked", "failed")


@dataclass
class CommercialRunEnvelope(BaseArtifact):
    artifact_type: str = field(default=ARTIFACT_TYPE)
    experiment_id: str = ""
    service_name: str = ""
    workspace_id: str = ""
    mode: str = "dry_run"
    status: str = "created"
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    proposed_spend: float = 0.0
    actual_spend: float = 0.0
    audit_log_refs: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)
    started_at: float | None = None
    finished_at: float | None = None

    def __post_init__(self) -> None:
        if self.workspace_id and self.workspace == "default":
            self.workspace = self.workspace_id
        super().__post_init__()
        if not self.experiment_id:
            self.experiment_id = self.artifact_id

    def mark_running(self) -> None:
        self.status = "running"
        self.started_at = self.started_at or time.time()

    def mark_completed(self, outputs: dict[str, Any]) -> None:
        self.status = "completed"
        self.outputs = outputs
        self.finished_at = time.time()

    def mark_blocked(self, reasons: list[str]) -> None:
        self.status = "blocked"
        self.blocked_reasons = list(reasons)
        self.finished_at = time.time()

    def mark_failed(self, reason: str) -> None:
        self.status = "failed"
        self.blocked_reasons = [reason]
        self.finished_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({
            "experiment_id": self.experiment_id,
            "service_name": self.service_name,
            "workspace_id": self.workspace_id,
            "mode": self.mode,
            "status": self.status,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "proposed_spend": round(self.proposed_spend, 2),
            "actual_spend": round(self.actual_spend, 2),
            "audit_log_refs": list(self.audit_log_refs),
            "blocked_reasons": list(self.blocked_reasons),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        })
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CommercialRunEnvelope":
        return cls(
            artifact_id=d.get("artifact_id", ""),
            artifact_type=d.get("artifact_type", ARTIFACT_TYPE),
            workspace=d.get("workspace", "default"),
            parent_ids=list(d.get("parent_ids", [])),
            created_at=d.get("created_at", time.time()),
            schema_version=d.get("schema_version", 1),
            metadata=dict(d.get("metadata", {})),
            replay_hash=d.get("replay_hash", ""),
            experiment_id=d.get("experiment_id", ""),
            service_name=d.get("service_name", ""),
            workspace_id=d.get("workspace_id", ""),
            mode=d.get("mode", "dry_run"),
            status=d.get("status", "created"),
            inputs=dict(d.get("inputs", {})),
            outputs=dict(d.get("outputs", {})),
            proposed_spend=d.get("proposed_spend", 0.0),
            actual_spend=d.get("actual_spend", 0.0),
            audit_log_refs=list(d.get("audit_log_refs", [])),
            blocked_reasons=list(d.get("blocked_reasons", [])),
            started_at=d.get("started_at"),
            finished_at=d.get("finished_at"),
        )

"""services.customer_intelligence.sprint — build_customer_intelligence_sprint,
the top-level entrypoint tying icp/segments/lead_strategy/publicity/vertical-
playbook together into one CommercialRunEnvelope-backed result."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from backend.experiments.audit_log import log_transition
from backend.experiments.envelope import CommercialRunEnvelope
from backend.experiments.registry import get_experiment_registry
from backend.workspaces.artifact_store import ArtifactStore
from backend.workspaces.client_workspace import ClientWorkspace

from .icp import generate_customer_segments, generate_icp
from .lead_strategy import build_lead_strategy
from .publicity_plan import build_publicity_strategy
from .vertical_playbooks import build_vertical_playbook

SERVICE_NAME = "customer_intelligence"


@dataclass
class CustomerIntelligenceSprint:
    business_type: str
    vertical: str | None
    icp: dict[str, Any] = field(default_factory=dict)
    segments: dict[str, Any] = field(default_factory=dict)
    lead_strategy: dict[str, Any] = field(default_factory=dict)
    publicity_strategy: dict[str, Any] = field(default_factory=dict)
    vertical_playbook: dict[str, Any] | None = None
    dry_run: bool = True
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "business_type": self.business_type, "vertical": self.vertical,
            "icp": self.icp, "segments": self.segments, "lead_strategy": self.lead_strategy,
            "publicity_strategy": self.publicity_strategy, "vertical_playbook": self.vertical_playbook,
            "dry_run": self.dry_run, "generated_at": self.generated_at,
        }


def _default_workspace() -> ClientWorkspace:
    return ClientWorkspace(name="ephemeral", workspace_type="internal")


def build_customer_intelligence_sprint(
    business_type: str,
    *,
    vertical: str | None = None,
    target_geo: str = "MX",
    category: str = "general",
    workspace: ClientWorkspace | None = None,
) -> tuple[CustomerIntelligenceSprint, CommercialRunEnvelope]:
    """Never raises."""
    workspace = workspace or _default_workspace()
    registry = get_experiment_registry()
    store = ArtifactStore()

    envelope = CommercialRunEnvelope(
        service_name=SERVICE_NAME,
        workspace_id=workspace.workspace_id,
        mode="dry_run" if workspace.dry_run_default else workspace.mode,
        inputs={"business_type": business_type, "vertical": vertical, "target_geo": target_geo},
    )
    registry.register(envelope)
    log_transition(envelope, "experiment_created")
    envelope.mark_running()

    icp = generate_icp(business_type, target_geo=target_geo, category=category)
    segments = generate_customer_segments(business_type, icp=icp)
    lead_strategy = build_lead_strategy(business_type)
    publicity = build_publicity_strategy(business_type, icp=icp)
    playbook = build_vertical_playbook(vertical).to_dict() if vertical else None

    result = CustomerIntelligenceSprint(
        business_type=business_type, vertical=vertical,
        icp=icp.to_dict(), segments=segments.to_dict(),
        lead_strategy=lead_strategy.to_dict(), publicity_strategy=publicity.to_dict(),
        vertical_playbook=playbook, dry_run=workspace.dry_run_default,
    )

    store.save(workspace.workspace_id, envelope.experiment_id, "result.json", result.to_dict())
    envelope.mark_completed(result.to_dict())
    log_transition(envelope, "experiment_completed")

    return result, envelope

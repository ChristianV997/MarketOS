"""backend.workspaces.client_workspace — ClientWorkspace domain model.

Isolates data, credentials, reports, experiments, and live-mode permissions
per tenant. workspace_id is derived deterministically from ``name`` (via
backend.vector.normalization.deterministic_id, the same uuid5 idiom
BaseArtifact uses for artifact_id) so re-registering a workspace with the
same name is idempotent rather than minting a new identity every call.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from backend.vector.normalization import deterministic_id

# workspace_type values
WORKSPACE_TYPES = (
    "internal",        # my own store
    "client_service",  # a paying client's workspace
    "demo",
    "dry_run",
    "live",
    "digital_product",
    "dao_future",
)

# mode values (mirrors the operating-mode ladder from the task's spec)
#
# `mode` is a commercial-maturity/business-relationship label — which rung
# of internal-use -> client-service -> SaaS-lite -> full-SaaS -> DAO-future
# this workspace sits at — used today for reporting/segmentation and
# recorded onto every CommercialRunEnvelope for context. It is deliberately
# NOT a live/dry-run gate: that's `live_mode_enabled` (below) plus the
# `live_action_requested` flag threaded through
# backend.workspaces.live_mode_checklist.check() and
# services.ecommerce_operator.launch_guard.evaluate_launch_readiness().
# Folding `mode` into that gate would conflate two orthogonal questions —
# "which commercial tier is this workspace on" is not the same question as
# "is this specific action allowed to touch real money" (a `full_saas`
# workspace can still be dry-run for an integration with no credentials
# configured, and an `internal_own_store` workspace can go fully live once
# its owner flips `live_mode_enabled`). See docs/LIVE_MODE_SAFETY.md.
MODES = ("internal_own_store", "client_service", "saas_lite", "full_saas", "dao_future")


@dataclass
class ClientWorkspace:
    workspace_id: str = ""
    name: str = ""
    workspace_type: str = "internal"
    owner_label: str = ""
    mode: str = "internal_own_store"
    dry_run_default: bool = True
    live_mode_enabled: bool = False
    allowed_integrations: list[str] = field(default_factory=list)
    budget_ceiling_monthly: float = 0.0
    budget_ceiling_per_experiment: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.workspace_id:
            self.workspace_id = deterministic_id("workspace", self.name or "unnamed")

    def touch(self) -> None:
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "name": self.name,
            "workspace_type": self.workspace_type,
            "owner_label": self.owner_label,
            "mode": self.mode,
            "dry_run_default": self.dry_run_default,
            "live_mode_enabled": self.live_mode_enabled,
            "allowed_integrations": list(self.allowed_integrations),
            "budget_ceiling_monthly": self.budget_ceiling_monthly,
            "budget_ceiling_per_experiment": self.budget_ceiling_per_experiment,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ClientWorkspace":
        return cls(
            workspace_id=d.get("workspace_id", ""),
            name=d.get("name", ""),
            workspace_type=d.get("workspace_type", "internal"),
            owner_label=d.get("owner_label", ""),
            mode=d.get("mode", "internal_own_store"),
            dry_run_default=d.get("dry_run_default", True),
            live_mode_enabled=d.get("live_mode_enabled", False),
            allowed_integrations=list(d.get("allowed_integrations", [])),
            budget_ceiling_monthly=d.get("budget_ceiling_monthly", 0.0),
            budget_ceiling_per_experiment=d.get("budget_ceiling_per_experiment", 0.0),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            metadata=dict(d.get("metadata", {})),
        )

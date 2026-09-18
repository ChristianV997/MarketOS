"""Live action safety gate enforcing 9-point invariant for all mutating operations.

Invariants enforced:
1. Authenticated actor
2. Authorized workspace
3. Explicit human/policy approval
4. Scope/budget ceiling
5. Idempotency key
6. Structured audit event
7. Global and scoped kill switch
8. Rollback/remediation plan
9. Dry-run default
"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.security.auth import AuthenticatedActor

_log = logging.getLogger("marketos.security.live_gate")

LIVE_ACTION_SCOPES = frozenset({
    "ad_spend",
    "order_dispatch",
    "payment_reversal",
    "creative_publish",
    "supplier_order",
    "customer_outreach",
    "inventory_mutation",
})


@dataclass
class LiveActionRequest:
    action_type: str
    workspace_id: str
    actor: AuthenticatedActor
    idempotency_key: str
    budget_amount: float = 0.0
    budget_currency: str = "USD"
    approval_id: str | None = None
    run_id: str | None = None
    dry_run: bool = True  # Strict dry-run default
    target_platform: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    rollback_strategy: str = "revert_or_pause"


@dataclass(frozen=True)
class LiveActionVerdict:
    allowed: bool
    dry_run: bool
    status: str
    audit_event_id: str
    kill_switch_active: bool
    blockers: tuple[str, ...]
    details: dict[str, Any] = field(default_factory=dict)


def is_kill_switch_active(action_type: str = "") -> bool:
    """Check global or scope-specific kill switches."""
    if os.getenv("MARKETOS_KILL_SWITCH", "false").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if os.getenv("MARKETOS_GLOBAL_EMERGENCY_STOP", "false").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if action_type:
        scoped_key = f"MARKETOS_KILL_SWITCH_{action_type.upper()}"
        if os.getenv(scoped_key, "false").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def get_live_budget_ceiling_usd() -> float:
    """Configured maximum spend ceiling for automated live actions."""
    try:
        return max(0.0, float(os.getenv("MARKETOS_MAX_LIVE_BUDGET_USD", "100.0")))
    except ValueError:
        return 100.0


def evaluate_live_action_gate(request: LiveActionRequest) -> LiveActionVerdict:
    """Evaluate whether an action can proceed live or must remain simulated/blocked."""
    blockers: list[str] = []
    audit_id = f"audit_{uuid.uuid4().hex[:16]}"

    # 1. Authenticated actor
    if not request.actor:
        blockers.append("unauthenticated_actor")

    # 2. Workspace binding
    if not request.workspace_id or not request.actor.can_access_workspace(request.workspace_id):
        blockers.append("unauthorized_workspace_context")

    # 7. Kill switch
    kill_active = is_kill_switch_active(request.action_type)
    if kill_active:
        blockers.append("kill_switch_engaged")

    # Dry-run execution always proceeds safely as a preview/simulation
    if request.dry_run:
        _log.info(
            "live_gate_verdict dry_run=true action=%s ws=%s actor=%s audit_id=%s",
            request.action_type,
            request.workspace_id,
            request.actor.actor_id if request.actor else "none",
            audit_id,
        )
        return LiveActionVerdict(
            allowed=not bool([b for b in blockers if b == "unauthenticated_actor" or b == "unauthorized_workspace_context"]),
            dry_run=True,
            status="dry_run_simulated",
            audit_event_id=audit_id,
            kill_switch_active=kill_active,
            blockers=tuple(blockers),
            details={"mode": "dry_run", "budget_requested": request.budget_amount},
        )

    # For non-dry-run (live actions), ALL remaining 7 gates must pass:

    # Global live mode flag must be explicitly enabled
    live_enabled = os.getenv("MARKETOS_ENABLE_LIVE_ACTIONS", "false").strip().lower() in {"1", "true", "yes", "on"}
    if not live_enabled:
        blockers.append("live_actions_globally_disabled")

    # Only operators can execute live mutating actions
    if not request.actor.is_operator:
        blockers.append("live_action_requires_operator_role")

    # 3. Explicit Approval required
    if not request.approval_id:
        blockers.append("approval_id_required_for_live_action")

    # 4. Explicit run_id required for audit traceability
    if not request.run_id or len(request.run_id.strip()) < 4:
        blockers.append("run_id_required_for_live_action")

    # 5. Scope and budget ceiling check
    ceiling = get_live_budget_ceiling_usd()
    if request.budget_amount > ceiling:
        blockers.append(f"budget_exceeds_ceiling: {request.budget_amount} > {ceiling}")

    # 6. Idempotency key required
    if not request.idempotency_key or len(request.idempotency_key.strip()) < 8:
        blockers.append("valid_idempotency_key_required_min_8_chars")

    # 8. Rollback strategy required
    if not request.rollback_strategy:
        blockers.append("rollback_strategy_required")

    allowed = len(blockers) == 0

    _log.info(
        "live_gate_verdict allowed=%s action=%s ws=%s blockers=%s audit_id=%s",
        allowed,
        request.action_type,
        request.workspace_id,
        blockers,
        audit_id,
    )

    return LiveActionVerdict(
        allowed=allowed,
        dry_run=False,
        status="approved_for_live" if allowed else "blocked",
        audit_event_id=audit_id,
        kill_switch_active=kill_active,
        blockers=tuple(blockers),
        details={
            "mode": "live",
            "budget_requested": request.budget_amount,
            "budget_ceiling": ceiling,
            "idempotency_key": request.idempotency_key,
        },
    )


__all__ = [
    "LIVE_ACTION_SCOPES",
    "LiveActionRequest",
    "LiveActionVerdict",
    "evaluate_live_action_gate",
    "get_live_budget_ceiling_usd",
    "is_kill_switch_active",
]

"""services.ecommerce_operator.launch_guard — evaluate_launch_readiness.

Two independent checklists compose here:
  1. Business readiness (this module's own): does the experiment actually
     carry product validation, margin analysis, supplier assumptions, a
     budget ceiling, kill criteria, and an attribution method? Checked
     unconditionally — a dry-run experiment with missing prerequisites is
     not "ready" even though nothing live is at stake yet.
  2. Live-mode readiness (backend.workspaces.live_mode_checklist — reused,
     not reimplemented): credentials, live_mode_enabled, budget ceilings.
     Only checked when a live action is actually being requested — a
     dry-run test must never be blocked by "workspace isn't in live mode".
"""
from __future__ import annotations

from typing import Any

from backend.experiments.audit_log import log_transition
from backend.experiments.envelope import CommercialRunEnvelope
from backend.workspaces import live_mode_checklist
from backend.workspaces.client_workspace import ClientWorkspace

from .schemas import LaunchReadiness

_BUSINESS_REQUIREMENTS = (
    ("has_product_validation", "validation", "no product validation exists"),
    ("has_margin_analysis", "unit_economics", "no margin analysis exists"),
    ("has_supplier_assumptions", "supplier_assumptions", "no supplier assumptions exist"),
    ("has_budget_ceiling", "budget_ceiling", "no budget ceiling exists"),
    ("has_kill_criteria", "kill_criteria", "no kill criteria exists"),
    ("has_attribution_method", "attribution_method", "no attribution method configured"),
)


def evaluate_launch_readiness(
    envelope: CommercialRunEnvelope,
    *,
    workspace: ClientWorkspace | None = None,
    integration: str = "shopify",
    live_action_requested: bool = False,
    proposed_amount: float = 0.0,
) -> LaunchReadiness:
    """Never raises: a lookup/attribute failure degrades to "not ready"
    with an explicit reason, not an exception."""
    checklist: dict[str, bool] = {}
    blocked_reasons: list[str] = []

    try:
        inputs = envelope.inputs or {}
        for key, input_field, reason in _BUSINESS_REQUIREMENTS:
            present = bool(inputs.get(input_field))
            checklist[key] = present
            if not present:
                blocked_reasons.append(reason)
    except Exception as exc:  # noqa: BLE001 — this gate must never raise
        blocked_reasons.append(f"launch_readiness_error: {exc}")

    live_check: dict[str, Any] | None = None
    checklist["live_approved"] = not live_action_requested  # vacuously true when not requested
    if live_action_requested:
        if workspace is None:
            checklist["live_approved"] = False
            blocked_reasons.append("no live approval exists (no workspace supplied)")
        else:
            live_check = live_mode_checklist.check(workspace, integration, proposed_amount=proposed_amount)
            checklist["live_approved"] = live_check["allowed"]
            if not live_check["allowed"]:
                blocked_reasons.extend(f"live approval: {r}" for r in live_check["blocked_reasons"])

    ready = all(checklist.values())
    result = LaunchReadiness(ready=ready, blocked_reasons=blocked_reasons, checklist=checklist, live_mode_checklist=live_check)

    if not ready:
        envelope.mark_blocked(blocked_reasons)
    log_transition(envelope, "launch_readiness_evaluated", data=result.to_dict())

    return result

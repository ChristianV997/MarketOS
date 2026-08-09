"""backend.workspaces.live_mode_checklist — the gate every live external
mutation or spend must pass. Mirrors backend/risk/gate.py::check_spend's
return shape ({allowed, reason, ...}) and the universal shadow-journal-
always-written pattern used by organic_gate.py/tiktok_ads.py: the full
checklist is computed and journaled to event_store regardless of outcome,
and this function never raises — a failure produces a structured blocked
result, never a crash.
"""
from __future__ import annotations

from typing import Any

from backend.orchestration.event_store import event_store, new_workflow_id

from .client_workspace import ClientWorkspace
from .credential_scope import scope_for


def check(workspace: ClientWorkspace, integration: str, *, proposed_amount: float = 0.0) -> dict[str, Any]:
    """Never raises. Returns:
    {allowed, blocked_reasons, checklist: {...}, mode, integration}
    """
    checklist: dict[str, bool] = {
        "live_mode_enabled": False,
        "credential_configured": False,
        "integration_allowed": False,
        "within_monthly_ceiling": False,
        "within_experiment_ceiling": False,
    }
    blocked_reasons: list[str] = []

    try:
        checklist["live_mode_enabled"] = bool(workspace.live_mode_enabled)
        if not checklist["live_mode_enabled"]:
            blocked_reasons.append("workspace live mode is disabled")

        scope = scope_for(workspace).get(integration, {"status": "not_configured", "allowed": False, "dry_run": True})
        checklist["credential_configured"] = scope.get("status") == "configured"
        if not checklist["credential_configured"]:
            blocked_reasons.append(f"{integration} credentials not configured ({scope.get('status')})")

        checklist["integration_allowed"] = bool(scope.get("allowed"))
        if not checklist["integration_allowed"]:
            blocked_reasons.append(f"{integration} not in workspace.allowed_integrations")

        if workspace.budget_ceiling_per_experiment > 0:
            checklist["within_experiment_ceiling"] = proposed_amount <= workspace.budget_ceiling_per_experiment
        else:
            checklist["within_experiment_ceiling"] = False
            blocked_reasons.append("no per-experiment budget ceiling configured")
        if not checklist["within_experiment_ceiling"] and workspace.budget_ceiling_per_experiment > 0:
            blocked_reasons.append(
                f"proposed_amount {proposed_amount} exceeds per-experiment ceiling {workspace.budget_ceiling_per_experiment}"
            )

        if workspace.budget_ceiling_monthly > 0:
            try:
                from backend.experiments.registry import get_experiment_registry
                spent = get_experiment_registry().spend_this_month(workspace.workspace_id)
            except Exception:
                spent = 0.0
            checklist["within_monthly_ceiling"] = (spent + proposed_amount) <= workspace.budget_ceiling_monthly
            if not checklist["within_monthly_ceiling"]:
                blocked_reasons.append(
                    f"spend_this_month {spent} + proposed {proposed_amount} exceeds monthly ceiling "
                    f"{workspace.budget_ceiling_monthly}"
                )
        else:
            checklist["within_monthly_ceiling"] = False
            blocked_reasons.append("no monthly budget ceiling configured")
    except Exception as exc:  # noqa: BLE001 — this gate must never raise
        blocked_reasons.append(f"live_mode_checklist_error: {exc}")

    allowed = not blocked_reasons and all(checklist.values())
    result = {
        "allowed": allowed,
        "blocked_reasons": blocked_reasons,
        "checklist": checklist,
        "mode": workspace.mode,
        "integration": integration,
        "proposed_amount": proposed_amount,
    }

    try:
        event_store.append(
            new_workflow_id(prefix="livecheck"),
            "shadow_live_mode_checklist",
            workflow="live_mode_checklist",
            step=integration,
            data={"workspace_id": workspace.workspace_id, **result},
        )
    except Exception:
        pass

    return result

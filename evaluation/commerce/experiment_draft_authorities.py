"""Read-only references to Governor and Approval Ledger.

This module never creates a second budget or approval authority.
When the canonical modules are importable it records their outcomes.
When they are not, it labels the reference unavailable.
"""
from __future__ import annotations

from typing import Any, Mapping

GOVERNOR_ACTION = "launch_ad_experiment"
LEDGER_REQUEST_TYPE = "ad_launch"
GOVERNOR_RESOURCE = "ad_spend"


def _try_governor() -> Any:
    try:
        from evaluation.companyos.resource_execution_governor import (  # type: ignore
            ExecutionDecisionRequest,
            evaluate_execution_request,
        )
    except Exception:
        return None
    return ExecutionDecisionRequest, evaluate_execution_request


def _try_ledger() -> Any:
    try:
        from evaluation.companyos.approval_ledger import REQUEST_TYPES, LIVE_ACTION_TYPES  # type: ignore
    except Exception:
        return None
    return REQUEST_TYPES, LIVE_ACTION_TYPES


def reference_governor(*, workspace_id: str, budget_cap: str, approval_state: str, hypothesis: str, success_metric: str) -> dict[str, Any]:
    imported = _try_governor()
    if imported is None:
        return {
            "authority": "evaluation.companyos.resource_execution_governor",
            "status": "unavailable",
            "action_referenced": GOVERNOR_ACTION,
            "resource_type": GOVERNOR_RESOURCE,
            "simulated_only": True,
            "live_action_allowed": False,
            "note": "Governor module not importable in this worktree; cap compared locally only.",
        }
    request_cls, evaluate = imported
    try:
        amount = float(budget_cap or 0)
    except ValueError:
        amount = 0.0
    request = request_cls(
        request_id="experiment-draft-governor-ref",
        action_type=GOVERNOR_ACTION,
        domain="ads_content",
        owner_department="consumer_attention",
        workspace_id=workspace_id or "internal-companyos",
        requested_amount=amount,
        resource_type=GOVERNOR_RESOURCE,
        approval_state="approved" if approval_state == "approved_for_simulation" else "not_requested",
        hypothesis=hypothesis,
        success_metric=success_metric,
        learning_captured=False,
        previous_learning_required=True,
    )
    result = evaluate(request)
    return {
        "authority": "evaluation.companyos.resource_execution_governor",
        "status": "referenced",
        "action_referenced": GOVERNOR_ACTION,
        "resource_type": GOVERNOR_RESOURCE,
        "outcome": getattr(result, "outcome", "unavailable"),
        "reason": getattr(result, "reason", ""),
        "blockers": list(getattr(result, "blockers", ()) or ()),
        "simulated_only": True,
        "live_action_allowed": False,
    }


def reference_approval_ledger(*, approval_state: str, approval_request_id: str) -> dict[str, Any]:
    imported = _try_ledger()
    if imported is None:
        return {
            "authority": "evaluation.companyos.approval_ledger",
            "status": "unavailable",
            "request_type_referenced": LEDGER_REQUEST_TYPE,
            "approval_state": approval_state,
            "approval_request_id": approval_request_id,
            "live_action_allowed": False,
            "note": "Approval Ledger module not importable in this worktree; state stored by reference only.",
        }
    request_types, live_types = imported
    return {
        "authority": "evaluation.companyos.approval_ledger",
        "status": "referenced",
        "request_type_referenced": LEDGER_REQUEST_TYPE,
        "request_type_known": LEDGER_REQUEST_TYPE in tuple(request_types),
        "live_request_type_blocked": LEDGER_REQUEST_TYPE in set(live_types),
        "approval_state": approval_state,
        "approval_request_id": approval_request_id,
        "live_action_allowed": False,
        "note": "ad_launch remains blocked_in_current_mode on the ledger. This layer does not approve spend.",
    }


def authority_bundle(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "governor": reference_governor(
            workspace_id=str(raw.get("workspace_id") or raw.get("workspace") or ""),
            budget_cap=str(raw.get("budget_cap") or "0"),
            approval_state=str(raw.get("approval_state") or "not_requested"),
            hypothesis=str(raw.get("hypothesis") or ""),
            success_metric=str(raw.get("success_metric") or ""),
        ),
        "approval_ledger": reference_approval_ledger(
            approval_state=str(raw.get("approval_state") or "not_requested"),
            approval_request_id=str(raw.get("approval_request_id") or ""),
        ),
    }

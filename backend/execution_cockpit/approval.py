from __future__ import annotations

import time
import uuid
from .cockpit_models import CockpitAction, CockpitApproval
from .cockpit_registry import get_cockpit_registry


def approval_required_for_action(action: CockpitAction) -> bool:
    return bool(action.approval_required and action.action_type not in {"advisory_manual", "blocked"})


def create_pending_approval(action: CockpitAction, approver: str = "operator") -> CockpitApproval:
    if action.action_type in {"blocked", "advisory_manual"} or action.status == "blocked":
        raise ValueError("action_not_approvable")
    approval = CockpitApproval(f"approval_{uuid.uuid5(uuid.NAMESPACE_URL, action.action_id).hex[:16]}", action.workspace_id, action.action_id, "pending", approver, "")
    get_cockpit_registry().register_approval(approval)
    action.status = "pending_approval"; action.updated_at = time.time(); get_cockpit_registry().update_action(action)
    return approval


def decide_approval(approval_id: str, decision: str, reason: str = "", approver: str = "operator") -> CockpitApproval:
    registry = get_cockpit_registry(); approval = registry.get_approval(approval_id)
    if approval is None: raise ValueError("approval_not_found")
    if decision not in {"approved", "rejected"}: raise ValueError("invalid_approval_decision")
    action = registry.get_action(approval.action_id)
    if action is None: raise ValueError("action_not_found")
    if action.status == "blocked": raise ValueError("blocked_action_cannot_be_approved")
    if approval.decision != "pending": raise ValueError("approval_already_decided")
    approval.decision, approval.reason, approval.approver, approval.decided_at = decision, reason, approver, time.time()
    registry.update_approval(approval)
    action.status = "approved" if decision == "approved" else "rejected"; action.updated_at = time.time(); registry.update_action(action)
    return approval

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any, Iterable


@dataclass
class ApprovalPolicy:
    policy_id: str = "default"
    name: str = "Default dry-run policy"
    require_reviewer: bool = True
    require_human_for_live_action: bool = True
    require_finance_for_budget_above: float = 0.0
    require_risk_for_budget_above: float = 0.0
    allowed_dry_run_without_human: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


def _workspace_identifier(workspace: Any) -> str:
    """Extract the already-authorized workspace identifier without trusting payload data."""
    if isinstance(workspace, str):
        return workspace.strip()
    if isinstance(workspace, Mapping):
        return str(workspace.get("workspace_id", "") or "").strip()
    return str(getattr(workspace, "workspace_id", "") or "").strip()


def evaluate_proposal_approval(proposal, agent_role, workspace=None, live_action_requested: bool = False,
                               policy: ApprovalPolicy | None = None, prior_decisions: Iterable[Any] = ()) -> dict[str, Any]:
    blocked: list[str] = []
    reviews: list[str] = []
    policy = policy or ApprovalPolicy()
    workspace_id = _workspace_identifier(workspace)
    if not workspace_id: blocked.append("workspace_required")
    proposal_workspace_id = str(getattr(proposal, "workspace_id", "") or "").strip()
    if proposal_workspace_id and workspace_id and proposal_workspace_id != workspace_id:
        blocked.append("workspace_mismatch")
    if agent_role is None or not getattr(agent_role, "active", False): blocked.append("active_agent_required")
    if live_action_requested:
        blocked.append("human_approval_required_for_live_action")
        reviews.append("human")
    budget = float(getattr(proposal, "requested_budget", 0.0) or 0.0)
    authority = float(getattr(agent_role, "max_budget_authority", 0.0) or 0.0)
    if budget > authority:
        reviews.extend(["finance", "risk"])
        blocked.extend(["finance_review_required", "risk_review_required"])
    budget_review_required = budget > float(getattr(agent_role, "requires_review_above", float("inf"))) if agent_role else True
    if budget_review_required:
        reviews.append("reviewer")
    specialist_review_required = getattr(agent_role, "role_type", "") == "specialist"
    if policy.require_reviewer and not live_action_requested and getattr(agent_role, "role_type", "") not in {"manager", "executive", "reviewer"}:
        reviews.append("reviewer")
    if (budget_review_required or specialist_review_required) and not live_action_requested:
        blocked.append("reviewer_required")
    finance_review_required = budget > policy.require_finance_for_budget_above
    risk_review_required = budget > policy.require_risk_for_budget_above
    if finance_review_required: reviews.append("finance")
    if risk_review_required: reviews.append("risk")
    if finance_review_required and not any(getattr(item, "decision", "") == "approved" and "finance" in getattr(item, "decided_by_agent_id", "") for item in prior_decisions):
        blocked.append("finance_policy_review_required")
    if risk_review_required and not any(getattr(item, "decision", "") == "approved" and "risk" in getattr(item, "decided_by_agent_id", "") for item in prior_decisions):
        blocked.append("risk_policy_review_required")
    if budget > authority and not any(getattr(item, "decision", "") == "approved" and ("finance" in getattr(item, "decided_by_agent_id", "") or "risk" in getattr(item, "decided_by_agent_id", "") or "human" in getattr(item, "decided_by_agent_id", "")) for item in prior_decisions):
        blocked.append("budget_authority_exceeded")
    dry_run_safe = not live_action_requested and policy.allowed_dry_run_without_human
    return {"allowed": not blocked, "blocked_reasons": list(dict.fromkeys(blocked)), "required_reviews": list(dict.fromkeys(reviews)),
            "policy_id": policy.policy_id, "dry_run_safe": dry_run_safe,
            "budget_review_required": budget_review_required, "finance_review_required": finance_review_required,
            "risk_review_required": risk_review_required, "human_review_required": live_action_requested}

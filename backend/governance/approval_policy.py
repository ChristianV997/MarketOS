from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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


def evaluate_proposal_approval(proposal, agent_role, workspace=None, live_action_requested: bool = False) -> dict[str, Any]:
    blocked: list[str] = []
    reviews: list[str] = []
    policy = ApprovalPolicy()
    if workspace is None or (isinstance(workspace, str) and not workspace.strip()): blocked.append("workspace_required")
    if agent_role is None or not getattr(agent_role, "active", False): blocked.append("active_agent_required")
    if live_action_requested:
        blocked.append("human_approval_required_for_live_action")
        reviews.append("human")
    budget = float(getattr(proposal, "requested_budget", 0.0) or 0.0)
    authority = float(getattr(agent_role, "max_budget_authority", 0.0) or 0.0)
    if budget > authority:
        reviews.extend(["finance", "risk"])
    if policy.require_reviewer and not live_action_requested: reviews.append("reviewer")
    dry_run_safe = not live_action_requested and policy.allowed_dry_run_without_human
    return {"allowed": not blocked, "blocked_reasons": blocked, "required_reviews": list(dict.fromkeys(reviews)),
            "policy_id": policy.policy_id, "dry_run_safe": dry_run_safe}

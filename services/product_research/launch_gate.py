"""Approval/evidence gate for the eventual single small live launch."""
from __future__ import annotations

from typing import Any

from backend.research.mode import is_research_only

REQUIRED_APPROVALS = ("brand", "inventory", "landing_page", "social_account", "ads")


def evaluate_launch_gate(subject_id: str, *, dossier: dict[str, Any], approvals: list[dict[str, Any]],
                         credentials_ready: bool = False, budget_ready: bool = False) -> dict[str, Any]:
    """Return a decision only; it never calls a provider or launches."""
    by_type = {str(item.get("subject_type")): item for item in approvals if item.get("subject_id") == subject_id}
    missing = [kind for kind in REQUIRED_APPROVALS if by_type.get(kind, {}).get("state") != "approved"]
    tipping = (dossier.get("tipping_point") or {}).get("status")
    reasons = []
    if is_research_only():
        reasons.append("research_only")
    if tipping != "candidate":
        reasons.append("tipping_point_not_candidate")
    if missing:
        reasons.append("approvals_missing")
    if not credentials_ready:
        reasons.append("credentials_not_ready")
    if not budget_ready:
        reasons.append("budget_not_ready")
    return {"allowed": not reasons, "status": "blocked" if reasons else "ready_for_explicit_launch",
            "subject_id": subject_id, "missing_approvals": missing, "reasons": reasons}

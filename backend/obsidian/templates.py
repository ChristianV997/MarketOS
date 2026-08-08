from __future__ import annotations

import json
from typing import Any


def _data(value: Any) -> Any:
    if hasattr(value, "to_dict"): return value.to_dict()
    if isinstance(value, dict): return {k: _data(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_data(v) for v in value]
    return value


def render_proposal_note(proposal, approval, decision, execution) -> str:
    p = _data(proposal); linked = p.get("linked_experiment_id") or ""
    front = {"type": "marketos_proposal", "proposal_id": p.get("proposal_id"), "workspace_id": p.get("workspace_id"), "department_id": p.get("department_id"), "service_name": p.get("service_name"), "status": p.get("status"), "risk_level": p.get("risk_level"), "requested_budget": p.get("requested_budget", 0), "linked_experiment_id": linked, "created_at": p.get("created_at")}
    approval_data, decision_data, execution_data = _data(approval), _data(decision), _data(execution)
    next_action = "Review and approve the proposal." if p.get("status") in {"proposed", "under_review"} else "No live action is permitted; inspect the recorded result."
    if p.get("status") in {"blocked", "revision_requested"}:
        next_action = "Resolve the blocked reasons or request a revision."
    return "---\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in front.items()) + "\n---\n\n# " + str(p.get("title", "Proposal")) + "\n\n" + str(p.get("summary", "")) + "\n\n## Approval\n\n" + f"- Allowed: `{approval_data.get('allowed')}`\n- Blocked reasons: `{json.dumps(approval_data.get('blocked_reasons', []))}`\n- Required reviews: `{json.dumps(approval_data.get('required_reviews', []))}`\n" + "\n```json\n" + json.dumps(approval_data, indent=2) + "\n```\n\n## Decision\n\n" + f"- Decision: `{decision_data.get('decision')}`\n- Reason: `{decision_data.get('reason', '')}`\n" + "\n```json\n" + json.dumps(decision_data, indent=2) + "\n```\n\n## Execution\n\n" + f"- Status: `{execution_data.get('status')}`\n- Service availability: `{execution_data.get('status', 'unknown')}`\n- Experiment ID: `{execution_data.get('experiment_id') or linked or ''}`\n" + "\n```json\n" + json.dumps(execution_data, indent=2) + "\n```\n\n## Next action\n\n" + next_action + "\n"


def render_department_daily(department, items) -> str:
    name = getattr(department, "name", "Department")
    return f"# {name} daily\n\n" + "\n".join(f"- {json.dumps(_data(item), sort_keys=True)}" for item in items) + "\n"

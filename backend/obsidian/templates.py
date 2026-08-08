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
    return "---\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in front.items()) + "\n---\n\n# " + str(p.get("title", "Proposal")) + "\n\n" + str(p.get("summary", "")) + "\n\n## Approval\n\n```json\n" + json.dumps(_data(approval), indent=2) + "\n```\n\n## Decision\n\n```json\n" + json.dumps(_data(decision), indent=2) + "\n```\n\n## Execution\n\n```json\n" + json.dumps(_data(execution), indent=2) + "\n```\n"


def render_department_daily(department, items) -> str:
    name = getattr(department, "name", "Department")
    return f"# {name} daily\n\n" + "\n".join(f"- {json.dumps(_data(item), sort_keys=True)}" for item in items) + "\n"

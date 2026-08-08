from __future__ import annotations

import json
from typing import Any


def _data(value: Any) -> Any:
    if hasattr(value, "to_dict"): return value.to_dict()
    if isinstance(value, dict): return {k: _data(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_data(v) for v in value]
    return value


def render_proposal_note(proposal, approval, decision, execution, report=None) -> str:
    p = _data(proposal); linked = p.get("linked_experiment_id") or ""
    front = {"type": "marketos_proposal", "proposal_id": p.get("proposal_id"), "workspace_id": p.get("workspace_id"), "department_id": p.get("department_id"), "service_name": p.get("service_name"), "status": p.get("status"), "risk_level": p.get("risk_level"), "requested_budget": p.get("requested_budget", 0), "linked_experiment_id": linked, "created_at": p.get("created_at")}
    approval_data, decision_data, execution_data = _data(approval), _data(decision), _data(execution)
    report_data = _data(report) if report is not None else {}
    next_action = "Review and approve the proposal." if p.get("status") in {"proposed", "under_review"} else "No live action is permitted; inspect the recorded result."
    if p.get("status") in {"blocked", "revision_requested"}:
        next_action = "Resolve the blocked reasons or request a revision."
    report_section = ""
    if report_data:
        report_section = "\n## Commercial report\n\n" + f"### {report_data.get('title', 'Report')}\n\n{report_data.get('summary', '')}\n\n**Report status:** `{report_data.get('status', '')}`\n\n### Findings\n\n" + "\n".join(f"- **{item.get('name')}**: {item.get('value')}" for item in report_data.get("findings", [])) + "\n\n### Recommendations\n\n" + "\n".join(f"- {item}" for item in report_data.get("recommendations", [])) + "\n\n### Report risks\n\n" + "\n".join(f"- {item}" for item in report_data.get("risk_flags", [])) + "\n"
    return "---\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in front.items()) + "\n---\n\n# " + str(p.get("title", "Proposal")) + "\n\n" + str(p.get("summary", "")) + "\n\n## Approval\n\n" + f"- Allowed: `{approval_data.get('allowed')}`\n- Blocked reasons: `{json.dumps(approval_data.get('blocked_reasons', []))}`\n- Required reviews: `{json.dumps(approval_data.get('required_reviews', []))}`\n" + "\n```json\n" + json.dumps(approval_data, indent=2) + "\n```\n\n## Decision\n\n" + f"- Decision: `{decision_data.get('decision')}`\n- Reason: `{decision_data.get('reason', '')}`\n" + "\n```json\n" + json.dumps(decision_data, indent=2) + "\n```\n\n## Execution\n\n" + f"- Status: `{execution_data.get('status')}`\n- Service availability: `{execution_data.get('status', 'unknown')}`\n- Experiment ID: `{execution_data.get('experiment_id') or linked or ''}`\n" + "\n```json\n" + json.dumps(execution_data, indent=2) + "\n```\n" + report_section + "\n## Next action\n\n" + next_action + "\n"


def render_department_daily(department, items) -> str:
    name = getattr(department, "name", "Department")
    return f"# {name} daily\n\n" + "\n".join(f"- {json.dumps(_data(item), sort_keys=True)}" for item in items) + "\n"


def render_portfolio_report_note(portfolio_report) -> str:
    data = _data(portfolio_report)
    front = {"type": "portfolio_report", "portfolio_report_id": data.get("portfolio_report_id"), "workspace_id": data.get("workspace_id"), "report_count": len(data.get("report_ids", [])), "created_at": data.get("created_at")}
    bullets = lambda values: "\n".join(f"- {value}" for value in values) or "- None."
    counts = lambda values: "\n".join(f"- `{key}`: {value}" for key, value in sorted(values.items())) or "- None."
    risks = "\n".join(f"- `{item.get('flag')}`: {item.get('count')}" for item in data.get("recurring_risk_flags", [])) or "- None."
    return "---\n" + "\n".join(f"{key}: {json.dumps(value)}" for key, value in front.items()) + "\n---\n\n# " + str(data.get("title", "Portfolio report")) + "\n\n" + str(data.get("summary", "")) + "\n\n## Service counts\n\n" + counts(data.get("service_counts", {})) + "\n\n## Status counts\n\n" + counts(data.get("status_counts", {})) + "\n\n## Recurring risk flags\n\n" + risks + "\n\n## Top recommendations\n\n" + bullets(data.get("top_recommendations", [])) + "\n\n## Next actions\n\n" + bullets(data.get("next_actions", [])) + "\n\n## Linked report IDs\n\n" + bullets(data.get("report_ids", [])) + "\n"

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


def render_category_discovery_note(discovery_run, portfolio_report_id: str = "") -> str:
    data = _data(discovery_run)
    front = {"type": "category_discovery", "discovery_id": data.get("discovery_id"), "workspace_id": data.get("workspace_id"), "evidence_count": data.get("evidence_count", 0), "created_at": data.get("created_at")}
    rows = []
    for item in data.get("category_opportunities", []):
        rows.append(f"- **{item.get('rank')}. {item.get('category_name')}** — `{item.get('recommendation')}`, score `{item.get('score')}`; missing: {', '.join(item.get('missing_evidence', [])) or 'none'}")
    return "---\n" + "\n".join(f"{key}: {json.dumps(value)}" for key, value in front.items()) + "\n---\n\n# " + str(data.get("title", "Category discovery")) + "\n\n" + str(data.get("objective", "")) + "\n\n**Sources:** " + ", ".join(data.get("source_names", [])) + "\n\n## Ranked categories\n\n" + ("\n".join(rows) or "- No categories available.") + "\n\n## Provenance warning\n\nEvidence is limited to the recorded local sources; synthetic fixtures are not real market data.\n\n## Linked portfolio report\n\n" + (portfolio_report_id or "None") + "\n"


def render_product_hypothesis_note(hypothesis_run, portfolio_report_id: str = "") -> str:
    data = _data(hypothesis_run)
    front = {"type": "product_hypothesis", "hypothesis_run_id": data.get("hypothesis_run_id"), "workspace_id": data.get("workspace_id"), "discovery_id": data.get("discovery_id"), "created_at": data.get("created_at")}
    rows = [f"- **{item.get('product_name')}** ({item.get('category_name')}) — audience: {item.get('target_audience')}; confidence: `{item.get('confidence')}`; missing: {', '.join(item.get('missing_evidence', [])) or 'none'}" for item in data.get("hypotheses", [])]
    return "---\n" + "\n".join(f"{key}: {json.dumps(value)}" for key, value in front.items()) + "\n---\n\n# Product hypotheses\n\n" + ("\n".join(rows) or "- No hypotheses available.") + "\n\n## Validation next steps\n\n- Validate demand, competition, supplier economics, and shipping with approved evidence sources.\n- Do not treat these hypotheses as products, sales, or profit claims.\n\n## Linked portfolio report\n\n" + (portfolio_report_id or "None") + "\n"


def render_evidence_import_note(import_job, source_quality, normalization_result=None) -> str:
    job, quality = _data(import_job), _data(source_quality)
    result = _data(normalization_result) if normalization_result is not None else {}
    front = {"type": "evidence_import", "import_id": job.get("import_id"), "workspace_id": job.get("workspace_id"), "source_name": job.get("source_name"), "parser_type": job.get("parser_type"), "status": job.get("status"), "records_imported": job.get("records_imported", 0), "records_rejected": job.get("records_rejected", 0), "created_at": job.get("created_at")}
    bullets = lambda values: "\n".join(f"- {value}" for value in values) or "- None."
    return "---\n" + "\n".join(f"{key}: {json.dumps(value)}" for key, value in front.items()) + "\n---\n\n# Evidence import\n\n**Quality score:** `" + str(quality.get("quality_score", 0)) + "`\n\n## Strengths\n\n" + bullets(quality.get("strengths", [])) + "\n\n## Weaknesses\n\n" + bullets(quality.get("weaknesses", [])) + "\n\n## Allowed signal types\n\n" + bullets(quality.get("allowed_signal_types", [])) + "\n\n## Blocked signal types\n\n" + bullets(quality.get("blocked_signal_types", [])) + "\n\n## Warnings\n\n" + bullets(job.get("warnings", []) + result.get("warnings", [])) + "\n\n## Provenance\n\nLocal/cache-only import. No network call or external mutation was performed.\n\n```json\n" + json.dumps({"provenance_requirements": quality.get("provenance_requirements", []), "metadata": quality.get("metadata", {})}, indent=2) + "\n```\n"

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


def render_refinement_cycle_note(gap_analysis, import_plan, templates) -> str:
    analysis, plan = _data(gap_analysis), _data(import_plan); items = _data(templates)
    gaps = "\n".join(f"- `{x.get('missing_signal_type')}` for **{x.get('entity_name')}** — priority `{x.get('priority_score')}`; fields: {', '.join(x.get('required_fields', []))}" for x in analysis.get("gaps", [])) or "- None."
    recs = "\n".join(f"- **{x.get('title')}** — `{x.get('template_path')}`" for x in plan.get("recommendations", [])) or "- None."
    return f"---\ntype: refinement_cycle\nanalysis_id: {json.dumps(analysis.get('analysis_id'))}\nworkspace_id: {json.dumps(analysis.get('workspace_id'))}\ncreated_at: {json.dumps(analysis.get('created_at'))}\n---\n\n# Evidence refinement cycle\n\n## Coverage\n\n```json\n{json.dumps(analysis.get('evidence_coverage', {}), indent=2)}\n```\n\n## Strongest categories\n\n{json.dumps(analysis.get('strongest_categories', []), indent=2)}\n\n## Weakest categories\n\n{json.dumps(analysis.get('weakest_categories', []), indent=2)}\n\n## Prioritized gaps\n\n{gaps}\n\n## Recommended imports\n\n{recs}\n\n## Templates\n\n" + "\n".join(f"- `{x.get('file_path')}` — required: {', '.join(x.get('required_fields', []))}" for x in items) + "\n\n## Next actions\n\n1. Replace placeholder rows with documented local exports.\n2. Import through the cache-only endpoint.\n3. Rerun discovery and compare recorded scores.\n"


def render_discovery_comparison_note(comparison) -> str:
    data = _data(comparison)
    return "---\ntype: discovery_comparison\ncomparison_id: " + json.dumps(data.get("comparison_id")) + "\nworkspace_id: " + json.dumps(data.get("workspace_id")) + "\ncreated_at: " + json.dumps(data.get("created_at")) + "\n---\n\n# Discovery comparison\n\n" + str(data.get("summary", "")) + "\n\n## Category movements\n\n" + "\n".join(f"- **{x.get('category_name')}**: rank {x.get('baseline_rank')} → {x.get('current_rank')}; score {x.get('baseline_score')} → {x.get('current_score')}" for x in data.get("category_movements", [])) + "\n\n## New categories\n\n" + ", ".join(data.get("new_categories", [])) + "\n\n## Dropped categories\n\n" + ", ".join(data.get("dropped_categories", [])) + "\n\n## Interpretation\n\nScore changes are descriptive outputs from different evidence sets. They do not prove causality or market improvement.\n"


def render_acquisition_plan_note(plan) -> str:
    data = _data(plan)
    steps = "\n".join(f"{step.get('order')}. **{step.get('title')}** — {step.get('instruction')}\n   - Verify: {'; '.join(step.get('verification_checks', []))}" for step in data.get("steps", []))
    return f"---\ntype: evidence_acquisition_plan\nplan_id: {json.dumps(data.get('plan_id'))}\nworkspace_id: {json.dumps(data.get('workspace_id'))}\nparser_type: {json.dumps(data.get('parser_type'))}\nstatus: {json.dumps(data.get('status'))}\ncreated_at: {json.dumps(data.get('created_at'))}\n---\n\n# {data.get('title')}\n\n**Mode:** `{data.get('current_mode')}`  \n**Connector stub:** `{data.get('connector_stub_name')}`  \n**Priority:** `{data.get('priority_score')}`\n\n{data.get('objective')}\n\n## Expected signals\n\n{', '.join(data.get('expected_signal_types', []))}\n\n## Manual export steps\n\n{steps}\n\n## Templates\n\n{', '.join(data.get('template_paths', [])) or 'None'}\n\n## Safety\n\nThis plan is manual/cache-only. No live API, scraping, credential, or mutation path is enabled.\n"


def render_connector_stub_note(stub) -> str:
    data = _data(stub)
    return f"---\ntype: evidence_connector_stub\nconnector_name: {json.dumps(data.get('connector_name'))}\nparser_type: {json.dumps(data.get('parser_type'))}\nstatus: {json.dumps(data.get('status'))}\ndefault_enabled: false\n---\n\n# {data.get('connector_name')}\n\n**Current mode:** disabled  \n**Output format:** {data.get('output_format')}  \n**Future environment variables:** {', '.join(data.get('required_env_vars', []))}\n\n## Blocked reasons\n\n" + "\n".join(f"- {x}" for x in data.get('blocked_reasons', [])) + "\n\n## Safety contract\n\n```json\n" + json.dumps(data.get('safety_contract', {}), indent=2) + "\n```\n\nNo executable connector exists in this phase.\n"


def render_source_calibration_note(calibration_run) -> str:
    data = _data(calibration_run)
    rows = "\n".join(f"- **{x.get('source_name')} / {x.get('parser_type')}** — usefulness `{x.get('usefulness_score')}`, priority adjustment `{float(x.get('recommended_priority_adjustment', 0)):+.1f}`; strengths: {', '.join(x.get('strengths', [])) or 'none'}; weaknesses: {', '.join(x.get('weaknesses', [])) or 'none'}" for x in data.get('profiles', [])) or "- No profiles available."
    return f"---\ntype: source_calibration\ncalibration_id: {json.dumps(data.get('calibration_id'))}\nworkspace_id: {json.dumps(data.get('workspace_id'))}\nstatus: {json.dumps(data.get('status'))}\ncreated_at: {json.dumps(data.get('created_at'))}\n---\n\n# {data.get('title')}\n\n**Summary:** {data.get('summary')}\n\n## Profiles\n\n{rows}\n\n## Recommendations\n\n" + "\n".join(f"- {x}" for x in data.get('recommendations', [])) + "\n\n## Interpretation\n\nObserved changes after evidence inclusion are descriptive and non-causal. Insufficient comparisons remain inconclusive.\n"

def render_opportunity_pipeline_snapshot_note(snapshot) -> str:
    data = _data(snapshot)
    rows = "\n".join(f"- **{x.get('name')}** — `{x.get('stage')}` — score `{x.get('score', 0)}`" for x in data.get('top_opportunities', [])) or "- None."
    return f"---\ntype: opportunity_pipeline_snapshot\nsnapshot_id: {json.dumps(data.get('snapshot_id'))}\nworkspace_id: {json.dumps(data.get('workspace_id'))}\ncreated_at: {json.dumps(data.get('created_at'))}\n---\n\n# {data.get('title')}\n\n## Stage counts\n\n```json\n{json.dumps(data.get('stage_counts', {}), indent=2)}\n```\n\n## Top opportunities\n\n{rows}\n\n## Next actions\n\n" + "\n".join(f"- {x}" for x in data.get('next_actions', [])) + "\n\n`launch_candidate` is planning-only and never authorizes live execution.\n"

def render_opportunity_note(opportunity, transitions=None) -> str:
    data = _data(opportunity); transitions = [_data(x) for x in (transitions or [])]
    history = "\n".join(f"- `{x.get('from_stage')}` → `{x.get('to_stage')}`: {x.get('reason')}" for x in transitions) or "- No transitions recorded."
    return f"---\ntype: opportunity\nopportunity_id: {json.dumps(data.get('opportunity_id'))}\nworkspace_id: {json.dumps(data.get('workspace_id'))}\nstage: {json.dumps(data.get('stage'))}\ncreated_at: {json.dumps(data.get('created_at'))}\n---\n\n# {data.get('name')}\n\n**Type:** `{data.get('opportunity_type')}`  \n**Stage:** `{data.get('stage')}`  \n**Recommendation:** `{data.get('recommendation')}`  \n**Score:** `{data.get('score')}`  \n**Confidence:** `{data.get('confidence')}`\n\n## Evidence and gaps\n\n- Evidence: {', '.join(data.get('evidence_ids', [])) or 'none'}\n- Reports: {', '.join(data.get('report_ids', [])) or 'none'}\n- Gaps: {', '.join(data.get('gap_ids', [])) or 'none'}\n- Missing evidence: {', '.join(data.get('missing_evidence', [])) or 'none'}\n\n## Next actions\n\n" + "\n".join(f"- {x}" for x in data.get('next_actions', [])) + "\n\n## Transition history\n\n" + history + "\n\nThis is a read-only planning artifact. `launch_candidate` is not launch approval.\n"

def render_validation_sprint_note(sprint) -> str:
    data=_data(sprint); targets="\n".join(f"- **{x.get('name')}** — {', '.join(x.get('service_plan', []))}" for x in data.get('targets', [])) or "- None."
    cards="\n".join(f"- **{x.get('opportunity_name')}** — score `{x.get('validation_score')}` — `{x.get('recommendation')}`" for x in data.get('scorecards', [])) or "- None."
    return f"---\ntype: validation_sprint\nsprint_id: {json.dumps(data.get('sprint_id'))}\nworkspace_id: {json.dumps(data.get('workspace_id'))}\nstatus: {json.dumps(data.get('status'))}\ncreated_at: {json.dumps(data.get('created_at'))}\n---\n\n# {data.get('title')}\n\n**Objective:** {data.get('objective')}\n\n## Targets\n\n{targets}\n\n## Scorecards\n\n{cards}\n\n## Safety\n\nThis sprint is dry-run and planning-only. It cannot launch ads, place orders, message customers, publish, take payment, or mutate commerce systems.\n"

def render_validation_scorecard_note(scorecard) -> str:
    data=_data(scorecard)
    return f"---\ntype: validation_scorecard\nscorecard_id: {json.dumps(data.get('scorecard_id'))}\nopportunity_id: {json.dumps(data.get('opportunity_id'))}\ncreated_at: {json.dumps(data.get('metadata', {}).get('created_at'))}\n---\n\n# Validation scorecard: {data.get('opportunity_name')}\n\n**Score:** `{data.get('validation_score')}`  \n**Confidence:** `{data.get('confidence')}`  \n**Recommendation:** `{data.get('recommendation')}`  \n**Transition:** `{data.get('transition_recommendation')}`\n\n## Risks and missing evidence\n\n- Risks: {', '.join(data.get('risk_flags', [])) or 'none'}\n- Missing: {', '.join(data.get('missing_evidence', [])) or 'none'}\n- Reports: {', '.join(x.get('report_id', '') for x in data.get('service_results', []) if x.get('report_id')) or 'none'}\n\nThis is a dry-run planning artifact, not launch authorization.\n"

def render_deliverable_package_note(package) -> str:
    data=_data(package)
    return f"---\ntype: deliverable_package\npackage_id: {json.dumps(data.get('package_id'))}\npackage_type: {json.dumps(data.get('package_type'))}\nworkspace_id: {json.dumps(data.get('workspace_id'))}\nstatus: {json.dumps(data.get('status'))}\nsource_sprint_id: {json.dumps(data.get('source_sprint_id'))}\ncreated_at: {json.dumps(data.get('created_at'))}\n---\n\n# {data.get('title')}\n\n## Executive summary\n\n{data.get('executive_summary','')}\n\n## Recommendations\n\n"+"\n".join(f"- {x}" for x in data.get('recommendations',[]))+"\n\n## Risks and missing evidence\n\n- Risks: {', '.join(data.get('risk_flags',[])) or 'none'}\n- Missing evidence: {', '.join(data.get('missing_evidence',[])) or 'none'}\n\n## Artifacts\n\n"+"\n".join(f"- `{x.get('relative_path')}`" for x in data.get('artifacts',[]))+"\n\n## Source IDs\n\n- Sprint: `"+str(data.get('source_sprint_id',''))+"`\n- Snapshot: `"+str(data.get('source_snapshot_id',''))+"`\n- Reports: "+", ".join(data.get('source_report_ids',[]))+"\n\nNo live launch or external action was executed.\n"

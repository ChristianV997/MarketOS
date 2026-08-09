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

def render_knowledge_graph_snapshot_note(snapshot):
    data=_data(snapshot);return "---\ntype: knowledge_graph_snapshot\nsnapshot_id: "+json.dumps(data.get("snapshot_id"))+"\nworkspace_id: "+json.dumps(data.get("workspace_id"))+"\n---\n\n# Knowledge Graph\n\nNodes: `"+str(data.get("node_count",0))+"`  \nEdges: `"+str(data.get("edge_count",0))+"`\n\n## Top nodes\n\n"+"\n".join(f"- {x.get('title')} — `{x.get('node_type')}`" for x in data.get("top_nodes",[]))+"\n\nGraph relationships are exact-ID, evidence-backed links only.\n"
def render_strategic_priority_plan_note(plan):
    data=_data(plan);return "---\ntype: strategic_priority_plan\nplan_id: "+json.dumps(data.get("plan_id"))+"\nworkspace_id: "+json.dumps(data.get("workspace_id"))+"\n---\n\n# Strategic Priorities\n\n"+"\n".join(f"- **{x.get('title')}** — `{x.get('total_priority_score')}` — {x.get('recommended_action')}" for x in data.get("priorities",[]))+"\n\nAll actions are dry-run and local/cache-only.\n"
def render_research_campaign_plan_note(plan):
    data=_data(plan);return "---\ntype: research_campaign_plan\nplan_id: "+json.dumps(data.get("plan_id"))+"\nworkspace_id: "+json.dumps(data.get("workspace_id"))+"\n---\n\n# Research Campaigns\n\n"+"\n".join(f"- **{x.get('title')}** — `{x.get('status')}`; gain `{x.get('expected_information_gain')}`" for x in data.get("campaigns",[]))+"\n\nCampaigns contain no live execution.\n"
def render_executive_brief_note(brief):
    data=_data(brief);return "---\ntype: executive_brief\nbrief_id: "+json.dumps(data.get("brief_id"))+"\nworkspace_id: "+json.dumps(data.get("workspace_id"))+"\nperiod: "+json.dumps(data.get("period_label"))+"\n---\n\n# "+str(data.get("title"))+"\n\n## Summary\n\n"+str(data.get("summary"))+"\n\n## Next actions\n\n"+"\n".join(f"- {x}" for x in data.get("recommended_next_actions",[]))+"\n\nNo live action was executed.\n"

def render_workflow_run_note(run):
    data=_data(run);return "---\ntype: workflow_run\nworkflow_id: "+json.dumps(data.get("workflow_id"))+"\nworkspace_id: "+json.dumps(data.get("workspace_id"))+"\nstatus: "+json.dumps(data.get("status"))+"\n---\n\n# "+str(data.get("title"))+"\n\n"+"\n".join(f"- **{x.get('stage_name')}** — `{x.get('status')}`" for x in data.get("stages",[]))+"\n\n## Checkpoints\n\n"+"\n".join(f"- `{x.get('checkpoint_id')}` — {x.get('checkpoint_type')} — recoverable `{x.get('recoverable')}`" for x in data.get("checkpoints",[]))+"\n\nNo live action is permitted.\n"
def render_workflow_timeline_note(run,events):return "# Workflow timeline\n\n"+"\n".join(f"- `{x.get('created_at')}` **{x.get('event_type')}** — {x.get('message')}" for x in [_data(e) for e in events])+"\n\nNo live action was executed.\n"
def render_workflow_runbook_note(runbook):return runbook.to_markdown()

def render_portfolio_optimization_note(plan):
    data = _data(plan)
    scenarios = "\n".join(f"- **{x.get('title')}** — cost `${x.get('total_simulated_cost', 0):.2f}`, hours `{x.get('total_estimated_hours', 0):.1f}`, info gain `{x.get('total_expected_information_gain', 0):.1f}`" for x in data.get("scenarios", [])) or "- None."
    actions = "\n".join(f"- **{x.get('title')}** — `{x.get('action_type')}` — `{x.get('safe_endpoint') or 'advisory/manual'}`" for x in data.get("recommended_actions", [])) or "- None."
    return f"---\ntype: portfolio_optimization\noptimization_id: {json.dumps(data.get('optimization_id'))}\nworkspace_id: {json.dumps(data.get('workspace_id'))}\ncreated_at: {json.dumps(data.get('created_at'))}\n---\n\n# {data.get('title')}\n\n{data.get('summary', '')}\n\n## Scenarios\n\n{scenarios}\n\n## Recommended scenario\n\n`{data.get('recommended_scenario_id')}`\n\n## Recommended actions\n\n{actions}\n\n## Next actions\n\n" + "\n".join(f"- {x}" for x in data.get("next_actions", [])) + "\n\n## Safety\n\nAll budgets, costs, and capital allocations are simulated planning assumptions. No live spending or external mutation occurred.\n"

def render_portfolio_action_set_note(action_set):
    data = _data(action_set)
    rows = "\n".join(f"- **{x.get('title')}** — score `{x.get('total_action_score')}` — cost `${x.get('estimated_cost', 0):.2f}` / `{x.get('estimated_hours', 0):.1f}h`" for x in data.get("actions", [])) or "- None."
    return f"---\ntype: portfolio_action_set\naction_set_id: {json.dumps(data.get('action_set_id'))}\nworkspace_id: {json.dumps(data.get('workspace_id'))}\ncreated_at: {json.dumps(data.get('created_at'))}\n---\n\n# {data.get('title')}\n\n{data.get('objective', '')}\n\n## Actions\n\n{rows}\n\n## Safety\n\nActions are dry-run/manual/cache-only recommendations. No budget is committed.\n"

def render_cockpit_action_note(action):
    data = _data(action)
    return f"---\ntype: cockpit_action\naction_id: {json.dumps(data.get('action_id'))}\nworkspace_id: {json.dumps(data.get('workspace_id'))}\nstatus: {json.dumps(data.get('status'))}\n---\n\n# {data.get('title')}\n\n**Action:** `{data.get('action_type')}`  \n**Approval required:** `{data.get('approval_required')}`  \n**Endpoint:** `{data.get('safe_endpoint') or 'manual/advisory only'}`\n\n## Payload reference\n\n```json\n{json.dumps(data.get('safe_payload', {}), indent=2, default=str)}\n```\n\n## Blockers\n\n" + "\n".join(f"- {x}" for x in data.get('blocked_reasons', [])) + "\n\n## Safety\n\n" + "\n".join(f"- {x}" for x in data.get('safety_notes', [])) + "\n\nNo live external action was executed.\n"

def render_cockpit_execution_note(execution):
    data = _data(execution)
    return f"---\ntype: cockpit_execution\nexecution_id: {json.dumps(data.get('execution_id'))}\naction_id: {json.dumps(data.get('action_id'))}\nstatus: {json.dumps(data.get('status'))}\n---\n\n# Cockpit Execution\n\n**Status:** `{data.get('status')}`\n\n## Checkpoints\n\n" + "\n".join(f"- `{x}`" for x in data.get('checkpoint_ids', [])) + "\n\n## Produced objects\n\n" + "\n".join(f"- `{x.get('object_type')}`: `{x.get('object_id')}`" for x in data.get('produced_object_ids', [])) + "\n\n## Warnings and errors\n\n" + "\n".join(f"- {x}" for x in data.get('warnings', []) + data.get('errors', [])) + "\n\nNo live external action was executed.\n"

def render_cockpit_summary_note(summary):
    data = _data(summary)
    return f"---\ntype: cockpit_summary\nsummary_id: {json.dumps(data.get('summary_id'))}\nplan_id: {json.dumps(data.get('plan_id'))}\n---\n\n# Cockpit Run Summary\n\n- Completed: `{data.get('completed_count', 0)}`\n- Blocked: `{data.get('blocked_count', 0)}`\n- Failed: `{data.get('failed_count', 0)}`\n- Skipped: `{data.get('skipped_count', 0)}`\n\n## Next actions\n\n" + "\n".join(f"- {x}" for x in data.get('next_actions', [])) + "\n\nThis cockpit is limited to approved internal local actions. No live external action was executed.\n"

def render_evidence_feature_set_note(feature_set):
    data=_data(feature_set); return f"---\ntype: evidence_feature_set\nfeature_set_id: {json.dumps(data.get('feature_set_id'))}\nworkspace_id: {json.dumps(data.get('workspace_id'))}\n---\n\n# Commercial Evidence Features\n\nFeatures: `{len(data.get('features', []))}`\n\n## Limitations\n\n"+"\n".join(f"- {x}" for x in data.get('limitation_summary', []))+"\n\nNo live market claim is made.\n"
def render_market_intelligence_note(report):
    data=_data(report); return f"---\ntype: market_intelligence_report\nreport_id: {json.dumps(data.get('report_id'))}\nworkspace_id: {json.dumps(data.get('workspace_id'))}\ncategory: {json.dumps(data.get('category_name'))}\n---\n\n# {data.get('title')}\n\n**Attractiveness:** `{data.get('attractiveness_score')}`  \n**Confidence:** `{data.get('confidence_score')}`\n\n## Reads\n\n- Demand: {data.get('demand_read')}\n- Trend: {data.get('trend_read')}\n- Competition: {data.get('competition_read')}\n- Saturation: {data.get('saturation_read')}\n\n## Risks and missing evidence\n\n"+"\n".join(f"- {x}" for x in data.get('major_risks',[])+data.get('missing_evidence',[]))+"\n\nEvidence-constrained only; no market-size, demand, profit, or ROI claim.\n"
def render_product_intelligence_note(report):
    data=_data(report); return f"---\ntype: product_intelligence_report\nreport_id: {json.dumps(data.get('report_id'))}\nworkspace_id: {json.dumps(data.get('workspace_id'))}\nproduct: {json.dumps(data.get('product_name'))}\n---\n\n# {data.get('title')}\n\n**Viability:** `{data.get('viability_score')}`  \n**Confidence:** `{data.get('confidence_score')}`\n\n## Failure modes\n\n"+"\n".join(f"- {x}" for x in data.get('failure_modes',[]))+"\n\n## Missing evidence\n\n"+"\n".join(f"- {x}" for x in data.get('missing_evidence',[]))+"\n\nPositioning and validation ideas are hypotheses. No profitability or launch claim is made.\n"

def render_creative_intelligence_report_note(report):
 data=_data(report);return f"---\ntype: creative_intelligence_report\nreport_id: {json.dumps(data.get('report_id'))}\nworkspace_id: {json.dumps(data.get('workspace_id'))}\nopportunity_id: {json.dumps(data.get('opportunity_id'))}\n---\n\n# {data.get('title')}\n\n**Confidence:** `{data.get('confidence_score')}`\n\n## Top angles\n\n"+"\n".join(f"- {x.get('title',x)}" for x in data.get('top_angles',[]))+"\n\n## Risks and missing proof\n\n"+"\n".join(f"- {x}" for x in data.get('major_risks',[])+data.get('missing_evidence',[]))+"\n\nSafety: drafts only. No ad was launched and no performance is predicted.\n"
def render_creative_angle_note(angle):
 data=_data(angle);return f"---\ntype: creative_angle\nangle_id: {json.dumps(data.get('angle_id'))}\n---\n\n# {data.get('title')}\n\n{data.get('premise')}\n\nSafety: hypothesis only; substantiate before use.\n"
def render_creative_test_matrix_note(matrix):
 data=_data(matrix);return f"---\ntype: creative_test_matrix\nmatrix_id: {json.dumps(data.get('matrix_id'))}\n---\n\n# Creative Test Matrix\n\n"+"\n".join(f"- {x.get('statement',x)}" for x in data.get('hypotheses',[]))+"\n\nNo live ad testing or performance prediction.\n"
def render_landing_page_claim_map_note(claim_map):
 data=_data(claim_map);return f"---\ntype: landing_page_claim_map\nclaim_map_id: {json.dumps(data.get('claim_map_id'))}\n---\n\n# Landing Page Claim Map\n\n"+"\n".join(f"- {x.get('claim',x)}" for x in data.get('hero_claims',[]))+"\n\nClaims are drafts; proof must be collected before use.\n"
def render_ugc_brief_note(brief):
 data=_data(brief);return f"---\ntype: ugc_brief\nbrief_id: {json.dumps(data.get('brief_id'))}\n---\n\n# {data.get('title')}\n\n## Do say\n\n"+"\n".join(f"- {x}" for x in data.get('do_say',[]))+"\n\n## Do not say\n\n"+"\n".join(f"- {x}" for x in data.get('do_not_say',[]))+"\n\nNo creator experience is implied; no ad was launched.\n"

def render_operating_plan_note(plan):
    data = _data(plan)
    rows = "\n".join(f"- **{x.get('title')}** — `{x.get('status')}` — `{x.get('due_day')}` — `{x.get('estimated_hours', 0):.1f}h`" for x in data.get('tasks', [])) or "- No tasks."
    return f"---\ntype: operating_plan\nplan_id: {json.dumps(data.get('plan_id'))}\nworkspace_id: {json.dumps(data.get('workspace_id'))}\nstatus: {json.dumps(data.get('status'))}\n---\n\n# {data.get('title')}\n\n**Objective:** {data.get('objective')}\n\n## Tasks\n\n{rows}\n\n## Day plan\n\n" + "\n".join(f"- **{day}:** {', '.join(ids)}" for day, ids in data.get('day_plan', {}).items()) + "\n\n## Safety\n\nTasks are operator-ready planning artifacts only. No task is automatically executed and no external calendar is written.\n"

def render_task_packet_note(packet):
    data = _data(packet)
    bullets = lambda values: "\n".join(f"- {value}" for value in values) or "- None."
    return f"---\ntype: task_packet\npacket_id: {json.dumps(data.get('packet_id'))}\nplan_id: {json.dumps(data.get('plan_id'))}\ntask_id: {json.dumps(data.get('task_id'))}\n---\n\n# {data.get('title')}\n\n{data.get('objective')}\n\n## Instructions\n\n{bullets(data.get('instructions', []))}\n\n## Checklist\n\n{bullets(data.get('checklist', []))}\n\n## Done definition\n\n{bullets(data.get('done_definition', []))}\n\n## Safe endpoint references\n\n```json\n{json.dumps(data.get('exact_commands_or_endpoints', []), indent=2, default=str)}\n```\n\n## Safety\n\n{bullets(data.get('safety_constraints', []))}\n\nThis packet does not execute tasks.\n"

def render_operating_calendar_note(calendar):
    data = _data(calendar)
    rows = "\n".join(f"- **{x.get('day_label')} / {x.get('start_slot')}** — `{x.get('duration_hours', 0):.1f}h` — {x.get('title')}" for x in data.get('blocks', [])) or "- No blocks."
    return f"---\ntype: operating_calendar\ncalendar_id: {json.dumps(data.get('calendar_id'))}\nplan_id: {json.dumps(data.get('plan_id'))}\n---\n\n# Operating Calendar\n\n{rows}\n\n## Safety\n\nThis is a local Markdown/ICS planning artifact. It does not write to Google Calendar or any external calendar.\n"

def render_review_cadence_note(cadence):
    data = _data(cadence)
    rows = "\n".join(f"- **{x.get('checkpoint_type')}** — {x.get('title')} — {', '.join(x.get('questions', []))}" for x in data.get('checkpoints', [])) or "- None."
    return f"---\ntype: review_cadence\ncadence_id: {json.dumps(data.get('cadence_id'))}\nplan_id: {json.dumps(data.get('plan_id'))}\n---\n\n# Review Cadence\n\n{rows}\n\nReview checkpoints are operator prompts only; no reminders or background jobs are created.\n"

def render_progress_snapshot_note(snapshot):
    data = _data(snapshot)
    return f"---\ntype: progress_snapshot\nsnapshot_id: {json.dumps(data.get('snapshot_id'))}\nplan_id: {json.dumps(data.get('plan_id'))}\n---\n\n# Progress Snapshot\n\n{data.get('progress_summary', '')}\n\n- Completed: {', '.join(data.get('completed_task_ids', [])) or 'none'}\n- Blocked: {', '.join(data.get('blocked_task_ids', [])) or 'none'}\n- Carried over: {', '.join(data.get('carried_over_task_ids', [])) or 'none'}\n\n## Next actions\n\n" + "\n".join(f"- {x}" for x in data.get('next_actions', [])) + "\n\nThis is a local status record; no task was executed automatically.\n"

from __future__ import annotations
import time,uuid
from .package import DeliverablePackage,DeliverableSection
from .decision_summary import build_executive_summary
from .import_request_packet import build_import_request_packet
from .renderer import write_deliverable_artifacts
from .registry import get_deliverable_registry
from backend.discovery.validation_sprint_registry import get_validation_sprint_registry
from backend.discovery.opportunity_registry import get_opportunity_registry
from backend.organization.report_registry import get_report_registry
from backend.discovery.refinement_registry import get_refinement_registry

def build_product_validation_sprint_package(workspace_id="default",sprint_id=None,snapshot_id=None,title=None,objective=None,include_appendices=True,formats=None):
    sr=get_validation_sprint_registry(); sprint=sr.get_sprint(sprint_id) if sprint_id else sr.latest_sprint(workspace_id); package_id="package_"+uuid.uuid4().hex[:16]
    if not sprint:
        package=DeliverablePackage(package_id=package_id,workspace_id=workspace_id,package_type="product_validation_sprint",title=title or "Product Validation Sprint Deliverable",objective=objective or "Summarize validation findings",status="blocked",executive_summary="No validation sprint is available. Run discovery, refresh the opportunity pipeline, and run a validation sprint first.",recommendations=["Run a dry-run validation sprint after discovery and pipeline refresh."],risk_flags=["no_validation_sprint"],missing_evidence=["validation_sprint_required"],next_actions=["Run market discovery.","Refresh the opportunity pipeline.","Run a dry-run validation sprint."],metadata={"blocked_reasons":["no_validation_sprint"]}); get_deliverable_registry().register_package(package); return package
    cards=sprint.scorecards; summary=build_executive_summary({"scorecards":cards}); opportunities=[get_opportunity_registry().get_opportunity(x.opportunity_id) for x in cards]; opportunities=[x for x in opportunities if x]
    snapshot=get_opportunity_registry().get_snapshot(snapshot_id) if snapshot_id else get_opportunity_registry().latest_snapshot(workspace_id); reports=[get_report_registry().get(x) for x in sprint.report_ids]; reports=[x for x in reports if x]; gaps=[g for a in get_refinement_registry().list_gap_analyses(workspace_id,20) for g in a.gaps]
    sections=[DeliverableSection("executive","Executive Summary",1,summary["summary"],summary["summary"]),DeliverableSection("scope","Scope and Method",2,"This package composes the recorded validation sprint, opportunity pipeline, deterministic governed service outputs, and local evidence records. It does not make unsupported market or profitability claims."),DeliverableSection("ranking","Opportunity Ranking",3,"\n".join(f"- **{x.name}** — stage `{x.stage}`, score `{x.score:.1f}`, confidence `{x.confidence:.2f}`" for x in opportunities) or "- No linked opportunities."),DeliverableSection("scorecards","Validation Scorecards",4,"\n".join(f"- **{x.opportunity_name}** — `{x.validation_score:.1f}` / `{x.confidence:.2f}` — `{x.recommendation}`" for x in cards) or "- No scorecards."),DeliverableSection("evidence","Evidence Gaps",7,"\n".join(f"- `{g.entity_name}`: `{g.missing_signal_type}` ({g.severity})" for g in gaps[:20]) or "- No persisted gap analysis available.")]
    if include_appendices: sections += [build_import_request_packet(workspace_id,package_id),DeliverableSection("provenance","Appendix: Source IDs and Provenance",10,f"- Sprint: `{sprint.sprint_id}`\n- Snapshot: `{snapshot.snapshot_id if snapshot else ''}`\n- Reports: {', '.join(sprint.report_ids) or 'none'}\n- Scorecards: {', '.join(x.scorecard_id for x in cards) or 'none'}")]
    package=DeliverablePackage(package_id,workspace_id,"product_validation_sprint",title or sprint.title,objective or sprint.objective,"completed",sprint.sprint_id,snapshot.snapshot_id if snapshot else "",sprint.portfolio_report_id,sorted({x.source_discovery_id for x in opportunities if x and x.source_discovery_id}),sprint.report_ids,[x.scorecard_id for x in cards],[x.opportunity_id for x in cards],sections,[],summary["summary"],summary["top_recommendations"],summary["risks"],summary["missing_evidence"],summary["next_actions"],metadata={"limitations":summary["limitations"],"report_count":len(reports),"planning_only":True}); registry=get_deliverable_registry(); registry.register_package(package)
    try:
        artifacts=write_deliverable_artifacts(package,formats=formats or ["markdown","html"]); package.artifacts=artifacts; registry.update_package(package)
        for artifact in artifacts: registry.register_artifact(package.package_id,artifact)
    except Exception: package.status="partial"; registry.update_package(package)
    package.finished_at=time.time(); registry.update_package(package)
    try:
        from backend.obsidian.sync import sync_deliverable_package_note
        package.metadata["obsidian"] = sync_deliverable_package_note(package)
        registry.update_package(package)
    except Exception:
        pass
    return package

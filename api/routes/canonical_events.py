"""Read-only operator inspection for configured canonical event sources.

Every route is operator-only and bound to the verified principal's sole internal workspace
(``backend.identity.http.require_workspace_permission``). A ``workspace_id`` query value may only
repeat that workspace; any other value is refused, and nothing else (headers, body) selects a workspace.
"""
from __future__ import annotations
import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from backend.events.query_models import EventQuery
from backend.events.query_service import WorkspaceScopeError, bind_query_to_workspace, event_query_report, load_events_from_jsonl
from backend.events.supabase_query_service import explain_supabase_readiness, query_supabase_canonical_events
from api.routes.event_access import MAX_EVENT_JSONL_BYTES, admit_event_read, event_read_gate
from backend.identity.errors import WorkspaceAccessDenied
from backend.identity.http import http_exception
from backend.identity.workspaces import WorkspaceAccess
from backend.adapters.research.cj_readonly_api import explain_cj_read_only_readiness

# Operator-only and workspace-bound (see api/routes/event_access.py). Throttled before identity.
router = APIRouter(prefix="/api/events", tags=["canonical-events"], dependencies=[Depends(admit_event_read), Depends(event_read_gate)])
ROOT = Path(__file__).resolve().parents[2]; ARTIFACTS = (ROOT / "artifacts").resolve()
MAX_JSONL_BYTES = MAX_EVENT_JSONL_BYTES

def _query(workspace_id: str | None, event_type: str | None, aggregate_type: str | None, aggregate_id: str | None, limit: int, offset: int, access: WorkspaceAccess) -> EventQuery:
    query = EventQuery(workspace_id, event_type, aggregate_type, aggregate_id, None, None, limit, offset)
    try:
        return bind_query_to_workspace(query, access.workspace_id)
    except WorkspaceScopeError:
        raise http_exception(WorkspaceAccessDenied()) from None


def _empty_jsonl_report(warning: str) -> dict:
    return {
        "timeline": {"events": [], "warnings": [warning]},
        "commerce_runs": [], "shopify_imports": [], "opportunity_rankings": [], "competition_summaries": [],
        "research_portfolios": [], "read_only": True, "network_calls": False, "mutated": False,
    }


def _jsonl_report(query: EventQuery) -> dict:
    configured = os.getenv("MARKETOS_EVENT_READ_JSONL_PATH", "")
    if not configured:
        return _empty_jsonl_report("jsonl_read_path_unconfigured")
    try:
        path = Path(configured).resolve()
    except (OSError, RuntimeError, ValueError):
        return _empty_jsonl_report("jsonl_read_path_unconfigured")
    if path != ARTIFACTS and ARTIFACTS not in path.parents:
        raise HTTPException(403, "configured JSONL read path must remain under artifacts/")
    try:
        is_file = path.is_file()
    except (OSError, ValueError):
        # e.g. ENAMETOOLONG: Path.is_file() only swallows ENOENT/ENOTDIR/EBADF/ELOOP.
        is_file = False
    if not is_file:
        return _empty_jsonl_report("jsonl_read_path_unconfigured")
    events, warnings = load_events_from_jsonl(
        path,
        max_bytes=MAX_JSONL_BYTES,
        oversized_warning="jsonl_read_path_oversized",
        allowed_root=ARTIFACTS,
    )
    return event_query_report(events, query, warnings)
def _report(source: str, query: EventQuery) -> dict:
    if source == "supabase_staging": return query_supabase_canonical_events(query)
    if source == "jsonl": return _jsonl_report(query)
    raise HTTPException(400, "source must be jsonl or supabase_staging")


@router.get("")
def events(workspace_id: str | None = None, event_type: str | None = None, aggregate_type: str | None = None, aggregate_id: str | None = None, limit: int = Query(100, ge=0, le=500), offset: int = Query(0, ge=0), source: str = "jsonl", request: Request = None, access: WorkspaceAccess = Depends(event_read_gate)):
    return _report(source, _query(workspace_id, event_type, aggregate_type, aggregate_id, limit, offset, access))
@router.get("/timeline")
def timeline(workspace_id: str | None = None, event_type: str | None = None, aggregate_type: str | None = None, aggregate_id: str | None = None, limit: int = Query(100, ge=0, le=500), offset: int = Query(0, ge=0), source: str = "jsonl", request: Request = None, access: WorkspaceAccess = Depends(event_read_gate)):
    return _report(source, _query(workspace_id, event_type, aggregate_type, aggregate_id, limit, offset, access))["timeline"]
@router.get("/commerce-runs")
def commerce_runs(workspace_id: str | None = None, limit: int = Query(100, ge=0, le=500), offset: int = Query(0, ge=0), source: str = "jsonl", request: Request = None, access: WorkspaceAccess = Depends(event_read_gate)):
    return {"runs": _report(source, _query(workspace_id, None, None, None, limit, offset, access))["commerce_runs"], "read_only": True}
@router.get("/shopify-imports")
def shopify_imports(workspace_id: str | None = None, limit: int = Query(100, ge=0, le=500), offset: int = Query(0, ge=0), source: str = "jsonl", request: Request = None, access: WorkspaceAccess = Depends(event_read_gate)):
    return {"imports": _report(source, _query(workspace_id, None, None, None, limit, offset, access))["shopify_imports"], "read_only": True}
@router.get("/supplier-evidence")
def supplier_evidence(workspace_id: str | None = None, limit: int = Query(100, ge=0, le=500), offset: int = Query(0, ge=0), source: str = "jsonl", request: Request = None, access: WorkspaceAccess = Depends(event_read_gate)):
    """Supplier-evidence events for one workspace: requested/observed/
    degraded attempts plus the resulting economics-enrichment record, newest
    first. A thin filter over the existing timeline (same events the
    generic /api/events?event_type=... already exposes) — no second query
    engine."""
    events = _report(source, _query(workspace_id, None, None, None, limit, offset, access))["timeline"]["events"]
    supplier_event_types = {"supplier_evidence_requested", "supplier_product_observed", "supplier_evidence_degraded", "commerce_economics_enriched"}
    return {"events": [event for event in events if event.get("event_type") in supplier_event_types], "read_only": True}
@router.get("/opportunity-rankings")
def opportunity_rankings(workspace_id: str | None = None, limit: int = Query(100, ge=0, le=500), offset: int = Query(0, ge=0), source: str = "jsonl", request: Request = None, access: WorkspaceAccess = Depends(event_read_gate)):
    """Decoded opportunity-ranking summaries: composite score, confidence,
    observed/derived/assumed/unknown mix, and per-dimension breakdown for
    every scored candidate in a run — the explainable view an operator
    reads to see why a candidate ranked where it did. Same
    query_service.py::build_*_summaries pattern as /commerce-runs and
    /shopify-imports; not a second query engine."""
    return {"rankings": _report(source, _query(workspace_id, None, None, None, limit, offset, access))["opportunity_rankings"], "read_only": True}
@router.get("/opportunity-scoring")
def opportunity_scoring(workspace_id: str | None = None, limit: int = Query(100, ge=0, le=500), offset: int = Query(0, ge=0), source: str = "jsonl", request: Request = None, access: WorkspaceAccess = Depends(event_read_gate)):
    """Opportunity-scoring events for one workspace: started/candidate-
    scored/ranked/completed, newest first. A thin filter over the existing
    timeline (same pattern as /api/events/supplier-evidence) — no second
    query engine."""
    events = _report(source, _query(workspace_id, None, None, None, limit, offset, access))["timeline"]["events"]
    scoring_event_types = {"opportunity_scoring_started", "candidate_scored", "opportunity_ranked", "opportunity_scoring_completed"}
    return {"events": [event for event in events if event.get("event_type") in scoring_event_types], "read_only": True}
@router.get("/competition-evidence")
def competition_evidence(workspace_id: str | None = None, limit: int = Query(100, ge=0, le=500), offset: int = Query(0, ge=0), source: str = "jsonl", request: Request = None, access: WorkspaceAccess = Depends(event_read_gate)):
    """Competition-intelligence events for one workspace: observed listings/
    summary/pricing/completed, newest first. A thin filter over the
    existing timeline (same pattern as /api/events/supplier-evidence and
    /api/events/opportunity-scoring) — no second query engine."""
    events = _report(source, _query(workspace_id, None, None, None, limit, offset, access))["timeline"]["events"]
    competition_event_types = {"competition_observed", "competition_summary_created", "market_pricing_computed", "market_intelligence_completed"}
    return {"events": [event for event in events if event.get("event_type") in competition_event_types], "read_only": True}
@router.get("/competition-summaries")
def competition_summaries(workspace_id: str | None = None, limit: int = Query(100, ge=0, le=500), offset: int = Query(0, ge=0), source: str = "jsonl", request: Request = None, access: WorkspaceAccess = Depends(event_read_gate)):
    """Decoded competition-summary reports: observed competitor count,
    median price, saturation, maturity, confidence, observed offers, and
    margin — the explainable view an operator reads to see why a market
    looks the way it does. Same query_service.py::build_*_summaries
    pattern as /commerce-runs and /opportunity-rankings; not a second query
    engine."""
    return {"summaries": _report(source, _query(workspace_id, None, None, None, limit, offset, access))["competition_summaries"], "read_only": True}
@router.get("/research-portfolio")
def research_portfolio(workspace_id: str | None = None, limit: int = Query(100, ge=0, le=500), offset: int = Query(0, ge=0), source: str = "jsonl", request: Request = None, access: WorkspaceAccess = Depends(event_read_gate)):
    """Decoded Product Research Intelligence summaries: candidate/cluster
    counts, bucket counts, quality metrics, cluster membership, and any
    ranking movements — the explainable view an operator reads to see how
    a research portfolio was built. Same query_service.py::build_*_summaries
    pattern as /opportunity-rankings and /competition-summaries; not a
    second query engine."""
    return {"portfolios": _report(source, _query(workspace_id, None, None, None, limit, offset, access))["research_portfolios"], "read_only": True}
@router.get("/product-research")
def product_research(workspace_id: str | None = None, limit: int = Query(100, ge=0, le=500), offset: int = Query(0, ge=0), source: str = "jsonl", request: Request = None, access: WorkspaceAccess = Depends(event_read_gate)):
    """Product Research events for one workspace: discovered/clustered/
    portfolio-updated/ranking-changed/completed, newest first. A thin
    filter over the existing timeline (same pattern as
    /api/events/opportunity-scoring and /api/events/competition-evidence)
    — no second query engine."""
    events = _report(source, _query(workspace_id, None, None, None, limit, offset, access))["timeline"]["events"]
    research_event_types = {"candidate_discovered", "candidate_clustered", "research_portfolio_updated", "ranking_changed", "research_completed"}
    return {"events": [event for event in events if event.get("event_type") in research_event_types], "read_only": True}
@router.get("/readiness")
def readiness():
    return {
        "jsonl_path_configured": bool(os.getenv("MARKETOS_EVENT_READ_JSONL_PATH")),
        "supabase_staging": explain_supabase_readiness(),
        "supplier_auth_readonly": explain_cj_read_only_readiness(),
        "read_only": True, "mutated": False,
    }

"""Read-only operator inspection for configured canonical event sources."""
from __future__ import annotations
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from backend.events.query_models import EventQuery
from backend.events.query_service import event_query_report, load_events_from_jsonl
from backend.events.supabase_query_service import explain_supabase_readiness, query_supabase_canonical_events
from backend.security.rate_limit import check_rate_limit, event_read_policy

router = APIRouter(prefix="/api/events", tags=["canonical-events"])
ROOT = Path(__file__).resolve().parents[2]; ARTIFACTS = (ROOT / "artifacts").resolve()

def _query(workspace_id: str | None, event_type: str | None, aggregate_type: str | None, aggregate_id: str | None, limit: int, offset: int) -> EventQuery:
    return EventQuery(workspace_id, event_type, aggregate_type, aggregate_id, None, None, limit, offset)
def _jsonl_report(query: EventQuery) -> dict:
    configured = os.getenv("MARKETOS_EVENT_READ_JSONL_PATH", "")
    if not configured: return {"timeline": {"events": [], "warnings": ["jsonl_read_path_unconfigured"]}, "commerce_runs": [], "shopify_imports": [], "read_only": True, "network_calls": False, "mutated": False}
    path = Path(configured).resolve()
    if ARTIFACTS not in path.parents: raise HTTPException(403, "configured JSONL read path must remain under artifacts/")
    events, warnings = load_events_from_jsonl(path); return event_query_report(events, query, warnings)
def _report(source: str, query: EventQuery) -> dict:
    if source == "supabase_staging": return query_supabase_canonical_events(query)
    if source == "jsonl": return _jsonl_report(query)
    raise HTTPException(400, "source must be jsonl or supabase_staging")


def _read_limit_response(request: Request | None) -> JSONResponse | None:
    key = getattr(getattr(request, "client", None), "host", None) or "direct"
    decision = check_rate_limit(event_read_policy(), key)
    if decision.allowed:
        return None
    return JSONResponse(
        {"status": "rate_limited", "retry_after_seconds": decision.retry_after_seconds, "read_only": True, "mutated": False},
        status_code=429,
        headers={"Retry-After": str(decision.retry_after_seconds)},
    )

@router.get("")
def events(workspace_id: str | None = None, event_type: str | None = None, aggregate_type: str | None = None, aggregate_id: str | None = None, limit: int = Query(100, ge=0, le=500), offset: int = Query(0, ge=0), source: str = "jsonl", request: Request = None):
    if limited := _read_limit_response(request): return limited
    return _report(source, _query(workspace_id, event_type, aggregate_type, aggregate_id, limit, offset))
@router.get("/timeline")
def timeline(workspace_id: str | None = None, event_type: str | None = None, aggregate_type: str | None = None, aggregate_id: str | None = None, limit: int = Query(100, ge=0, le=500), offset: int = Query(0, ge=0), source: str = "jsonl", request: Request = None):
    if limited := _read_limit_response(request): return limited
    return _report(source, _query(workspace_id, event_type, aggregate_type, aggregate_id, limit, offset))["timeline"]
@router.get("/commerce-runs")
def commerce_runs(workspace_id: str | None = None, limit: int = Query(100, ge=0, le=500), offset: int = Query(0, ge=0), source: str = "jsonl", request: Request = None):
    if limited := _read_limit_response(request): return limited
    return {"runs": _report(source, _query(workspace_id, None, None, None, limit, offset))["commerce_runs"], "read_only": True}
@router.get("/shopify-imports")
def shopify_imports(workspace_id: str | None = None, limit: int = Query(100, ge=0, le=500), offset: int = Query(0, ge=0), source: str = "jsonl", request: Request = None):
    if limited := _read_limit_response(request): return limited
    return {"imports": _report(source, _query(workspace_id, None, None, None, limit, offset))["shopify_imports"], "read_only": True}
@router.get("/readiness")
def readiness(): return {"jsonl_path_configured": bool(os.getenv("MARKETOS_EVENT_READ_JSONL_PATH")), "supabase_staging": explain_supabase_readiness(), "read_only": True, "mutated": False}

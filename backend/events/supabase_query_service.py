"""Server-side, read-only Supabase canonical event queries."""
from __future__ import annotations
import os
from typing import Any
from backend.contracts.events import Event
from .adapters.supabase import SupabaseEventRepositoryError
from .adapters.supabase_staging import explain_supabase_staging_readiness
from .query_models import EventQuery
from .query_service import event_query_report

def explain_supabase_readiness(environ: dict[str, str] | None = None) -> dict[str, Any]:
    values = os.environ if environ is None else environ; staging = explain_supabase_staging_readiness(values)
    missing = [key for key in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY") if not values.get(key)]
    return {"configured": not missing, "missing_env": missing, "server_side_only": True, "write_gate_enabled": staging["write_gate_enabled"], "read_only": True, "network_calls": False}

def build_supabase_read_client(environ: dict[str, str] | None = None, client: Any | None = None) -> Any:
    if client is not None: return client
    values = os.environ if environ is None else environ
    readiness = explain_supabase_readiness(values)
    if not readiness["configured"]: raise SupabaseEventRepositoryError("Supabase read view is unconfigured; set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY server-side")
    try:
        from supabase import create_client
    except ImportError as exc: raise SupabaseEventRepositoryError("Supabase client package is unavailable") from exc
    return create_client(values["SUPABASE_URL"], values["SUPABASE_SERVICE_ROLE_KEY"])

def _rows(response: Any) -> list[dict[str, Any]]:
    value = response.get("data") if isinstance(response, dict) else getattr(response, "data", response)
    return list(value or []) if isinstance(value, (list, tuple)) else []

def query_supabase_canonical_events(query: EventQuery, client: Any | None = None, environ: dict[str, str] | None = None) -> dict[str, Any]:
    reader = build_supabase_read_client(environ, client); request = reader.table("canonical_events").select("*")
    for column, value in (("workspace_id", query.workspace_id), ("event_type", query.event_type), ("aggregate_type", query.aggregate_type), ("aggregate_id", query.aggregate_id), ("correlation_id", query.correlation_id), ("source", query.source)):
        if value is not None: request = request.eq(column, value)
    if query.since is not None: request = request.gte("occurred_at", query.since)
    if query.until is not None: request = request.lte("occurred_at", query.until)
    request = request.order("occurred_at", desc=query.sort == "desc").order("event_id", desc=query.sort == "desc").range(query.offset, query.offset + max(0, query.limit - 1))
    events = [Event.from_dict({key: row.get(key) for key in Event.__dataclass_fields__}) for row in _rows(request.execute())]
    # Keep a local filter pass for injected/fake clients and as a defensive
    # guard against an adapter that does not honour a server-side predicate.
    # Offset is already applied by the Supabase range call, so it must not be
    # applied again while summarising the returned page.
    local_query = EventQuery(
        workspace_id=query.workspace_id,
        event_type=query.event_type,
        aggregate_type=query.aggregate_type,
        aggregate_id=query.aggregate_id,
        correlation_id=query.correlation_id,
        source=query.source,
        limit=query.limit,
        since=query.since,
        until=query.until,
        sort=query.sort,
    )
    report = event_query_report(events, local_query, ())
    report["source"] = "supabase_staging"; report["readiness"] = explain_supabase_readiness(environ); report["network_calls"] = client is None
    return report

__all__ = ["build_supabase_read_client", "explain_supabase_readiness", "query_supabase_canonical_events"]

"""Explicitly gated public-network Commerce MVP operator endpoint."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.ecommerce.shopify_readonly.events import shopify_batch_events
from backend.ecommerce.shopify_readonly.importer import import_shopify_readonly
from backend.events.adapters.supabase_staging import build_supabase_staging_repository, explain_supabase_staging_readiness
from backend.events.repository import JsonlEventRepository
from backend.events.supabase_event_validation import validate_events_for_supabase
from backend.mvp_commerce.public_run import run_commerce_mvp_from_public_rss
from backend.security.rate_limit import check_rate_limit, public_run_policy

router = APIRouter(prefix="/api/commerce-mvp", tags=["commerce-mvp"])
ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = (ROOT / "artifacts").resolve()


class PublicCommerceRunRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    workspace_id: str = Field(default="commerce-mvp-public", min_length=1, max_length=100)
    max_signals: int = Field(default=10, ge=1, le=25)
    max_candidates: int = Field(default=5, ge=1, le=10)
    allow_public_network: bool = False
    include_shopify_fixture_context: bool = False
    source: Literal["google_news_rss"] = "google_news_rss"
    event_target: Literal["none", "jsonl", "supabase_staging", "both"] = "none"
    operator_note: str = Field(default="", max_length=500)
    attempt_supplier_evidence: bool = False
    supplier_candidate_urls: list[str] = Field(default_factory=list, max_length=5)
    use_opportunity_ranking: bool = False


def _blocked(message: str, *, request: PublicCommerceRunRequest) -> dict:
    return {
        "status": "blocked",
        "public_source_status": "blocked",
        "blockers": [message],
        "query": request.query,
        "source": request.source,
        "read_only": True,
        "advisory": True,
        "mutated": False,
        "network_used": False,
        "write_targets": [],
    }


def _client_key(http_request: Request | None) -> str:
    return getattr(getattr(http_request, "client", None), "host", None) or "direct"


def _request_id(http_request: Request | None) -> str | None:
    return getattr(getattr(http_request, "state", None), "marketos_request_id", None)


def _server_jsonl_path() -> Path | None:
    configured = os.getenv("MARKETOS_EVENT_WRITE_JSONL_PATH", "")
    if not configured:
        return None
    path = Path(configured).resolve()
    return path if ARTIFACTS in path.parents else None


@router.post("/public-run")
def public_run(request: PublicCommerceRunRequest, http_request: Request = None) -> dict:
    """Run one bounded public RSS query after explicit server/operator gates."""
    if os.getenv("MARKETOS_PUBLIC_COMMERCE_RUNS", "0") != "1":
        return _blocked("MARKETOS_PUBLIC_COMMERCE_RUNS=1 is required on the server", request=request)
    if not request.allow_public_network:
        return _blocked("allow_public_network must be true for a public-network run", request=request)
    decision = check_rate_limit(public_run_policy(), _client_key(http_request))
    if not decision.allowed:
        return JSONResponse(
            {
                "status": "rate_limited",
                "blockers": ["public_commerce_run_rate_limit_exceeded"],
                "retry_after_seconds": decision.retry_after_seconds,
                "request_id": _request_id(http_request),
                "read_only": True,
                "advisory": True,
                "mutated": False,
            },
            status_code=429,
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )

    target = request.event_target
    jsonl_path = _server_jsonl_path() if target in {"jsonl", "both"} else None
    if target in {"jsonl", "both"} and jsonl_path is None:
        return _blocked("MARKETOS_EVENT_WRITE_JSONL_PATH must point beneath artifacts/ for JSONL writes", request=request)
    supabase_readiness = explain_supabase_staging_readiness()
    if target in {"supabase_staging", "both"} and not supabase_readiness["configured"]:
        return _blocked("Supabase staging requires its server-side credentials and explicit write gate", request=request)

    context = None
    batch = None
    if request.include_shopify_fixture_context:
        batch, context = import_shopify_readonly(ROOT / "tests/fixtures/shopify_readonly/shopify_sample.json", request.workspace_id)

    # Supplier evidence is an enhancement on top of the gated public-commerce
    # run, not a second capability with its own blocking gate: if the
    # operator asks for it but the server hasn't opted in, it's silently
    # not attempted (economics fall back to assumptions) rather than
    # blocking the whole run.
    attempt_supplier_evidence = request.attempt_supplier_evidence and os.getenv("MARKETOS_SUPPLIER_EVIDENCE_LIVE", "0") == "1"

    result = run_commerce_mvp_from_public_rss(
        workspace_id=request.workspace_id,
        query=request.query,
        max_signals=request.max_signals,
        max_candidates=request.max_candidates,
        allow_network=True,
        cache_dir=os.getenv("MARKETOS_PUBLIC_SIGNAL_CACHE_DIR", str(ROOT / "artifacts/public-signal-cache")),
        shopify_store_context=context,
        operator_note=request.operator_note,
        attempt_supplier_evidence=attempt_supplier_evidence,
        supplier_candidate_urls=list(request.supplier_candidate_urls),
        use_opportunity_ranking=request.use_opportunity_ranking,
    )
    events = list(result.events)
    if batch is not None:
        events = shopify_batch_events(batch, context) + events
    written: list[str] = []
    if jsonl_path is not None:
        JsonlEventRepository(jsonl_path).append_many(events)
        written.append("jsonl")
    if target in {"supabase_staging", "both"}:
        build_supabase_staging_repository().append_many(events)
        written.append("supabase_staging")
    report = result.to_dict()
    report.update({
        "status": result.status,
        "write_targets": written,
        "event_count": len(events),
        "supplier_evidence_attempted": attempt_supplier_evidence,
        "opportunity_ranking_used": request.use_opportunity_ranking,
        "read_only": True,
        "advisory": True,
        "mutated": False,
        "event_type_counts": dict(sorted({event.event_type: sum(item.event_type == event.event_type for item in events) for event in events}.items())),
    })
    if target in {"supabase_staging", "both"}:
        report["supabase_validation"] = validate_events_for_supabase(events)
    return report


__all__ = ["PublicCommerceRunRequest", "router"]

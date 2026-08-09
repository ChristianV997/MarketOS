from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query

from backend.discovery.discovery_registry import get_discovery_registry
from backend.discovery.market_discovery_runner import run_market_discovery

router = APIRouter(prefix="/api/discovery", tags=["discovery"])


@router.post("/market-discovery")
def market_discovery(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    try:
        paths = payload.get("dataset_paths") or []
        if not isinstance(paths, list) or len(paths) > 10:
            return {"status": "blocked", "blocked_reasons": ["dataset_path_limit_exceeded"]}
        max_categories = min(max(int(payload.get("max_categories", 10)), 0), 50)
        max_hypotheses = min(max(int(payload.get("max_hypotheses", 20)), 0), 100)
        return run_market_discovery(
            workspace_id=str(payload.get("workspace_id", "default")),
            title=str(payload.get("title", "Autonomous Market Discovery")),
            objective=str(payload.get("objective", "Find promising product categories and product hypotheses")),
            dataset_paths=[str(item) for item in paths],
            source_names=payload.get("source_names"),
            max_categories=max_categories,
            max_hypotheses=max_hypotheses,
            run_validation_services=bool(payload.get("run_validation_services", True)),
        )
    except Exception as exc:
        return {"status": "error", "error": "market_discovery_failed", "error_type": type(exc).__name__}


@router.get("/evidence")
def evidence(source_name: str | None = Query(None), entity_type: str | None = Query(None), signal_type: str | None = Query(None), limit: int = Query(100, ge=0, le=1000)) -> dict[str, Any]:
    try:
        items = get_discovery_registry().list_evidence(source_name, entity_type, signal_type, limit)
        return {"evidence": [item.to_dict() for item in items], "count": len(items)}
    except Exception as exc:
        return {"status": "error", "error": "evidence_listing_failed", "error_type": type(exc).__name__, "evidence": []}


@router.get("/categories")
def categories(workspace_id: str | None = Query(None), status: str | None = Query(None), limit: int = Query(50, ge=0, le=500)) -> dict[str, Any]:
    items = get_discovery_registry().list_category_discoveries(workspace_id, status, limit)
    return {"discoveries": [item.to_dict() for item in items], "count": len(items)}


@router.get("/categories/{discovery_id}")
def category(discovery_id: str) -> dict[str, Any]:
    item = get_discovery_registry().get_category_discovery(discovery_id)
    return {"status": "not_found", "discovery_id": discovery_id} if item is None else {"discovery": item.to_dict()}


@router.get("/hypotheses")
def hypotheses(workspace_id: str | None = Query(None), discovery_id: str | None = Query(None), limit: int = Query(50, ge=0, le=500)) -> dict[str, Any]:
    items = get_discovery_registry().list_product_hypothesis_runs(workspace_id, discovery_id, limit)
    return {"hypothesis_runs": [item.to_dict() for item in items], "count": len(items)}


@router.get("/hypotheses/{hypothesis_run_id}")
def hypothesis(hypothesis_run_id: str) -> dict[str, Any]:
    item = get_discovery_registry().get_product_hypothesis_run(hypothesis_run_id)
    return {"status": "not_found", "hypothesis_run_id": hypothesis_run_id} if item is None else {"hypotheses": item.to_dict()}

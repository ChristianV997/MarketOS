"""Market-research ingestion and canonical trend read APIs."""
from __future__ import annotations

import os

from fastapi import APIRouter, Query

from backend.research import IngestionRunStore, TrendRecordStore

router = APIRouter()


def _store() -> TrendRecordStore:
    return TrendRecordStore(path=os.getenv("RESEARCH_DB_PATH", "backend/state/research.db"))


def _runs() -> IngestionRunStore:
    return IngestionRunStore(path=os.getenv("RESEARCH_DB_PATH", "backend/state/research.db"))


@router.get("/research/ingestion/status")
def ingestion_status():
    return {"latest": _runs().latest()}


@router.get("/research/ingestion/runs")
def ingestion_runs(limit: int = Query(default=20, ge=1, le=100)):
    return {"runs": _runs().list(limit)}


@router.get("/research/trends/top")
def top_research_trends(
    limit: int = Query(default=20, ge=1, le=100),
    require_competition: bool = False,
):
    return {
        "records": _store().findTopN(limit, require_competition=require_competition),
    }

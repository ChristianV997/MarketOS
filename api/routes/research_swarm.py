"""Read-only operational status for governed research-swarm jobs."""
from __future__ import annotations

import os

from fastapi import APIRouter, Query

from backend.research.swarm import SwarmJobStore, swarm_readiness

router = APIRouter()


def _store() -> SwarmJobStore:
    return SwarmJobStore(path=os.getenv("RESEARCH_DB_PATH", "backend/state/research.db"))


@router.get("/research/swarm/status")
def research_swarm_status():
    jobs = _store().list_public(5)
    return {"readiness": swarm_readiness(), "recent_jobs": jobs}


@router.get("/research/swarm/jobs")
def research_swarm_jobs(limit: int = Query(default=20, ge=1, le=100)):
    return {"jobs": _store().list_public(limit)}

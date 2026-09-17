"""api.control — operator-level product pause, resume, budget, and approval controls."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.security.auth import AuthenticatedActor, require_operator

_log = logging.getLogger("marketos.control")

router = APIRouter()

STATE: dict[str, Any] = {
    "paused_products": set(),
    "manual_budgets": {},
    "approved_products": set(),
}


@router.post("/pause/{product_id}")
def pause(
    product_id: str,
    actor: AuthenticatedActor = Depends(require_operator),
) -> dict[str, str]:
    pid = product_id.strip()
    STATE["paused_products"].add(pid)
    _log.info("product_paused actor=%s product_id=%s", actor.actor_id, pid)
    return {"status": "paused", "product_id": pid}


@router.post("/resume/{product_id}")
def resume(
    product_id: str,
    actor: AuthenticatedActor = Depends(require_operator),
) -> dict[str, str]:
    pid = product_id.strip()
    STATE["paused_products"].discard(pid)
    _log.info("product_resumed actor=%s product_id=%s", actor.actor_id, pid)
    return {"status": "resumed", "product_id": pid}


@router.post("/budget/{product_id}")
def override_budget(
    product_id: str,
    budget: float,
    actor: AuthenticatedActor = Depends(require_operator),
) -> dict[str, Any]:
    if budget <= 0:
        raise HTTPException(status_code=400, detail="budget must be positive")
    pid = product_id.strip()
    STATE["manual_budgets"][pid] = budget
    _log.info("budget_overridden actor=%s product_id=%s budget=%.2f", actor.actor_id, pid, budget)
    return {"status": "updated", "product_id": pid, "budget": budget}


@router.post("/approve/{product_id}")
def approve(
    product_id: str,
    actor: AuthenticatedActor = Depends(require_operator),
) -> dict[str, str]:
    pid = product_id.strip()
    STATE["approved_products"].add(pid)
    _log.info("product_approved actor=%s product_id=%s", actor.actor_id, pid)
    return {"status": "approved", "product_id": pid}


__all__ = ["STATE", "router"]

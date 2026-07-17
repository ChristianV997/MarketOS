"""api.dropship_dashboard — REST API for dropship campaign metrics and analytics.

Exposes endpoints for real-time campaign monitoring, profitability tracking,
and cost analysis.

Usage:
  from fastapi import FastAPI
  from api.dropship_dashboard import router as dropship_router

  app = FastAPI()
  app.include_router(dropship_router, prefix="/api/dropship", tags=["dropship"])

  # GET /api/dropship/summary
  # GET /api/dropship/campaigns
  # GET /api/dropship/costs
  # GET /api/dropship/errors
  # GET /api/dropship/status
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query

_log = logging.getLogger(__name__)

router = APIRouter()

# Paths to persistent state
_DROPSHIP_SNAPSHOT_PATH = Path("state/dropship.json")
_COSTS_DB_PATH = Path("state/costs.jsonl")
_ERRORS_DB_PATH = Path("state/errors.jsonl")


# ── health and status ─────────────────────────────────────────────────────────


@router.get("/status")
async def get_status() -> dict:
    """System health and configuration status."""
    from backend.config import list_configured_services, is_dry_run

    services = list_configured_services()
    dry_run = {s: is_dry_run(s) for s in services.keys()}

    return {
        "status": "ok",
        "services": services,
        "dry_run_modes": dry_run,
        "timestamp": datetime.now().isoformat(),
    }


# ── campaign summary and history ──────────────────────────────────────────────


@router.get("/summary")
async def get_summary() -> dict:
    """Latest dropship cycle summary."""
    if not _DROPSHIP_SNAPSHOT_PATH.exists():
        return {
            "status": "no_cycles_yet",
            "discovered": 0,
            "validated": 0,
            "green": 0,
            "launched": 0,
            "launches": [],
        }

    try:
        with open(_DROPSHIP_SNAPSHOT_PATH) as f:
            snapshot = json.load(f)
        return snapshot
    except Exception as exc:
        _log.error("Failed to load snapshot: %s", exc)
        return {"status": "error", "error": str(exc)}


@router.get("/campaigns")
async def get_campaigns(
    limit: int = Query(100, ge=1, le=1000),
    status_filter: Optional[str] = Query(None),
) -> dict:
    """List all launched campaigns with their performance."""
    campaigns = []

    # Load from snapshot (most recent)
    if _DROPSHIP_SNAPSHOT_PATH.exists():
        try:
            with open(_DROPSHIP_SNAPSHOT_PATH) as f:
                snapshot = json.load(f)
            for launch in snapshot.get("launches", [])[:limit]:
                for campaign in launch.get("campaigns", []):
                    if status_filter and campaign.get("status") != status_filter:
                        continue
                    campaigns.append({
                        "product": launch.get("product"),
                        "campaign_id": campaign.get("campaign_id"),
                        "platform": campaign.get("platform"),
                        "status": campaign.get("status"),
                        "budget": campaign.get("budget"),
                        "hook": campaign.get("hook"),
                        "angle": campaign.get("angle"),
                        "confidence": launch.get("confidence"),
                        "predicted_roas": launch.get("predicted_roas"),
                    })
        except Exception as exc:
            _log.error("Failed to load campaigns: %s", exc)

    return {
        "count": len(campaigns),
        "campaigns": campaigns,
        "last_updated": datetime.now().isoformat(),
    }


# ── profitability and ROAS ────────────────────────────────────────────────────


@router.get("/profitability")
async def get_profitability(
    lookback_days: int = Query(7, ge=1, le=90),
) -> dict:
    """Profitability summary for the last N days."""
    snapshot = {}
    if _DROPSHIP_SNAPSHOT_PATH.exists():
        try:
            with open(_DROPSHIP_SNAPSHOT_PATH) as f:
                snapshot = json.load(f)
        except Exception:
            pass

    total_budget = 0.0
    total_predicted_spend = 0.0
    total_predicted_revenue = 0.0
    num_products = 0

    for launch in snapshot.get("launches", []):
        num_products += 1
        budget = launch.get("budget", 0.0)
        predicted_roas = launch.get("predicted_roas", 1.0)
        total_budget += budget
        total_predicted_spend += budget
        total_predicted_revenue += budget * predicted_roas

    predicted_profit = total_predicted_revenue - total_predicted_spend
    predicted_roi = (predicted_profit / total_predicted_spend * 100) if total_predicted_spend > 0 else 0

    return {
        "period_days": lookback_days,
        "num_products_launched": num_products,
        "total_spend": round(total_predicted_spend, 2),
        "total_predicted_revenue": round(total_predicted_revenue, 2),
        "total_predicted_profit": round(predicted_profit, 2),
        "avg_roas": round(total_predicted_revenue / total_predicted_spend, 2) if total_predicted_spend > 0 else 0,
        "predicted_roi_pct": round(predicted_roi, 1),
        "breakeven_threshold": 1.0,
        "note": "These are predictions; real ROAS comes from campaign metrics",
    }


# ── cost tracking ─────────────────────────────────────────────────────────────


@router.get("/costs/summary")
async def get_cost_summary(
    lookback_minutes: int = Query(60, ge=1, le=10080),
) -> dict:
    """API cost summary for the last N minutes."""
    from backend.cost_tracking import cost_report

    try:
        report = cost_report(lookback_minutes=lookback_minutes)
        return {
            "status": "ok",
            **report,
        }
    except Exception as exc:
        _log.error("Failed to get cost report: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "total_spend": 0.0,
        }


@router.get("/costs/timeline")
async def get_cost_timeline(
    lookback_minutes: int = Query(60, ge=1, le=10080),
    bucket_minutes: int = Query(5, ge=1, le=60),
) -> dict:
    """Cost timeline bucketed by time."""
    from backend.cost_tracking import cost_timeline

    try:
        timeline = cost_timeline(
            lookback_minutes=lookback_minutes,
            bucket_minutes=bucket_minutes,
        )
        return {
            "status": "ok",
            "data": timeline,
            "bucket_size_minutes": bucket_minutes,
            "period_minutes": lookback_minutes,
        }
    except Exception as exc:
        _log.error("Failed to get cost timeline: %s", exc)
        return {"status": "error", "error": str(exc), "data": []}


@router.get("/costs/by-service")
async def get_costs_by_service(
    lookback_minutes: int = Query(60, ge=1, le=10080),
) -> dict:
    """Cost breakdown by service (Meta, TikTok, Shopify, etc.)."""
    from backend.cost_tracking import cost_report

    try:
        report = cost_report(lookback_minutes=lookback_minutes)
        return {
            "status": "ok",
            "by_service": report.get("by_service", {}),
            "total_spend": report.get("total_spend", 0.0),
            "period_minutes": lookback_minutes,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc), "by_service": {}}


# ── error tracking ───────────────────────────────────────────────────────────


@router.get("/errors/summary")
async def get_error_summary(
    lookback_hours: int = Query(24, ge=1, le=720),
) -> dict:
    """Error summary for the last N hours."""
    from backend.error_telemetry import error_summary

    try:
        summary = error_summary(lookback_minutes=lookback_hours * 60)
        return {
            "status": "ok",
            **summary,
        }
    except Exception as exc:
        _log.error("Failed to get error summary: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "total_errors": 0,
        }


@router.get("/errors/recent")
async def get_recent_errors(
    stage: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """Get recent error details."""
    from backend.error_telemetry import error_details

    try:
        details = error_details(stage=stage, limit=limit)
        return {
            "status": "ok",
            "count": len(details),
            "errors": details,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc), "errors": []}


# ── credentials and config ────────────────────────────────────────────────────


@router.get("/config/services")
async def get_configured_services() -> dict:
    """List configured services and their status."""
    from backend.config import list_configured_services

    services = list_configured_services()
    return {
        "status": "ok",
        "services": services,
        "ready_services": [s for s, ready in services.items() if ready],
        "requires_setup": [s for s, ready in services.items() if not ready],
    }


@router.get("/config/credentials-needed")
async def get_credentials_needed() -> dict:
    """List which credentials are missing."""
    from backend.config import _SERVICE_CREDENTIALS, get_credential

    missing = {}
    for service, keys in _SERVICE_CREDENTIALS.items():
        service_missing = [k for k in keys if not get_credential(k)]
        if service_missing:
            missing[service] = service_missing

    return {
        "status": "ok" if not missing else "setup_required",
        "missing_credentials": missing,
        "instructions": {
            "meta": "Get credentials from https://developers.facebook.com/apps/",
            "tiktok": "Get credentials from https://business.tiktok.com/",
            "shopify": "Get API key from Shopify Store > Apps and channels > App and sales channel settings",
        },
    }


__all__ = ["router"]

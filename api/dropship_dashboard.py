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
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query

from backend.core.persistence import state_path

_log = logging.getLogger(__name__)

router = APIRouter()

# Paths to persistent state (respect MARKETOS_STATE_DIR)
_DROPSHIP_SNAPSHOT_PATH = Path(state_path("dropship.json"))


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
    """Actual profitability (real metrics + predictions)."""
    try:
        from backend.metrics.profitability import calculate_profitability
        return calculate_profitability(lookback_days=lookback_days)
    except Exception as exc:
        _log.error("Failed to calculate profitability: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "total_profit": 0.0,
        }


@router.get("/profitability/products")
async def get_profitability_by_product(
    lookback_days: int = Query(7, ge=1, le=90),
) -> dict:
    """Profitability breakdown by product."""
    try:
        from backend.metrics.profitability import calculate_profitability
        report = calculate_profitability(lookback_days=lookback_days)
        return {
            "status": "ok",
            "period_days": lookback_days,
            "products": report.get("products", []),
            "summary": {
                "total_profit": report.get("total_profit", 0.0),
                "roi_pct": report.get("roi_pct", 0.0),
                "profitable_count": report.get("profitable_count", 0),
            },
        }
    except Exception as exc:
        _log.error("Failed to get product profitability: %s", exc)
        return {"status": "error", "error": str(exc), "products": []}


@router.get("/profitability/product/{product_name}")
async def get_product_timeline(product_name: str) -> dict:
    """Profitability timeline for a single product."""
    try:
        from backend.metrics.profitability import product_timeline
        timeline = product_timeline(product_name, lookback_days=30)
        return {
            "status": "ok",
            "product": product_name,
            "data_points": len(timeline),
            "timeline": timeline,
        }
    except Exception as exc:
        _log.error("Failed to get product timeline: %s", exc)
        return {"status": "error", "error": str(exc), "timeline": []}


@router.get("/forecast")
async def get_revenue_forecast(
    horizon_days: int = Query(7, ge=1, le=90),
) -> dict:
    """Projected revenue bands (pessimistic/realistic/optimistic) from live
    campaigns, with the realistic band corrected by observed prediction error."""
    try:
        from backend.metrics.profitability import revenue_forecast
        return revenue_forecast(horizon_days=horizon_days)
    except Exception as exc:
        _log.error("Failed to compute forecast: %s", exc)
        return {"status": "error", "error": str(exc)}


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


# ── campaign metrics ─────────────────────────────────────────────────────────


@router.get("/metrics/ingest")
async def ingest_metrics() -> dict:
    """Fetch and ingest campaign metrics from real platforms."""
    try:
        from backend.metrics.campaign_metrics import ingest_campaign_metrics
        return ingest_campaign_metrics()
    except Exception as exc:
        _log.error("Failed to ingest metrics: %s", exc)
        return {"status": "error", "error": str(exc)}


@router.get("/metrics/performance")
async def get_campaign_performance(
    lookback_days: int = Query(7, ge=1, le=90),
    platform: Optional[str] = Query(None),
) -> dict:
    """Campaign performance summary."""
    try:
        from backend.metrics.campaign_metrics import campaign_performance
        campaigns = campaign_performance(lookback_days=lookback_days, platform=platform)
        return {
            "status": "ok",
            "count": len(campaigns),
            "campaigns": campaigns,
            "period_days": lookback_days,
            "platform_filter": platform,
        }
    except Exception as exc:
        _log.error("Failed to get performance: %s", exc)
        return {"status": "error", "error": str(exc), "campaigns": []}


@router.get("/metrics/campaign/{campaign_id}")
async def get_campaign_metrics(campaign_id: str) -> dict:
    """Detailed metrics for one campaign."""
    try:
        from backend.metrics.campaign_metrics import campaign_by_id
        metrics = campaign_by_id(campaign_id)
        if not metrics:
            return {"status": "not_found", "campaign_id": campaign_id}
        return {"status": "ok", **metrics}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


# ── budget optimization ───────────────────────────────────────────────────────


@router.get("/optimization/scaling-decisions")
async def get_scaling_decisions() -> dict:
    """Compute budget scaling decisions based on recent performance."""
    try:
        from backend.optimization.budget_scaling import compute_scaling_decisions, apply_scaling_decisions
        decisions = compute_scaling_decisions(lookback_days=3)
        result = apply_scaling_decisions(decisions)
        result["decisions"] = decisions
        return result
    except Exception as exc:
        _log.error("Failed to compute scaling: %s", exc)
        return {"status": "error", "error": str(exc), "decisions": []}


@router.get("/optimization/scaling-summary")
async def get_scaling_summary(
    lookback_days: int = Query(7, ge=1, le=90),
) -> dict:
    """Summary of scaling decisions made."""
    try:
        from backend.optimization.budget_scaling import scaling_summary
        return scaling_summary(lookback_days=lookback_days)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


# ── alerts and reporting ──────────────────────────────────────────────────────


@router.get("/alerts")
async def get_alerts(
    lookback_hours: int = Query(24, ge=1, le=720),
) -> dict:
    """Recent alerts (error bursts, spend bursts, ROAS floors, stalls)."""
    try:
        from backend.monitoring.alerts import alert_summary
        return {"status": "ok", **alert_summary(lookback_hours=lookback_hours)}
    except Exception as exc:
        _log.error("Failed to get alerts: %s", exc)
        return {"status": "error", "error": str(exc), "alerts": []}


@router.post("/alerts/evaluate")
async def trigger_alert_evaluation() -> dict:
    """Run alert checks now (also runs automatically in the orchestrator)."""
    try:
        from backend.monitoring.alerts import evaluate_alerts
        fired = evaluate_alerts()
        return {"status": "ok", "alerts_fired": len(fired), "alerts": fired}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@router.get("/report")
async def get_report(regenerate: bool = Query(False)) -> dict:
    """Latest full status report (profitability, forecast, costs, errors,
    scaling, calibration, alerts). Pass regenerate=true to build fresh."""
    try:
        from backend.reporting.weekly_report import generate_report, latest_report
        if not regenerate:
            existing = latest_report()
            if existing:
                return existing
        return generate_report()
    except Exception as exc:
        _log.error("Failed to build report: %s", exc)
        return {"status": "error", "error": str(exc)}


@router.get("/calibration")
async def get_calibration_report() -> dict:
    """Does validation confidence actually predict real ROAS?"""
    try:
        from backend.metrics.calibration_tuning import confidence_report
        return confidence_report()
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@router.get("/signal-cache")
async def get_signal_cache_status() -> dict:
    """Discovery signal cache freshness."""
    try:
        from backend.discovery.signal_cache import cache_status
        return {"status": "ok", **cache_status()}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@router.get("/discovery/sources")
async def get_discovery_sources_status() -> dict:
    """Health of every registered discovery/market-research data source.

    Reports, per source: live/mock_fallback/mock_only/error/not_registered
    status, required credentials, and the last fetch's signal count/error.
    """
    try:
        from backend.discovery.registry import discovery_registry
        return {"status": "ok", "sources": discovery_registry.status_report()}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


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

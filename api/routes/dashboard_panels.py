"""api.routes.dashboard_panels — campaigns, creatives, risk, geo, accounts, alerts.

Kept as one module (rather than split further) because /alerts calls the
/risk handler directly as a Python function, and both share the mock
campaign/geo/account/creative data and the manual-override store — all
still defined in backend/api.py and referenced via ``_core``.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend import api as _core

router = APIRouter()


@router.post("/ajo/apply")
def ajo_apply(campaign_id: str, action: str, budget_multiplier: float = 1.5):
    """Apply a MarketOS action (pause/scale/hold) to an Adobe AJO campaign."""
    from backend.integrations.adobe_ajo import apply_decision
    try:
        return apply_decision(campaign_id, action, budget_multiplier)
    except Exception:
        return {"error": "AJO action failed", "campaign_id": campaign_id}


@router.get("/campaigns")
def campaigns():
    """Campaign performance table with ROAS, spend, status, and geo filters."""
    rows = _core._state.event_log.rows
    recent = rows[-_core._RECENT_ROWS_WINDOW:] if rows else []

    # Enrich mock campaigns with live avg ROAS from event log if available
    live_avg_roas: float | None = (
        round(sum(r.get("roas", 0) for r in recent) / len(recent), 4)
        if recent else None
    )

    result = []
    for c in _core._MOCK_CAMPAIGNS:
        entry = dict(c)
        # Apply any manual overrides
        override = _core._campaign_overrides.get(c["campaign_id"])
        if override:
            entry["status"] = override
            entry["override"] = True
        else:
            entry["override"] = False
        # Attach live system avg_roas as a reference
        if live_avg_roas is not None:
            entry["system_avg_roas"] = live_avg_roas
        result.append(entry)

    return result


@router.post("/campaigns/{campaign_id}/override")
def campaign_override(campaign_id: str, action: str):
    """Manual override for a campaign: scale | pause | kill."""
    allowed = {"scale", "pause", "kill", "hold"}
    if action not in allowed:
        raise HTTPException(status_code=400, detail=f"action must be one of {allowed}")
    _core._campaign_overrides[campaign_id] = action
    return {"campaign_id": campaign_id, "status": action, "overridden": True}


@router.get("/creatives")
def creatives():
    """Creative performance: hooks ranking, clip ROAS, sequence performance, variant leaderboard."""
    rows = _core._state.event_log.rows
    recent = rows[-_core._RECENT_ROWS_WINDOW:] if rows else []

    # Build live variant leaderboard from event log
    variant_buckets: dict[str, list[float]] = {}
    for r in recent:
        v = str(r.get("variant", ""))
        if v:
            variant_buckets.setdefault(v, []).append(float(r.get("roas", 0)))
    leaderboard = sorted(
        [
            {"variant": v, "avg_roas": round(sum(vs) / len(vs), 4), "count": len(vs)}
            for v, vs in variant_buckets.items()
        ],
        key=lambda x: x["avg_roas"],
        reverse=True,
    )

    payload = dict(_core._MOCK_CREATIVES)
    payload["variant_leaderboard"] = leaderboard or payload["variant_leaderboard"]
    return payload


@router.get("/risk")
def risk():
    """Risk monitoring panel: alerts, drawdown, anomaly flags, system health."""
    state = _core._state
    rows = state.event_log.rows
    recent_48h = rows[-_core._ROWS_PER_48H:] if rows else []

    # Drawdown from event-log capital proxy
    capital = state.capital
    from core.risk.drawdown import DrawdownProtector
    dp = DrawdownProtector()
    for r in rows:
        rev = float(r.get("revenue", 0))
        dp.update(rev)
    drawdown_pct = round(dp.drawdown(capital), 4)

    # ROAS over last 48 h
    roas_48h_values = [float(r.get("roas", 0)) for r in recent_48h]
    avg_roas_48h = (
        round(sum(roas_48h_values) / len(roas_48h_values), 4) if roas_48h_values else 0.0
    )

    # Anomaly detection on ROAS
    from core.risk.anomaly import AnomalyDetector
    ad = AnomalyDetector()
    all_roas = [float(r.get("roas", 0)) for r in rows]
    for v in all_roas[:-1]:
        ad.update(v)
    latest_roas = all_roas[-1] if all_roas else 0.0
    is_anomaly = ad.is_anomaly(latest_roas) if all_roas else False

    alerts = []
    if drawdown_pct > 0.30:
        alerts.append({
            "level": "critical",
            "color": "red",
            "message": f"Drawdown {round(drawdown_pct * 100, 1)}% exceeds 30% threshold",
            "metric": "drawdown",
        })
    if avg_roas_48h < 1.0 and roas_48h_values:
        alerts.append({
            "level": "critical",
            "color": "red",
            "message": f"ROAS {avg_roas_48h} below 1.0 over last 48 h — review campaigns",
            "metric": "roas_48h",
        })
    if is_anomaly:
        alerts.append({
            "level": "warning",
            "color": "yellow",
            "message": f"ROAS anomaly detected: latest value {round(latest_roas, 4)}",
            "metric": "anomaly",
        })

    # System health colour
    if any(a["color"] == "red" for a in alerts):
        health = "critical"
    elif alerts:
        health = "warning"
    else:
        health = "healthy"

    return {
        "system_health": health,
        "drawdown_pct": drawdown_pct,
        "avg_roas_48h": avg_roas_48h,
        "anomaly_detected": is_anomaly,
        "alerts": alerts,
    }


@router.get("/geo")
def geo():
    """Geo performance: ROAS per country, spend distribution, expansion status."""
    rows = _core._state.event_log.rows
    recent = rows[-_core._RECENT_ROWS_WINDOW:] if rows else []

    # Compute live system-wide avg ROAS as a reference
    live_avg: float | None = (
        round(sum(r.get("roas", 0) for r in recent) / len(recent), 4)
        if recent else None
    )

    result = [dict(g) for g in _core._MOCK_GEO]
    if live_avg is not None:
        for entry in result:
            entry["system_avg_roas"] = live_avg
    return result


@router.get("/accounts")
def accounts():
    """Account health: status, spend per account, risk flags."""
    return list(_core._MOCK_ACCOUNTS)


@router.get("/alerts")
def alerts():
    """Real-time alerts across all sub-systems with severity levels."""
    # Delegate to the /risk endpoint logic and aggregate
    risk_data = risk()
    base_alerts = list(risk_data.get("alerts", []))

    # Additional alert: pacing (check capital vs expected)
    rows = _core._state.event_log.rows
    recent = rows[-20:] if rows else []
    if recent:
        avg_cost = sum(float(r.get("cost", r.get("spend", 0))) for r in recent) / len(recent)
        if avg_cost > 50:
            base_alerts.append({
                "level": "warning",
                "color": "yellow",
                "message": f"Pacing alert: avg cycle cost {round(avg_cost, 2)} may exceed budget",
                "metric": "pacing",
            })

    return {
        "count": len(base_alerts),
        "system_health": risk_data.get("system_health", "healthy"),
        "alerts": base_alerts,
    }


__all__ = ["router"]

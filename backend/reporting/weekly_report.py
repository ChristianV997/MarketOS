"""backend.reporting.weekly_report — one document that answers "how's it going?"

Aggregates every telemetry stream into a single JSON report:

    profitability   real spend / revenue / profit per product
    forecast        projected revenue bands for the coming week
    costs           API cost breakdown by service
    errors          top failure modes
    scaling         budget decisions taken
    calibration     is confidence predicting reality?
    alerts          anything that fired

Reports persist to state/reports/report_<YYYY-MM-DD>.json and the newest is
served by GET /api/dropship/report.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.core.persistence import save_json_atomic, state_path

_log = logging.getLogger(__name__)

_REPORT_DIR = Path(state_path("reports"))


def generate_report(period_days: int = 7, persist: bool = True) -> dict[str, Any]:
    """Build (and optionally persist) the full status report.

    Every section degrades independently — a broken stream reports its error
    instead of sinking the whole document.
    """
    report: dict[str, Any] = {
        "generated_at": time.time(),
        "generated_at_iso": datetime.now(timezone.utc).isoformat(),
        "period_days": period_days,
    }

    def _section(name: str, builder) -> None:
        try:
            report[name] = builder()
        except Exception as exc:
            _log.debug("report_section_failed section=%s error=%s", name, exc)
            report[name] = {"status": "error", "error": str(exc)}

    from backend.metrics.profitability import calculate_profitability, revenue_forecast
    from backend.metrics.calibration_tuning import confidence_report
    from backend.cost_tracking import cost_report
    from backend.error_telemetry import error_summary
    from backend.optimization.budget_scaling import scaling_summary
    from backend.monitoring.alerts import alert_summary

    _section("profitability", lambda: calculate_profitability(lookback_days=period_days))
    _section("forecast", lambda: revenue_forecast(horizon_days=period_days))
    _section("costs", lambda: cost_report(lookback_minutes=period_days * 1440))
    _section("errors", lambda: error_summary(lookback_minutes=period_days * 1440))
    _section("scaling", lambda: scaling_summary(lookback_days=period_days))
    _section("calibration", lambda: confidence_report())
    _section("alerts", lambda: alert_summary(lookback_hours=period_days * 24))

    # One-line executive summary
    prof = report.get("profitability", {})
    report["headline"] = {
        "total_profit": prof.get("total_profit", 0.0),
        "roi_pct": prof.get("roi_pct", 0.0),
        "products_live": prof.get("num_products", 0) + len(prof.get("awaiting_data", [])),
        "api_cost": report.get("costs", {}).get("total_spend", 0.0),
        "errors": report.get("errors", {}).get("total_errors", 0),
        "alerts": report.get("alerts", {}).get("total_alerts", 0),
    }

    if persist:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = _REPORT_DIR / f"report_{date}.json"
        save_json_atomic(str(path), report)
        report["persisted_to"] = str(path)

    return report


def latest_report() -> dict[str, Any] | None:
    """Most recently persisted report, or None."""
    try:
        paths = sorted(_REPORT_DIR.glob("report_*.json"))
        if not paths:
            return None
        from backend.core.persistence import load_json
        return load_json(str(paths[-1]), default=None)
    except Exception as exc:
        _log.debug("latest_report_failed error=%s", exc)
        return None


__all__ = ["generate_report", "latest_report"]

"""backend.monitoring.alerts — know when it breaks before the customer does.

Four cheap checks over local state (no network calls):

  error_burst        > N errors in the last hour
  spend_burst        daily spend above the configured ceiling
  roas_floor         a campaign with real spend is burning money (ROAS < 0.5)
  pipeline_stalled   no dropship cycle has completed in > 24h

Fired alerts append to state/alerts.jsonl.  Each alert key has a cooldown
(default 6h) so a persistent condition pages once, not every tick.

    from backend.monitoring.alerts import evaluate_alerts, alert_summary
    fired = evaluate_alerts()
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from backend.core.persistence import load_json, save_json_atomic, state_path

_log = logging.getLogger(__name__)

_ALERTS_PATH = Path(state_path("alerts.jsonl"))
_COOLDOWN_STATE = state_path("alerts_state.json")

_COOLDOWN_S = float(os.getenv("ALERT_COOLDOWN_S", str(6 * 3600)))
_ERROR_BURST_THRESHOLD = int(os.getenv("ALERT_ERROR_BURST", "10"))
_SPEND_DAILY_CEILING = float(os.getenv("ALERT_SPEND_DAILY_USD", "200"))
_ROAS_FLOOR = 0.5
_ROAS_FLOOR_MIN_SPEND = 20.0
_STALL_HOURS = 24.0


def _fire(alerts: list[dict], key: str, level: str, message: str,
          cooldowns: dict, **data: Any) -> None:
    """Append an alert unless the same key fired within the cooldown."""
    now = time.time()
    if now - float(cooldowns.get(key, 0)) < _COOLDOWN_S:
        return
    cooldowns[key] = now
    alerts.append({"key": key, "level": level, "message": message,
                   "ts": now, **data})


def evaluate_alerts() -> list[dict]:
    """Run every check; append fired alerts to the log and return them."""
    alerts: list[dict] = []
    cooldowns: dict = load_json(_COOLDOWN_STATE, default={}) or {}

    # 1. Error burst
    try:
        from backend.error_telemetry import error_summary
        summary = error_summary(lookback_minutes=60)
        n = summary.get("total_errors", 0)
        if n > _ERROR_BURST_THRESHOLD:
            top = summary.get("top_errors", [])
            _fire(alerts, "error_burst", "error",
                  f"{n} errors in the last hour (threshold {_ERROR_BURST_THRESHOLD})",
                  cooldowns, count=n,
                  top_error=(top[0] if top else {}))
    except Exception as exc:
        _log.debug("alert_error_check_failed error=%s", exc)

    # 2. Spend burst
    try:
        from backend.metrics.campaign_metrics import campaign_performance
        day_spend = sum(c["spend"] for c in campaign_performance(lookback_days=1))
        if day_spend > _SPEND_DAILY_CEILING:
            _fire(alerts, "spend_burst", "error",
                  f"daily spend ${day_spend:.2f} above ceiling ${_SPEND_DAILY_CEILING:.0f}",
                  cooldowns, spend=round(day_spend, 2),
                  ceiling=_SPEND_DAILY_CEILING)
    except Exception as exc:
        _log.debug("alert_spend_check_failed error=%s", exc)

    # 3. ROAS floor — campaigns with real spend burning money
    try:
        from backend.metrics.campaign_metrics import campaign_performance
        for c in campaign_performance(lookback_days=3):
            if c["spend"] >= _ROAS_FLOOR_MIN_SPEND and c["roas"] < _ROAS_FLOOR:
                _fire(alerts, f"roas_floor:{c['campaign_id']}", "warn",
                      f"campaign {c['campaign_id']} ({c['product']}) "
                      f"ROAS {c['roas']:.2f} on ${c['spend']:.2f} spend",
                      cooldowns, campaign_id=c["campaign_id"],
                      product=c["product"], roas=c["roas"], spend=c["spend"])
    except Exception as exc:
        _log.debug("alert_roas_check_failed error=%s", exc)

    # 4. Pipeline stalled
    try:
        snapshot = load_json(state_path("dropship.json"), default=None)
        if isinstance(snapshot, dict) and snapshot.get("ts"):
            age_h = (time.time() - float(snapshot["ts"])) / 3600
            if age_h > _STALL_HOURS:
                _fire(alerts, "pipeline_stalled", "warn",
                      f"no dropship cycle completed in {age_h:.0f}h",
                      cooldowns, age_hours=round(age_h, 1))
    except Exception as exc:
        _log.debug("alert_stall_check_failed error=%s", exc)

    # Persist fired alerts + cooldown state
    if alerts:
        try:
            _ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_ALERTS_PATH, "a") as f:
                for a in alerts:
                    f.write(json.dumps(a) + "\n")
            for a in alerts:
                _log.warning("ALERT [%s] %s", a["level"], a["message"])
        except Exception as exc:
            _log.error("alert_write_failed error=%s", exc)
    save_json_atomic(_COOLDOWN_STATE, cooldowns)

    return alerts


def alert_summary(lookback_hours: int = 24) -> dict[str, Any]:
    """Recent alerts, newest first, with counts by level."""
    since = time.time() - lookback_hours * 3600
    rows: list[dict] = []
    if _ALERTS_PATH.exists():
        try:
            with open(_ALERTS_PATH) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        a = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if a.get("ts", 0) >= since:
                        rows.append(a)
        except Exception as exc:
            _log.error("alert_read_failed error=%s", exc)

    rows.sort(key=lambda a: a["ts"], reverse=True)
    by_level: dict[str, int] = {}
    for a in rows:
        by_level[a.get("level", "info")] = by_level.get(a.get("level", "info"), 0) + 1

    return {
        "period_hours": lookback_hours,
        "total_alerts": len(rows),
        "by_level": by_level,
        "alerts": rows[:50],
    }


__all__ = ["evaluate_alerts", "alert_summary"]

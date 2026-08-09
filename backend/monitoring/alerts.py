"""backend.monitoring.alerts — know when it breaks before the customer does.

Eight cheap checks over local state (no network calls):

  error_burst                  > N errors in the last hour
  spend_burst                  daily spend above the configured ceiling
  roas_floor                   a campaign with real spend is burning money (ROAS < 0.5)
  pipeline_stalled             no dropship cycle has completed in > 24h
  stuck_workflow                a workflow started but never reached a terminal event
  webhook_signature_failures    a burst of invalid/missing webhook signatures
  supplier_placement_failures   too high a share of fulfillment placements failing
  capital_drawdown              current capital has dropped too far below peak

Fired alerts append to state/alerts.jsonl.  Each alert key has a cooldown
(default 6h) so a persistent condition pages once, not every tick.
Error-level alerts additionally push to Slack/Telegram when configured
(backend.monitoring.alerting) — a no-op otherwise, same "presence of the
credential is the opt-in" convention as every other integration here.

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

_STUCK_WORKFLOW_MIN_AGE_S = float(os.getenv("ALERT_STUCK_WORKFLOW_MIN_AGE_S", str(10 * 60)))
_WEBHOOK_SIG_FAILURE_LOOKBACK_S = 3600.0
_WEBHOOK_SIG_FAILURE_THRESHOLD = int(os.getenv("ALERT_WEBHOOK_SIG_FAILURES", "5"))
_SUPPLIER_FAILURE_LOOKBACK_S = 3600.0
_SUPPLIER_FAILURE_MIN_ATTEMPTS = int(os.getenv("ALERT_SUPPLIER_FAILURE_MIN_ATTEMPTS", "5"))
_SUPPLIER_FAILURE_RATE_THRESHOLD = float(os.getenv("ALERT_SUPPLIER_FAILURE_RATE", "0.3"))


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

    # 5. Stuck workflow — a workflow_started with no terminal event, older
    # than the threshold. incomplete_workflows() previously had no caller
    # besides a passive GET endpoint and tests; this is what actually
    # surfaces a crash mid-fulfillment/mid-checkout to a human.
    try:
        from backend.orchestration.event_store import event_store
        now = time.time()
        stuck = [
            w for w in event_store.incomplete_workflows()
            if w.get("started_at") and (now - float(w["started_at"])) > _STUCK_WORKFLOW_MIN_AGE_S
        ]
        if stuck:
            oldest = max(stuck, key=lambda w: now - float(w["started_at"]))
            age_min = (now - float(oldest["started_at"])) / 60
            _fire(alerts, "stuck_workflow", "error",
                  f"{len(stuck)} workflow(s) stuck mid-execution, oldest {age_min:.0f}m "
                  f"({oldest.get('workflow', '')}/{oldest['workflow_id']}, "
                  f"last event {oldest.get('last_event', '')})",
                  cooldowns, count=len(stuck), oldest_workflow_id=oldest["workflow_id"],
                  oldest_age_minutes=round(age_min, 1))
    except Exception as exc:
        _log.debug("alert_stuck_workflow_check_failed error=%s", exc)

    # 6. Webhook signature failures — a burst is either a misconfigured
    # secret or an attacker probing the endpoint; previously invalid/missing
    # signatures were just a 400 response with no signal anywhere.
    try:
        from backend.orchestration.event_store import event_store
        since = time.time() - _WEBHOOK_SIG_FAILURE_LOOKBACK_S
        count = sum(
            1 for e in event_store._iter_events()
            if e.get("event") == "webhook_signature_failed" and e.get("ts", 0) >= since
        )
        if count >= _WEBHOOK_SIG_FAILURE_THRESHOLD:
            _fire(alerts, "webhook_signature_failures", "error",
                  f"{count} webhook signature failures in the last hour "
                  f"(threshold {_WEBHOOK_SIG_FAILURE_THRESHOLD})",
                  cooldowns, count=count)
    except Exception as exc:
        _log.debug("alert_webhook_signature_check_failed error=%s", exc)

    # 7. Supplier placement failure rate — too many fulfillment placements
    # failing in a row; previously _place_one_order's failures were only
    # journaled to the event store, never fed to anything that pages a human.
    try:
        from backend.orchestration.event_store import event_store
        since = time.time() - _SUPPLIER_FAILURE_LOOKBACK_S
        started = failed = 0
        for e in event_store._iter_events():
            if e.get("workflow") != "fulfillment" or e.get("ts", 0) < since:
                continue
            if e.get("event") == "workflow_started":
                started += 1
            elif e.get("event") == "workflow_failed":
                failed += 1
        if started >= _SUPPLIER_FAILURE_MIN_ATTEMPTS:
            rate = failed / started
            if rate >= _SUPPLIER_FAILURE_RATE_THRESHOLD:
                _fire(alerts, "supplier_placement_failures", "error",
                      f"{failed}/{started} fulfillment placements failed in the "
                      f"last hour ({rate * 100:.0f}%)",
                      cooldowns, failed=failed, started=started, rate=round(rate, 2))
    except Exception as exc:
        _log.debug("alert_supplier_failure_check_failed error=%s", exc)

    # 8. Capital drawdown — GlobalRiskEngine already computes this; nothing
    # previously read it outside the read-only /capital_allocation endpoint.
    try:
        from core.risk.global_risk_engine import global_risk_engine
        from backend.api import _state, _current_peak_capital
        current = float(_state.capital)
        peak = float(_current_peak_capital())
        if global_risk_engine.drawdown_exceeded(current, peak):
            drawdown_pct = (peak - current) / peak * 100 if peak > 0 else 0.0
            _fire(alerts, "capital_drawdown", "error",
                  f"capital drawdown {drawdown_pct:.1f}% (capital=${current:.2f}, "
                  f"peak=${peak:.2f}) exceeds threshold",
                  cooldowns, current_capital=round(current, 2),
                  peak_capital=round(peak, 2), drawdown_pct=round(drawdown_pct, 2))
    except Exception as exc:
        _log.debug("alert_drawdown_check_failed error=%s", exc)

    # Persist fired alerts + cooldown state
    if alerts:
        try:
            _ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_ALERTS_PATH, "a") as f:
                for a in alerts:
                    f.write(json.dumps(a) + "\n")
            for a in alerts:
                _log.warning("ALERT [%s] %s", a["level"], a["message"])
                if a["level"] == "error":
                    _notify_critical(a)
        except Exception as exc:
            _log.error("alert_write_failed error=%s", exc)
    save_json_atomic(_COOLDOWN_STATE, cooldowns)

    return alerts


def _notify_critical(alert: dict) -> None:
    """Push error-level alerts to Slack/Telegram when configured — a no-op
    when neither is set, same "presence of the credential is the opt-in"
    convention every other integration in this codebase follows. Never
    raises: a notification failure must not break alert evaluation."""
    try:
        from backend.monitoring.alerting import send_slack, send_telegram
        message = f"MarketOS ALERT [{alert.get('level', '')}] {alert.get('message', '')}"
        send_slack(message)
        send_telegram(message)
    except Exception as exc:
        _log.warning("alert_notify_failed key=%s error=%s", alert.get("key", ""), exc)


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

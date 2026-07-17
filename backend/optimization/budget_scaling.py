"""backend.optimization.budget_scaling — dynamic budget rules from real ROAS.

Reads the campaign metric log and turns observed ROAS into budget actions:

    ROAS > 2.0            scale_up    +20%/decision (capped at 2x, $500/day)
    1.0 ≤ ROAS ≤ 2.0      maintain
    0.5 ≤ ROAS < 1.0      scale_down  −50%
    ROAS < 0.5            kill        budget → 0

Campaigns below the spend threshold are left alone — deciding on noise is
worse than not deciding.  Decisions are appended to
state/scaling_decisions.jsonl; applying them to the live platforms is the
orchestrator's job (dry-run: recorded only).
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from backend.core.persistence import load_json, state_path

_log = logging.getLogger(__name__)

_DECISIONS_PATH = Path(state_path("scaling_decisions.jsonl"))

# Rule thresholds (env-tunable later if needed)
_SCALE_UP_ROAS = 2.0
_BREAKEVEN_ROAS = 1.0
_KILL_ROAS = 0.5
_SCALE_UP_MULT = 1.2
_SCALE_DOWN_MULT = 0.5
_MAX_GROWTH_MULT = 2.0
_MAX_DAILY_BUDGET = 500.0
_MIN_SPEND_FOR_DECISION = 20.0


def _current_budgets() -> dict[str, float]:
    """campaign_id → daily budget from the launch snapshot."""
    snapshot = load_json(state_path("dropship.json"), default={}) or {}
    budgets: dict[str, float] = {}
    for launch in snapshot.get("launches", []):
        for c in launch.get("campaigns", []):
            cid = c.get("campaign_id", "")
            if cid:
                budgets[cid] = float(c.get("budget", 0.0))
    return budgets


def compute_scaling_decisions(
    lookback_days: int = 3,
    min_spend_threshold: float = _MIN_SPEND_FOR_DECISION,
) -> list[dict[str, Any]]:
    """Turn recent campaign performance into budget decisions.

    Returns [{campaign_id, action, current_budget, new_budget, roas, reason}]
    sorted best-ROAS-first.  Empty when no campaign clears the spend
    threshold — silence is a valid decision.
    """
    from backend.metrics.campaign_metrics import campaign_performance

    budgets = _current_budgets()
    decisions: list[dict[str, Any]] = []

    for perf in campaign_performance(lookback_days=lookback_days):
        spend = perf["spend"]
        if spend < min_spend_threshold:
            continue

        cid = perf["campaign_id"]
        roas = perf["roas"]
        current = budgets.get(cid, spend / max(lookback_days, 1))

        if roas > _SCALE_UP_ROAS:
            action, new_budget = "scale_up", current * _SCALE_UP_MULT
            reason = f"ROAS {roas:.2f} > {_SCALE_UP_ROAS}"
        elif roas >= _BREAKEVEN_ROAS:
            action, new_budget = "maintain", current
            reason = f"ROAS {roas:.2f} at/above breakeven"
        elif roas >= _KILL_ROAS:
            action, new_budget = "scale_down", current * _SCALE_DOWN_MULT
            reason = f"ROAS {roas:.2f} below breakeven"
        else:
            action, new_budget = "kill", 0.0
            reason = f"ROAS {roas:.2f} critical"

        # Safety rails
        new_budget = min(new_budget, current * _MAX_GROWTH_MULT, _MAX_DAILY_BUDGET)

        decisions.append({
            "campaign_id": cid,
            "platform": perf["platform"],
            "product": perf["product"],
            "action": action,
            "reason": reason,
            "roas": roas,
            "spend": spend,
            "revenue": perf["revenue"],
            "profit": perf["profit"],
            "current_budget": round(current, 2),
            "new_budget": round(new_budget, 2),
            "timestamp": time.time(),
        })
        _log.info("scaling_decision campaign=%s action=%s budget %.2f→%.2f roas=%.2f",
                  cid, action, current, new_budget, roas)

    return sorted(decisions, key=lambda d: d["roas"], reverse=True)


def apply_scaling_decisions(decisions: list[dict]) -> dict[str, Any]:
    """Persist decisions (and, when live credentials exist, push them).

    Currently records to the decision log; live budget mutation goes through
    the platform clients once real campaign IDs exist.  Idempotent per call.
    """
    if not decisions:
        return {"status": "ok", "applied": 0, "total_old_budget": 0.0,
                "total_new_budget": 0.0, "budget_change": 0.0}

    applied = 0
    old_total = new_total = 0.0
    try:
        _DECISIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_DECISIONS_PATH, "a") as f:
            for d in decisions:
                f.write(json.dumps(d) + "\n")
                applied += 1
                old_total += d.get("current_budget", 0.0)
                new_total += d.get("new_budget", 0.0)
    except Exception as exc:
        _log.error("scaling_decisions_write_failed error=%s", exc)
        return {"status": "error", "error": str(exc), "applied": applied}

    return {
        "status": "ok",
        "applied": applied,
        "total_old_budget": round(old_total, 2),
        "total_new_budget": round(new_total, 2),
        "budget_change": round(new_total - old_total, 2),
    }


def scaling_summary(lookback_days: int = 7) -> dict[str, Any]:
    """Aggregate the decision log: counts and budget deltas per action."""
    since = time.time() - lookback_days * 86400
    by_action: dict[str, dict] = {}
    total_change = 0.0
    total = 0

    if _DECISIONS_PATH.exists():
        try:
            with open(_DECISIONS_PATH) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if d.get("timestamp", 0) < since:
                        continue
                    a = by_action.setdefault(d.get("action", "unknown"),
                                             {"count": 0, "budget_change": 0.0})
                    change = d.get("new_budget", 0.0) - d.get("current_budget", 0.0)
                    a["count"] += 1
                    a["budget_change"] = round(a["budget_change"] + change, 2)
                    total_change += change
                    total += 1
        except Exception as exc:
            _log.error("scaling_summary_read_failed error=%s", exc)

    return {
        "period_days": lookback_days,
        "total_decisions": total,
        "by_action": by_action,
        "total_budget_change": round(total_change, 2),
    }


__all__ = ["compute_scaling_decisions", "apply_scaling_decisions", "scaling_summary"]

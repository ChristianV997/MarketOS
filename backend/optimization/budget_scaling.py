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
import os
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

# A supplier whose reliability craters after a product goes live wasn't
# feeding back into spend decisions at all (only into which supplier gets
# picked at validation time) — given fulfillment failures directly cause
# refunds (the single most expensive failure mode), a below-threshold
# supplier now nudges the decision to "kill" regardless of ROAS.
_RELIABILITY_KILL_THRESHOLD = float(os.getenv("SCALING_RELIABILITY_KILL_THRESHOLD", "0.5"))


def _supplier_reliability_for_product(product: str) -> float | None:
    """Best-effort: resolve *product* to its most likely supplier and
    return observed reliability. Returns None (never blocks the decision)
    if the product can't be resolved or no observations exist yet."""
    try:
        from backend.validation.suppliers import find_best_supplier
        from backend.economics.supplier_feedback import supplier_feedback

        quote = find_best_supplier(product)
        if quote is None:
            return None
        return supplier_feedback.reliability_for(quote.supplier, "general")
    except Exception as exc:
        _log.debug("scaling_reliability_lookup_failed product=%s error=%s", product, exc)
        return None


def _current_budgets() -> dict[str, float]:
    """campaign_id → daily budget.

    Merges the dropship launch snapshot with the orchestrator's in-process
    campaign registry (_campaign_artifacts) — campaigns launched via the
    playbook path (orchestrator._run_scaling) or AJO never appear in
    dropship.json, so without this merge their scaling decisions ran
    against a fabricated fallback baseline (spend / lookback_days) instead
    of the campaign's real tracked budget.
    """
    snapshot = load_json(state_path("dropship.json"), default={}) or {}
    budgets: dict[str, float] = {}
    for launch in snapshot.get("launches", []):
        for c in launch.get("campaigns", []):
            cid = c.get("campaign_id", "")
            if cid:
                budgets[cid] = float(c.get("budget", 0.0))

    try:
        from orchestrator.main import _campaign_artifacts
        for cid, artifact in _campaign_artifacts.items():
            if cid not in budgets:
                budgets[cid] = float(artifact.budget)
    except Exception:
        pass

    return budgets


def _adgroup_ids() -> dict[str, str]:
    """campaign_id -> Meta ad-set id, from the orchestrator's in-process
    campaign registry — needed by the live actuator since Meta's budget
    lives on the ad set, not the campaign. Lazy/guarded import so this
    module has no hard dependency on the orchestrator entrypoint (e.g.
    when used standalone or in isolated tests)."""
    try:
        from orchestrator.main import _campaign_artifacts
        return {cid: artifact.adgroup_id for cid, artifact in _campaign_artifacts.items()}
    except Exception:
        return {}


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

        reliability = _supplier_reliability_for_product(perf["product"])
        if (reliability is not None and reliability < _RELIABILITY_KILL_THRESHOLD
                and action != "kill"):
            action, new_budget = "kill", 0.0
            reason = (f"{reason}; supplier reliability {reliability:.2f} "
                     f"below {_RELIABILITY_KILL_THRESHOLD}")

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


def _journal_budget_apply(decision: dict, live: bool) -> None:
    try:
        from backend.orchestration.event_store import event_store, new_workflow_id
        event_store.append(
            new_workflow_id("budgetapply"), "shadow_budget_apply",
            workflow="budget_scaling", step="apply",
            data={"campaign_id": decision.get("campaign_id", ""),
                 "platform": decision.get("platform", ""),
                 "action": decision.get("action", ""),
                 "current_budget": decision.get("current_budget", 0.0),
                 "new_budget": decision.get("new_budget", 0.0),
                 "live": live},
        )
    except Exception:
        _log.warning("budget_apply_journal_failed campaign=%s",
                    decision.get("campaign_id", ""), exc_info=True)


def apply_scaling_decisions(decisions: list[dict]) -> dict[str, Any]:
    """Persist decisions to the decision log, always journal a
    shadow_budget_apply per decision, and — only when BUDGET_APPLY_LIVE=true
    — actually actuate them against the real platform via
    backend.optimization.budget_actuator (pause_campaign/scale_budget).
    Idempotent per call.
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

    from backend.optimization.budget_actuator import live as _actuator_live
    is_live = _actuator_live()
    for d in decisions:
        _journal_budget_apply(d, live=is_live)

    actuated = 0
    actuation_errors = 0
    if is_live:
        from backend.optimization.budget_actuator import apply_decisions_live
        actuation = apply_decisions_live(decisions, adgroup_ids=_adgroup_ids())
        actuated = actuation["applied"]
        actuation_errors = actuation["errors"]

    return {
        "status": "ok",
        "applied": applied,
        "total_old_budget": round(old_total, 2),
        "total_new_budget": round(new_total, 2),
        "budget_change": round(new_total - old_total, 2),
        "live": is_live,
        "actuated": actuated,
        "actuation_errors": actuation_errors,
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

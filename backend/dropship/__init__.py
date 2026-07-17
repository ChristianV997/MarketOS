"""backend.dropship — the end-to-end dropship cycle.

One call runs the full spine in order:

    discover_products()          Pipeline 1  (backend.discovery)
      → validate_product()      Pipeline 2  (backend.validation)
      → build_product()         Pipeline 3  (backend.creation)
      → launch_product()        Pipeline 4  (backend.launch)

Pipeline 5 (Optimize) is the existing live loop: launched campaign IDs are
returned so the orchestrator can register them in _campaign_artifacts, where
metrics ingestion already fetches ROAS, records calibration outcomes, kills
losers, and scales winners.

Every stage is dry-run safe by default; a cycle with zero green products is
a normal "skipped" outcome, not an error.  The last cycle summary persists
to state/dropship.json for the dashboard.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from backend.core.persistence import save_json_atomic, state_path

_log = logging.getLogger(__name__)

_SNAPSHOT_PATH = state_path("dropship.json")

# Predicted ROAS by margin verdict — used to stage calibration predictions so
# the metrics loop can pair them with real outcomes per product.
_ROAS_PRIOR = {"profitable": 2.0, "breakeven": 1.2, "loss": 0.6}


def run_dropship_cycle(
    max_products: int = 3,
    budget_daily: float = 50.0,
    platforms: tuple[str, ...] = ("tiktok", "meta"),
) -> dict[str, Any]:
    """Run one full discover→validate→create→launch cycle.

    Returns a summary dict:
      {status, discovered, validated, green, launched,
       launches: [{product, confidence, campaigns, ...}]}
    """
    started = time.time()

    # ── Pipeline 1: discover ──────────────────────────────────────────────────
    try:
        from backend.discovery import discover_products
        opportunities = discover_products(limit=max_products * 3)
    except Exception as exc:
        _log.exception("dropship_discovery_failed")
        return {"status": "error", "stage": "discover", "error": str(exc)}

    if not opportunities:
        return {"status": "skipped", "reason": "no_opportunities"}

    # ── Pipeline 2: validate ──────────────────────────────────────────────────
    from backend.validation import validate_product

    verdicts: list[dict] = []
    for opp in opportunities:
        try:
            verdicts.append(validate_product(opp["product"]))
        except Exception as exc:
            _log.debug("dropship_validate_failed product=%s error=%s",
                       opp.get("product"), exc)
    green = [v for v in verdicts if v.get("ready_for_creation")][:max_products]

    if not green:
        summary = {
            "status": "skipped",
            "reason": "no_green_products",
            "discovered": len(opportunities),
            "validated": len(verdicts),
            "green": 0,
            "launched": 0,
            "launches": [],
            "duration_s": round(time.time() - started, 2),
        }
        save_json_atomic(_SNAPSHOT_PATH, summary)
        return summary

    # ── Pipelines 3 + 4: create, then launch ─────────────────────────────────
    from backend.creation import build_product
    from backend.launch import launch_product

    launches: list[dict] = []
    for verdict in green:
        product = verdict["product"]
        try:
            build = build_product(verdict)
            if build.get("status") != "ok":
                _log.debug("dropship_build_skipped product=%s reason=%s",
                           product, build.get("reason", build.get("error", "")))
                continue

            # Budget scales with validation confidence (0.6→60%, 1.0→100%)
            budget = round(budget_daily * verdict["confidence"], 2)
            launch = launch_product(build, budget_daily=budget, platforms=platforms)

            # Stage a calibration prediction per product so the metrics loop
            # can close the loop against real ROAS when outcomes arrive.
            predicted = _ROAS_PRIOR.get(
                (verdict.get("margin") or {}).get("margin_status", ""), 1.0)
            try:
                from simulation.calibration import calibration_store
                calibration_store.record_prediction(product, predicted_roas=predicted)
            except Exception as exc:
                _log.debug("dropship_calibration_stage_failed error=%s", exc)

            launches.append({
                "product": product,
                "confidence": verdict["confidence"],
                "retail_price": verdict.get("retail_price"),
                "predicted_roas": predicted,
                "budget": budget,
                "page_url": (build.get("page") or {}).get("url", ""),
                "launch_status": launch.get("status"),
                "campaigns": launch.get("campaigns", []),
            })
        except Exception:
            _log.exception("dropship_launch_failed product=%s", product)

    launched = sum(1 for l in launches if l.get("launch_status") == "ok")
    summary = {
        "status": "ok" if launched else "skipped",
        "reason": "" if launched else "no_launches",
        "discovered": len(opportunities),
        "validated": len(verdicts),
        "green": len(green),
        "launched": launched,
        "launches": launches,
        "duration_s": round(time.time() - started, 2),
        "ts": time.time(),
    }
    save_json_atomic(_SNAPSHOT_PATH, summary)
    _log.info("dropship_cycle_done discovered=%d green=%d launched=%d",
              len(opportunities), len(green), launched)
    return summary

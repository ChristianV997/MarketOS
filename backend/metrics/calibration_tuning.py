"""backend.metrics.calibration_tuning — does confidence predict reality?

Joins the calibration audit trail (predicted vs. actual ROAS per product)
with the validation confidence each product launched at, then answers:

  * do higher-confidence products actually achieve higher ROAS?
  * how far off are the ROAS priors, and in which direction?
  * should the green-light confidence threshold move?

Output feeds two knobs:
  - ``roas_prior_correction``: multiplicative fix for the dropship cycle's
    predicted-ROAS priors (e.g. 0.85 = priors run 15% hot).
  - ``recommended_green_threshold``: lowest confidence bucket whose average
    actual ROAS clears breakeven.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.core.persistence import load_json, state_path

_log = logging.getLogger(__name__)

# Confidence buckets: (label, low, high)
_BUCKETS = [
    ("0.0-0.6", 0.0, 0.6),
    ("0.6-0.75", 0.6, 0.75),
    ("0.75-0.9", 0.75, 0.9),
    ("0.9-1.0", 0.9, 1.01),
]

_BREAKEVEN_ROAS = 1.0
_MIN_SAMPLES_PER_BUCKET = 3


def _product_confidence() -> dict[str, float]:
    """product → confidence at launch (latest snapshot wins)."""
    snapshot = load_json(state_path("dropship.json"), default={}) or {}
    return {
        l["product"]: float(l.get("confidence", 0.5))
        for l in snapshot.get("launches", [])
        if l.get("product")
    }


def _paired_records(max_records: int = 500) -> list[dict]:
    """Calibration pairs [{product, predicted, actual, error, ts}]."""
    try:
        from simulation.calibration import calibration_store
        return calibration_store.recent_errors(n=max_records)
    except Exception as exc:
        _log.debug("calibration_records_unavailable error=%s", exc)
        return []


def confidence_report(max_records: int = 500) -> dict[str, Any]:
    """Bucket calibration outcomes by launch confidence.

    Returns:
      {status, samples, buckets: [{bucket, n, avg_confidence, avg_predicted,
       avg_actual, win_rate, roas_lift}], monotonic, roas_prior_correction,
       recommended_green_threshold, rationale}
    """
    confidence = _product_confidence()
    records = _paired_records(max_records)

    joined = [
        {"confidence": confidence[r["product"]],
         "predicted": r["predicted"], "actual": r["actual"]}
        for r in records if r.get("product") in confidence
    ]

    if not joined:
        return {
            "status": "insufficient_data",
            "samples": 0,
            "buckets": [],
            "monotonic": None,
            "roas_prior_correction": 1.0,
            "recommended_green_threshold": None,
            "rationale": "no calibration outcomes joined to launch confidence yet",
        }

    buckets = []
    for label, lo, hi in _BUCKETS:
        rows = [j for j in joined if lo <= j["confidence"] < hi]
        if not rows:
            continue
        n = len(rows)
        avg_actual = sum(r["actual"] for r in rows) / n
        avg_predicted = sum(r["predicted"] for r in rows) / n
        buckets.append({
            "bucket": label,
            "n": n,
            "avg_confidence": round(sum(r["confidence"] for r in rows) / n, 3),
            "avg_predicted": round(avg_predicted, 3),
            "avg_actual": round(avg_actual, 3),
            "win_rate": round(sum(1 for r in rows if r["actual"] >= _BREAKEVEN_ROAS) / n, 3),
            "reliable": n >= _MIN_SAMPLES_PER_BUCKET,
        })

    # Monotonicity: does avg actual ROAS rise with confidence (reliable buckets)?
    reliable = [b for b in buckets if b["reliable"]]
    actuals = [b["avg_actual"] for b in reliable]
    monotonic = all(a <= b for a, b in zip(actuals, actuals[1:])) if len(actuals) >= 2 else None

    # Global multiplicative prior correction: mean(actual) / mean(predicted)
    tot_pred = sum(j["predicted"] for j in joined)
    tot_act = sum(j["actual"] for j in joined)
    correction = round(tot_act / tot_pred, 3) if tot_pred > 0 else 1.0

    # Recommended green threshold: lower bound of the cheapest reliable bucket
    # whose average actual ROAS clears breakeven
    recommended = None
    for b in buckets:
        if b["reliable"] and b["avg_actual"] >= _BREAKEVEN_ROAS:
            lo = next(lo for (label, lo, hi) in _BUCKETS if label == b["bucket"])
            recommended = lo
            break

    if monotonic is False:
        rationale = ("confidence does NOT rank real ROAS — review validator "
                     "weights before trusting confidence-scaled budgets")
    elif recommended is not None:
        rationale = (f"buckets ≥{recommended} confidence average breakeven "
                     f"or better; prior correction ×{correction}")
    else:
        rationale = "no reliable bucket clears breakeven yet — keep budgets minimal"

    return {
        "status": "ok",
        "samples": len(joined),
        "buckets": buckets,
        "monotonic": monotonic,
        "roas_prior_correction": correction,
        "recommended_green_threshold": recommended,
        "rationale": rationale,
    }


def prior_correction() -> float:
    """Multiplicative ROAS-prior correction (1.0 when insufficient data).

    Consumed by the dropship cycle to de-bias its predicted-ROAS priors:
    corrected_prior = raw_prior × prior_correction().
    Clamped to [0.25, 4.0] so a burst of weird outcomes can't zero budgets.
    """
    report = confidence_report()
    if report["status"] != "ok" or report["samples"] < 5:
        return 1.0
    return max(0.25, min(4.0, report["roas_prior_correction"]))


__all__ = ["confidence_report", "prior_correction"]

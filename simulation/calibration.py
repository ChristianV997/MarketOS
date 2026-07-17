"""simulation.calibration — prediction-vs-reality audit trail.

Separate from ``simulation/calibrator.py`` (which applies Bayesian bias
correction to future predictions).  This module is the AUDIT layer:

  1. Records every (predicted_roas, actual_roas) pair with metadata.
  2. Computes MAE, RMSE, bias, and per-product breakdowns.
  3. Exposes a ``summary()`` dict consumed by the dashboard + API.
  4. Feeds the calibration loop: after enough records accumulate, the
     scoring model can be retrained with corrected labels.

Lifecycle
---------
  simulation/integration._run_simulation() calls:
    calibration_store.record_prediction(product, predicted_roas)

  After execution, when actual outcomes arrive:
    calibration_store.record_outcome(product, actual_roas)

  The store auto-pairs predictions with outcomes by product + recency.
  Unpaired records expire after PAIR_TIMEOUT_S seconds.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from typing import Any

from backend.core.persistence import save_json_atomic, load_json, state_path

_log = logging.getLogger(__name__)

_MAX_RECORDS    = 2000
_PAIR_TIMEOUT_S = 300.0   # seconds to wait for outcome before expiring prediction
_CALIBRATION_PATH = state_path("calibration.json")


class CalibrationRecord:
    """One matched (predicted, actual) pair."""
    __slots__ = ("product", "predicted", "actual", "error", "abs_error", "ts")

    def __init__(self, product: str, predicted: float, actual: float, ts: float):
        self.product   = product
        self.predicted = predicted
        self.actual    = actual
        self.error     = predicted - actual   # positive = over-predicted
        self.abs_error = abs(self.error)
        self.ts        = ts

    def to_dict(self) -> dict:
        return {
            "product":   self.product,
            "predicted": round(self.predicted, 4),
            "actual":    round(self.actual, 4),
            "error":     round(self.error, 4),
            "ts":        self.ts,
        }


class CalibrationStore:
    """Thread-safe store for prediction vs. reality audit records.

    Two-phase ingestion
    -------------------
    Phase 1 — record_prediction(product, predicted_roas):
        Stores a pending prediction timestamped now.

    Phase 2 — record_outcome(product, actual_roas):
        Matches the most recent pending prediction for ``product``,
        closes it as a CalibrationRecord, and discards expired pendigns.

    Alternatively, record(product, predicted, actual) closes a pair
    directly when both values are known at the same time (e.g. replay).
    """

    def __init__(self, max_records: int = _MAX_RECORDS):
        self._records:  deque[CalibrationRecord] = deque(maxlen=max_records)
        self._pending:  dict[str, list[dict]]    = {}   # product → [{predicted, ts}]
        self._lock      = threading.Lock()
        self.total_paired = 0

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def record(
        self,
        product: str,
        predicted: float,
        actual: float,
        ts: float | None = None,
    ) -> None:
        """Close a pair directly (predicted + actual known simultaneously)."""
        rec = CalibrationRecord(product, float(predicted), float(actual),
                                ts or time.time())
        with self._lock:
            self._records.append(rec)
            self.total_paired += 1

    def record_prediction(self, product: str, predicted: float = 0.0,
                          predicted_roas: float | None = None) -> None:
        """Stage a prediction; will be matched when outcome arrives."""
        value = predicted_roas if predicted_roas is not None else predicted
        with self._lock:
            self._pending.setdefault(product, []).append({
                "predicted": float(value),
                "ts":        time.time(),
            })

    def record_outcome(self, product: str, actual: float = 0.0,
                       actual_roas: float | None = None) -> bool:
        """Match the most recent pending prediction for product, if any.

        Returns True if a pair was created.
        """
        # Honor the actual_roas keyword — callers use it exclusively; the
        # positional ``actual`` previously shadowed it and every pair was
        # recorded with actual=0.0, poisoning the whole audit trail.
        value = actual_roas if actual_roas is not None else actual
        now = time.time()
        with self._lock:
            pending = self._pending.get(product, [])
            # expire stale predictions
            pending = [p for p in pending if now - p["ts"] < _PAIR_TIMEOUT_S]
            if not pending:
                self._pending.pop(product, None)
                return False
            # take the most recent
            p = pending.pop()
            self._pending[product] = pending
            rec = CalibrationRecord(product, p["predicted"], float(value), now)
            self._records.append(rec)
            self.total_paired += 1
        return True

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def recent_errors(self, n: int = 50) -> list[dict]:
        with self._lock:
            recs = list(self._records)
        return [r.to_dict() for r in recs[-n:]]

    def summary(self, n: int = 200) -> dict[str, Any]:
        """Return calibration health summary (last ``n`` records)."""
        with self._lock:
            recs = list(self._records)[-n:]

        if not recs:
            return {
                "total_records": 0,
                "mae": None,
                "rmse": None,
                "bias": None,
                "ready": False,
            }

        errors = [r.error for r in recs]
        abs_errors = [r.abs_error for r in recs]
        n_recs = len(recs)

        mae  = sum(abs_errors) / n_recs
        rmse = math.sqrt(sum(e * e for e in errors) / n_recs)
        bias = sum(errors) / n_recs   # positive = systematically over-predicting

        # Per-product breakdown (top 5 most active products)
        by_product: dict[str, list[float]] = {}
        for r in recs:
            by_product.setdefault(r.product, []).append(r.abs_error)
        top_products = sorted(
            [
                {"product": p, "n": len(errs), "mae": sum(errs) / len(errs)}
                for p, errs in by_product.items()
            ],
            key=lambda x: x["n"],
            reverse=True,
        )[:5]

        return {
            "total_records": self.total_paired,
            "window":        n_recs,
            "mae":           round(mae, 4),
            "rmse":          round(rmse, 4),
            "bias":          round(bias, 4),
            "over_predicts": bias > 0.1,
            "under_predicts": bias < -0.1,
            "ready":         n_recs >= 20,
            "by_product":    top_products,
        }

    def is_calibrated(self) -> bool:
        """True when enough paired records exist for reliable statistics."""
        with self._lock:
            return len(self._records) >= 20

    def reset(self) -> None:
        with self._lock:
            self._records.clear()
            self._pending.clear()
            self.total_paired = 0

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "records": [
                    {"product": r.product, "predicted": r.predicted,
                     "actual": r.actual, "ts": r.ts}
                    for r in self._records
                ],
                "total_paired": self.total_paired,
            }

    def restore(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return
        with self._lock:
            self._records.clear()
            for d in data.get("records", []):
                try:
                    self._records.append(CalibrationRecord(
                        d["product"], float(d["predicted"]),
                        float(d["actual"]), float(d.get("ts", 0.0)),
                    ))
                except Exception:
                    continue
            self.total_paired = int(data.get("total_paired", len(self._records)))

    def persist(self) -> bool:
        return save_json_atomic(_CALIBRATION_PATH, self.snapshot())


# ── module-level singleton ────────────────────────────────────────────────────

calibration_store = CalibrationStore()

_saved = load_json(_CALIBRATION_PATH)
if _saved:
    calibration_store.restore(_saved)

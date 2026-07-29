"""backend.learning.calibration — online prediction calibration.

Phase 4 fix: the legacy formula estimated bias AND uncertainty from the
same rolling window, which understates true uncertainty (a fitted
correction evaluated on the data that fit it always looks better than it
will on new data — the leak gets worse the more expressive the
correction, which matters here since isotonic regression is a
near-arbitrary monotone fit). ``_compute_holdout`` fixes this with a
chronological, non-overlapping train/holdout split: the correction curve
(flat mean-bias, or isotonic regression once enough data has accumulated)
is fit exclusively on the older ``train`` slice, and ``uncertainty`` is
the residual spread measured only on the newer ``holdout`` slice that
never touched the fit — an honest, out-of-sample confidence estimate.

Shadow-mode gated (``CALIBRATION_HOLDOUT_LIVE``, default false): both the
legacy same-window formula and the new holdout formula are computed every
call and journaled to event_store for comparison; ``stats()`` /
``adjust_prediction()`` / ``confidence_weight()`` return the legacy
branch until the flag flips, so behavior is unchanged today.
"""
from __future__ import annotations

import math
import os

import numpy as np
from sklearn.isotonic import IsotonicRegression

WINDOW = 100
MIN_STATS_N = 5           # unchanged cold-start floor
MIN_SPLIT_N = 20          # below this, no train/holdout split is meaningful
HOLDOUT_FRACTION = 0.30
MIN_HOLDOUT_N = 6
MIN_ISOTONIC_TRAIN = 30   # below this train size, isotonic is unstable
ISOTONIC_TAPER_END = 50   # train size at which isotonic is fully trusted


def _holdout_live() -> bool:
    return os.getenv("CALIBRATION_HOLDOUT_LIVE", "false").lower() == "true"


class CalibrationModel:

    def __init__(self, window=WINDOW):
        self.errors = []          # public contract, unchanged: flat float
                                   # list of (predicted - actual), persisted
                                   # directly by db_serializer.py / serializer.py
        self.window = window
        self._pairs = []          # internal-only: [(predicted, actual), ...],
                                   # not persisted today (restart-safe: degrades
                                   # gracefully back through cold_start states)
        self._version = 0
        self._fit_version = -1
        self._cached = None       # {"legacy": {...}, "holdout": {...}, "active": {...}}
        self._cached_correction = {"legacy": None, "holdout": None, "active": None}

    def update(self, predicted, actual):
        err = predicted - actual
        self.errors.append(err)
        self._pairs.append((float(predicted), float(actual)))
        if len(self.errors) > self.window:
            self.errors = self.errors[-self.window:]
            self._pairs = self._pairs[-self.window:]
        self._version += 1

    # ── holdout-based fit ────────────────────────────────────────────────

    def _split(self):
        n = len(self._pairs)
        holdout_n = max(MIN_HOLDOUT_N, round(HOLDOUT_FRACTION * n))
        holdout_n = min(holdout_n, n - 1)
        return self._pairs[:n - holdout_n], self._pairs[n - holdout_n:]

    def _fit_train(self, train):
        preds = np.array([p for p, _ in train])
        acts = np.array([a for _, a in train])
        train_n = len(train)
        bias_train = float(np.mean(preds - acts))
        flat = lambda x: x - bias_train

        if train_n < MIN_ISOTONIC_TRAIN:
            return flat, bias_train, "flat"

        iso = IsotonicRegression(increasing=True, out_of_bounds="clip")
        iso.fit(preds, acts)
        iso_fn = lambda x: float(iso.predict([x])[0])

        if train_n >= ISOTONIC_TAPER_END:
            return iso_fn, bias_train, "isotonic"

        # linear taper between thresholds prevents a discontinuous jump in
        # adjust_prediction() right at the isotonic-eligibility boundary
        lam = (train_n - MIN_ISOTONIC_TRAIN) / (ISOTONIC_TAPER_END - MIN_ISOTONIC_TRAIN)
        blended = lambda x: lam * iso_fn(x) + (1 - lam) * flat(x)
        return blended, bias_train, "isotonic_taper"

    def _compute_holdout(self):
        n = len(self.errors)
        if n < MIN_STATS_N:
            return (lambda x: x), {
                "bias": 0.0, "uncertainty": 1.0, "n": n,
                "method": "cold_start", "holdout_n": 0,
            }
        if n < MIN_SPLIT_N:
            bias = float(np.mean(self.errors))
            raw_std = float(np.std(self.errors, ddof=1)) if n > 1 else 1.0
            inflation = math.sqrt(MIN_SPLIT_N / n)  # widen: no real holdout yet
            return (lambda x, b=bias: x - b), {
                "bias": bias, "uncertainty": raw_std * inflation, "n": n,
                "method": "flat_smallsample", "holdout_n": 0,
            }
        train, holdout = self._split()
        correction, bias_train, method = self._fit_train(train)
        resid = np.array([correction(p) - a for p, a in holdout])
        uncertainty = float(np.std(resid, ddof=1))
        return correction, {
            "bias": bias_train, "uncertainty": uncertainty, "n": n,
            "train_n": len(train), "holdout_n": len(holdout), "method": method,
        }

    def _compute_legacy(self):
        """Byte-for-byte the pre-Phase-4 formula: same-window bias + std."""
        n = len(self.errors)
        if n < MIN_STATS_N:
            return (lambda x: x), {"bias": 0.0, "uncertainty": 1.0, "n": n,
                                    "method": "legacy_cold_start"}
        bias = float(np.mean(self.errors))
        unc = float(np.std(self.errors))
        return (lambda x, b=bias: x - b), {"bias": bias, "uncertainty": unc,
                                            "n": n, "method": "legacy"}

    def _ensure_fit(self):
        if self._fit_version == self._version:
            return
        legacy_fn, legacy_stats = self._compute_legacy()
        holdout_fn, holdout_stats = self._compute_holdout()
        live = _holdout_live()
        active_fn, active_stats = (holdout_fn, holdout_stats) if live else (legacy_fn, legacy_stats)

        self._cached_correction = {"legacy": legacy_fn, "holdout": holdout_fn, "active": active_fn}
        self._cached = {"legacy": legacy_stats, "holdout": holdout_stats, "active": dict(active_stats)}
        self._cached["active"]["live"] = live
        self._cached["active"]["_shadow"] = {"legacy": legacy_stats, "holdout": holdout_stats}

        try:
            from backend.orchestration.event_store import event_store, new_workflow_id
            event_store.append(
                new_workflow_id("calib"), "shadow_calibration_stats",
                workflow="calibration", step="ensure_fit",
                data={
                    "legacy_bias": round(legacy_stats["bias"], 4),
                    "legacy_uncertainty": round(legacy_stats["uncertainty"], 4),
                    "holdout_bias": round(holdout_stats["bias"], 4),
                    "holdout_uncertainty": round(holdout_stats["uncertainty"], 4),
                    "method": holdout_stats["method"],
                    "train_n": holdout_stats.get("train_n"),
                    "holdout_n": holdout_stats.get("holdout_n"),
                    "n": holdout_stats["n"],
                    "live": live,
                },
            )
        except Exception:
            pass  # journaling must never break calibration

        self._fit_version = self._version

    def stats(self):
        self._ensure_fit()
        return dict(self._cached["active"])

    def adjust_prediction(self, pred):
        self._ensure_fit()
        return float(self._cached_correction["active"](pred))

    def confidence_weight(self):
        self._ensure_fit()
        return 1.0 / (1.0 + self._cached["active"]["uncertainty"])


calibration_model = CalibrationModel()

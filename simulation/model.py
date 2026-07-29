"""simulation.model — Ridge-based pre-execution scoring model.

Trains on historical event rows (roas, ctr, cvr, label) and predicts a
composite engagement score for new candidates.  Falls back to a heuristic
score when insufficient data is available.
"""
from __future__ import annotations

import logging
import math
import threading
from typing import Any

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from simulation.features import FEATURE_NAMES, batch_extract, extract

_log = logging.getLogger(__name__)

_MIN_ROWS = 20  # minimum history rows before training


def _engagement_target(row: dict) -> float:
    """0–1 composite target from historical event row."""
    roas = float(row.get("roas", 0) or 0)
    ctr = float(row.get("ctr", 0) or 0)
    cvr = float(row.get("cvr", 0) or 0)
    # normalise against typical maxima
    r = min(roas / 3.0, 1.0)
    c = min(ctr / 0.05, 1.0)
    v = min(cvr / 0.04, 1.0)
    return 0.5 * r + 0.3 * c + 0.2 * v


class ScoringModel:
    """Ridge regression scorer with online retraining.

    Thread-safe: all public methods acquire ``_lock``.
    """

    def __init__(self, alpha: float = 1.0):
        self._alpha = alpha
        self._ridge: Ridge | None = None
        self._scaler = StandardScaler()
        self._fitted = False
        self._lock = threading.Lock()
        self._train_count = 0
        # Phase 7: track training residuals for Monte Carlo prediction intervals
        self._residuals: list[float] = []  # residuals from last fit
        self._y_train: np.ndarray | None = None  # training targets for interval computation

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def fit(
        self,
        rows: list[dict],
        patterns: dict | None = None,
        playbooks: dict | None = None,
    ) -> bool:
        """Train on historical event rows. Returns True if trained."""
        if len(rows) < _MIN_ROWS:
            return False

        history_map: dict[str, list[dict]] = {}
        for r in rows:
            p = r.get("product", "")
            history_map.setdefault(p, []).append(r)

        # Build signal-like dicts from event rows for feature extraction
        signals = [
            {
                "product": r.get("product", ""),
                "score": float(r.get("roas", 0) or 0) / 3.0,
                "velocity": float(r.get("velocity", 0) or 0),
                "hook": r.get("hook", ""),
                "angle": r.get("angle", ""),
                "regime": r.get("env_regime", ""),
                "engagement_rate": float(r.get("engagement_rate", 0) or 0),
            }
            for r in rows
        ]

        X_raw = batch_extract(signals, patterns=patterns, playbooks=playbooks,
                              history_map=history_map)
        y = [_engagement_target(r) for r in rows]

        X = np.array(X_raw, dtype=float)
        y_arr = np.array(y, dtype=float)

        with self._lock:
            try:
                X_scaled = self._scaler.fit_transform(X)
                ridge = Ridge(alpha=self._alpha)
                ridge.fit(X_scaled, y_arr)
                # Phase 7: store residuals for Monte Carlo prediction intervals
                y_pred = ridge.predict(X_scaled)
                self._residuals = [float(y - yp) for y, yp in zip(y_arr, y_pred)]
                self._y_train = y_arr
                self._ridge = ridge
                self._fitted = True
                self._train_count += 1
                return True
            except Exception as exc:
                _log.warning("scoring_model_fit_failed error=%s", exc)
                return False

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(
        self,
        signals: list[dict],
        patterns: dict | None = None,
        playbooks: dict | None = None,
        history_map: dict[str, list[dict]] | None = None,
    ) -> list[float]:
        """Return predicted engagement scores in [0, 1] for each signal."""
        if not signals:
            return []

        X_raw = batch_extract(signals, patterns=patterns, playbooks=playbooks,
                              history_map=history_map)
        X = np.array(X_raw, dtype=float)

        with self._lock:
            if self._fitted and self._ridge is not None:
                try:
                    X_scaled = self._scaler.transform(X)
                    raw = self._ridge.predict(X_scaled)
                    return [float(np.clip(v, 0.0, 1.0)) for v in raw]
                except Exception as exc:
                    _log.warning("scoring_model_predict_failed error=%s", exc)

        # Fallback: heuristic from feature vector
        return [_heuristic_score(fv) for fv in X_raw]

    def predict_one(
        self,
        signal: dict,
        patterns: dict | None = None,
        playbook: Any | None = None,
        history: list[dict] | None = None,
    ) -> float:
        fv = extract(signal, patterns=patterns, playbook=playbook, history=history)
        X = np.array([fv], dtype=float)
        with self._lock:
            if self._fitted and self._ridge is not None:
                try:
                    X_scaled = self._scaler.transform(X)
                    return float(np.clip(self._ridge.predict(X_scaled)[0], 0.0, 1.0))
                except Exception:
                    pass
        return _heuristic_score(fv)

    def predict_with_intervals(
        self,
        signal: dict,
        patterns: dict | None = None,
        playbook: Any | None = None,
        history: list[dict] | None = None,
        percentiles: tuple[int, ...] = (5, 25, 50, 75, 95),
    ) -> dict:
        """Phase 7: prediction with Monte Carlo confidence intervals.

        Returns dict with:
          point_estimate: single predicted score [0, 1]
          percentiles: dict {5: val, 25: val, 50: val, 75: val, 95: val}
          confidence_interval_lower: 5th percentile
          confidence_interval_upper: 95th percentile
          mean_interval_width: width of [5%, 95%] interval
        """
        # Compute point estimate
        point_est = self.predict_one(signal, patterns=patterns, playbook=playbook, history=history)

        with self._lock:
            if not self._fitted or self._ridge is None or len(self._residuals) < 10:
                # Cold start: no residuals to bootstrap from
                return {
                    "point_estimate": round(point_est, 4),
                    "percentiles": {p: round(point_est, 4) for p in percentiles},
                    "confidence_interval_lower": round(max(0.0, point_est - 0.1), 4),
                    "confidence_interval_upper": round(min(1.0, point_est + 0.1), 4),
                    "mean_interval_width": 0.2,
                }

            # Bootstrap residuals: sample residuals, add to point estimate
            residuals_arr = np.array(self._residuals, dtype=float)
            rng = np.random.default_rng(seed=hash(str(signal)) % (2**31))
            bootstrap_preds = []

            for _ in range(1000):  # 1000 Monte Carlo samples
                sampled_residual = float(rng.choice(residuals_arr))
                bootstrap_pred = np.clip(point_est + sampled_residual, 0.0, 1.0)
                bootstrap_preds.append(bootstrap_pred)

            bootstrap_arr = np.array(bootstrap_preds, dtype=float)
            percentile_vals = {p: float(np.percentile(bootstrap_arr, p)) for p in percentiles}

            lower = percentile_vals.get(5, point_est)
            upper = percentile_vals.get(95, point_est)
            interval_width = max(0.0, upper - lower)

            return {
                "point_estimate": round(point_est, 4),
                "percentiles": {p: round(v, 4) for p, v in percentile_vals.items()},
                "confidence_interval_lower": round(lower, 4),
                "confidence_interval_upper": round(upper, 4),
                "mean_interval_width": round(interval_width, 4),
            }

    @property
    def is_fitted(self) -> bool:
        with self._lock:
            return self._fitted

    def info(self) -> dict:
        with self._lock:
            return {
                "fitted": self._fitted,
                "train_count": self._train_count,
                "feature_names": FEATURE_NAMES,
                "n_features": len(FEATURE_NAMES),
            }


# ── heuristic fallback ────────────────────────────────────────────────────────

def _heuristic_score(fv: list[float]) -> float:
    """Weighted sum of key features as a cold-start fallback."""
    # indices: signal_score=0, hook_score=2, angle_score=3,
    #          playbook_estimated_roas=5, hist_avg_roas=8, hist_win_rate=11
    weights = {0: 0.30, 2: 0.15, 3: 0.10, 5: 0.20, 8: 0.20, 11: 0.05}
    score = sum(fv[i] * w for i, w in weights.items() if i < len(fv))
    return float(max(0.0, min(1.0, score)))


# module-level singleton
scoring_model = ScoringModel()

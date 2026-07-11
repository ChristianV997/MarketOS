"""World Model Calibration — Bayesian update of simulation accuracy.

Compares predicted ROAS against actual ROAS outcomes and performs an online
Bayesian update of the world model's bias and scale parameters.

The calibrator maintains a Normal–Normal conjugate model:
  prior: μ_bias ~ N(prior_mean, prior_var)
  likelihood: observed_error ~ N(μ_bias, obs_var)

After each update the posterior mean is used as the bias estimate and the
posterior variance tracks our remaining uncertainty.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any


class WorldModelCalibrator:
    """Online Bayesian calibrator for world-model prediction accuracy.

    Parameters
    ----------
    prior_mean:
        Initial belief about prediction bias (0 = no bias).
    prior_var:
        Initial uncertainty about the bias (larger = less confident).
    obs_var:
        Assumed observation noise variance (fixed).
    window:
        Rolling window of raw errors for non-parametric stats.
    """

    def __init__(
        self,
        prior_mean: float = 0.0,
        prior_var: float = 1.0,
        obs_var: float = 0.5,
        window: int = 200,
        process_var: float = 0.01,
    ):
        # Bayesian Normal–Normal conjugate parameters
        self._mu: float = prior_mean       # posterior mean (bias estimate)
        self._var: float = prior_var       # posterior variance
        self._obs_var: float = obs_var     # observation noise (fixed)
        # Process noise added to the prior before each update. Without it the
        # posterior variance collapses monotonically toward 0 and the filter
        # stops responding to new observations (bias estimate freezes). This
        # is the standard Kalman "process noise" that keeps the estimator
        # tracking a bias that may drift over the life of the run.
        self._process_var: float = process_var

        # Raw error window for reporting
        self._errors: deque[float] = deque(maxlen=window)
        self._predictions: deque[float] = deque(maxlen=window)
        self._actuals: deque[float] = deque(maxlen=window)

        self.total_updates: int = 0

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, predicted: float, actual: float) -> None:
        """Ingest one (predicted, actual) observation and update the posterior."""
        error = predicted - actual
        self._errors.append(error)
        self._predictions.append(predicted)
        self._actuals.append(actual)
        self.total_updates += 1

        # Inflate the prior with process noise so the filter keeps tracking a
        # drifting bias instead of freezing as the posterior variance collapses.
        prior_var = self._var + self._process_var

        # Bayesian update: conjugate Normal–Normal
        # posterior_var = 1 / (1/prior_var + 1/obs_var)
        # posterior_mean = posterior_var * (prior_mean/prior_var + obs/obs_var)
        new_var = 1.0 / (1.0 / prior_var + 1.0 / self._obs_var)
        new_mu = new_var * (self._mu / prior_var + error / self._obs_var)
        self._mu = new_mu
        self._var = new_var

    # ------------------------------------------------------------------
    # Correction
    # ------------------------------------------------------------------

    def correct_prediction(self, pred: float) -> float:
        """Return a bias-corrected prediction."""
        return pred - self._mu

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return calibration statistics."""
        n = len(self._errors)
        if n < 2:
            return {
                "bias": 0.0,
                "uncertainty": 1.0,
                "mae": 0.0,
                "rmse": 0.0,
                "posterior_var": self._var,
                "n_samples": n,
            }
        errors = list(self._errors)
        bias = sum(errors) / n
        mae = sum(abs(e) for e in errors) / n
        rmse = math.sqrt(sum(e ** 2 for e in errors) / n)
        return {
            "bias": round(bias, 6),
            "uncertainty": round(math.sqrt(self._var), 6),
            "mae": round(mae, 6),
            "rmse": round(rmse, 6),
            "posterior_var": round(self._var, 8),
            "n_samples": n,
        }

    def prediction_errors(self) -> list[dict[str, float]]:
        """Return recent (predicted, actual, error) triples for dashboard use."""
        return [
            {"predicted": round(p, 4), "actual": round(a, 4), "error": round(p - a, 4)}
            for p, a in zip(self._predictions, self._actuals)
        ]


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

world_model_calibrator = WorldModelCalibrator()

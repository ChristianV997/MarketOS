"""Tests for simulation.model — Phase 7 Monte Carlo prediction intervals."""
from __future__ import annotations

import pytest
import numpy as np

from simulation.model import ScoringModel


class TestPredictionIntervalColdStart:
    """Prediction intervals when model not yet fitted."""

    def test_unfitted_model_returns_default_intervals(self):
        model = ScoringModel()
        signal = {
            "product": "test_product",
            "score": 0.6,
            "velocity": 0.5,
            "hook": "hook_1",
            "angle": "angle_1",
            "regime": "stable",
            "engagement_rate": 0.04,
        }
        result = model.predict_with_intervals(signal)

        assert "point_estimate" in result
        assert "percentiles" in result
        assert "confidence_interval_lower" in result
        assert "confidence_interval_upper" in result
        assert result["confidence_interval_lower"] == pytest.approx(result["point_estimate"] - 0.1, abs=0.01)
        assert result["confidence_interval_upper"] == pytest.approx(result["point_estimate"] + 0.1, abs=0.01)

    def test_cold_start_interval_width_is_standard(self):
        model = ScoringModel()
        signal = {"product": "test", "score": 0.5}
        result = model.predict_with_intervals(signal)

        interval_width = result["confidence_interval_upper"] - result["confidence_interval_lower"]
        assert interval_width == pytest.approx(0.2, abs=0.01)


class TestPredictionIntervalFitted:
    """Prediction intervals after model is fitted."""

    def test_fitted_model_computes_residuals(self):
        model = ScoringModel()
        # Simple synthetic data
        rows = [
            {
                "product": f"prod_{i}",
                "roas": 1.0 + 0.1 * (i % 5),
                "ctr": 0.03 + 0.001 * i,
                "cvr": 0.02 + 0.0005 * i,
                "hook": "hook_1",
                "angle": "angle_1",
                "velocity": 0.5,
                "engagement_rate": 0.04,
                "env_regime": "stable",
            }
            for i in range(25)
        ]

        model.fit(rows)
        assert model.is_fitted
        assert len(model._residuals) > 0

    def test_prediction_interval_narrower_than_cold_start(self):
        model = ScoringModel()
        rows = [
            {
                "product": f"prod_{i}",
                "roas": 2.0 + 0.05 * (i % 5),
                "ctr": 0.03,
                "cvr": 0.02,
                "hook": "hook_1",
                "angle": "angle_1",
                "velocity": 0.5,
                "engagement_rate": 0.04,
                "env_regime": "stable",
            }
            for i in range(30)
        ]

        model.fit(rows)

        signal = {
            "product": "test_product",
            "score": 0.6,
            "velocity": 0.5,
            "hook": "hook_1",
            "angle": "angle_1",
            "regime": "stable",
            "engagement_rate": 0.04,
        }

        result = model.predict_with_intervals(signal)
        interval_width = result["confidence_interval_upper"] - result["confidence_interval_lower"]

        # Fitted model with low-noise data should have narrower intervals
        assert interval_width < 0.2

    def test_percentile_bounds_consistent(self):
        model = ScoringModel()
        rows = [
            {
                "product": f"prod_{i}",
                "roas": 1.5,
                "ctr": 0.03,
                "cvr": 0.02,
                "hook": "hook_1",
                "angle": "angle_1",
                "velocity": 0.5,
                "engagement_rate": 0.04,
                "env_regime": "stable",
            }
            for i in range(25)
        ]

        model.fit(rows)

        signal = {"product": "test", "score": 0.6}
        result = model.predict_with_intervals(signal)

        percentiles = result["percentiles"]
        # Percentiles should be monotonically increasing
        assert percentiles[5] <= percentiles[25]
        assert percentiles[25] <= percentiles[50]
        assert percentiles[50] <= percentiles[75]
        assert percentiles[75] <= percentiles[95]

    def test_confidence_interval_bounds_clipped_01(self):
        model = ScoringModel()
        # Data with high variance to generate wide intervals
        rows = [
            {
                "product": f"prod_{i}",
                "roas": float((i % 3) * 2),  # Highly variable
                "ctr": 0.02 + 0.01 * (i % 3),
                "cvr": 0.01 + 0.005 * (i % 3),
                "hook": "hook_1",
                "angle": "angle_1",
                "velocity": 0.5,
                "engagement_rate": 0.04,
                "env_regime": "stable",
            }
            for i in range(25)
        ]

        model.fit(rows)

        signal = {"product": "test", "score": 0.95}  # High score
        result = model.predict_with_intervals(signal)

        # Bounds should be clipped to [0, 1]
        assert 0.0 <= result["confidence_interval_lower"]
        assert result["confidence_interval_upper"] <= 1.0

    def test_mean_interval_width_computed(self):
        model = ScoringModel()
        rows = [
            {
                "product": f"prod_{i}",
                "roas": 1.5,
                "ctr": 0.03,
                "cvr": 0.02,
                "hook": "hook_1",
                "angle": "angle_1",
                "velocity": 0.5,
                "engagement_rate": 0.04,
                "env_regime": "stable",
            }
            for i in range(25)
        ]

        model.fit(rows)

        signal = {"product": "test", "score": 0.6}
        result = model.predict_with_intervals(signal)

        interval_width = result["confidence_interval_upper"] - result["confidence_interval_lower"]
        assert result["mean_interval_width"] == pytest.approx(interval_width, abs=0.001)


class TestPredictionIntervalDeterminism:
    """Prediction intervals should be consistent for same signal."""

    def test_same_signal_gives_same_intervals_within_tolerance(self):
        model = ScoringModel()
        rows = [
            {
                "product": f"prod_{i}",
                "roas": 1.5,
                "ctr": 0.03,
                "cvr": 0.02,
                "hook": "hook_1",
                "angle": "angle_1",
                "velocity": 0.5,
                "engagement_rate": 0.04,
                "env_regime": "stable",
            }
            for i in range(25)
        ]

        model.fit(rows)

        signal = {"product": "test_product_123", "score": 0.6}

        result1 = model.predict_with_intervals(signal)
        result2 = model.predict_with_intervals(signal)

        # Should produce identical results (deterministic seed from signal)
        assert result1["confidence_interval_lower"] == result2["confidence_interval_lower"]
        assert result1["confidence_interval_upper"] == result2["confidence_interval_upper"]

    def test_different_signals_may_have_different_intervals(self):
        model = ScoringModel()
        rows = [
            {
                "product": f"prod_{i}",
                "roas": 1.5,
                "ctr": 0.03,
                "cvr": 0.02,
                "hook": "hook_1",
                "angle": "angle_1",
                "velocity": 0.5,
                "engagement_rate": 0.04,
                "env_regime": "stable",
            }
            for i in range(25)
        ]

        model.fit(rows)

        signal1 = {"product": "product_A", "score": 0.6}
        signal2 = {"product": "product_B", "score": 0.6}

        result1 = model.predict_with_intervals(signal1)
        result2 = model.predict_with_intervals(signal2)

        # Different signals may produce different bootstrap samples (seeded differently)
        # but point estimates should be similar
        assert abs(result1["point_estimate"] - result2["point_estimate"]) < 0.2


class TestPredictionIntervalShape:
    """Interval shape reflects residual distribution."""

    def test_symmetric_residuals_give_symmetric_intervals(self):
        model = ScoringModel()
        # Create perfectly symmetric residuals
        rows = [
            {
                "product": f"prod_{i}",
                "roas": 2.0 if i % 2 == 0 else 1.0,  # Bimodal
                "ctr": 0.03,
                "cvr": 0.02,
                "hook": "hook_1",
                "angle": "angle_1",
                "velocity": 0.5,
                "engagement_rate": 0.04,
                "env_regime": "stable",
            }
            for i in range(30)
        ]

        model.fit(rows)

        signal = {"product": "test", "score": 0.5}
        result = model.predict_with_intervals(signal)

        point = result["point_estimate"]
        lower = result["confidence_interval_lower"]
        upper = result["confidence_interval_upper"]

        # For symmetric distribution, point estimate should be roughly centered
        dist_to_lower = point - lower
        dist_to_upper = upper - point
        assert abs(dist_to_lower - dist_to_upper) < 0.1

    def test_high_variance_residuals_give_wide_intervals(self):
        model1 = ScoringModel()
        model2 = ScoringModel()

        # Low-variance data
        rows_low_var = [
            {
                "product": f"prod_{i}",
                "roas": 1.5 + 0.01 * (i % 3),  # ±0.01 variation
                "ctr": 0.03,
                "cvr": 0.02,
                "hook": "hook_1",
                "angle": "angle_1",
                "velocity": 0.5,
                "engagement_rate": 0.04,
                "env_regime": "stable",
            }
            for i in range(25)
        ]

        # High-variance data
        rows_high_var = [
            {
                "product": f"prod_{i}",
                "roas": 1.5 + 0.5 * (i % 3),  # ±0.5 variation
                "ctr": 0.03,
                "cvr": 0.02,
                "hook": "hook_1",
                "angle": "angle_1",
                "velocity": 0.5,
                "engagement_rate": 0.04,
                "env_regime": "stable",
            }
            for i in range(25)
        ]

        model1.fit(rows_low_var)
        model2.fit(rows_high_var)

        signal = {"product": "test", "score": 0.5}
        result1 = model1.predict_with_intervals(signal)
        result2 = model2.predict_with_intervals(signal)

        width1 = result1["mean_interval_width"]
        width2 = result2["mean_interval_width"]

        # High variance should produce wider intervals
        assert width2 > width1


class TestPredictionIntervalOutputFormat:
    """Output structure and types."""

    def test_all_required_keys_present(self):
        model = ScoringModel()
        rows = [
            {
                "product": f"prod_{i}",
                "roas": 1.5,
                "ctr": 0.03,
                "cvr": 0.02,
                "hook": "hook_1",
                "angle": "angle_1",
                "velocity": 0.5,
                "engagement_rate": 0.04,
                "env_regime": "stable",
            }
            for i in range(25)
        ]
        model.fit(rows)

        signal = {"product": "test", "score": 0.6}
        result = model.predict_with_intervals(signal)

        required_keys = {
            "point_estimate",
            "percentiles",
            "confidence_interval_lower",
            "confidence_interval_upper",
            "mean_interval_width",
        }
        assert required_keys.issubset(result.keys())

    def test_percentiles_dict_has_requested_values(self):
        model = ScoringModel()
        rows = [{"product": f"p_{i}", "roas": 1.5, "ctr": 0.03, "cvr": 0.02} for i in range(25)]
        model.fit(rows)

        signal = {"product": "test", "score": 0.6}
        result = model.predict_with_intervals(signal, percentiles=(5, 25, 50, 75, 95))

        percentiles = result["percentiles"]
        for p in [5, 25, 50, 75, 95]:
            assert p in percentiles
            assert 0.0 <= percentiles[p] <= 1.0

    def test_values_are_floats(self):
        model = ScoringModel()
        rows = [{"product": f"p_{i}", "roas": 1.5, "ctr": 0.03, "cvr": 0.02} for i in range(25)]
        model.fit(rows)

        signal = {"product": "test", "score": 0.6}
        result = model.predict_with_intervals(signal)

        assert isinstance(result["point_estimate"], float)
        assert isinstance(result["confidence_interval_lower"], float)
        assert isinstance(result["confidence_interval_upper"], float)
        assert isinstance(result["mean_interval_width"], float)

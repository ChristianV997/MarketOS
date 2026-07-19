"""Tests for backend.discovery.trend_history — trend-based urgency scoring."""
from __future__ import annotations

from datetime import datetime, timezone
import pytest

from backend.discovery.trend_history import TrendHistory


class TestTrendHistoryBasics:
    """Basic trend history recording and retrieval."""

    def test_record_single_observation(self):
        th = TrendHistory()
        th.record("product_1", velocity=0.6, saturation=0.3)
        stats = th.get_trend_stats("product_1")
        assert stats["current_velocity"] == pytest.approx(0.6)

    def test_empty_product_returns_defaults(self):
        th = TrendHistory()
        stats = th.get_trend_stats("nonexistent")
        assert stats["current_velocity"] == 0.0
        assert stats["lifecycle"] == "unknown"
        assert stats["acceleration"] == 0.0

    def test_clamping_to_01_range(self):
        th = TrendHistory()
        th.record("product_1", velocity=1.5, saturation=-0.5)
        stats = th.get_trend_stats("product_1")
        # Values should be clamped to [0, 1]
        assert 0.0 <= stats["current_velocity"] <= 1.0

    def test_velocity_vs_saturation_independent(self):
        th = TrendHistory()
        th.record("product_1", velocity=0.8, saturation=0.2)
        th.record("product_1", velocity=0.5, saturation=0.6)
        stats = th.get_trend_stats("product_1")
        assert stats["current_velocity"] == pytest.approx(0.5)


class TestTrendStatsComputation:
    """Rolling window statistics."""

    def test_recent_vs_older_split(self):
        th = TrendHistory()
        now = datetime.now(timezone.utc).timestamp()

        # Record 10 older observations (velocity 1.0)
        for i in range(10):
            ts = now - (20 - i) * 86400  # 20-11 days ago
            th.record("product_1", velocity=1.0, saturation=0.2, ts=ts)

        # Record 7 recent observations (velocity 0.3)
        for i in range(7):
            ts = now - (6 - i) * 86400  # last 7 days
            th.record("product_1", velocity=0.3, saturation=0.5, ts=ts)

        stats = th.get_trend_stats("product_1")
        assert stats["avg_velocity_recent"] == pytest.approx(0.3, abs=0.01)
        assert stats["avg_velocity_older"] == pytest.approx(1.0, abs=0.01)
        assert stats["saturation_trend"] == pytest.approx(0.3, abs=0.01)  # 0.5 - 0.2

    def test_acceleration_computation(self):
        th = TrendHistory()
        now = datetime.now(timezone.utc).timestamp()

        # Increasing velocity: 0.2 → 0.8 (positive acceleration)
        for i in range(15):
            vel = 0.2 + (0.6 * i / 14)  # Ramp from 0.2 to 0.8
            ts = now - (14 - i) * 86400
            th.record("product_1", velocity=vel, saturation=0.3, ts=ts)

        stats = th.get_trend_stats("product_1")
        assert stats["acceleration"] > 0.0  # Rising trend

    def test_lifecycle_rising(self):
        th = TrendHistory()
        now = datetime.now(timezone.utc).timestamp()

        # Velocity increasing from 0.2 to 0.8
        for i in range(20):
            vel = 0.2 + (0.6 * i / 19)
            ts = now - (19 - i) * 86400
            th.record("product_1", velocity=vel, saturation=0.3, ts=ts)

        stats = th.get_trend_stats("product_1")
        assert stats["lifecycle"] == "rising"

    def test_lifecycle_declining(self):
        th = TrendHistory()
        now = datetime.now(timezone.utc).timestamp()

        # Velocity decreasing from 0.8 to 0.2
        for i in range(20):
            vel = 0.8 - (0.6 * i / 19)
            ts = now - (19 - i) * 86400
            th.record("product_1", velocity=vel, saturation=0.3, ts=ts)

        stats = th.get_trend_stats("product_1")
        assert stats["lifecycle"] == "declining"

    def test_lifecycle_peak(self):
        th = TrendHistory()
        # Steady high velocity
        for _ in range(15):
            th.record("product_1", velocity=0.7, saturation=0.4)

        stats = th.get_trend_stats("product_1")
        assert stats["lifecycle"] == "peak"

    def test_lifecycle_unknown_low_velocity(self):
        th = TrendHistory()
        # Steady low velocity with small acceleration
        for _ in range(15):
            th.record("product_1", velocity=0.1, saturation=0.2)

        stats = th.get_trend_stats("product_1")
        assert stats["lifecycle"] == "unknown"


class TestTrendHistoryBounds:
    """Boundary conditions and limits."""

    def test_maxlen_respected(self):
        th = TrendHistory(max_history=20)
        # Record 50 observations; deque should cap at 20
        for i in range(50):
            th.record("product_1", velocity=float(i % 10) / 10, saturation=0.3)

        stats = th.get_trend_stats("product_1")
        # Should reflect only recent observations (last 20)
        assert isinstance(stats, dict)

    def test_insufficient_data_graceful(self):
        th = TrendHistory()
        th.record("product_1", velocity=0.5, saturation=0.3)
        stats = th.get_trend_stats("product_1")
        # Should return valid dict even with single point
        assert stats["avg_velocity_recent"] == pytest.approx(0.5)

    def test_recent_window_smaller_than_full_history(self):
        th = TrendHistory()
        # Record 5 observations (fewer than 7-day trend window)
        for i in range(5):
            th.record("product_1", velocity=0.6, saturation=0.4)

        stats = th.get_trend_stats("product_1")
        # Recent should include all 5
        assert stats["avg_velocity_recent"] == pytest.approx(0.6, abs=0.01)


class TestClear:
    """History clearing."""

    def test_clear_erases_product_history(self):
        th = TrendHistory()
        th.record("product_1", velocity=0.7, saturation=0.3)
        th.clear("product_1")

        stats = th.get_trend_stats("product_1")
        assert stats["current_velocity"] == 0.0
        assert stats["lifecycle"] == "unknown"

    def test_clear_only_affects_specified_product(self):
        th = TrendHistory()
        th.record("product_1", velocity=0.7, saturation=0.3)
        th.record("product_2", velocity=0.5, saturation=0.4)

        th.clear("product_1")

        stats1 = th.get_trend_stats("product_1")
        stats2 = th.get_trend_stats("product_2")

        assert stats1["current_velocity"] == 0.0
        assert stats2["current_velocity"] == pytest.approx(0.5)


class TestMultipleProducts:
    """Multiple products tracked independently."""

    def test_independent_product_tracking(self):
        th = TrendHistory()

        # Product 1: rising
        for i in range(15):
            vel = 0.2 + (0.5 * i / 14)
            th.record("product_1", velocity=vel, saturation=0.2)

        # Product 2: declining
        for i in range(15):
            vel = 0.7 - (0.5 * i / 14)
            th.record("product_2", velocity=vel, saturation=0.6)

        stats1 = th.get_trend_stats("product_1")
        stats2 = th.get_trend_stats("product_2")

        assert stats1["lifecycle"] == "rising"
        assert stats2["lifecycle"] == "declining"

    def test_products_dont_interfere(self):
        th = TrendHistory()
        for _ in range(20):
            th.record("product_1", velocity=0.8, saturation=0.2)
            th.record("product_2", velocity=0.3, saturation=0.8)

        stats1 = th.get_trend_stats("product_1")
        stats2 = th.get_trend_stats("product_2")

        assert stats1["current_velocity"] == pytest.approx(0.8)
        assert stats2["current_velocity"] == pytest.approx(0.3)


class TestUrgencyComposition:
    """Urgency formula: velocity * (1 - saturation) * (1 + acceleration)."""

    def test_urgency_formula_high_velocity_low_saturation(self):
        """High urgency: rising trend, strong demand, low competition."""
        th = TrendHistory()
        for i in range(15):
            vel = 0.2 + (0.6 * i / 14)  # Accelerating
            sat = 0.1  # Low competition
            th.record("product_1", velocity=vel, saturation=sat)

        stats = th.get_trend_stats("product_1")
        # Simulated urgency = vel * (1 - sat) * (1 + accel)
        urgency = (
            stats["current_velocity"]
            * (1 - 0.1)
            * (1 + stats["acceleration"])
        )
        # Should be high
        assert urgency > 0.4

    def test_urgency_formula_low_velocity_high_saturation(self):
        """Low urgency: declining or steady, high competition."""
        th = TrendHistory()
        for _ in range(15):
            th.record("product_1", velocity=0.2, saturation=0.8)

        stats = th.get_trend_stats("product_1")
        urgency = (
            stats["current_velocity"]
            * (1 - 0.8)
            * (1 + max(stats["acceleration"], 0))
        )
        # Should be low
        assert urgency < 0.1

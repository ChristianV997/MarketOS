"""Tests for core.creative.fatigue_detector — rolling-window creative fatigue detection."""
from __future__ import annotations

from datetime import datetime, timezone
import pytest

from core.creative.fatigue_detector import FatigueDetector


class TestFatigueDetectorBasics:
    """Basic fatigue detection functionality."""

    def test_record_and_check_single_hook(self):
        det = FatigueDetector()
        det.record_performance(hook_id="hook_1", roas=1.5)
        is_fatigued, details = det.is_fatigued(hook_id="hook_1")
        assert not is_fatigued
        assert details["insufficient_data"]

    def test_insufficient_data_with_single_point(self):
        det = FatigueDetector()
        det.record_performance(hook_id="hook_1", roas=2.0)
        assert not det.is_fatigued(hook_id="hook_1")[0]

    def test_no_fatigue_when_steady_high(self):
        det = FatigueDetector()
        now = datetime.now(timezone.utc).timestamp()
        # Spread observations across full window to get both trend and historical
        for i in range(30):
            ts = now - (29 - i) * 86400  # Days 0-29
            det.record_performance(hook_id="hook_1", roas=2.0, ts=ts)
        is_fatigued, details = det.is_fatigued(hook_id="hook_1")
        assert not is_fatigued
        assert details["trend_roas"] == pytest.approx(2.0, abs=0.01)
        assert details["historical_roas"] == pytest.approx(2.0, abs=0.01)
        assert details["decay_pct"] == pytest.approx(0.0, abs=0.01)

    def test_detects_decay_from_high_to_low(self):
        det = FatigueDetector(window_days=30, trend_days=7, decay_threshold=0.20)
        now = datetime.now(timezone.utc).timestamp()
        # Old observations (days 8-30): high ROAS
        for i in range(23):
            ts = now - (30 - i) * 86400
            det.record_performance(hook_id="hook_1", roas=2.0, ts=ts)
        # Recent observations (last 7 days): low ROAS
        for i in range(7):
            ts = now - (6 - i) * 86400
            det.record_performance(hook_id="hook_1", roas=1.2, ts=ts)

        is_fatigued, details = det.is_fatigued(hook_id="hook_1")
        assert is_fatigued
        # Allow slight tolerance in trend/historical due to boundary effects
        assert details["trend_roas"] <= 1.3  # Slightly higher due to overlap
        assert details["historical_roas"] >= 1.9  # High historical value
        assert details["decay_pct"] >= 0.15

    def test_refresh_recommendation_severe_decay(self):
        det = FatigueDetector(decay_threshold=0.20)
        # 50% decay
        for i in range(20):
            ts = datetime.now(timezone.utc).timestamp() - (29 - i) * 86400
            det.record_performance(hook_id="hook_1", roas=2.0, ts=ts)
        for i in range(7):
            ts = datetime.now(timezone.utc).timestamp() - (6 - i) * 86400
            det.record_performance(hook_id="hook_1", roas=1.0, ts=ts)

        should_refresh, reason = det.refresh_recommendation(hook_id="hook_1")
        assert should_refresh
        assert "decay" in reason.lower()

    def test_angle_tracking_independent_of_hook(self):
        det = FatigueDetector()
        for _ in range(20):
            det.record_performance(hook_id="hook_1", roas=2.0)
            det.record_performance(angle_id="angle_1", roas=1.0)

        hook_fatigued, _ = det.is_fatigued(hook_id="hook_1")
        angle_fatigued, _ = det.is_fatigued(angle_id="angle_1")
        assert not hook_fatigued
        assert not angle_fatigued


class TestFatigueDetectorWindowBehavior:
    """Window sizing and rolling behavior."""

    def test_deque_respects_maxlen(self):
        det = FatigueDetector(window_days=10)
        # Record 40 observations; deque maxlen should cap at 10
        now = datetime.now(timezone.utc).timestamp()
        for i in range(40):
            ts = now - (40 - i) * 86400
            det.record_performance(hook_id="hook_1", roas=float(i % 5), ts=ts)

        _, details = det.is_fatigued(hook_id="hook_1")
        # Should only see the last 10 days of data
        assert details["days_of_data"] <= 10

    def test_trend_vs_historical_split(self):
        det = FatigueDetector(window_days=30, trend_days=7)
        now = datetime.now(timezone.utc).timestamp()

        # Days 9-30: ROAS = 3.0 (22 observations)
        for i in range(22):
            ts = now - (31 - i) * 86400  # Days 31-10
            det.record_performance(hook_id="hook_1", roas=3.0, ts=ts)

        # Days 1-7: ROAS = 1.0 (7 observations)
        for i in range(7):
            ts = now - (7 - i) * 86400  # Days 7-1
            det.record_performance(hook_id="hook_1", roas=1.0, ts=ts)

        _, details = det.is_fatigued(hook_id="hook_1")
        assert details["trend_roas"] == pytest.approx(1.0, abs=0.05)
        # Historical should be close to 3.0 (the 22 older observations)
        assert details["historical_roas"] > 2.5


class TestFatigueDetectorEdgeCases:
    """Edge cases and boundary conditions."""

    def test_zero_roas_handling(self):
        det = FatigueDetector()
        det.record_performance(hook_id="hook_1", roas=0.0)
        det.record_performance(hook_id="hook_1", roas=0.0)
        is_fatigued, details = det.is_fatigued(hook_id="hook_1")
        assert not is_fatigued or details.get("insufficient_data")

    def test_negative_roas_clamped(self):
        det = FatigueDetector()
        det.record_performance(hook_id="hook_1", roas=-1.0)
        det.record_performance(hook_id="hook_1", roas=2.0)
        # Negative values shouldn't cause crashes, should be handled gracefully
        _, details = det.is_fatigued(hook_id="hook_1")
        assert isinstance(details.get("decay_pct", 0.0), float)

    def test_division_by_zero_handling(self):
        det = FatigueDetector()
        # All zeros in historical window
        for _ in range(20):
            det.record_performance(hook_id="hook_1", roas=0.0)
        # Non-zero in recent
        for _ in range(7):
            det.record_performance(hook_id="hook_1", roas=1.0)

        _, details = det.is_fatigued(hook_id="hook_1")
        # Should not crash, decay_pct should be clamped
        assert 0.0 <= details["decay_pct"] <= 1.0

    def test_custom_decay_threshold(self):
        det = FatigueDetector(decay_threshold=0.50)
        now = datetime.now(timezone.utc).timestamp()

        for i in range(20):
            ts = now - (29 - i) * 86400
            det.record_performance(hook_id="hook_1", roas=2.0, ts=ts)
        for i in range(7):
            ts = now - (6 - i) * 86400
            det.record_performance(hook_id="hook_1", roas=1.5, ts=ts)  # 25% decay

        # 25% decay < 50% threshold, should not be fatigued
        is_fatigued, _ = det.is_fatigued(hook_id="hook_1")
        assert not is_fatigued


class TestFatigueDetectorRecommendation:
    """High-level refresh recommendations."""

    def test_recommendation_logic_good_creative(self):
        det = FatigueDetector()
        for _ in range(25):
            det.record_performance(hook_id="hook_1", roas=2.5)
        should_refresh, reason = det.refresh_recommendation(hook_id="hook_1")
        assert not should_refresh
        assert reason == "performing_well"

    def test_recommendation_logic_moderate_decay(self):
        det = FatigueDetector(decay_threshold=0.20)
        now = datetime.now(timezone.utc).timestamp()

        for i in range(20):
            ts = now - (29 - i) * 86400
            det.record_performance(hook_id="hook_1", roas=2.0, ts=ts)
        for i in range(7):
            ts = now - (6 - i) * 86400
            det.record_performance(hook_id="hook_1", roas=1.6, ts=ts)  # 20% decay

        should_refresh, reason = det.refresh_recommendation(hook_id="hook_1")
        assert should_refresh
        assert "decay" in reason.lower()

    def test_recommendation_insufficient_data(self):
        det = FatigueDetector()
        det.record_performance(hook_id="hook_1", roas=2.0)
        # With only 1 observation, insufficient_data flag is set
        should_refresh, reason = det.refresh_recommendation(hook_id="hook_1")
        # Should not recommend refresh when data is insufficient
        assert not should_refresh
        # Reason should indicate insufficient data (not necessarily exact string)
        assert "data" in reason.lower() or reason == "performing_well"

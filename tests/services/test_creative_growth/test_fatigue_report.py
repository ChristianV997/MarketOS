"""Tests for services.creative_growth.fatigue_report.analyze_creative_fatigue.

hook_fatigue_detector/sequence_fatigue_optimizer are process-wide, unpersisted
singletons (no test-isolation fixture exists for them upstream, matching
tests/test_phase7_creative_optimization.py's approach of testing fresh
instances directly) — this module wraps the singletons directly (matching
what the live orchestrator loop actually uses), so tests use unique hook/
angle IDs per test to avoid cross-test contamination instead.
"""
import uuid
from datetime import datetime, timedelta

from services.creative_growth.fatigue_report import analyze_creative_fatigue

# HookFatigueDetector/SequenceOptimizer compute cutoffs via naive
# datetime.utcnow() internally — timestamps recorded here must be naive
# too, or the >= comparison inside get_recent_roas/get_historical_roas
# raises TypeError (which analyze_creative_fatigue's fail-soft wrapper
# would otherwise silently swallow, masking the real data).
_now = datetime.utcnow


def _unique(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class TestAnalyzeCreativeFatigue:
    def test_unrecorded_hook_and_angle_report_not_fatigued(self):
        hook, angle = _unique("hook"), _unique("angle")
        report = analyze_creative_fatigue([hook], [angle])
        assert report["fatigued_hooks"] == []
        assert report["fatigued_angles"] == []
        assert report["refresh_needed"] is False

    def test_declining_hook_roas_is_flagged_fatigued(self):
        from core.creative.hook_performance import hook_fatigue_detector
        hook = _unique("hook")
        now = _now()
        # historical (8-30 days ago): strong ROAS
        for days_ago in (10, 15, 20, 25):
            hook_fatigue_detector.record_roas(hook, 3.0, timestamp=now - timedelta(days=days_ago))
        # recent (last 7 days): decayed ROAS
        for days_ago in (1, 2, 3):
            hook_fatigue_detector.record_roas(hook, 0.5, timestamp=now - timedelta(days=days_ago))

        report = analyze_creative_fatigue([hook], [])
        assert hook in report["fatigued_hooks"]
        assert report["refresh_needed"] is True

    def test_stable_hook_roas_not_flagged_fatigued(self):
        from core.creative.hook_performance import hook_fatigue_detector
        hook = _unique("hook")
        now = _now()
        for days_ago in (1, 5, 10, 20):
            hook_fatigue_detector.record_roas(hook, 2.0, timestamp=now - timedelta(days=days_ago))

        report = analyze_creative_fatigue([hook], [])
        assert hook not in report["fatigued_hooks"]

    def test_declining_angle_roas_is_flagged_fatigued(self):
        from core.creative.sequence_optimizer import sequence_fatigue_optimizer
        angle = _unique("angle")
        now = _now()
        for days_ago in (10, 15, 20, 25):
            sequence_fatigue_optimizer.update(angle, 3.0, timestamp=now - timedelta(days=days_ago))
        for days_ago in (1, 2, 3):
            sequence_fatigue_optimizer.update(angle, 0.5, timestamp=now - timedelta(days=days_ago))

        report = analyze_creative_fatigue([], [angle])
        assert angle in report["fatigued_angles"]

    def test_never_raises_when_hook_detector_fails(self, monkeypatch):
        def _boom(hook):
            raise RuntimeError("boom")
        monkeypatch.setattr("core.creative.hook_performance.hook_fatigue_detector.get_fatigue_metrics", _boom)
        report = analyze_creative_fatigue([_unique("hook")], [])
        assert report["hook_reports"] == []

    def test_empty_inputs_return_empty_report(self):
        report = analyze_creative_fatigue([], [])
        assert report["refresh_needed"] is False
        assert report["hook_reports"] == []
        assert report["angle_reports"] == []

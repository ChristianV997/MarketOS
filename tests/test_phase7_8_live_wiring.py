"""Tests for Phase 7-8 live wiring: core/creative/selection.py, core/portfolio.py
organic blending, and simulation/engine.py Monte Carlo gating.

These modules were originally built standalone with no call sites in the
live execution path (see DEPLOYMENT_GUIDE.md "Live Wiring"). This suite
locks in the selection ladder, the flag gating, and the shadow journaling
added when they were wired in.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for flag in (
        "PHASE7_FATIGUE_DETECTION_LIVE", "PHASE7_AB_TEST_VALIDITY_LIVE",
        "PHASE7_URGENCY_SCORING_LIVE", "PHASE7_MONTE_CARLO_LIVE",
        "PHASE8_ORGANIC_CHANNEL_LIVE", "PHASE8_AFFILIATE_SCALING_LIVE",
    ):
        monkeypatch.delenv(flag, raising=False)
    yield


class TestCreativeSelectionLadder:
    """core/creative/selection.py: fatigue + A/B-validity gated pool selection."""

    def test_flags_off_returns_legacy_pool(self, monkeypatch):
        from core.content.patterns import PatternStore
        import core.content.patterns as pat_mod

        store = PatternStore()
        store.update({"hook_scores": {"h1": 0.9, "h2": 0.5}, "angle_scores": {}, "regime_scores": {}})
        monkeypatch.setattr(pat_mod, "pattern_store", store)

        from core.creative.selection import select_hooks
        hooks = select_hooks(n=5, fallback=["fallback"])
        assert hooks == ["h1", "h2"]

    def test_fatigued_candidate_excluded_when_flag_live(self, monkeypatch):
        from core.content.patterns import PatternStore
        import core.content.patterns as pat_mod
        from core.creative.hook_performance import HookFatigueDetector
        import core.creative.hook_performance as hook_mod

        store = PatternStore()
        store.update({"hook_scores": {"h1": 0.9, "h2": 0.5}, "angle_scores": {}, "regime_scores": {}})
        monkeypatch.setattr(pat_mod, "pattern_store", store)

        detector = HookFatigueDetector()
        now = datetime.utcnow()
        for i in range(10):
            detector.record_roas("h1", 2.0, timestamp=now - timedelta(days=10 + i))
        for i in range(5):
            detector.record_roas("h1", 0.2, timestamp=now - timedelta(days=1))
        assert detector.is_fatigued("h1")
        monkeypatch.setattr(hook_mod, "hook_fatigue_detector", detector)

        monkeypatch.setenv("PHASE7_FATIGUE_DETECTION_LIVE", "true")
        from core.creative.selection import select_hooks
        hooks = select_hooks(n=5, fallback=["fallback"])
        assert "h1" not in hooks
        assert "h2" in hooks

    def test_all_candidates_fatigued_falls_back_without_readmitting(self, monkeypatch):
        """Regression test: when every candidate in every broadening tier is
        fatigued, the ladder must not silently re-admit a fatigued hook just
        to avoid returning an empty pool from an intermediate tier — it
        should exhaust every tier (base -> legacy -> fallback) first."""
        from core.content.patterns import PatternStore
        import core.content.patterns as pat_mod
        from core.creative.hook_performance import HookFatigueDetector
        import core.creative.hook_performance as hook_mod

        store = PatternStore()
        # Build h1 up to statistical validity (n>=20) so the validated pool
        # is exactly {"h1"} - the scenario where the old bug manifested.
        for _ in range(25):
            store.update({"hook_scores": {"h1": 0.9}, "angle_scores": {}, "regime_scores": {}})
        store.update({"hook_scores": {"h2": 0.5}, "angle_scores": {}, "regime_scores": {}})
        monkeypatch.setattr(pat_mod, "pattern_store", store)

        detector = HookFatigueDetector()
        now = datetime.utcnow()
        for i in range(10):
            detector.record_roas("h1", 2.0, timestamp=now - timedelta(days=10 + i))
        for i in range(5):
            detector.record_roas("h1", 0.2, timestamp=now - timedelta(days=1))
        assert detector.is_fatigued("h1")
        monkeypatch.setattr(hook_mod, "hook_fatigue_detector", detector)

        monkeypatch.setenv("PHASE7_AB_TEST_VALIDITY_LIVE", "true")
        monkeypatch.setenv("PHASE7_FATIGUE_DETECTION_LIVE", "true")
        from core.creative.selection import select_hooks
        hooks = select_hooks(n=5, fallback=["fallback"])
        # validated pool is {h1} but h1 is fatigued -> must broaden to legacy
        # {h1, h2} minus fatigued -> {h2}, NOT silently return {h1}.
        assert hooks == ["h2"]

    def test_record_creative_outcome_feeds_both_detectors(self, monkeypatch):
        from core.creative.hook_performance import HookFatigueDetector
        import core.creative.hook_performance as hook_mod
        from core.creative.sequence_optimizer import SequenceOptimizer
        import core.creative.sequence_optimizer as seq_mod

        hd = HookFatigueDetector()
        so = SequenceOptimizer()
        monkeypatch.setattr(hook_mod, "hook_fatigue_detector", hd)
        monkeypatch.setattr(seq_mod, "sequence_fatigue_optimizer", so)

        from core.creative.selection import record_creative_outcome
        record_creative_outcome("h1", "a1", 1.5)

        assert hd.hook_history["h1"]
        assert so.sequence_history["a1"]


class TestOrganicChannelPortfolioBlend:
    """core/portfolio.py: Phase 8 organic ROAS blended into capital allocation."""

    def test_no_organic_data_leaves_pred_unchanged(self, monkeypatch):
        import core.portfolio as portfolio

        portfolio.reset()
        portfolio.update_portfolio("prod_a", {"revenue": 200.0, "spend": 100.0, "roas": 2.0})
        pred, _ = portfolio._pred_and_width("prod_a", portfolio.portfolio["prod_a"])
        assert pred == pytest.approx(2.0, rel=0.01)

    def test_organic_blend_applied_only_when_flag_live(self, monkeypatch):
        import core.portfolio as portfolio
        from core.ugc.creator_tracker import CreatorTracker
        import core.ugc.creator_tracker as ct_mod

        tracker = CreatorTracker()
        tracker.record_seed("creator_1", "prod_b", seeding_cost=100.0)
        tracker.add_organic_order("creator_1", "prod_b", order_value=500.0)
        monkeypatch.setattr(ct_mod, "creator_tracker", tracker)

        portfolio.reset()
        portfolio.update_portfolio("prod_b", {"revenue": 200.0, "spend": 100.0, "roas": 2.0})

        # organic_roas = 500/100 = 5.0; paid pred = 2.0
        pred_off, _ = portfolio._pred_and_width("prod_b", portfolio.portfolio["prod_b"])
        assert pred_off == pytest.approx(2.0, rel=0.01)  # flag off -> unchanged

        monkeypatch.setenv("PHASE8_ORGANIC_CHANNEL_LIVE", "true")
        pred_on, _ = portfolio._pred_and_width("prod_b", portfolio.portfolio["prod_b"])
        expected = 0.8 * 2.0 + 0.2 * 5.0
        assert pred_on == pytest.approx(expected, rel=0.01)


class TestMonteCarloGating:
    """simulation/engine.py: Phase 7 Monte Carlo interval widening of risk_score."""

    def test_intervals_attached_but_risk_unchanged_when_flag_off(self, monkeypatch):
        from simulation.engine import SimulationEngine
        from simulation.ranking import SimulationResult

        engine = SimulationEngine()
        signals = [{"product": "p1", "hook": "h1", "angle": "a1"}]
        results = [SimulationResult(signal=signals[0], product="p1", hook="h1", angle="a1",
                                     predicted_engagement=0.8, risk_score=0.1)]
        engine._apply_monte_carlo_intervals(signals, results, None, None, None)

        # Interval fields populated (cold-start default) but risk_score untouched
        assert results[0].mc_interval_width >= 0.0
        assert results[0].risk_score == pytest.approx(0.1, rel=0.01)

    def test_risk_widened_when_flag_live_and_interval_larger(self, monkeypatch):
        from simulation.engine import SimulationEngine
        from simulation.ranking import SimulationResult

        monkeypatch.setenv("PHASE7_MONTE_CARLO_LIVE", "true")
        engine = SimulationEngine()
        signals = [{"product": "p1", "hook": "h1", "angle": "a1"}]
        # Cold-start (unfitted model) interval width defaults to 0.2, which
        # exceeds the seeded risk_score of 0.1.
        results = [SimulationResult(signal=signals[0], product="p1", hook="h1", angle="a1",
                                     predicted_engagement=0.8, risk_score=0.1)]
        engine._apply_monte_carlo_intervals(signals, results, None, None, None)

        assert results[0].risk_score >= 0.1
        assert results[0].risk_score == pytest.approx(max(0.1, results[0].mc_interval_width), rel=0.01)

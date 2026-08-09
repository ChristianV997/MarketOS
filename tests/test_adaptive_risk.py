"""Tests for backend.risk.config and its Phase 5 wiring into
agents.hierarchy::RiskAgent and core.risk.global_risk_engine::GlobalRiskEngine.

Covers: adaptive formula math (capital/volatility/concentration scaling),
single-sourced constants, backward-compat when the RISK_ADAPTIVE_LIVE flag
is off or adaptive context is absent, flag-on behavior divergence, and
shadow-mode journaling.
"""
from __future__ import annotations

import importlib

import pytest

from backend.risk.config import (
    BASE_MAX_DRAWDOWN, BASE_MAX_DAILY_SPEND, DEFAULT_INITIAL_CAPITAL,
    MIN_MAX_DRAWDOWN, MIN_DAILY_SPEND, BASELINE_VOLATILITY,
    adaptive_max_daily_spend, adaptive_max_drawdown, concentration_fraction,
)


# ─────────────────────────────────────────────────────────────────────────────
# adaptive_max_daily_spend
# ─────────────────────────────────────────────────────────────────────────────


class TestAdaptiveMaxDailySpend:
    def test_matches_base_at_reference_point(self):
        # capital == initial_capital, no volatility signal -> unchanged
        spend = adaptive_max_daily_spend(DEFAULT_INITIAL_CAPITAL, DEFAULT_INITIAL_CAPITAL)
        assert spend == pytest.approx(BASE_MAX_DAILY_SPEND)

    def test_scales_up_with_capital_growth(self):
        spend = adaptive_max_daily_spend(10_000.0, 1_000.0)
        assert spend > BASE_MAX_DAILY_SPEND

    def test_scales_down_with_capital_loss(self):
        spend = adaptive_max_daily_spend(100.0, 1_000.0)
        assert spend < BASE_MAX_DAILY_SPEND

    def test_high_volatility_reduces_cap(self):
        calm = adaptive_max_daily_spend(1000.0, 1000.0, volatility=BASELINE_VOLATILITY)
        volatile = adaptive_max_daily_spend(1000.0, 1000.0, volatility=BASELINE_VOLATILITY * 4)
        assert volatile < calm

    def test_low_volatility_allows_modest_increase(self):
        calm_spend = adaptive_max_daily_spend(1000.0, 1000.0, volatility=BASELINE_VOLATILITY / 10)
        assert calm_spend > BASE_MAX_DAILY_SPEND
        # bounded — never runs away
        assert calm_spend <= BASE_MAX_DAILY_SPEND * 5.0 * 1.5

    def test_never_below_floor(self):
        spend = adaptive_max_daily_spend(1.0, 1_000_000.0, volatility=1000.0)
        assert spend >= MIN_DAILY_SPEND

    def test_extreme_capital_growth_bounded(self):
        spend = adaptive_max_daily_spend(1_000_000_000.0, 1.0)
        # capital_scale alone would be enormous; overall scale is clipped
        assert spend <= BASE_MAX_DAILY_SPEND * 5.0


# ─────────────────────────────────────────────────────────────────────────────
# adaptive_max_drawdown
# ─────────────────────────────────────────────────────────────────────────────


class TestAdaptiveMaxDrawdown:
    def test_matches_base_with_no_concentration_or_volatility(self):
        dd = adaptive_max_drawdown(concentration_frac=0.0, volatility=None)
        assert dd == pytest.approx(BASE_MAX_DRAWDOWN)

    def test_full_concentration_hits_floor(self):
        dd = adaptive_max_drawdown(concentration_frac=1.0)
        assert dd == pytest.approx(MIN_MAX_DRAWDOWN)

    def test_partial_concentration_narrows_tolerance(self):
        dd = adaptive_max_drawdown(concentration_frac=0.5)
        assert dd < BASE_MAX_DRAWDOWN
        assert dd == pytest.approx(BASE_MAX_DRAWDOWN * 0.5)

    def test_higher_concentration_narrows_more(self):
        dd_low = adaptive_max_drawdown(concentration_frac=0.2)
        dd_high = adaptive_max_drawdown(concentration_frac=0.8)
        assert dd_high < dd_low

    def test_elevated_volatility_never_widens_beyond_base(self):
        dd = adaptive_max_drawdown(concentration_frac=0.0, volatility=BASELINE_VOLATILITY / 100)
        # Even under very low ("calm") volatility, drawdown tolerance must
        # never exceed the static base — only concentration=0 achieves the
        # ceiling, volatility can only tighten.
        assert dd <= BASE_MAX_DRAWDOWN

    def test_high_volatility_tightens_further(self):
        calm = adaptive_max_drawdown(concentration_frac=0.0, volatility=BASELINE_VOLATILITY)
        volatile = adaptive_max_drawdown(concentration_frac=0.0, volatility=BASELINE_VOLATILITY * 5)
        assert volatile < calm

    def test_never_below_floor(self):
        dd = adaptive_max_drawdown(concentration_frac=1.0, volatility=1000.0)
        assert dd >= MIN_MAX_DRAWDOWN

    def test_concentration_frac_clipped_to_valid_range(self):
        dd_over = adaptive_max_drawdown(concentration_frac=5.0)
        dd_full = adaptive_max_drawdown(concentration_frac=1.0)
        assert dd_over == pytest.approx(dd_full)


# ─────────────────────────────────────────────────────────────────────────────
# concentration_fraction
# ─────────────────────────────────────────────────────────────────────────────


class TestConcentrationFraction:
    def test_empty_returns_zero(self):
        assert concentration_fraction({}) == 0.0

    def test_single_group_is_full_concentration(self):
        assert concentration_fraction({"tiktok": 100.0}) == pytest.approx(1.0)

    def test_even_split_returns_correct_fraction(self):
        frac = concentration_fraction({"tiktok": 50.0, "meta": 50.0})
        assert frac == pytest.approx(0.5)

    def test_skewed_split_returns_max_share(self):
        frac = concentration_fraction({"tiktok": 80.0, "meta": 20.0})
        assert frac == pytest.approx(0.8)

    def test_zero_total_returns_zero(self):
        assert concentration_fraction({"tiktok": 0.0, "meta": 0.0}) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# RiskAgent (agents/hierarchy.py) — backward compat + adaptive wiring
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_event_store(tmp_path, monkeypatch):
    from backend.orchestration.event_store import EventStore
    store = EventStore(path=str(tmp_path / "shadow.jsonl"))
    es_mod = importlib.import_module("backend.orchestration.event_store")
    monkeypatch.setattr(es_mod, "event_store", store)
    monkeypatch.setattr("agents.hierarchy.event_store", store, raising=False)
    yield store


class TestRiskAgentBackwardCompat:
    def test_default_constructor_uses_base_constants(self):
        from agents.hierarchy import RiskAgent
        agent = RiskAgent()
        assert agent.max_drawdown == pytest.approx(BASE_MAX_DRAWDOWN)
        assert agent.max_daily_spend == pytest.approx(BASE_MAX_DAILY_SPEND)

    def test_flag_off_static_threshold_used(self, monkeypatch):
        monkeypatch.delenv("RISK_ADAPTIVE_LIVE", raising=False)
        from agents.hierarchy import RiskAgent
        agent = RiskAgent(max_drawdown=0.30)

        # 40% drawdown, but concentration_frac=1.0 (would floor adaptive to 0.05)
        decision = agent.decide({
            "current_capital": 600.0, "peak_capital": 1000.0,
            "concentration_frac": 1.0,
        })
        # With flag off, static 0.30 threshold applies regardless of
        # concentration_frac — 40% drawdown > 30% -> kill either way here,
        # so use a drawdown that would NOT trigger under static but WOULD
        # under adaptive to distinguish the two.
        assert decision.action == "kill"  # 40% > both static and adaptive here

    def test_flag_off_moderate_drawdown_survives_despite_concentration(self, monkeypatch):
        monkeypatch.delenv("RISK_ADAPTIVE_LIVE", raising=False)
        from agents.hierarchy import RiskAgent
        agent = RiskAgent(max_drawdown=0.30)

        # 20% drawdown: below static 0.30, but adaptive (with full
        # concentration) would floor to 0.05 and trigger kill. Flag off ->
        # static threshold used -> should NOT kill on drawdown.
        decision = agent.decide({
            "current_capital": 800.0, "peak_capital": 1000.0,
            "concentration_frac": 1.0, "roas": 1.0,
        })
        assert decision.action != "kill" or "drawdown" not in decision.reason

    def test_flag_on_concentration_triggers_earlier_kill(self, monkeypatch):
        monkeypatch.setenv("RISK_ADAPTIVE_LIVE", "true")
        from agents.hierarchy import RiskAgent
        agent = RiskAgent(max_drawdown=0.30)

        # Same 20% drawdown as above, but flag on + full concentration ->
        # adaptive threshold floors to 0.05 -> 20% > 5% -> kill.
        decision = agent.decide({
            "current_capital": 800.0, "peak_capital": 1000.0,
            "concentration_frac": 1.0, "roas": 1.0,
        })
        assert decision.action == "kill"
        assert "drawdown" in decision.reason

    def test_flag_on_no_concentration_context_behaves_like_static(self, monkeypatch):
        monkeypatch.setenv("RISK_ADAPTIVE_LIVE", "true")
        from agents.hierarchy import RiskAgent
        agent = RiskAgent(max_drawdown=0.30)

        # No concentration_frac supplied -> defaults to 0.0 -> adaptive
        # drawdown == base (0.30) -> same as static.
        decision = agent.decide({
            "current_capital": 800.0, "peak_capital": 1000.0, "roas": 1.0,
        })
        assert decision.action != "kill" or "drawdown" not in decision.reason

    def test_shadow_journal_persists(self, _isolate_event_store):
        from agents.hierarchy import RiskAgent
        agent = RiskAgent()
        agent.decide({"current_capital": 1000.0, "peak_capital": 1000.0, "roas": 1.0})

        events = _isolate_event_store.tail(10)
        shadow = [e for e in events if e.get("event") == "shadow_adaptive_risk"]
        assert len(shadow) > 0
        assert "adaptive_max_drawdown" in shadow[0]["data"]
        assert "adaptive_max_daily_spend" in shadow[0]["data"]


# ─────────────────────────────────────────────────────────────────────────────
# GlobalRiskEngine (core/risk/global_risk_engine.py) — backward compat + adaptive
# ─────────────────────────────────────────────────────────────────────────────


class TestGlobalRiskEngineBackwardCompat:
    def test_default_constructor_uses_base_constants(self):
        from core.risk.global_risk_engine import GlobalRiskEngine
        eng = GlobalRiskEngine()
        assert eng.max_drawdown == pytest.approx(BASE_MAX_DRAWDOWN)
        assert eng.max_daily_spend == pytest.approx(BASE_MAX_DAILY_SPEND)

    def test_enforce_without_adaptive_context_unchanged(self, monkeypatch):
        monkeypatch.setenv("RISK_ADAPTIVE_LIVE", "true")  # flag on...
        from core.risk.global_risk_engine import GlobalRiskEngine
        eng = GlobalRiskEngine(max_daily_spend=1000.0, max_drawdown=0.30)

        # ...but no initial_capital passed -> legacy static behavior
        r = eng.enforce(100.0, current_capital=1000.0, peak_capital=1000.0)
        assert r.allowed is True
        assert r.adjusted_budget == 100.0

    def test_enforce_flag_off_ignores_adaptive_context(self, monkeypatch):
        monkeypatch.delenv("RISK_ADAPTIVE_LIVE", raising=False)
        from core.risk.global_risk_engine import GlobalRiskEngine
        eng = GlobalRiskEngine(max_daily_spend=1000.0, max_drawdown=0.30)

        # 20% drawdown with full concentration passed, but flag off
        r = eng.enforce(
            100.0, current_capital=800.0, peak_capital=1000.0,
            initial_capital=1000.0, concentration_frac=1.0,
        )
        assert r.allowed is True  # static 0.30 threshold not breached by 20%

    def test_enforce_flag_on_with_concentration_triggers_drawdown_kill(self, monkeypatch):
        monkeypatch.setenv("RISK_ADAPTIVE_LIVE", "true")
        from core.risk.global_risk_engine import GlobalRiskEngine
        eng = GlobalRiskEngine(max_daily_spend=1000.0, max_drawdown=0.30)

        r = eng.enforce(
            100.0, current_capital=800.0, peak_capital=1000.0,
            initial_capital=1000.0, concentration_frac=1.0,
        )
        assert r.allowed is False
        assert r.triggered_cap == "drawdown"

    def test_enforce_flag_on_capital_growth_raises_spend_cap(self, monkeypatch):
        monkeypatch.setenv("RISK_ADAPTIVE_LIVE", "true")
        from core.risk.global_risk_engine import GlobalRiskEngine
        eng = GlobalRiskEngine(max_daily_spend=1000.0, max_drawdown=0.30)

        # Capital grew 10x -> adaptive spend cap should allow more than
        # the static 1000 cap (bounded at 5x -> up to 5000).
        r = eng.enforce(
            4000.0, current_capital=10_000.0, peak_capital=10_000.0,
            initial_capital=1_000.0,
        )
        assert r.allowed is True
        assert r.adjusted_budget == pytest.approx(4000.0)

    def test_legacy_test_suite_still_passes(self):
        """Spot-check the exact assertions from test_step52_production_hardening.py
        continue to hold post-Phase-5 without any adaptive context supplied."""
        from core.risk.global_risk_engine import GlobalRiskEngine
        eng = GlobalRiskEngine(max_daily_spend=500.0, max_drawdown=0.30)
        eng.record_spend(400.0)
        r = eng.enforce(200.0, 1000.0, 1000.0)
        assert r.allowed is True
        assert r.adjusted_budget == 100.0

    def test_shadow_journal_persists(self, _isolate_event_store, monkeypatch):
        from core.risk.global_risk_engine import GlobalRiskEngine
        monkeypatch.setattr("core.risk.global_risk_engine.event_store", _isolate_event_store, raising=False)
        eng = GlobalRiskEngine()
        eng.enforce(100.0, current_capital=1000.0, peak_capital=1000.0)

        events = _isolate_event_store.tail(10)
        shadow = [e for e in events if e.get("event") == "shadow_adaptive_risk"]
        assert len(shadow) > 0
        assert "static_max_drawdown" in shadow[0]["data"]

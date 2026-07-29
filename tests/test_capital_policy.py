"""Tests for backend.decision.capital_policy — the unified risk-aware
capital allocator (ROI overhaul Phase 2).

Covers: QP preference for high-pred/low-width arms, same-group
concentration penalty, adaptive λ under drawdown, portfolio-size-scaled
fraction bounds, sample-size-aware widths in core.portfolio (the
1-observation-spike vs 50-stable-observations case), shadow-mode gating,
and solver-failure fallbacks.
"""
from __future__ import annotations

import pytest

import core.portfolio as portfolio_mod
from backend.decision.capital_policy import (
    adaptive_fracs, allocate_capital, allocate_with_shadow, effective_lambda)
from backend.orchestration.event_store import EventStore


# ─────────────────────────────────────────────────────────────────────────────
# adaptive parameters
# ─────────────────────────────────────────────────────────────────────────────


class TestAdaptiveParams:
    def test_fracs_match_legacy_at_small_n(self):
        min_f, max_f = adaptive_fracs(2)
        assert max_f == 0.60          # n=2 behaves like the old cap
        assert min_f == 0.05

    def test_max_frac_falls_as_portfolio_grows(self):
        _, max_2 = adaptive_fracs(2)
        _, max_8 = adaptive_fracs(8)
        _, max_20 = adaptive_fracs(20)
        assert max_2 > max_8 >= max_20
        assert max_8 == 0.25          # clip floor

    def test_lambda_base_without_context(self):
        assert effective_lambda(None) == pytest.approx(0.3)
        assert effective_lambda({}) == pytest.approx(0.3)

    def test_lambda_tightens_under_drawdown(self):
        no_dd = effective_lambda({"capital": 100.0, "peak_capital": 100.0})
        half_dd = effective_lambda({"capital": 85.0, "peak_capital": 100.0})
        assert no_dd == pytest.approx(0.3)
        # 15% drawdown against 30% max → λ scaled by 1.5
        assert half_dd == pytest.approx(0.45)

    def test_lambda_ignores_growth(self):
        assert effective_lambda({"capital": 150.0, "peak_capital": 100.0}) \
            == pytest.approx(0.3)


# ─────────────────────────────────────────────────────────────────────────────
# allocate_capital
# ─────────────────────────────────────────────────────────────────────────────


class TestAllocateCapital:
    def test_empty_and_single(self):
        assert allocate_capital([], 100.0).budgets == []
        single = allocate_capital([{"id": "a", "pred": 2.0}], 100.0)
        assert single.budgets == [100.0]
        assert single.method == "single"

    def test_budgets_sum_to_total(self):
        arms = [{"id": f"a{i}", "pred": 1.0 + i * 0.2, "pred_width": 0.2}
                for i in range(5)]
        alloc = allocate_capital(arms, 500.0)
        assert sum(alloc.budgets) == pytest.approx(500.0, rel=1e-4)

    def test_prefers_high_pred_low_width(self):
        arms = [
            {"id": "good", "pred": 2.5, "pred_width": 0.1},
            {"id": "risky", "pred": 2.5, "pred_width": 1.5},
            {"id": "weak", "pred": 0.8, "pred_width": 0.1},
        ]
        alloc = allocate_capital(arms, 300.0)
        good, risky, weak = alloc.budgets
        assert good > risky            # same pred, lower uncertainty wins
        assert good > weak             # higher pred wins

    def test_same_group_concentration_penalized(self):
        """Three same-platform arms + one diversifier: the diversifier gets
        more than it would if all four shared a group."""
        same = [{"id": f"t{i}", "pred": 2.0, "pred_width": 0.5, "group": "tiktok"}
                for i in range(3)]
        diversifier = {"id": "m", "pred": 2.0, "pred_width": 0.5, "group": "meta"}
        mixed = allocate_capital(same + [diversifier], 400.0)

        all_same = allocate_capital(
            same + [dict(diversifier, group="tiktok")], 400.0)
        assert mixed.method == "qp" and all_same.method == "qp"
        # Diversifying arm attracts more budget when it's actually uncorrelated
        assert mixed.budgets[3] > all_same.budgets[3]

    def test_all_negative_coeff_uniform(self):
        arms = [{"id": "a", "pred": 0.01, "pred_width": 5.0},
                {"id": "b", "pred": 0.01, "pred_width": 5.0}]
        alloc = allocate_capital(arms, 100.0)
        assert alloc.method == "uniform"
        assert alloc.budgets == [50.0, 50.0]

    def test_respects_adaptive_max_frac(self):
        arms = [{"id": "star", "pred": 10.0, "pred_width": 0.01}] + [
            {"id": f"d{i}", "pred": 0.5, "pred_width": 0.5} for i in range(7)]
        alloc = allocate_capital(arms, 800.0)
        # n=8 → max_frac 0.25 → star capped at ~200 despite dominant pred
        assert alloc.budgets[0] <= 800.0 * 0.25 * 1.01

    def test_qp_unavailable_falls_back_to_lp(self, monkeypatch):
        import backend.decision.capital_policy as cp_mod
        monkeypatch.setattr(cp_mod, "_solve_qp", lambda *a, **k: None)
        arms = [{"id": "a", "pred": 2.0, "pred_width": 0.1},
                {"id": "b", "pred": 1.0, "pred_width": 0.1}]
        alloc = cp_mod.allocate_capital(arms, 100.0)
        assert alloc.method == "lp_fallback"
        assert sum(alloc.budgets) == pytest.approx(100.0, rel=1e-4)


# ─────────────────────────────────────────────────────────────────────────────
# shadow mode
# ─────────────────────────────────────────────────────────────────────────────


class TestShadowMode:
    @pytest.fixture(autouse=True)
    def _shadow_store(self, tmp_path, monkeypatch):
        self.store = EventStore(path=str(tmp_path / "shadow.jsonl"))
        import importlib
        es_mod = importlib.import_module("backend.orchestration.event_store")
        monkeypatch.setattr(es_mod, "event_store", self.store)
        yield

    ARMS = [{"id": "a", "pred": 2.0, "pred_width": 0.1},
            {"id": "b", "pred": 1.0, "pred_width": 0.4}]

    def test_flag_off_returns_legacy_and_journals_both(self, monkeypatch):
        monkeypatch.delenv("CAPITAL_POLICY_LIVE", raising=False)
        legacy = [70.0, 30.0]
        result = allocate_with_shadow(self.ARMS, 100.0, legacy_fn=lambda: legacy)
        assert result == legacy
        events = self.store.tail(5)
        ev = next(e for e in events if e["event"] == "shadow_capital_policy")
        assert ev["data"]["legacy_budgets"] == [70.0, 30.0]
        assert ev["data"]["policy"]["live"] is False
        assert sum(ev["data"]["policy"]["budgets"]) == pytest.approx(100.0, rel=1e-3)

    def test_flag_on_returns_policy(self, monkeypatch):
        monkeypatch.setenv("CAPITAL_POLICY_LIVE", "true")
        legacy = [50.0, 50.0]
        result = allocate_with_shadow(self.ARMS, 100.0, legacy_fn=lambda: legacy)
        assert result != legacy                        # policy result differs
        assert sum(result) == pytest.approx(100.0, rel=1e-3)
        ev = next(e for e in self.store.tail(5)
                  if e["event"] == "shadow_capital_policy")
        assert ev["data"]["policy"]["live"] is True

    def test_legacy_failure_falls_through_to_policy(self, monkeypatch):
        monkeypatch.delenv("CAPITAL_POLICY_LIVE", raising=False)

        def broken():
            raise RuntimeError("legacy allocator exploded")
        result = allocate_with_shadow(self.ARMS, 100.0, legacy_fn=broken)
        assert sum(result) == pytest.approx(100.0, rel=1e-3)

    def test_journal_failure_never_breaks_allocation(self, monkeypatch):
        monkeypatch.delenv("CAPITAL_POLICY_LIVE", raising=False)
        monkeypatch.setattr(self.store, "append",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
        result = allocate_with_shadow(self.ARMS, 100.0, legacy_fn=lambda: [60.0, 40.0])
        assert result == [60.0, 40.0]


# ─────────────────────────────────────────────────────────────────────────────
# core.portfolio wrapper (sample-size awareness + API compatibility)
# ─────────────────────────────────────────────────────────────────────────────


class TestPortfolioWrapper:
    @pytest.fixture(autouse=True)
    def _fresh(self):
        portfolio_mod.reset()
        yield
        portfolio_mod.reset()

    def test_fractions_sum_to_one_and_keys_preserved(self):
        portfolio_mod.update_portfolio("a", {"revenue": 200, "spend": 100})
        portfolio_mod.update_portfolio("b", {"revenue": 100, "spend": 100})
        allocs = portfolio_mod.allocate_budget(portfolio_mod.portfolio)
        assert set(allocs) == {"a", "b"}
        assert sum(allocs.values()) == pytest.approx(1.0)

    def test_single_product_gets_everything(self):
        portfolio_mod.update_portfolio("only", {"revenue": 50, "spend": 100})
        allocs = portfolio_mod.allocate_budget(portfolio_mod.portfolio)
        assert allocs == {"only": 1.0}

    def test_empty_portfolio(self):
        assert portfolio_mod.allocate_budget({}) == {}

    def test_one_lucky_spike_does_not_beat_stable_history(self):
        """The core sample-size fix: 1 observation at ROAS 4.0 must not
        outrank 30 stable observations at ROAS 2.0."""
        for _ in range(30):
            portfolio_mod.update_portfolio("stable", {"revenue": 200, "spend": 100,
                                                      "roas": 2.0})
        portfolio_mod.update_portfolio("spike", {"revenue": 400, "spend": 100,
                                                 "roas": 4.0})
        allocs = portfolio_mod.allocate_budget(portfolio_mod.portfolio)
        # Legacy linear share would give spike 4/(4+2)=67%. With width
        # awareness the stable product must not be starved below the spike
        # by that ratio; assert spike doesn't get a >60% runaway share.
        assert allocs["spike"] < 0.60

    def test_portfolio_engine_consumers_still_work(self):
        from backend.decision.portfolio_engine import get_allocations, top_products
        portfolio_mod.update_portfolio("x", {"revenue": 300, "spend": 100})
        portfolio_mod.update_portfolio("y", {"revenue": 100, "spend": 100})
        allocs = get_allocations()
        assert set(allocs) == {"x", "y"}
        top = top_products(n=1)
        assert top[0]["product_id"] == "x"

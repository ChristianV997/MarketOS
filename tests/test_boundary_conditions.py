"""Boundary-value and error-path tests for the metrics/scaling/supplier stack.

Complements the happy-path coverage in test_budget_scaling.py,
test_metrics_profitability.py, and test_dropship_validation.py with the
edge cases those files don't exercise: exact rule boundaries, zero/negative
inputs, and all-suppliers-failing scenarios.
"""
import uuid

import pytest

import backend.metrics.campaign_metrics as cm
import backend.optimization.budget_scaling as bs
import backend.validation.suppliers as suppliers


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(cm, "_METRICS_PATH", tmp_path / "metrics.jsonl")
    monkeypatch.setattr(bs, "_DECISIONS_PATH", tmp_path / "decisions.jsonl")
    monkeypatch.setattr(bs, "_current_budgets", lambda: getattr(bs, "_test_budgets", {}))
    return tmp_path


def _seed(cid, spend, revenue):
    cm.record_metric(cid, "tiktok", f"P {cid}", spend_usd=spend, revenue_usd=revenue)


def _decision_for(decisions, cid):
    return next(d for d in decisions if d["campaign_id"] == cid)


class TestBudgetScalingExactBoundaries:
    """The rule bands are: >2.0 scale_up, [1.0, 2.0] maintain, [0.5, 1.0)
    scale_down, <0.5 kill. Exact boundary values must land on the
    documented side of each `>` vs `>=` comparison."""

    def test_roas_exactly_2_0_is_maintain_not_scale_up(self, isolated, monkeypatch):
        cid = f"c_{uuid.uuid4().hex[:8]}"
        _seed(cid, spend=50.0, revenue=100.0)  # ROAS exactly 2.0
        monkeypatch.setattr(bs, "_test_budgets", {cid: 40.0}, raising=False)
        d = _decision_for(bs.compute_scaling_decisions(), cid)
        assert d["action"] == "maintain"  # rule is roas > 2.0, not >=
        assert d["new_budget"] == 40.0

    def test_roas_just_above_2_0_is_scale_up(self, isolated, monkeypatch):
        cid = f"c_{uuid.uuid4().hex[:8]}"
        _seed(cid, spend=50.0, revenue=100.5)  # ROAS 2.01
        monkeypatch.setattr(bs, "_test_budgets", {cid: 40.0}, raising=False)
        d = _decision_for(bs.compute_scaling_decisions(), cid)
        assert d["action"] == "scale_up"

    def test_roas_exactly_1_0_is_maintain(self, isolated, monkeypatch):
        cid = f"c_{uuid.uuid4().hex[:8]}"
        _seed(cid, spend=50.0, revenue=50.0)  # ROAS exactly 1.0 (breakeven)
        monkeypatch.setattr(bs, "_test_budgets", {cid: 40.0}, raising=False)
        d = _decision_for(bs.compute_scaling_decisions(), cid)
        assert d["action"] == "maintain"

    def test_roas_exactly_0_5_is_scale_down_not_kill(self, isolated, monkeypatch):
        cid = f"c_{uuid.uuid4().hex[:8]}"
        _seed(cid, spend=100.0, revenue=50.0)  # ROAS exactly 0.5
        monkeypatch.setattr(bs, "_test_budgets", {cid: 40.0}, raising=False)
        d = _decision_for(bs.compute_scaling_decisions(), cid)
        assert d["action"] == "scale_down"  # rule is roas >= 0.5, not just > 0.5
        assert d["new_budget"] == 20.0

    def test_roas_just_below_0_5_is_kill(self, isolated, monkeypatch):
        cid = f"c_{uuid.uuid4().hex[:8]}"
        _seed(cid, spend=100.0, revenue=49.0)  # ROAS 0.49
        monkeypatch.setattr(bs, "_test_budgets", {cid: 40.0}, raising=False)
        d = _decision_for(bs.compute_scaling_decisions(), cid)
        assert d["action"] == "kill"

    def test_spend_exactly_at_min_threshold_makes_a_decision(self, isolated, monkeypatch):
        """Spend >= the $20 threshold should qualify, not just spend > $20."""
        cid = f"c_{uuid.uuid4().hex[:8]}"
        _seed(cid, spend=20.0, revenue=10.0)  # exactly at threshold
        monkeypatch.setattr(bs, "_test_budgets", {cid: 40.0}, raising=False)
        decisions = bs.compute_scaling_decisions()
        assert any(d["campaign_id"] == cid for d in decisions)


class TestZeroAndNegativeInputs:
    def test_zero_spend_gives_zero_roas_no_division_error(self, isolated):
        cid = f"c_{uuid.uuid4().hex[:8]}"
        ok = cm.record_metric(cid, "tiktok", "Free Sample", spend_usd=0.0, revenue_usd=50.0)
        assert ok is True
        row = cm.campaign_by_id(cid)
        assert row["roas"] == 0.0  # guarded, not a ZeroDivisionError

    def test_zero_spend_campaign_excluded_from_scaling_decisions(self, isolated, monkeypatch):
        cid = f"c_{uuid.uuid4().hex[:8]}"
        _seed(cid, spend=0.0, revenue=0.0)
        monkeypatch.setattr(bs, "_test_budgets", {cid: 40.0}, raising=False)
        decisions = bs.compute_scaling_decisions()
        assert not any(d["campaign_id"] == cid for d in decisions)

    def test_negative_revenue_chargeback_does_not_crash(self, isolated):
        """A chargeback/refund can make revenue negative; ROAS goes negative
        too but must not raise."""
        cid = f"c_{uuid.uuid4().hex[:8]}"
        ok = cm.record_metric(cid, "meta", "Refunded Widget", spend_usd=50.0, revenue_usd=-20.0)
        assert ok is True
        row = cm.campaign_by_id(cid)
        assert row["roas"] < 0

    def test_negative_revenue_triggers_kill_decision(self, isolated, monkeypatch):
        cid = f"c_{uuid.uuid4().hex[:8]}"
        _seed(cid, spend=50.0, revenue=-20.0)
        monkeypatch.setattr(bs, "_test_budgets", {cid: 40.0}, raising=False)
        d = _decision_for(bs.compute_scaling_decisions(), cid)
        assert d["action"] == "kill"
        assert d["new_budget"] == 0.0

    def test_empty_campaign_id_rejected(self, isolated):
        assert cm.record_metric("", "tiktok", "X", spend_usd=10.0) is False

    def test_campaign_performance_empty_log_returns_empty_list(self, isolated):
        assert cm.campaign_performance() == []

    def test_unknown_campaign_by_id_returns_none(self, isolated):
        assert cm.campaign_by_id("never_seen_campaign") is None


class TestSupplierAllFailuresGracefulFallback:
    """When every live supplier raises, quote_all must still return mock
    quotes rather than propagating the failure — validation should never
    hard-fail just because every supplier API happened to be down."""

    def test_all_suppliers_raising_falls_back_to_mock_quotes(self, monkeypatch):
        for client in suppliers._CLIENTS:
            monkeypatch.setattr(client, "is_configured", lambda: True)
            monkeypatch.setattr(
                client, "_live_quote",
                lambda product_name: (_ for _ in ()).throw(ConnectionError("timeout")),
            )
        monkeypatch.setattr(suppliers, "_DRY_RUN", False)

        quotes = suppliers.quote_all("Boundary Test Widget")
        assert len(quotes) == len(suppliers._CLIENTS)  # every client fell back to mock
        assert all(q.cost > 0 for q in quotes)

    def test_find_best_supplier_with_all_live_failures_still_returns_a_quote(self, monkeypatch):
        for client in suppliers._CLIENTS:
            monkeypatch.setattr(client, "is_configured", lambda: True)
            monkeypatch.setattr(
                client, "_live_quote",
                lambda product_name: (_ for _ in ()).throw(TimeoutError("slow")),
            )
        monkeypatch.setattr(suppliers, "_DRY_RUN", False)

        best = suppliers.find_best_supplier("Boundary Test Widget 2")
        assert best is not None  # mock fallback still produces a usable quote

    def test_quote_all_with_empty_product_name(self):
        """Deterministic mock quoting must handle an empty seed without
        raising (hashlib.md5 on an empty string is well-defined)."""
        quotes = suppliers.quote_all("")
        assert len(quotes) == len(suppliers._CLIENTS)

"""Tests for backend.optimization.budget_scaling — rules, rails, summary."""
import uuid

import pytest

import backend.metrics.campaign_metrics as cm
import backend.optimization.budget_scaling as bs
from backend.core.persistence import save_json_atomic


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Private metric log, decision log, and launch snapshot."""
    monkeypatch.setattr(cm, "_METRICS_PATH", tmp_path / "metrics.jsonl")
    monkeypatch.setattr(bs, "_DECISIONS_PATH", tmp_path / "decisions.jsonl")
    snapshot = tmp_path / "dropship.json"
    monkeypatch.setattr(bs, "_current_budgets",
                        lambda: getattr(bs, "_test_budgets", {}))
    return tmp_path


def _seed(cid, spend, revenue):
    cm.record_metric(cid, "tiktok", f"P {cid}", spend_usd=spend, revenue_usd=revenue)


def _decision_for(decisions, cid):
    return next(d for d in decisions if d["campaign_id"] == cid)


def test_scale_up_on_high_roas(isolated, monkeypatch):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    _seed(cid, spend=50.0, revenue=150.0)          # ROAS 3.0
    monkeypatch.setattr(bs, "_test_budgets", {cid: 40.0}, raising=False)
    d = _decision_for(bs.compute_scaling_decisions(), cid)
    assert d["action"] == "scale_up"
    assert d["new_budget"] == 48.0                  # 40 × 1.2


def test_maintain_at_breakeven(isolated, monkeypatch):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    _seed(cid, spend=50.0, revenue=75.0)            # ROAS 1.5
    monkeypatch.setattr(bs, "_test_budgets", {cid: 40.0}, raising=False)
    d = _decision_for(bs.compute_scaling_decisions(), cid)
    assert d["action"] == "maintain"
    assert d["new_budget"] == 40.0


def test_scale_down_below_breakeven(isolated, monkeypatch):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    _seed(cid, spend=50.0, revenue=40.0)            # ROAS 0.8
    monkeypatch.setattr(bs, "_test_budgets", {cid: 40.0}, raising=False)
    d = _decision_for(bs.compute_scaling_decisions(), cid)
    assert d["action"] == "scale_down"
    assert d["new_budget"] == 20.0                  # 40 × 0.5


def test_kill_on_critical_roas(isolated, monkeypatch):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    _seed(cid, spend=50.0, revenue=10.0)            # ROAS 0.2
    monkeypatch.setattr(bs, "_test_budgets", {cid: 40.0}, raising=False)
    d = _decision_for(bs.compute_scaling_decisions(), cid)
    assert d["action"] == "kill"
    assert d["new_budget"] == 0.0


def test_low_spend_makes_no_decision(isolated, monkeypatch):
    """Below the spend threshold there is not enough signal to act."""
    cid = f"c_{uuid.uuid4().hex[:8]}"
    _seed(cid, spend=5.0, revenue=0.0)              # terrible ROAS, tiny spend
    monkeypatch.setattr(bs, "_test_budgets", {cid: 40.0}, raising=False)
    assert not any(d["campaign_id"] == cid for d in bs.compute_scaling_decisions())


def test_budget_cap_rail(isolated, monkeypatch):
    """New budget never exceeds the $500/day rail."""
    cid = f"c_{uuid.uuid4().hex[:8]}"
    _seed(cid, spend=600.0, revenue=3000.0)         # ROAS 5.0
    monkeypatch.setattr(bs, "_test_budgets", {cid: 490.0}, raising=False)
    d = _decision_for(bs.compute_scaling_decisions(), cid)
    assert d["new_budget"] == 500.0


def test_apply_and_summary_roundtrip(isolated, monkeypatch):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    _seed(cid, spend=50.0, revenue=150.0)
    monkeypatch.setattr(bs, "_test_budgets", {cid: 40.0}, raising=False)
    decisions = bs.compute_scaling_decisions()
    mine = [d for d in decisions if d["campaign_id"] == cid]

    result = bs.apply_scaling_decisions(mine)
    assert result["status"] == "ok"
    assert result["applied"] == 1
    assert result["budget_change"] == 8.0           # 48 − 40

    summary = bs.scaling_summary(lookback_days=1)
    assert summary["total_decisions"] == 1
    assert summary["by_action"]["scale_up"]["count"] == 1
    assert summary["total_budget_change"] == 8.0


def test_apply_empty_is_noop(isolated):
    result = bs.apply_scaling_decisions([])
    assert result == {"status": "ok", "applied": 0, "total_old_budget": 0.0,
                      "total_new_budget": 0.0, "budget_change": 0.0}


def test_low_supplier_reliability_forces_kill_despite_high_roas(isolated, monkeypatch):
    """A supplier whose reliability craters must nudge the decision to
    kill regardless of ROAS — fulfillment failures cause refunds, the
    single most expensive failure mode, so this can't be ROAS-blind."""
    from backend.validation.suppliers import SupplierQuote
    from backend.economics.supplier_feedback import supplier_feedback

    cid = f"c_{uuid.uuid4().hex[:8]}"
    _seed(cid, spend=50.0, revenue=200.0)  # ROAS 4.0 — would normally scale_up
    monkeypatch.setattr(bs, "_test_budgets", {cid: 40.0}, raising=False)

    unreliable_quote = SupplierQuote(
        supplier="flaky_supplier", product_id="p1", product_name=f"P {cid}",
        cost=5.0, shipping=2.0, fulfillment_days=10, reliability=0.9,
    )
    monkeypatch.setattr("backend.validation.suppliers.find_best_supplier",
                        lambda *a, **kw: unreliable_quote)
    supplier_feedback.reset()
    supplier_feedback._reliability[("flaky_supplier", "general")] = 0.2
    try:
        d = _decision_for(bs.compute_scaling_decisions(), cid)
        assert d["action"] == "kill"
        assert d["new_budget"] == 0.0
        assert "supplier reliability" in d["reason"]
    finally:
        supplier_feedback.reset()


def test_reliability_lookup_failure_does_not_block_decision(isolated, monkeypatch):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    _seed(cid, spend=50.0, revenue=150.0)  # ROAS 3.0
    monkeypatch.setattr(bs, "_test_budgets", {cid: 40.0}, raising=False)

    def boom(*a, **kw):
        raise RuntimeError("quote service down")
    monkeypatch.setattr("backend.validation.suppliers.find_best_supplier", boom)

    d = _decision_for(bs.compute_scaling_decisions(), cid)
    assert d["action"] == "scale_up"  # unaffected — lookup failure is not a signal


class TestApplyScalingDecisionsLiveActuation:
    def test_shadow_mode_never_actuates(self, isolated, monkeypatch):
        monkeypatch.delenv("BUDGET_APPLY_LIVE", raising=False)
        calls = []
        monkeypatch.setattr("backend.integrations.tiktok_ads.pause_campaign",
                            lambda cid: calls.append(cid) or True)
        cid = f"c_{uuid.uuid4().hex[:8]}"
        _seed(cid, spend=50.0, revenue=5.0)  # ROAS 0.1 -> kill
        monkeypatch.setattr(bs, "_test_budgets", {cid: 40.0}, raising=False)
        decisions = [d for d in bs.compute_scaling_decisions() if d["campaign_id"] == cid]

        result = bs.apply_scaling_decisions(decisions)
        assert result["live"] is False
        assert calls == []  # shadow mode never touches the real platform

    def test_live_mode_actuates_through_budget_actuator(self, isolated, monkeypatch):
        monkeypatch.setenv("BUDGET_APPLY_LIVE", "true")
        calls = []
        monkeypatch.setattr("backend.integrations.tiktok_ads.pause_campaign",
                            lambda cid: calls.append(cid) or True)
        cid = f"c_{uuid.uuid4().hex[:8]}"
        _seed(cid, spend=50.0, revenue=5.0)  # ROAS 0.1 -> kill
        monkeypatch.setattr(bs, "_test_budgets", {cid: 40.0}, raising=False)
        decisions = [d for d in bs.compute_scaling_decisions() if d["campaign_id"] == cid]

        try:
            result = bs.apply_scaling_decisions(decisions)
            assert result["live"] is True
            assert result["actuated"] == 1
            assert calls == [cid]
        finally:
            monkeypatch.delenv("BUDGET_APPLY_LIVE", raising=False)

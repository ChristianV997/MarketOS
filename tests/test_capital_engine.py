import pytest
from core.capital import CapitalEngine, SCALE_ROAS_THRESHOLD, KILL_ROAS_THRESHOLD
from core.pods import Pod


def _pod_with_roas(roas: float) -> Pod:
    pod = Pod("widget", "US", "meta", budget=100.0)
    pod.metrics = {"roas": roas, "spend": 100.0, "revenue": roas * 100.0}
    return pod


def test_evaluate_scale():
    engine = CapitalEngine()
    pod = _pod_with_roas(SCALE_ROAS_THRESHOLD + 0.1)
    assert engine.evaluate(pod) == "scale"


def test_evaluate_kill():
    engine = CapitalEngine()
    pod = _pod_with_roas(KILL_ROAS_THRESHOLD - 0.1)
    assert engine.evaluate(pod) == "kill"


def test_evaluate_hold():
    engine = CapitalEngine()
    pod = _pod_with_roas(2.0)
    assert engine.evaluate(pod) == "hold"


def test_apply_scale_increases_budget():
    engine = CapitalEngine()
    pod = _pod_with_roas(SCALE_ROAS_THRESHOLD + 1.0)
    old_budget = pod.budget
    decision = engine.apply(pod)
    assert decision == "scale"
    assert pod.budget > old_budget
    assert pod.status == "scaling"


def test_apply_kill_sets_status():
    engine = CapitalEngine()
    pod = _pod_with_roas(KILL_ROAS_THRESHOLD - 1.0)
    decision = engine.apply(pod)
    assert decision == "kill"
    assert pod.status == "killed"


def test_apply_hold_no_change():
    engine = CapitalEngine()
    pod = _pod_with_roas(2.0)
    original_budget = pod.budget
    decision = engine.apply(pod)
    assert decision == "hold"
    assert pod.budget == original_budget
    assert pod.status == "testing"


def test_apply_scale_caps_at_max_budget():
    engine = CapitalEngine(max_budget=150.0, scale_factor=10.0)
    pod = _pod_with_roas(SCALE_ROAS_THRESHOLD + 1.0)
    engine.apply(pod)
    assert pod.budget <= 150.0


def test_allocate_budget_equal_metrics_equal_shares():
    engine = CapitalEngine()
    pods = [Pod("a", "US", "meta", budget=50.0), Pod("b", "EU", "tiktok", budget=50.0)]
    allocation = engine.allocate_budget(pods, 1000.0)
    assert len(allocation) == 2
    values = list(allocation.values())
    # equal metrics → equal shares, each within the 5–35% clamp band
    assert abs(values[0] - values[1]) < 1e-6
    for v in values:
        assert 50.0 <= v <= 350.0


def test_allocate_budget_winner_gets_more():
    # 3 pods so the 35% cap leaves room for ranking to show through
    engine = CapitalEngine()
    winner = Pod("a", "US", "meta", budget=50.0)
    mid    = Pod("b", "EU", "tiktok", budget=50.0)
    loser  = Pod("c", "UK", "meta", budget=50.0)
    winner.metrics.update({"roas": 3.0, "revenue": 300.0, "spend": 100.0})
    mid.metrics.update({"roas": 1.2, "revenue": 120.0, "spend": 100.0})
    loser.metrics.update({"roas": 0.5, "revenue": 50.0, "spend": 100.0})
    allocation = engine.allocate_budget([winner, mid, loser], 1000.0)
    assert allocation[winner.id] >= allocation[mid.id] >= allocation[loser.id]
    assert allocation[winner.id] > allocation[loser.id]


def test_allocate_budget_skips_killed():
    engine = CapitalEngine()
    pod_a = Pod("a", "US", "meta", budget=50.0)
    pod_b = Pod("b", "EU", "tiktok", budget=50.0)
    pod_b.status = "killed"
    allocation = engine.allocate_budget([pod_a, pod_b], 1000.0)
    assert pod_b.id not in allocation
    assert abs(allocation[pod_a.id] - 1000.0) < 1e-6


def test_allocate_budget_all_killed():
    engine = CapitalEngine()
    pod = Pod("a", "US", "meta")
    pod.status = "killed"
    assert engine.allocate_budget([pod], 1000.0) == {}


def test_allocate_budget_no_pods():
    engine = CapitalEngine()
    assert engine.allocate_budget([], 1000.0) == {}

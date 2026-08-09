"""Tests for backend.risk.gate — the choke point real ad spend must pass
through before hitting a platform API.

Before this module, GlobalRiskEngine had a real kill switch and daily cap
but nothing in the spend path ever consulted enforce() or fed
record_spend(), so POST /risk/kill_switch had no effect on anything that
actually spends and the daily cap could never fire (today_spend() was
permanently 0.0).
"""
import pytest


@pytest.fixture(autouse=True)
def _fresh_engine(monkeypatch):
    """Swap in a fresh GlobalRiskEngine so tests don't share spend-log/
    kill-switch state with each other or with production code."""
    from core.risk.global_risk_engine import GlobalRiskEngine
    import backend.risk.gate as gate_mod

    engine = GlobalRiskEngine(max_daily_spend=1000.0, max_drawdown=0.30)
    monkeypatch.setattr(gate_mod, "_engine", lambda: engine)
    monkeypatch.setattr(gate_mod, "_capital_context", lambda: (1000.0, 1000.0))
    return engine


def test_check_spend_allowed_by_default():
    from backend.risk.gate import check_spend
    result = check_spend(50.0)
    assert result["allowed"] is True
    assert result["adjusted_amount"] == 50.0


def test_kill_switch_blocks_spend(_fresh_engine):
    from backend.risk.gate import check_spend
    _fresh_engine.activate_kill_switch(reason="test")
    result = check_spend(50.0)
    assert result["allowed"] is False
    assert result["triggered_cap"] == "kill_switch"


def test_record_spend_feeds_today_spend(_fresh_engine):
    from backend.risk.gate import record_spend
    record_spend(100.0)
    record_spend(50.0)
    assert _fresh_engine.today_spend() == 150.0


def test_record_spend_ignores_non_positive_amounts(_fresh_engine):
    from backend.risk.gate import record_spend
    record_spend(0.0)
    record_spend(-10.0)
    assert _fresh_engine.today_spend() == 0.0


def test_daily_cap_blocks_spend_once_exceeded(_fresh_engine):
    from backend.risk.gate import check_spend, record_spend
    record_spend(1000.0)  # exhausts the $1000 daily cap
    result = check_spend(50.0)
    assert result["allowed"] is False
    assert result["triggered_cap"] == "daily_spend"


def test_spend_capped_down_to_remaining_budget(_fresh_engine):
    from backend.risk.gate import check_spend, record_spend
    record_spend(970.0)  # leaves $30 of the $1000 cap
    result = check_spend(50.0)
    assert result["allowed"] is True
    assert result["adjusted_amount"] == 30.0

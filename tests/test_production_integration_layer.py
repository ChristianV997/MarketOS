import pytest
from fastapi import HTTPException

from api.control import STATE, approve, override_budget, pause, resume
from agents.human_gate import can_launch
from backend.core.state import SystemState
from backend.execution.loop import run_cycle
from core.bridge import Bridge


def test_run_cycle_emits_real_feedback_metrics_and_profit():
    state = SystemState()
    state = run_cycle(state)

    row = state.event_log.rows[-1]

    assert "ctr" in row
    assert "cvr" in row
    assert "cac" in row
    assert "profit" in row
    assert "cost" in row
    assert row["profit"] == round(row["revenue"] - row["cost"], 2)


def test_bridge_execute_dispatches_real_cycles(monkeypatch):
    class Runner:
        def __init__(self):
            self.products = []

        def delay(self, product):
            self.products.append(product)

    runner = Runner()
    monkeypatch.setattr("core.bridge.run_intelligence", lambda _keywords: ["idea one", "idea two"])
    monkeypatch.setattr("core.bridge.run_real_cycle", runner)

    launched = Bridge().execute(["ignored"])

    assert launched == 2
    assert len(runner.products) == 2
    assert all("budget" in product for product in runner.products)


def test_control_gate_rules():
    STATE["approved_products"].clear()
    STATE["paused_products"].clear()

    product_id = "p-1"

    assert can_launch(product_id) is False
    approve(product_id)
    assert can_launch(product_id) is True

    pause(product_id)
    assert product_id in STATE["paused_products"]
    resume(product_id)
    assert product_id not in STATE["paused_products"]

    with pytest.raises(HTTPException):
        override_budget(product_id, 0)

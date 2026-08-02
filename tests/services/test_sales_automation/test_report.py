"""Tests for services.sales_automation.report."""
import backend.core.persistence as pers
import pytest
from services.sales_automation.report import render_sales_bot_setup_plan_markdown
from services.sales_automation.simulate import run_sales_bot_simulation


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))


def test_renders_all_sections():
    session, handoff, flow, _ = run_sales_bot_simulation(
        "real_estate", ["I'm looking to buy a house in Austin", "asap, budget is $500,000"],
    )
    md = render_sales_bot_setup_plan_markdown(session, handoff, flow)
    assert "MarketOS Appointment Setter Bot Setup Plan" in md
    assert "Qualification Flow" in md
    assert "Simulated Transcript" in md
    assert "Appointment Handoff" in md
    assert "DRY RUN" in md

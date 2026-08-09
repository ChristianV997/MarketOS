from backend.obsidian.sync import sync_portfolio_action_set_note, sync_portfolio_optimization_note
from backend.optimization.action_generator import generate_portfolio_actions
from backend.optimization.optimizer import build_portfolio_optimization_plan


def test_optimization_obsidian_notes_skip_or_write_safely(tmp_path, monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    action_set = generate_portfolio_actions("obsidian-optimization-test", 3)
    plan = build_portfolio_optimization_plan("obsidian-optimization-test")
    assert sync_portfolio_action_set_note(action_set)["status"] == "skipped"
    assert sync_portfolio_optimization_note(plan)["status"] == "skipped"
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    assert sync_portfolio_action_set_note(action_set)["status"] == "written"
    assert sync_portfolio_optimization_note(plan)["status"] == "written"
    text = (tmp_path / "MarketOS/00_Executive/PortfolioOptimization" / f"{plan.optimization_id}.md").read_text(encoding="utf-8")
    assert "simulated" in text.lower() and "No live" in text

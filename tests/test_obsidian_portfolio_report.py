from backend.obsidian.sync import sync_portfolio_report_note
from backend.organization.portfolio_report import build_portfolio_report


def test_portfolio_note_skips_without_vault(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    result = sync_portfolio_report_note(build_portfolio_report("w", []))
    assert result["status"] == "skipped"


def test_portfolio_note_writes_linked_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    portfolio = build_portfolio_report("w", [])
    portfolio.report_ids = ["report-a", "report-b"]
    result = sync_portfolio_report_note(portfolio)
    assert result["status"] == "written"
    path = tmp_path / "MarketOS/07_Dashboards/PortfolioReports" / f"{portfolio.portfolio_report_id}.md"
    assert path.exists() and "report-a" in path.read_text(encoding="utf-8")

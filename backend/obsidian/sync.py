from __future__ import annotations

from .client import ObsidianClient
from .templates import render_portfolio_report_note, render_proposal_note


def sync_proposal_note(proposal, approval, decision, execution, report=None) -> dict:
    relative = f"MarketOS/02_Proposals/{proposal.proposal_id}.md"
    result = ObsidianClient().write_note(relative, render_proposal_note(proposal, approval, decision, execution, report=report))
    proposal.obsidian_note_path = relative if result.get("status") == "written" else ""
    return {"status": result.get("status", "skipped"), "path": relative, "detail": result}


def sync_portfolio_report_note(portfolio_report) -> dict:
    relative = f"MarketOS/07_Dashboards/PortfolioReports/{portfolio_report.portfolio_report_id}.md"
    result = ObsidianClient().write_note(relative, render_portfolio_report_note(portfolio_report))
    return {"status": result.get("status", "skipped"), "path": relative, "detail": result}

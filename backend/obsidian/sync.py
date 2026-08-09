from __future__ import annotations

from .client import ObsidianClient
from .templates import render_category_discovery_note, render_discovery_comparison_note, render_evidence_import_note, render_portfolio_report_note, render_product_hypothesis_note, render_proposal_note, render_refinement_cycle_note


def sync_proposal_note(proposal, approval, decision, execution, report=None) -> dict:
    relative = f"MarketOS/02_Proposals/{proposal.proposal_id}.md"
    result = ObsidianClient().write_note(relative, render_proposal_note(proposal, approval, decision, execution, report=report))
    proposal.obsidian_note_path = relative if result.get("status") == "written" else ""
    return {"status": result.get("status", "skipped"), "path": relative, "detail": result}


def sync_portfolio_report_note(portfolio_report) -> dict:
    relative = f"MarketOS/07_Dashboards/PortfolioReports/{portfolio_report.portfolio_report_id}.md"
    result = ObsidianClient().write_note(relative, render_portfolio_report_note(portfolio_report))
    return {"status": result.get("status", "skipped"), "path": relative, "detail": result}


def sync_category_discovery_note(discovery_run, portfolio_report_id: str = "") -> dict:
    relative = f"MarketOS/01_Research/CategoryDiscovery/{discovery_run.discovery_id}.md"
    result = ObsidianClient().write_note(relative, render_category_discovery_note(discovery_run, portfolio_report_id))
    return {"status": result.get("status", "skipped"), "path": relative, "detail": result}


def sync_product_hypothesis_note(hypothesis_run, portfolio_report_id: str = "") -> dict:
    relative = f"MarketOS/01_Research/ProductHypotheses/{hypothesis_run.hypothesis_run_id}.md"
    result = ObsidianClient().write_note(relative, render_product_hypothesis_note(hypothesis_run, portfolio_report_id))
    return {"status": result.get("status", "skipped"), "path": relative, "detail": result}


def sync_evidence_import_note(import_job, source_quality, normalization_result=None) -> dict:
    relative = f"MarketOS/01_Research/EvidenceImports/{import_job.import_id}.md"
    result = ObsidianClient().write_note(relative, render_evidence_import_note(import_job, source_quality, normalization_result))
    return {"status": result.get("status", "skipped"), "path": relative, "detail": result}


def sync_refinement_cycle_note(gap_analysis, import_plan, templates) -> dict:
    relative = f"MarketOS/01_Research/RefinementCycles/{gap_analysis.analysis_id}.md"
    result = ObsidianClient().write_note(relative, render_refinement_cycle_note(gap_analysis, import_plan, templates))
    return {"status": result.get("status", "skipped"), "path": relative, "detail": result}


def sync_discovery_comparison_note(comparison) -> dict:
    relative = f"MarketOS/01_Research/DiscoveryComparisons/{comparison.comparison_id}.md"
    result = ObsidianClient().write_note(relative, render_discovery_comparison_note(comparison))
    return {"status": result.get("status", "skipped"), "path": relative, "detail": result}

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.organization.portfolio_report import build_portfolio_report
from backend.organization.planner_executor_reviewer import run_planner_executor_reviewer
from backend.organization.report_registry import get_report_registry
from backend.obsidian.sync import (
    sync_category_discovery_note,
    sync_evidence_import_note,
    sync_portfolio_report_note,
    sync_product_hypothesis_note,
)

from .category_discovery import discover_categories_from_evidence
from .discovery_registry import get_discovery_registry
from .evidence_source_contract import get_evidence_source_registry
from .evidence_normalizer import normalize_imported_evidence
from .import_registry import get_import_registry
from .local_dataset import load_local_evidence_dataset, parse_evidence_records
from .product_hypothesis import generate_product_hypotheses


def _cap(value: Any, default: int, maximum: int) -> int:
    try:
        return max(0, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def run_market_discovery(
    workspace_id: str = "default",
    title: str = "Autonomous Market Discovery",
    objective: str = "Find promising product categories and product hypotheses",
    dataset_paths: list[str] | None = None,
    source_names: list[str] | None = None,
    max_categories: int = 10,
    max_hypotheses: int = 20,
    run_validation_services: bool = True,
    import_paths: list[str] | None = None,
    parser_type_by_path: dict[str, str] | None = None,
    source_name_by_path: dict[str, str] | None = None,
    import_only: bool = False,
) -> dict[str, Any]:
    """Run category-first discovery using only local, provenance-bearing evidence."""
    warnings: list[str] = []
    registry = get_discovery_registry()
    sources = get_evidence_source_registry()
    paths = list(dataset_paths or [])
    import_paths = list(import_paths or [])
    records = []
    if len(import_paths) > 10:
        return {"status": "blocked", "blocked_reasons": ["import_path_limit_exceeded"], "warnings": [], "imports": []}
    import_results: list[dict[str, Any]] = []
    import_obsidian: list[dict[str, Any]] = []
    for raw_path in import_paths:
        parser = (parser_type_by_path or {}).get(raw_path, "generic_market_csv")
        source_name = (source_name_by_path or {}).get(raw_path, parser)
        normalized = normalize_imported_evidence(raw_path, parser, source_name, workspace_id, {"type": "local_export", "not_live": True})
        get_import_registry().register_import_job(normalized.import_job)
        get_import_registry().register_source_quality(normalized.source_quality)
        import_obsidian.append(sync_evidence_import_note(normalized.import_job, normalized.source_quality, normalized))
        if normalized.records:
            records.extend(normalized.records)
            registry.register_evidence(normalized.records)
        import_results.append(normalized.to_dict())
        warnings.extend(normalized.warnings)
        if normalized.import_job.status != "completed": warnings.extend(normalized.import_job.blocked_reasons or [normalized.import_job.status])
    if import_only:
        return {"status": "completed" if any(item["import_job"]["status"] == "completed" for item in import_results) else "blocked", "imports": import_results, "obsidian": import_obsidian, "warnings": warnings}
    if len(paths) > 10:
        return {"status": "blocked", "blocked_reasons": ["dataset_path_limit_exceeded"], "warnings": []}
    max_categories = _cap(max_categories, 10, 50)
    max_hypotheses = _cap(max_hypotheses, 20, 100)
    for raw_path in paths:
        try:
            dataset = load_local_evidence_dataset(raw_path)
            source_name = str(dataset.get("source_name", "local_dataset"))
            if source_names and source_name not in source_names:
                warnings.append(f"source_filtered:{source_name}")
                continue
            safety = sources.validate_source_safe(source_name)
            if not safety.get("allowed"):
                warnings.append(f"source_blocked:{source_name}")
                continue
            records.extend(parse_evidence_records(dataset))
        except Exception as exc:
            warnings.append(f"dataset_failed:{Path(raw_path).name}:{type(exc).__name__}")
    if not paths:
        persisted = registry.list_evidence(limit=10000)
        records = [record for record in persisted if not source_names or record.source_name in source_names]
        if not records:
            warnings.append("no_local_or_persisted_evidence")
    if records:
        registry.register_evidence(records)
    discovery = discover_categories_from_evidence(records, workspace_id, title, objective)
    discovery.category_opportunities = discovery.category_opportunities[:max_categories]
    for index, opportunity in enumerate(discovery.category_opportunities, 1):
        opportunity.rank = index
    registry.register_category_discovery(discovery)
    hypotheses = generate_product_hypotheses(discovery, records, max_total=max_hypotheses)
    registry.register_product_hypothesis_run(hypotheses)
    validation_reports = []
    if run_validation_services:
        for hypothesis in hypotheses.hypotheses:
            result = run_planner_executor_reviewer(
                objective=f"Validate product hypothesis: {hypothesis.product_name}",
                workspace=workspace_id,
                department_id="product",
                service_name="product_research",
                inputs={"product_name": hypothesis.product_name, "category": hypothesis.category_name, "target_geo": "MX"},
            )
            if result.get("report"):
                validation_reports.append(result["report"])
    report_objects = []
    for item in validation_reports:
        report_id = item.get("report_id") if isinstance(item, dict) else None
        if report_id:
            report = get_report_registry().get(report_id)
            if report:
                report_objects.append(report)
    portfolio = build_portfolio_report(workspace_id, report_objects, f"{title} validation portfolio")
    get_report_registry().register_portfolio_report(portfolio)
    obsidian = {
        "category": sync_category_discovery_note(discovery, portfolio.portfolio_report_id),
        "hypotheses": sync_product_hypothesis_note(hypotheses, portfolio.portfolio_report_id),
        "portfolio": sync_portfolio_report_note(portfolio),
    }
    if not records:
        discovery.status = "blocked"
    return {
        "imports": import_results,
        "import_obsidian": import_obsidian,
        "status": "completed" if records else "blocked",
        "warnings": warnings,
        "discovery": discovery.to_dict(),
        "hypotheses": hypotheses.to_dict(),
        "validation_reports": validation_reports,
        "portfolio_report": portfolio.to_dict(),
        "obsidian": obsidian,
    }

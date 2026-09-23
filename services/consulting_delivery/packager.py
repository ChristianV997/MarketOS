from __future__ import annotations

import json
from typing import Any

from backend.workspaces.artifact_store import ArtifactStore
from backend.organization.report_registry import get_report_registry
from backend.deliverables.registry import get_deliverable_registry
from backend.deliverables.package import DeliverableSection

from .package import build_consulting_delivery, ConsultingDeliveryPackage


def package_consulting_deliverable(
    workspace_id: str,
    package_id: str,
    title: str,
    objective: str,
    executive_summary: str,
    metadata: dict[str, Any],
    report_ids: list[str],
    portfolio_report_ids: list[str] | None = None,
    artifact_store: ArtifactStore | None = None,
) -> ConsultingDeliveryPackage:
    """
    Accepts component reports from MarketOS services (CommercialReport, PortfolioReport)
    and produces a coherent consulting deliverable enforcing report-reference integrity.
    """
    registry = get_report_registry()
    sections = []
    artifacts = []

    # Report-reference integrity: ensure all IDs exist and belong to the workspace
    for r_id in report_ids:
        report = registry.get(r_id)
        if not report:
            raise ValueError(f"linked_report_missing: {r_id}")
        if report.workspace_id != workspace_id:
            raise ValueError(f"cross_workspace_leakage: Report {r_id} does not belong to {workspace_id}")

        # Build a section out of the CommercialReport
        section = DeliverableSection(
            section_id=f"rep_{r_id}",
            title=f"Commercial Report: {report.title}",
            order=len(sections) + 1,
            content_markdown=report.findings,
            summary=report.summary,
            source_refs=[{"type": "commercial_report", "id": r_id}]
        )
        sections.append(section)

    for p_id in (portfolio_report_ids or []):
        p_report = registry.get_portfolio_report(p_id)
        if not p_report:
            raise ValueError(f"linked_portfolio_report_missing: {p_id}")
        if p_report.workspace_id != workspace_id:
            raise ValueError(f"cross_workspace_leakage: Portfolio report {p_id} does not belong to {workspace_id}")

        # Build a section out of the PortfolioReport
        section = DeliverableSection(
            section_id=f"port_{p_id}",
            title=f"Portfolio Analysis: {p_report.title}",
            order=len(sections) + 1,
            content_markdown="\n".join(p_report.recommendations) if hasattr(p_report, "recommendations") else p_report.summary,
            summary=p_report.summary,
            source_refs=[{"type": "portfolio_report", "id": p_id}]
        )
        sections.append(section)

    metadata["linked_report_ids"] = report_ids + (portfolio_report_ids or [])

    pkg = build_consulting_delivery(
        workspace_id=workspace_id,
        package_id=package_id,
        title=title,
        objective=objective,
        executive_summary=executive_summary,
        metadata=metadata,
        sections=sections,
        artifacts=artifacts
    )

    # Enforce bounded output directly on the structure
    # Hard bounds on payload to avoid massive uncontrolled deliverables
    pkg_dict = pkg.to_dict()
    payload_size = len(json.dumps(pkg_dict))
    if payload_size > 1024 * 500: # 500 KB limit
        raise ValueError("bounded_output_exceeded: Generated deliverable exceeds 500KB size limit.")

    # Register output to deliverable registry
    d_registry = get_deliverable_registry()
    d_registry.register_package(pkg.as_deliverable_package())

    return pkg

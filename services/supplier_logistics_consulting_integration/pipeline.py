"""services.supplier_logistics_consulting_integration.pipeline -- the single
entrypoint that composes ``engagement``, ``portfolio``, and ``export`` for
one supplier/logistics evidence report.

This is planning-only, offline composition. Nothing in this module (or
anything it calls) sends a client message, places a supplier order, books
logistics capacity, moves money, or authorizes a launch -- see
``ConsultingIntegrationResult``'s own fixed safety fields.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from backend.deliverables.package import DeliverablePackage
from backend.deliverables.registry import DeliverableRegistry
from backend.organization.portfolio_report import PortfolioReport
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from evaluation.companyos.service_delivery import ClientEngagement, ClientFacingServicePackage
from services.supplier_logistics_research.schemas import SupplierLogisticsReport

from .engagement import record_supplier_logistics_evidence
from .export import build_client_safe_deliverable, export_supplier_logistics_status
from .portfolio import build_supplier_logistics_portfolio


@dataclass(frozen=True)
class ConsultingIntegrationResult:
    """The complete, planning-only output of one supplier/logistics
    evidence report entering the consulting engagement/portfolio/export
    pipeline. ``read_only``/``network_calls``/``mutated`` are fixed
    invariants, matching every safety declaration elsewhere in this
    integration and in the upstream ``SupplierLogisticsReport`` itself."""

    engagement: ClientEngagement
    deliverable: DeliverablePackage
    portfolio: PortfolioReport
    # evaluation.trustos.client_workspace_isolation.ClientWorkspaceEvidenceExport,
    # typed loosely here to avoid a module-level import of evaluation.trustos
    # from services/** (export.py imports it function-locally, matching the
    # existing convention in evaluation.companyos.service_delivery and
    # backend.deployment.service_delivery_smoke).
    status_export: object
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False

    def __post_init__(self) -> None:
        if self.read_only is not True or self.network_calls is not False or self.mutated is not False:
            raise ValueError("this pipeline is read-only and must never mutate or call a live network")


def build_consulting_package(
    report: SupplierLogisticsReport,
    *,
    engagement: ClientEngagement,
    package: ClientFacingServicePackage,
    workspace: ClientWorkspace,
    other_reports_for_portfolio: Sequence[SupplierLogisticsReport] = (),
    registry: WorkspaceRegistry | None = None,
    deliverable_registry: DeliverableRegistry | None = None,
    include_supplier_notes: bool = False,
    updated_at: str = "offline-deterministic",
    generated_at: str = "offline-deterministic",
) -> ConsultingIntegrationResult:
    """Attach ``report`` to ``engagement``, build a client-safe deliverable
    and TrustOS status export for it, and roll it (plus any
    ``other_reports_for_portfolio``, e.g. other offers for the same or a
    different candidate) into a workspace-scoped portfolio.

    Every negative control enforced by ``engagement.
    record_supplier_logistics_evidence`` and ``export.
    build_client_safe_deliverable`` -- workspace mismatch, currency
    mismatch, engagement-identity forgery, cross-client leakage -- applies
    here unchanged; this function adds no new bypass path.
    """
    updated_engagement = record_supplier_logistics_evidence(
        engagement, report, workspace=workspace, updated_at=updated_at, registry=registry
    )
    deliverable = build_client_safe_deliverable(
        report,
        engagement=updated_engagement,
        package=package,
        workspace=workspace,
        registry=registry,
        deliverable_registry=deliverable_registry,
        include_supplier_notes=include_supplier_notes,
        generated_at=generated_at,
    )
    status_export = export_supplier_logistics_status(report, workspace=workspace, registry=registry)
    portfolio = build_supplier_logistics_portfolio(
        workspace.workspace_id, (report, *other_reports_for_portfolio)
    )
    return ConsultingIntegrationResult(
        engagement=updated_engagement,
        deliverable=deliverable,
        portfolio=portfolio,
        status_export=status_export,
    )

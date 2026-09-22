"""services.supplier_logistics_consulting_integration.portfolio -- roll up
one or more ``SupplierLogisticsReport`` objects into the existing,
workspace-scoped ``backend.organization.portfolio_report.PortfolioReport``.

``build_portfolio_report`` is duck-typed against any object exposing
``.report_id``/``.service_name``/``.status``/``.recommendations``/
``.next_actions``/``.risk_flags``; this module supplies that shape via
``SupplierLogisticsPortfolioEntry`` rather than modifying
``backend.organization.portfolio_report`` or
``services.supplier_logistics_research.schemas``. No second portfolio
authority is created.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Sequence

from backend.organization.portfolio_report import PortfolioReport, build_portfolio_report
from services.supplier_logistics_research.schemas import SupplierLogisticsReport

SERVICE_NAME = "supplier_logistics_research"


def _report_id(report: SupplierLogisticsReport) -> str:
    """Deterministic id derived from the report's own identity + content,
    not a random uuid -- the same report built twice from the same input
    must roll up to the same report_id every time."""
    offer = report.offer
    seed = "|".join((
        report.candidate_id,
        offer.identity.supplier_offer.supplier_id,
        offer.identity.supplier_offer.offer_id,
        offer.identity.supplier_offer.supplier_sku,
        report.generated_at,
    ))
    return f"supplier-logistics-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:24]}"


@dataclass(frozen=True)
class SupplierLogisticsPortfolioEntry:
    """The minimal duck-typed shape ``build_portfolio_report`` requires,
    derived entirely from one ``SupplierLogisticsReport``'s own persisted
    facts -- no new claim is synthesized here."""

    report_id: str
    service_name: str
    status: str
    recommendations: tuple[str, ...]
    next_actions: tuple[str, ...]
    risk_flags: tuple[str, ...]

    @classmethod
    def from_report(cls, report: SupplierLogisticsReport) -> "SupplierLogisticsPortfolioEntry":
        status = "blocked" if report.blockers else "completed"
        recommendations = tuple(action.description for action in report.next_actions if not action.blocking)
        next_actions = tuple(action.description for action in report.next_actions if action.blocking)
        risk_flags = tuple(
            f"{entry.category}:{entry.severity}" for entry in report.risk_matrix if entry.severity in {"high", "blocked"}
        )
        return cls(
            report_id=_report_id(report),
            service_name=SERVICE_NAME,
            status=status,
            recommendations=recommendations,
            next_actions=next_actions,
            risk_flags=risk_flags,
        )


def build_supplier_logistics_portfolio(
    workspace_id: str,
    reports: Sequence[SupplierLogisticsReport],
    *,
    title: str | None = None,
) -> PortfolioReport:
    """Aggregate any number of supplier/logistics evidence reports -- for
    the same candidate across multiple offers, or across multiple
    candidates -- into one workspace-scoped ``PortfolioReport``. An empty
    ``reports`` sequence is valid and produces an "empty" portfolio,
    exactly as ``build_portfolio_report`` already defines for zero input
    reports; this function adds no special case for it."""
    if not workspace_id:
        raise ValueError("workspace_id is required for a client-facing portfolio rollup")
    for report in reports:
        if not isinstance(report, SupplierLogisticsReport):
            raise TypeError("every report must be a SupplierLogisticsReport")
    entries = [SupplierLogisticsPortfolioEntry.from_report(report) for report in reports]
    return build_portfolio_report(workspace_id, entries, title=title or "Supplier & logistics evidence portfolio")

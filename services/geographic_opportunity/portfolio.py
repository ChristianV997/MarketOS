"""services.geographic_opportunity.portfolio -- duck-typed adapter onto
``backend.organization.portfolio_report.build_portfolio_report``.

``build_portfolio_report`` performs no ``isinstance`` check of its own
(confirmed by reading ``backend/organization/portfolio_report.py`` before
writing this module): it only reads ``.report_id`` / ``.service_name`` /
``.status`` / ``.recommendations`` / ``.next_actions`` / ``.risk_flags``
off each entry it is given.
``GeographicOpportunityPortfolioEntry.from_report`` projects one
``GeographicOpportunityReport`` onto exactly that shape, so this
service's own reports can be aggregated into a cross-service
``PortfolioReport`` alongside reports from other services (e.g. an
"opportunity discovery" service) without either side importing the
other's dataclasses. This module depends only on this service's own,
already-merged ``GeographicOpportunityReport`` -- it does not import any
unmerged "opportunity discovery" branch, and ``backend/**`` still never
imports ``services/**`` anywhere in this repository.

This module performs no I/O of its own and calls
``backend.organization.portfolio_report.build_portfolio_report``
directly -- it never re-derives portfolio-aggregation logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from backend.organization.portfolio_report import PortfolioReport, build_portfolio_report

from .schemas import GeographicOpportunityReport

SERVICE_NAME = "geographic_opportunity"


@dataclass(frozen=True)
class GeographicOpportunityPortfolioEntry:
    """The exact duck-typed shape
    ``backend.organization.portfolio_report.build_portfolio_report``
    expects from one entry. Built only via ``from_report`` -- never
    constructed by hand from unverified data, so every field here is
    traceable back to one ``GeographicOpportunityReport``'s own,
    already-validated content."""

    report_id: str
    service_name: str
    status: str
    recommendations: tuple[str, ...]
    next_actions: tuple[str, ...]
    risk_flags: tuple[str, ...]

    @classmethod
    def from_report(cls, report: GeographicOpportunityReport) -> "GeographicOpportunityPortfolioEntry":
        """``recommendations`` are this report's own non-blocking next
        research actions (suggestions); ``next_actions`` are its blocking
        next research actions plus its own plain-text blockers (things
        that must happen before this opportunity can be relied on);
        ``risk_flags`` are ``"{category}:{severity}"`` for every
        ``high``/``blocked``-severity risk-matrix entry. Nothing here
        invents a recommendation, action, or risk this report did not
        already surface."""
        if not isinstance(report, GeographicOpportunityReport):
            raise TypeError("report must be a GeographicOpportunityReport")
        recommendations = tuple(action.description for action in report.next_actions if not action.blocking)
        next_actions = tuple(action.description for action in report.next_actions if action.blocking) + tuple(report.blockers)
        risk_flags = tuple(
            f"{entry.category}:{entry.severity}" for entry in report.risk_matrix if entry.severity in {"high", "blocked"}
        )
        return cls(
            report_id=f"geo_opportunity:{report.candidate_id}:{report.generated_at}",
            service_name=SERVICE_NAME,
            status=report.status,
            recommendations=recommendations,
            next_actions=next_actions,
            risk_flags=risk_flags,
        )


def build_geographic_opportunity_portfolio(
    workspace_id: str,
    reports: Sequence[GeographicOpportunityReport],
    *,
    title: str | None = None,
    limit_recommendations: int = 10,
) -> PortfolioReport:
    """Aggregates ``GeographicOpportunityReport`` objects into a
    ``backend.organization.portfolio_report.PortfolioReport`` by
    projecting each one through
    ``GeographicOpportunityPortfolioEntry.from_report`` first. Delegates
    all aggregation to the canonical ``build_portfolio_report`` -- this
    function never re-derives that logic."""
    entries = [GeographicOpportunityPortfolioEntry.from_report(report) for report in reports]
    return build_portfolio_report(workspace_id, entries, title=title, limit_recommendations=limit_recommendations)

"""services.supplier_logistics_consulting_integration -- connects
services.supplier_logistics_research's evidence reports to the existing
consulting engagement lifecycle (evaluation.companyos.service_delivery),
the existing workspace-scoped portfolio rollup
(backend.organization.portfolio_report), and the existing TrustOS
client-safe export boundary (evaluation.trustos.client_workspace_isolation).

Does not duplicate or rewrite services.supplier_logistics_research's
schemas, controls, or report-building logic; does not create a second
engagement, deliverable, portfolio, or export authority. Planning-only:
never creates orders, bookings, inventory actions, payments, supplier
contact, logistics execution, or launch authorization.
"""
from .controls import (
    CrossClientLeakageError,
    NegativeControlError,
    WorkspaceMismatchError,
    is_verified,
    reject_cross_client_leakage,
    reject_unsafe_input,
    require_matching_currency,
    require_present,
    require_workspace_match,
)
from .engagement import record_supplier_logistics_evidence
from .export import (
    build_client_safe_deliverable,
    build_client_safe_deliverable_payload,
    collect_supplier_notes,
    export_supplier_logistics_status,
)
from .pipeline import ConsultingIntegrationResult, build_consulting_package
from .portfolio import SupplierLogisticsPortfolioEntry, build_supplier_logistics_portfolio

__all__ = [
    "CrossClientLeakageError",
    "NegativeControlError",
    "WorkspaceMismatchError",
    "is_verified",
    "reject_cross_client_leakage",
    "reject_unsafe_input",
    "require_matching_currency",
    "require_present",
    "require_workspace_match",
    "record_supplier_logistics_evidence",
    "build_client_safe_deliverable",
    "build_client_safe_deliverable_payload",
    "collect_supplier_notes",
    "export_supplier_logistics_status",
    "ConsultingIntegrationResult",
    "build_consulting_package",
    "SupplierLogisticsPortfolioEntry",
    "build_supplier_logistics_portfolio",
]

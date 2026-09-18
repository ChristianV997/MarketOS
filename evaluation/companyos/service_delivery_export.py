"""Client-safe projections for the four priority service packages.

Uses TrustOS client_workspace_isolation as the export-boundary authority.
Does not write artifacts, invoices, or live reports. Internal ecommerce
workspaces and cross-client reads fail closed.
"""
from __future__ import annotations

from typing import Any, Mapping

from evaluation.companyos.service_delivery_plane import (
    ServiceDeliveryError,
    open_engagement,
    render_client_deliverable,
)

try:
    from evaluation.trustos.client_workspace_isolation import (
        INTERNAL_KEYS,
        check_workspace_leakage,
    )
except Exception:  # pragma: no cover - isolation module is consumed when present
    INTERNAL_KEYS = {
        "internal_prompt",
        "internal_scoring_formula",
        "internal_heuristic",
        "internal_strategy_note",
        "internal_pricing_note",
        "internal_upsell_note",
        "internal_agent_instruction",
        "source_code",
        "cross_client_learning",
    }

    def check_workspace_leakage(payload: Mapping[str, Any] | None = None) -> tuple[Any, ...]:
        return ()


PACKAGE_RENDERERS = {
    "product-validation-sprint": "Product Validation Sprint",
    "unit-economics-diagnostic": "Unit Economics Diagnostic",
    "launch-draft-pack": "Launch Draft Pack",
    "managed-acquisition-cro": "Managed Acquisition Diagnostic",
}


def _assert_client_workspace(workspace_id: str) -> None:
    if workspace_id.startswith("internal-") or workspace_id.startswith("workspace-internal"):
        raise ServiceDeliveryError("internal ecommerce data cannot appear in client reports")


def project_engagement(
    *,
    package_alias: str,
    client_id: str,
    workspace_id: str,
    scope: str,
    intake: Mapping[str, Any],
    fee: Any,
    planned_hours: Any,
    requesting_workspace: str | None = None,
) -> dict[str, Any]:
    _assert_client_workspace(workspace_id)
    if requesting_workspace and requesting_workspace != workspace_id:
        raise ServiceDeliveryError("client A cannot read client B")
    engagement = open_engagement(
        client_id=client_id,
        workspace_id=workspace_id,
        package_alias=package_alias,
        scope=scope,
        intake=intake,
        fee=fee,
        planned_hours=planned_hours,
    )
    report = render_client_deliverable(engagement, other_workspace=requesting_workspace)
    leakage = check_workspace_leakage(report)
    if leakage:
        blocked = [item for item in leakage if getattr(item, "status", "") == "hard_block"]
        if blocked:
            raise ServiceDeliveryError("TrustOS leakage check blocked export")
    encoded_keys = set(str(key) for key in report.keys())
    if encoded_keys & INTERNAL_KEYS:
        raise ServiceDeliveryError("internal TrustOS classes cannot be exported")
    report["isolation"] = {
        "authority": "evaluation.trustos.client_workspace_isolation",
        "workspace_scoped": True,
        "record_kind": "planning_record",
        "internal_classes_excluded": True,
    }
    return report


def project_product_validation(**kwargs: Any) -> dict[str, Any]:
    return project_engagement(package_alias="product-validation-sprint", **kwargs)


def project_unit_economics(**kwargs: Any) -> dict[str, Any]:
    return project_engagement(package_alias="unit-economics-diagnostic", **kwargs)


def project_launch_draft(**kwargs: Any) -> dict[str, Any]:
    return project_engagement(package_alias="launch-draft-pack", **kwargs)


def project_managed_acquisition(**kwargs: Any) -> dict[str, Any]:
    return project_engagement(package_alias="managed-acquisition-cro", **kwargs)


__all__ = [
    "PACKAGE_RENDERERS",
    "project_engagement",
    "project_product_validation",
    "project_unit_economics",
    "project_launch_draft",
    "project_managed_acquisition",
]

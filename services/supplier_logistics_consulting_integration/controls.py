"""services.supplier_logistics_consulting_integration.controls -- negative
controls specific to the integration boundary between
``services.supplier_logistics_research`` and the consulting engagement/
portfolio/TrustOS-export surfaces.

This module never re-implements a control ``services.supplier_logistics_
research.controls`` already owns (credential-shaped input, raw HTML,
mismatched currency, missing money, supplier-claim-vs-verified-evidence):
those are re-exported below for convenient reuse at this boundary. This
module adds only the two negative controls that are new at THIS boundary
and have no equivalent in the upstream service: workspace mismatch and
cross-client leakage of a richer, less-curated export payload than the
upstream service ever produces on its own.
"""
from __future__ import annotations

from typing import Any, Mapping

from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry, get_workspace_registry

# Re-exported, not re-implemented -- see module docstring.
from services.supplier_logistics_research.controls import (  # noqa: F401
    NegativeControlError,
    is_verified,
    reject_unsafe_input,
    require_matching_currency,
    require_present,
)


class WorkspaceMismatchError(ValueError):
    """Raised when a caller-supplied ``ClientWorkspace`` does not match the
    workspace_id a record (an engagement, a report, a deliverable) is
    actually scoped to."""


class CrossClientLeakageError(ValueError):
    """Raised when a client-egress payload fails
    ``evaluation.trustos.client_workspace_isolation.check_workspace_leakage``
    -- this integration never redacts-and-continues; it fails closed."""


def require_workspace_match(
    claimed_workspace_id: str,
    workspace: ClientWorkspace,
    *,
    registry: WorkspaceRegistry | None = None,
) -> ClientWorkspace:
    """Verify ``workspace`` is the genuine, currently-registered workspace
    for ``claimed_workspace_id`` before any client-facing action proceeds.

    Mirrors ``evaluation.trustos.client_workspace_isolation.
    export_client_evidence``'s own identity check (re-fetch by id, compare
    ``to_dict()`` byte-for-byte) and ``evaluation.companyos.
    service_delivery.get_client_engagement_for_workspace``'s "never trust
    an object's own claimed field alone" pattern: a caller cannot simply
    hand this function a ``ClientWorkspace`` object that merely *claims* to
    have the right ``workspace_id`` -- it must be the one actually on file.
    """
    if not isinstance(workspace, ClientWorkspace):
        raise WorkspaceMismatchError("invalid workspace object")
    if not claimed_workspace_id:
        raise WorkspaceMismatchError("a workspace_id is required")
    if workspace.workspace_id != claimed_workspace_id:
        raise WorkspaceMismatchError(
            f"workspace mismatch: expected {claimed_workspace_id!r}, got {workspace.workspace_id!r}"
        )
    reg = registry or get_workspace_registry()
    registered = reg.get(claimed_workspace_id)
    if registered is None or registered.to_dict() != workspace.to_dict():
        raise WorkspaceMismatchError(f"workspace {claimed_workspace_id!r} is not the registered record")
    return registered


def reject_cross_client_leakage(payload: Mapping[str, Any], *, field_name: str = "payload") -> None:
    """Run ``payload`` through TrustOS's own leakage detector -- the sole
    authority for this check in this repository -- and fail closed on any
    finding rather than attempting a partial redaction. Imported function-
    locally to match the existing convention in
    ``evaluation.companyos.service_delivery`` and
    ``backend.deployment.service_delivery_smoke`` (both of which defer this
    same import to call time to avoid an import-time companyos<->trustos
    cycle)."""
    from evaluation.trustos.client_workspace_isolation import check_workspace_leakage

    findings = check_workspace_leakage(payload, client_safe=True)
    if findings:
        described = ", ".join(f"{item.field_path} ({item.data_class})" for item in findings)
        raise CrossClientLeakageError(f"{field_name} failed the TrustOS client-safety leakage check: {described}")

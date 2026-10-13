"""Bind an intelligence run to the workspace the operator gate verified, never to a caller-supplied value.

``require_workspace_permission`` resolves the caller's sole internal membership and returns it as
``WorkspaceAccess``. Mutating handlers take their target from ``access.workspace_id`` through these helpers:

* a body ``workspace_id`` that is absent or blank is ignored; any other value must name the verified
  workspace, or the request is refused with the 403 code an unknown workspace already gets;
* an ``opportunity_id`` or angle id reaches an engine only when its record belongs to the verified
  workspace. A foreign id is dropped exactly as an unknown one is, so the response reveals nothing
  about other workspaces.

Call these before any ``try`` block: a refusal must not be turned into a partial response.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from backend.identity.errors import WorkspaceAccessDenied
from backend.identity.http import http_exception
from backend.identity.workspaces import WorkspaceAccess


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def bound_workspace(payload: Mapping[str, Any], access: WorkspaceAccess) -> str:
    """The verified workspace. A caller value is accepted only when it names that same workspace."""
    requested = payload.get("workspace_id")
    if _blank(requested):
        return access.workspace_id
    if not isinstance(requested, str) or requested.strip() != access.workspace_id:
        raise http_exception(WorkspaceAccessDenied())
    return access.workspace_id


def bound_opportunity_id(opportunity_id: Any, workspace_id: str) -> str | None:
    """The opportunity id if its record is in ``workspace_id``; otherwise None, as for an unknown id."""
    if _blank(opportunity_id):
        return None
    from backend.discovery.opportunity_registry import get_opportunity_registry

    record = get_opportunity_registry().get_opportunity(str(opportunity_id))
    return str(opportunity_id) if record is not None and record.workspace_id == workspace_id else None


def owned_angles(registry: Any, angle_ids: Iterable[Any], workspace_id: str) -> list[Any]:
    """The angles among ``angle_ids`` that belong to ``workspace_id``. Foreign and unknown ids are skipped."""
    angles = []
    for angle_id in angle_ids:
        angle = registry.get_angle(angle_id)
        if angle is not None and angle.workspace_id == workspace_id:
            angles.append(angle)
    return angles

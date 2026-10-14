"""Bind intelligence requests to the workspace the operator gate verified, never to a caller-supplied value.

``require_workspace_permission`` resolves the caller's sole internal membership and returns it as
``WorkspaceAccess``. Handlers take their target from ``access.workspace_id`` through these helpers:

* a ``workspace_id`` (body or query) that is absent or blank is ignored; any other value must name the
  verified workspace, or the request is refused with the 403 code an unknown workspace already gets;
* a by-ID read or mutation reaches its record only when the record belongs to the verified workspace.
  A foreign id gets exactly the response an unknown id gets, so the response reveals nothing about
  other workspaces;
* an ``opportunity_id`` or angle id reaches an engine only when its record belongs to the verified
  workspace, for the same reason.

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


def verified_workspace(requested: Any, access: WorkspaceAccess) -> str:
    """The verified workspace. A caller value is accepted only when it names that same workspace."""
    if _blank(requested):
        return access.workspace_id
    if not isinstance(requested, str) or requested.strip() != access.workspace_id:
        raise http_exception(WorkspaceAccessDenied())
    return access.workspace_id


def bound_workspace(payload: Mapping[str, Any], access: WorkspaceAccess) -> str:
    """The verified workspace for a request body."""
    return verified_workspace(payload.get("workspace_id"), access)


def owned(record: Any, workspace_id: str) -> bool:
    return record is not None and getattr(record, "workspace_id", None) == workspace_id


def owned_or_none(record: Any, workspace_id: str) -> Any:
    """The record if it belongs to ``workspace_id``; otherwise None, which callers answer as not found."""
    return record if owned(record, workspace_id) else None


def bound_opportunity_id(opportunity_id: Any, workspace_id: str) -> str | None:
    """The opportunity id if its record is in ``workspace_id``; otherwise None, as for an unknown id."""
    if _blank(opportunity_id):
        return None
    from backend.discovery.opportunity_registry import get_opportunity_registry

    record = get_opportunity_registry().get_opportunity(str(opportunity_id))
    return str(opportunity_id) if owned(record, workspace_id) else None


def owned_angles(registry: Any, angle_ids: Iterable[Any], workspace_id: str) -> list[Any]:
    """The angles among ``angle_ids`` that belong to ``workspace_id``. Foreign and unknown ids are skipped."""
    angles = []
    for angle_id in angle_ids:
        angle = registry.get_angle(angle_id)
        if owned(angle, workspace_id):
            angles.append(angle)
    return angles

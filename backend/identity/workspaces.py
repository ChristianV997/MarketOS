"""backend.identity.workspaces -- principal-to-workspace resolution.

A client-supplied workspace value is only a *selector among the principal's own
memberships*. It never creates access, and workspace names never select
anything. A workspace the principal does not belong to is indistinguishable
from one that does not exist (same 403 code).
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from .errors import WorkspaceAccessDenied, WorkspaceSelectionRequired
from .principal import VerifiedPrincipal

WORKSPACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass(frozen=True)
class WorkspaceAccess:
    """A principal's membership in one workspace, as resolved server-side."""

    issuer: str
    subject: str
    workspace_id: str
    workspace_type: str
    display_name: str
    role: str | None = None


class WorkspaceRepository(Protocol):
    def memberships_for(self, principal: VerifiedPrincipal) -> Sequence[WorkspaceAccess]:
        """Return only the given principal's memberships."""


def resolve_workspace(
    principal: VerifiedPrincipal,
    requested_workspace_id: str | None,
    repository: WorkspaceRepository,
) -> WorkspaceAccess:
    memberships = sorted(
        (
            m
            for m in repository.memberships_for(principal)
            if m.issuer == principal.issuer and m.subject == principal.subject
        ),
        key=lambda m: m.workspace_id,
    )

    selector = requested_workspace_id.strip() if isinstance(requested_workspace_id, str) else ""
    if selector:
        if not WORKSPACE_ID_PATTERN.fullmatch(selector):
            raise WorkspaceAccessDenied()
        for membership in memberships:
            if membership.workspace_id == selector:
                return membership
        raise WorkspaceAccessDenied()

    if not memberships:
        raise WorkspaceAccessDenied("no_workspace_membership")
    if len(memberships) > 1:
        raise WorkspaceSelectionRequired()
    return memberships[0]


def resolve_sole_workspace(
    principal: VerifiedPrincipal,
    repository: WorkspaceRepository,
    workspace_type: str,
) -> WorkspaceAccess:
    """Resolve the principal's single workspace of ``workspace_type`` from memberships alone.

    No client-supplied selector exists on this path. Zero memberships and several
    memberships both fail closed (403), so a caller can never choose a workspace.
    """
    memberships = [
        m
        for m in repository.memberships_for(principal)
        if m.issuer == principal.issuer and m.subject == principal.subject and m.workspace_type == workspace_type
    ]
    if not memberships:
        raise WorkspaceAccessDenied("no_workspace_membership")
    if len(memberships) > 1:
        raise WorkspaceAccessDenied("workspace_ambiguous")
    return memberships[0]

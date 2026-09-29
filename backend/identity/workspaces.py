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

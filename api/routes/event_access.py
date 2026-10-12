"""Shared access dependencies for every route that reads or writes canonical events.

Identity comes only from ``require_workspace_permission``: the verified bearer token and the principal's sole
internal membership. Nothing here reads a workspace from a query, header or body; routes bind their own input
to ``WorkspaceAccess.workspace_id``. Without a configured verifier and repository the gate answers 503.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from backend.identity.http import require_workspace_permission
from backend.identity.repository import OWNER_TYPE
from backend.identity.roles import CANONICAL_EVENT_READ, CANONICAL_EVENT_WRITE
from backend.security.rate_limit import check_rate_limit, event_read_policy

event_read_gate = require_workspace_permission(OWNER_TYPE, CANONICAL_EVENT_READ)
event_write_gate = require_workspace_permission(OWNER_TYPE, CANONICAL_EVENT_WRITE)


def admit_event_read(request: Request) -> None:
    """Throttle before identity: anonymous and denied requests count, so token checks are never free."""
    key = getattr(getattr(request, "client", None), "host", None) or "direct"
    decision = check_rate_limit(event_read_policy(), key)
    if not decision.allowed:
        raise HTTPException(
            429,
            detail={
                "status": "rate_limited",
                "retry_after_seconds": decision.retry_after_seconds,
                "read_only": True,
                "mutated": False,
            },
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )


__all__ = ["admit_event_read", "event_read_gate", "event_write_gate"]

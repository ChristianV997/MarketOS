"""Server-side authority for commerce dispatch that could reach a provider or publish.

A live (non-dry-run) request may dispatch only with a grant from the canonical approval ledger,
``evaluation.companyos.approval_ledger``. That ledger is offline: ``transition_status`` refuses
``approved`` ("offline mode cannot grant live approval") and it has no grant store to look a request up
in. So every live request is refused here, before any dispatch. When a grant source exists it must bind
the approval to the verified principal's workspace and to the action; that binding does not exist yet.

Nothing a caller sends grants authority. ``confirm_live``, ``approval_state``, ``approval_id``, approver,
actor, workspace and approval-shaped JSON are not read. The only input is ``dry_run``, and only as a
strict JSON boolean. A dry run dispatches nothing live and carries ``approval_state="not_required"``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

REASON_LIVE_UNAVAILABLE = "live_approval_unavailable"
REASON_INVALID_DRY_RUN = "invalid_dry_run_flag"


@dataclass(frozen=True)
class DispatchDecision:
    allowed: bool
    dry_run: bool
    approval_state: str
    reasons: tuple[str, ...] = ()


def parse_dry_run(payload: dict[str, Any]) -> bool | None:
    """Return the strict ``dry_run`` flag. Absent means a dry run. Any non-boolean is malformed (``None``)."""
    raw = payload.get("dry_run", True)
    return raw if isinstance(raw, bool) else None


def decide_dispatch(*, dry_run: bool) -> DispatchDecision:
    """Decide whether a commerce request may dispatch. Only dry runs can; live requests are refused."""
    if dry_run:
        return DispatchDecision(allowed=True, dry_run=True, approval_state="not_required")
    return DispatchDecision(
        allowed=False,
        dry_run=False,
        approval_state="not_granted",
        reasons=(REASON_LIVE_UNAVAILABLE,),
    )


__all__ = [
    "REASON_INVALID_DRY_RUN",
    "REASON_LIVE_UNAVAILABLE",
    "DispatchDecision",
    "decide_dispatch",
    "parse_dry_run",
]

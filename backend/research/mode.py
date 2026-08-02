"""Runtime safety controls for the research-first operating mode.

Research-only is intentionally an environment/runtime policy rather than a
second set of provider implementations.  Read paths remain available, while
external mutations must explicitly pass through :func:`require_write_allowed`.
The library default is disabled so existing unit tests and embedded callers
remain backwards compatible; production/supervisor entrypoints set it to
``true`` before starting workers.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


class ResearchOnlyError(PermissionError):
    """Raised when a live external mutation is attempted in research mode."""

    code = "research_only"


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def is_research_only() -> bool:
    """Return whether the current process is restricted to research paths."""
    return _truthy(os.getenv("MARKETOS_RESEARCH_ONLY", "false"))


@dataclass(frozen=True)
class WriteDecision:
    allowed: bool
    reason: str = ""


def write_decision(*, dry_run: bool, approval_state: str = "not_required") -> WriteDecision:
    if is_research_only() and not dry_run:
        return WriteDecision(False, "research_only")
    if not dry_run and approval_state not in {"approved", "not_required"}:
        return WriteDecision(False, "approval_required")
    return WriteDecision(True)


def require_write_allowed(*, dry_run: bool, approval_state: str = "not_required", action: str = "external_write") -> None:
    """Raise before a non-dry-run external mutation when policy forbids it."""
    decision = write_decision(dry_run=dry_run, approval_state=approval_state)
    if not decision.allowed:
        raise ResearchOnlyError(f"{action} blocked: {decision.reason}")


def research_block(*, action: str) -> dict[str, object]:
    """Stable JSON shape for API/orchestrator callers that skip a mutation."""
    return {"status": "blocked", "reason": "research_only", "action": action, "dry_run": True}

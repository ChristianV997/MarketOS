"""Fail-closed HTTP mutation boundary keyed on MARKETOS_ENVIRONMENT.

Canonical deployment modes live in ``backend.deployment.environment_contract``:
``local_dry_run``, ``staging``, and ``production``. This module does not invent
a bypass variable. It only answers whether credential-writing or
provider-executing HTTP routes may proceed:

- ``local_dry_run`` — permitted (explicit local fixture / dry-run path)
- absent — denied
- ``staging`` / ``production`` (hosted) — denied
- any other value — denied

Read-only health/readiness and credential *status* routes stay ungated.
Library helpers such as ``backend.config.set_credential`` remain callable from
local scripts; HTTP surfaces must call ``assert_local_mutation_allowed`` (or
``enforce_local_mutation_http``) before mutating or invoking providers.

Cycle/runner/control routes owned by other PRs should reuse this seam; this
module does not enable live actions.
"""
from __future__ import annotations

import os
from typing import Any, Mapping

ENV_VAR = "MARKETOS_ENVIRONMENT"
PERMITTED_MUTATION_MODES = frozenset({"local_dry_run"})
HOSTED_MODES = frozenset({"staging", "production"})
KNOWN_MODES = PERMITTED_MUTATION_MODES | HOSTED_MODES

# Stable client-facing denial text — no credentials, payloads, or exception text.
SAFE_DENIAL_DETAIL = (
    "Mutation and provider execution are denied outside "
    "MARKETOS_ENVIRONMENT=local_dry_run."
)


class MutationBoundaryError(PermissionError):
    """Raised when a mutating/provider HTTP action is blocked by runtime mode."""

    def __init__(self, reason: str, mode: str | None = None) -> None:
        self.reason = reason
        self.mode = mode
        super().__init__(SAFE_DENIAL_DETAIL)


def resolve_runtime_mode(environ: Mapping[str, str] | None = None) -> str | None:
    """Return the stripped MARKETOS_ENVIRONMENT value, or None if absent/blank."""
    values = os.environ if environ is None else environ
    raw = values.get(ENV_VAR)
    if raw is None:
        return None
    stripped = str(raw).strip()
    return stripped or None


def mutation_boundary_decision(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return a structured allow/deny decision without raising."""
    mode = resolve_runtime_mode(environ)
    if mode is None:
        return {
            "allowed": False,
            "mode": None,
            "reason": "runtime_mode_absent",
            "env_var": ENV_VAR,
        }
    if mode in PERMITTED_MUTATION_MODES:
        return {
            "allowed": True,
            "mode": mode,
            "reason": "local_dry_run_permitted",
            "env_var": ENV_VAR,
        }
    if mode in HOSTED_MODES:
        return {
            "allowed": False,
            "mode": mode,
            "reason": "hosted_mode_denied",
            "env_var": ENV_VAR,
        }
    return {
        "allowed": False,
        "mode": mode,
        "reason": "unrecognized_mode_denied",
        "env_var": ENV_VAR,
    }


def assert_local_mutation_allowed(
    environ: Mapping[str, str] | None = None,
    *,
    action: str = "mutation",
) -> dict[str, Any]:
    """Fail closed unless MARKETOS_ENVIRONMENT is explicitly local_dry_run.

    ``action`` is recorded for operators/logs only; it never selects a mode
    and is never returned to HTTP clients.
    """
    decision = mutation_boundary_decision(environ)
    if decision["allowed"]:
        return decision
    _ = action  # reserved for future structured audit; not client-visible
    raise MutationBoundaryError(reason=str(decision["reason"]), mode=decision.get("mode"))


def enforce_local_mutation_http(*, action: str = "mutation") -> dict[str, Any]:
    """FastAPI-facing helper: assert local mutation or raise HTTP 403.

    Imports FastAPI lazily so non-API callers can use ``assert_local_mutation_allowed``
    without requiring the web stack.
    """
    from fastapi import HTTPException

    try:
        return assert_local_mutation_allowed(action=action)
    except MutationBoundaryError:
        raise HTTPException(status_code=403, detail=SAFE_DENIAL_DETAIL) from None


__all__ = [
    "ENV_VAR",
    "HOSTED_MODES",
    "KNOWN_MODES",
    "MutationBoundaryError",
    "PERMITTED_MUTATION_MODES",
    "SAFE_DENIAL_DETAIL",
    "assert_local_mutation_allowed",
    "enforce_local_mutation_http",
    "mutation_boundary_decision",
    "resolve_runtime_mode",
]

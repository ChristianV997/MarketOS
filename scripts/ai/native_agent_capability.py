"""Sanitized native-agent capability record and provider command catalog.

MarketOS.NativeAgentCapability.v1 — a single, normalized answer to "which
AI-chat agents/providers are actually usable from this machine right now,"
so an operator or another AI-chat lane never infers readiness from mere
installation. This module never executes a provider, never reads a secret
value, and never stores an account ID or credential — it only detects
whether a named command exists on PATH (``shutil.which``) and whether a few
already-safe, allowlisted, read-only probes about it succeed.

This is the single authority for both the "native-agent capability record"
and the "native provider command catalog" the AI-chat reconciliation lane
asked for -- they are the same underlying detection, not two catalogs.

Does not replace #252's ``MarketOS.AIContext.v1`` (repository/session
context) or #254's ``MarketOS.WorktreeSafety.v1`` (git worktree safety);
``worktree_safety.py`` consumes this module's ``probe_agent`` for its own
"native agent command unavailable" and "CoderOS unavailable" checks instead
of re-detecting commands itself.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

SCHEMA = "MarketOS.NativeAgentCapability.v1"

# Readiness is never a single boolean -- each stage must be independently
# evidenced. "installed" (on PATH) never implies "configured" (has whatever
# config/auth the tool needs) or "enabled" (this session is actually allowed
# to invoke it) or "actually_used" (it was invoked and produced real output
# in this run).
STATES = frozenset(
    {"installed", "configured", "reachable", "enabled", "actually_used", "unavailable", "not_run"}
)

# Command name -> (display name, category). Detection only: no execution,
# no argv beyond an optional allowlisted --version/--help probe elsewhere.
PROVIDER_COMMANDS: dict[str, tuple[str, str]] = {
    "codex": ("Codex CLI", "coding_agent"),
    "claude": ("Claude Code CLI", "coding_agent"),
    "cursor": ("Cursor CLI", "coding_agent"),
    "grok": ("Grok CLI", "coding_agent"),
    "gemini": ("Gemini CLI", "coding_agent"),
    "aider": ("Aider", "coding_agent"),
    "ollama": ("Ollama", "local_inference"),
    "orca": ("Orca", "coding_agent"),
    "gh": ("GitHub CLI", "vcs_platform"),
    "coderos": ("CoderOS CLI", "external_orchestrator"),
    "gstack": ("gstack", "external_orchestrator"),
    "hermes": ("Hermes", "external_orchestrator"),
}


def _which(command: str) -> str | None:
    return shutil.which(command)


def probe_agent(command: str) -> dict[str, Any]:
    """Detect one provider command. Never executes it; never reads secrets."""
    if command not in PROVIDER_COMMANDS:
        return {
            "command": command,
            "name": command,
            "category": "unknown",
            "installed": False,
            "path_present": False,
            "state": "not_run",
            "reason": "command_not_in_catalog",
        }
    name, category = PROVIDER_COMMANDS[command]
    resolved = _which(command)
    installed = resolved is not None
    return {
        "command": command,
        "name": name,
        "category": category,
        "installed": installed,
        "path_present": installed,
        # This module only ever detects; it never configures, connects, or
        # invokes -- so anything past "installed" is honestly "not_run"
        # unless a caller supplies independent, already-collected evidence.
        "configured": "not_run",
        "reachable": "not_run",
        "enabled": "not_run",
        "actually_used": "not_run",
        "state": "installed" if installed else "unavailable",
        "reason": None if installed else "not_found_on_path",
        "credential_state": "not_read",
        "account_id_stored": False,
    }


def build_capability_record(
    *,
    commands: list[str] | None = None,
    observed: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the full capability record.

    ``observed`` lets a caller attach independently-proven evidence (e.g.
    "this run actually invoked `claude` and got real stdout") for specific
    commands, keyed by command name, with the same field names as
    ``probe_agent``'s output. Never trust a caller-supplied "state" upgrade
    without also requiring that record to carry evidence (checked below);
    absent that, every command stays at its detected floor.
    """
    names = commands or sorted(PROVIDER_COMMANDS)
    cache: dict[str, dict[str, Any]] = {}
    entries: list[dict[str, Any]] = []
    for command in names:
        record = _process_command(command, observed)
        cache[command] = record
        entries.append(record)
    coderos = cache.get("coderos") or _process_command("coderos", observed)
    return {
        "schema": SCHEMA,
        "read_only": True,
        "network_calls": False,
        "credentials_read": False,
        "account_ids_stored": False,
        "agents": entries,
        "worktree_support": {
            "state": "installed" if _which("git") else "unavailable",
            "mechanism": "git worktree (native)",
        },
        "browser_computer_use_available": {"state": "not_run", "reason": "not_probed_by_this_utility"},
        "coderos": _tag_coderos(coderos),
        "next_best_action": "treat every state below 'actually_used' as unproven readiness",
    }


def _process_command(command: str, observed: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    """Detect one command, then apply (and evidence-gate) any caller claim.

    Any claimed upgrade without an accompanying ``*_evidence`` value is
    rejected outright and recorded in ``rejected_claims`` rather than
    silently ignored, so a caller (including a CoderOS "work-order plan"
    -shaped payload) cannot quietly smuggle in an unproven state.
    """
    record = probe_agent(command)
    supplied = (observed or {}).get(command)
    if supplied and isinstance(supplied, dict):
        for field in ("configured", "reachable", "enabled", "actually_used"):
            value = supplied.get(field)
            evidence = supplied.get(f"{field}_evidence")
            if value in STATES and value != "not_run" and evidence:
                record[field] = value
            elif value not in (None, "not_run"):
                record[field] = "not_run"
                record.setdefault("rejected_claims", []).append(field)
    return record


def _tag_coderos(entry: dict[str, Any]) -> dict[str, Any]:
    """CoderOS is consumed as sanitized, read-only, in-repo metadata only.

    MarketOS never imports a live CoderOS runtime (see
    ``tests/ai/test_coderos_separation.py``); this tags the (already
    evidence-gated) detection entry with an explicit reminder that CoderOS
    metadata can never carry live-action authority.
    """
    entry = dict(entry)
    entry["marketos_runtime_import"] = "never"
    entry["can_authorize_live_actions"] = False
    return entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", action="append", default=[])
    parser.add_argument("--observed", type=Path, help="optional JSON file of caller-supplied evidence")
    args = parser.parse_args(argv)
    observed = None
    if args.observed and args.observed.is_file():
        try:
            observed = json.loads(args.observed.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            observed = None
    record = build_capability_record(commands=args.command or None, observed=observed)
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

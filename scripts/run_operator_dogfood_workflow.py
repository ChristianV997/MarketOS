#!/usr/bin/env python3
"""Operator dogfood readiness bridge: one documented, fail-closed sequence
over MarketOS's existing commands, for a fresh operator checkout.

This is a thin orchestrator. It does not create a second replay runner,
quality gate, readiness authority, event system, economics engine, service
catalog, or export boundary -- every phase below shells out to, or directly
calls, an existing authority and only translates its real output into one
small closed classification vocabulary:

    passed | not_run | unavailable | ci_unavailable | blocked | malformed

Phases (== the target dogfood workflow, minus the steps that already have
their own single existing command covering the whole slice):

    1. state_collision_check   -- scripts/ai/session_start.py
    2. readiness_preflight     -- scripts/ai/check_dev_stack.py +
                                   scripts/coderos_snapshot.py (read-only) +
                                   scripts/ai/run_local_quality_gate.py
                                   (informational only; its own well-known
                                   sandbox-CI/toolchain findings never block
                                   this bridge -- see _classify_quality_gate)
    3. commercial_dry_run      -- scripts/run_commercial_replay_integration.py
                                   (already covers research/evidence ->
                                   supplier_offer -> market_lane ->
                                   unit_economics -> competition ->
                                   promotion_gate -> offer -> experiment_draft
                                   -> campaign_draft -> simulated_order ->
                                   supplier_dispatch_draft -> tracking_draft
                                   -> delivery -> return_rma ->
                                   contribution_reconciliation, in one call)
    4. trustos_export          -- evaluation.trustos.client_workspace_isolation
                                   .check_workspace_leakage / .export_client_evidence
                                   (the real export boundary; a throwaway,
                                   per-run local WorkspaceRegistry file is used
                                   and discarded -- no persistent state)
    5. sanitized_handoff       -- this bridge's own final, leakage-checked
                                   rollup (never raw subprocess stdout)

The genuine gap this bridge closes: each of the above already exists and
works in isolation, but nothing previously chained "is this checkout safe to
edit" through "does the commercial dry-run replay correctly" through "does
its result pass the real TrustOS export boundary" into one fail-closed,
evidence-classified report for an operator to read before doing anything
live. Composing them is the whole of this file; none of their math, state
machines, or schemas are re-derived here.

Safety:
    - No network calls, no credentials read, no live provider action.
    - Every subprocess call is shell=False with a fixed argv list.
    - Raw subprocess stdout is never embedded in the final report; only
      already-JSON-parsed, explicitly selected fields are carried forward.
    - The one caller-supplied path (--repo) is resolved and used only as a
      subprocess cwd / positional argument to existing scripts that already
      accept the same argument themselves; no path is read as file content
      by this script directly.
    - The final report is an operator-facing internal handoff, not a
      client-facing export; it legitimately names the local checkout path
      and branch. The real TrustOS client-safe export boundary
      (check_workspace_leakage / export_client_evidence) is applied only
      where client-facing export actually happens: phase 4, per scenario.
      This report's own safety property is structural, not a second
      checked boundary: only hand-selected, already-parsed fields are
      included -- raw subprocess stdout/stderr is never carried forward.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = "MarketOS.OperatorDogfoodReadinessBridge.v1"
PHASES = ("state_collision_check", "readiness_preflight", "commercial_dry_run", "trustos_export", "sanitized_handoff")
CLASSIFICATIONS = frozenset({"passed", "not_run", "unavailable", "ci_unavailable", "blocked", "malformed"})
# Most-severe-wins ordering for the overall verdict -- the same pattern
# scripts/ai/execution_bundle.py uses for its own (unrelated) command
# classifications, re-derived independently here rather than imported,
# since this is a different subsystem with a deliberately different,
# smaller closed vocabulary.
_SEVERITY = {"passed": 0, "not_run": 1, "ci_unavailable": 1, "unavailable": 2, "blocked": 3, "malformed": 4}
DEFAULT_TIMEOUT_S = 120.0


def _run(argv: list[str], *, cwd: Path, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """Run one existing script's CLI. shell=False always; argv is a fixed list.

    Every composed script prints a JSON document on essentially every exit
    path (including its own error/configuration-error paths) -- rather than
    hardcode an exit-code allowlist that has to be kept in sync with each
    script's own exit-code contract (run_local_quality_gate.py alone uses
    four: 0/1/2/3), "ok" is decided purely by whether stdout parses as JSON.
    A script that crashed before printing anything still correctly reports
    "stdout_not_json" here.
    """
    try:
        completed = subprocess.run(
            argv, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout_s, shell=False, check=False,
        )
    except FileNotFoundError:
        return {"ok": False, "reason": "executable_not_found", "json": None}
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": f"timed_out_after_{timeout_s}s", "json": None}
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "reason": "stdout_not_json", "json": None}
    return {"ok": True, "reason": None, "json": parsed}


def _phase(name: str, classification: str, detail: dict[str, Any]) -> dict[str, Any]:
    if classification not in CLASSIFICATIONS:
        raise ValueError(f"unknown classification: {classification!r}")
    return {"phase": name, "classification": classification, "detail": detail}


# ---------------------------------------------------------------------------
# Phase 1: state_collision_check
# ---------------------------------------------------------------------------


def state_collision_check(repo: Path) -> dict[str, Any]:
    result = _run([sys.executable, "scripts/ai/session_start.py", "--json"], cwd=repo)
    if not result["ok"]:
        return _phase("state_collision_check", "unavailable", {"reason": result["reason"]})
    document = result["json"]
    conflicts = document.get("owned_path_changes") or []
    if conflicts:
        return _phase(
            "state_collision_check", "blocked",
            {"reason": "owned_path_changes_present", "conflicts": conflicts, "branch": document.get("branch"), "head": document.get("head")},
        )
    return _phase(
        "state_collision_check", "passed",
        {"branch": document.get("branch"), "head": document.get("head"), "upstream_exists": document.get("upstream_exists")},
    )


# ---------------------------------------------------------------------------
# Phase 2: readiness_preflight
# ---------------------------------------------------------------------------


def _classify_quality_gate(document: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    """The local quality gate's own well-documented sandbox findings
    (ci_unavailable, pre-existing toolchain mismatches) are informational
    for this bridge, never a hard blocker -- every merged PR in this
    repository treats this exact signal the same way. A genuine mutation
    or secret-shaped flag from the gate is still surfaced, never hidden.
    """
    if document is None:
        return "unavailable", {}
    # Verified directly against the tool's real (non---execute) --json
    # output: it is a flat document, not the nested "gate"/"pr_readiness"
    # shape an earlier draft of this function assumed -- that assumption
    # was never exercised against real output and would have silently
    # short-circuited to "passed" on every empty .get() fallback, which is
    # exactly the silent-vacuous-check failure mode this bridge exists to
    # avoid. --execute is deliberately not used here: it would additionally
    # run a full-repository compileall/pytest/ruff pass, which is too slow
    # for a per-run operator preflight; the planning-only pass already
    # yields real mutation/secret-shaped signals from git-state analysis.
    planning = document.get("planning_summary") or {}
    mutation_flags = planning.get("mutation_flags") or {}
    secret_flags = planning.get("secret_or_artifact_flags") or {}
    if any(mutation_flags.values()) or any(secret_flags.values()):
        return "blocked", {"mutation_flags": mutation_flags, "secret_or_artifact_flags": secret_flags}
    ci_classification = (document.get("ci") or {}).get("classification")
    top_classification = document.get("classification")
    if "ci_unavailable" in {ci_classification, top_classification}:
        return "ci_unavailable", {"ci_classification": ci_classification, "top_classification": top_classification}
    return "passed", {"ci_classification": ci_classification, "top_classification": top_classification}


def readiness_preflight(repo: Path, *, skip_quality_gate: bool) -> dict[str, Any]:
    dev_stack = _run([sys.executable, "scripts/ai/check_dev_stack.py", "--json"], cwd=repo)
    if not dev_stack["ok"]:
        return _phase("readiness_preflight", "unavailable", {"reason": f"check_dev_stack: {dev_stack['reason']}"})
    tools = dev_stack["json"].get("tools", {})
    # check_dev_stack.py only ever probes the literal command name "python"
    # (shutil.which("python")), which is None on any host that only has
    # "python3" on PATH -- exactly the common case on a fresh Linux/macOS
    # checkout. This bridge is itself running under sys.executable, which
    # is already conclusive proof a working Python exists; "git" is the
    # one tool this bridge's own subprocess calls (session_start.py,
    # coderos_snapshot.py) genuinely cannot function without.
    if not tools.get("git"):
        return _phase("readiness_preflight", "blocked", {"reason": "required_tool_missing", "tools": tools})

    coderos = _run([sys.executable, "scripts/coderos_snapshot.py", "--repo", str(repo), "--mode", "plan_only", "--json"], cwd=repo)
    coderos_state = "unavailable"
    coderos_detail: dict[str, Any] = {"reason": coderos["reason"]} if not coderos["ok"] else {}
    if coderos["ok"] and coderos["json"].get("status") == "success":
        coderos_state = "passed"
        coderos_detail = {
            "target_repo": coderos["json"].get("target_repo"),
            "evidence_class": coderos["json"].get("evidence_class"),
        }

    if skip_quality_gate:
        quality_gate_classification, quality_gate_detail = "not_run", {}
    else:
        # --from-git is required for real signal: without it, paths stays
        # empty and provider_mutation_like_detected/secret_value_like_detected
        # /artifacts_detected/credential_file_detected are permanently False
        # regardless of what is actually in the working tree (verified
        # directly by calling the underlying run_local_quality_gate.run()
        # with and without changed paths on an identical diff).
        gate_result = _run([sys.executable, "scripts/ai/run_local_quality_gate.py", "--from-git", "--json"], cwd=repo, timeout_s=180.0)
        quality_gate_classification, quality_gate_detail = _classify_quality_gate(gate_result["json"])

    # CoderOS is explicitly optional, read-only tooling (per this bridge's
    # own scope) -- its own "unavailable" never blocks the phase. The
    # quality-gate sub-check's classification is not similarly downgraded:
    # "unavailable" there (the subprocess itself failed to run/parse) must
    # be visible as this phase's own "unavailable", not silently reported
    # as "passed" -- a phase that never actually checked anything is not
    # the same thing as one that checked and found no problem.
    classification = quality_gate_classification
    return _phase(
        "readiness_preflight", classification,
        {
            "tools": tools,
            "coderos": {"classification": coderos_state, **coderos_detail},
            "quality_gate": {"classification": quality_gate_classification, **quality_gate_detail},
        },
    )


# ---------------------------------------------------------------------------
# Phase 3: commercial_dry_run
# ---------------------------------------------------------------------------


def commercial_dry_run(repo: Path) -> dict[str, Any]:
    result = _run([sys.executable, "scripts/run_commercial_replay_integration.py", "--json"], cwd=repo, timeout_s=180.0)
    if not result["ok"]:
        return _phase("commercial_dry_run", "malformed", {"reason": result["reason"]})
    document = result["json"]
    scenarios = document.get("scenarios") or {}
    if scenarios.get("result") != "actual":
        return _phase("commercial_dry_run", "unavailable", {"reason": scenarios.get("reason", "scenarios_not_actual")})
    rows = scenarios.get("rows") or []
    replay_clean = all(row.get("replay_equal") for row in rows)
    live_clean = all(not row.get("sequence_issues") and not row.get("live_authority_violations") for row in rows)
    if not rows or not replay_clean or not live_clean:
        return _phase(
            "commercial_dry_run", "blocked",
            {"reason": "replay_mismatch_or_live_authority_violation", "row_count": len(rows), "replay_clean": replay_clean, "live_clean": live_clean},
        )
    summary_rows = [
        {"scenario": row["scenario"], "achievable_stage": row["achievable_stage"], "promoted_to_launch": row["promoted_to_launch"], "blockers": row["blockers"]}
        for row in rows
    ]
    return _phase("commercial_dry_run", "passed", {"row_count": len(rows), "rows": summary_rows})


# ---------------------------------------------------------------------------
# Phase 4: trustos_export
# ---------------------------------------------------------------------------


def trustos_export(dry_run_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not dry_run_rows:
        return _phase("trustos_export", "not_run", {"reason": "no_commercial_dry_run_rows"})
    try:
        from backend.workspaces.client_workspace import ClientWorkspace
        from backend.workspaces.registry import WorkspaceRegistry
        from evaluation.trustos.client_workspace_isolation import (
            ClientWorkspaceExportError,
            check_workspace_leakage,
            export_client_evidence,
        )
    except ImportError as exc:
        return _phase("trustos_export", "unavailable", {"reason": f"{type(exc).__name__}: {exc}"})

    with tempfile.TemporaryDirectory(prefix="marketos_dogfood_workspace_registry_") as tmp:
        registry = WorkspaceRegistry(str(Path(tmp) / "workspaces.json"))
        exports: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        for row in dry_run_rows:
            workspace_id = f"dogfood-{row['scenario']}"
            promoted = bool(row["promoted_to_launch"])
            payload = {
                "workspace_id": workspace_id,
                "status": f"fixture_dry_run_{'promoted' if promoted else 'blocked'}",
                "blockers": list(row["blockers"]),
                "evidence_required": [] if promoted else ["resolve the listed blockers with real evidence"],
                "approvals_required": [] if promoted else ["human review"],
                "next_actions": ["proceed to human review before any live action"] if promoted else ["provide missing evidence and rerun the dry-run lifecycle"],
            }
            leakage = check_workspace_leakage(payload, client_safe=True)
            if leakage:
                blocked.append({"workspace_id": workspace_id, "leakage": [item.to_dict() for item in leakage]})
                continue
            workspace = registry.register(ClientWorkspace(workspace_id=workspace_id, name=workspace_id, workspace_type="dry_run", mode="internal_own_store", dry_run_default=True))
            try:
                exported = export_client_evidence(
                    workspace=workspace, registry=registry, provenance="fixture://operator-dogfood-readiness-bridge",
                    evidence_state="present", payload=payload,
                )
            except ClientWorkspaceExportError as exc:
                blocked.append({"workspace_id": workspace_id, "reason": exc.code})
                continue
            exports.append({"workspace_id": workspace_id, "fingerprint": exported.fingerprint, "redaction_status": exported.redaction_status})

    if blocked:
        return _phase("trustos_export", "blocked", {"blocked": blocked, "exported_count": len(exports)})
    return _phase("trustos_export", "passed", {"exported_count": len(exports), "exports": exports})


# ---------------------------------------------------------------------------
# Phase 5: sanitized_handoff
# ---------------------------------------------------------------------------


def _next_action(overall: str) -> str:
    return {
        "passed": "Review the sanitized handoff below and proceed to human approval before any live action.",
        "not_run": "One or more phases were skipped by request; rerun without --skip-* for a complete readiness picture.",
        "ci_unavailable": "No executed CI evidence is available in this environment; this is informational and does not block a local dogfood pass.",
        "unavailable": "Install or restore the missing tool/module named in the relevant phase's detail, then rerun.",
        "blocked": "Resolve the blockers listed in the relevant phase's detail (see 'blocked'/'conflicts'/'mutation_flags'), then rerun.",
        "malformed": "Inspect the malformed phase's 'reason' field; the underlying script or its output shape may have changed.",
    }[overall]


def sanitized_handoff(repo: Path, phases: list[dict[str, Any]]) -> dict[str, Any]:
    """Assemble the final operator-facing report.

    This is explicitly an *operator*-facing handoff, not a client-facing
    export -- it legitimately names the local checkout path, branch, and
    tool versions, none of which TrustOS's client-safe export boundary
    would ever allow through (verified directly: running this report's own
    assembled content through check_workspace_leakage(client_safe=True)
    flags "repository" and "coderos.target_repo" as filesystem-path
    leakage, which is that check working exactly as designed for a
    *client* export -- applying it here as well would be scope-confused,
    not "defense in depth"). Client-safe sanitization already happened
    where it actually matters: trustos_export() ran the real
    check_workspace_leakage()/export_client_evidence() boundary against
    the one payload this bridge ever considers exporting to a client.

    This report's own safety property is structural rather than a second
    checked boundary: every field below is hand-selected from already
    -parsed JSON; raw subprocess stdout/stderr is never carried forward
    anywhere in this module, so there is no path for secret-shaped or
    provider-raw content to reach this report undetected in the first
    place.
    """
    overall = max((item["classification"] for item in phases), key=lambda item: _SEVERITY[item])
    return {
        "schema": SCHEMA,
        "audience": "operator_internal",
        "repository": str(repo),
        "dry_run": True,
        "live_actions_taken": False,
        "network_calls": False,
        "mutated": False,
        "phases": phases,
        "overall_classification": overall,
        "next_action": _next_action(overall),
        "rollback": "This workflow is read-only and dry-run only; no files were modified and no live action was taken. The TrustOS export phase's workspace registry is a per-run temporary file, already deleted. No repository rollback is required.",
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run(repo: Path, *, skip_quality_gate: bool = False, skip_commercial: bool = False) -> dict[str, Any]:
    phases: list[dict[str, Any]] = []

    state_phase = state_collision_check(repo)
    phases.append(state_phase)
    if state_phase["classification"] in {"blocked", "malformed"}:
        return sanitized_handoff(repo, phases)

    phases.append(readiness_preflight(repo, skip_quality_gate=skip_quality_gate))

    if skip_commercial:
        phases.append(_phase("commercial_dry_run", "not_run", {"reason": "--skip-commercial"}))
        phases.append(_phase("trustos_export", "not_run", {"reason": "commercial_dry_run_skipped"}))
        return sanitized_handoff(repo, phases)

    dry_run_phase = commercial_dry_run(repo)
    phases.append(dry_run_phase)
    rows = dry_run_phase["detail"].get("rows", [])
    phases.append(trustos_export(rows))

    return sanitized_handoff(repo, phases)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--skip-quality-gate", action="store_true", help="skip the informational local-quality-gate sub-check")
    parser.add_argument("--skip-commercial", action="store_true", help="skip the commercial dry-run + TrustOS export phases")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    report = run(args.repo.resolve(), skip_quality_gate=args.skip_quality_gate, skip_commercial=args.skip_commercial)
    if args.markdown:
        lines = [f"# Operator dogfood readiness -- {report['overall_classification']}", "", f"Next action: {report['next_action']}", "", "## Phases"]
        for phase in report.get("phases", []):
            lines.append(f"- **{phase['phase']}**: `{phase['classification']}`")
        print("\n".join(lines))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["overall_classification"] in {"passed", "not_run", "ci_unavailable"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

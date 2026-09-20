"""Complete AI-chat execution bundle: prepare -> admit -> select -> execute ->
evaluate -> handoff -> pr.

This module does not create a second context snapshot, quality gate,
readiness authority, event system, or CoderOS runtime. It is a thin
orchestrator over the authorities that already exist:

  * #252 ``MarketOS.AIContext.v1`` snapshot -- consumed by reference
    (``prepare`` requires its ``replay_hash``, never recomputes it).
  * ``scripts.ai.worktree_safety`` (``MarketOS.WorktreeSafety.v1``) -- the
    ``admit`` phase.
  * ``scripts.ai.select_tests`` -- the ``select`` phase.
  * ``scripts.ai.agent_output_eval`` (``MarketOS.AgentEval.v1``) -- the
    ``evaluate`` phase.
  * ``scripts.ai.operator_task_packet`` (``MarketOS.AITask.v1`` /
    ``MarketOS.AIResume.v1``) -- ``prepare`` and ``handoff``.

The only genuinely new surface is the ``execute`` phase's allowlisted,
non-shell command runner (``MarketOS.AIExecutionBundle.v1`` is an explicitly
versioned subordinate artifact that packages the above phase outputs
together -- it does not redefine any of their schemas).

Public pattern credit (concepts only; nothing vendored):
  * OpenHands (github.com/All-Hands-AI/OpenHands, MIT) -- resume from a
    stored, replayable conversation/action state was the model for
    ``handoff``'s resumable bundle.
  * Aider (github.com/Aider-AI/aider, Apache-2.0) -- bounding repository
    context to files actually in scope shaped ``select``'s reuse of
    ``select_tests.select``.
  * SWE-agent (github.com/SWE-agent/SWE-agent, MIT) -- separating an agent's
    *claim* from independent *evaluation* of that claim shaped
    ``evaluate``'s reuse of ``agent_output_eval``.
  * Open Policy Agent (github.com/open-policy-agent/opa, Apache-2.0) --
    default-deny allowlisting shaped ``validate_argv``'s fail-closed design.
  * OpenTelemetry (github.com/open-telemetry/opentelemetry-python,
    Apache-2.0) -- a bounded, closed status vocabulary per unit of work
    shaped ``COMMAND_CLASSES``.
  * OpenLineage (github.com/OpenLineage/OpenLineage, Apache-2.0) --
    producer/job/run identity shaped this module's
    ``{agent_id, lane, worktree, head_sha}`` identity fields.
  * reproducible-builds.org (Apache-2.0-licensed tooling in that project) --
    recording the exact argv executed, not a human paraphrase, shaped
    ``run_allowlisted``'s ``argv`` field.
"""
from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.ai import agent_output_eval, select_tests, worktree_safety
from scripts.ai.operator_task_packet import (
    SECRET_SHAPED,
    _normalize_path,
    build_resume_packet,
    validate_packet,
)

SCHEMA = "MarketOS.AIExecutionBundle.v1"
PHASES = ("prepare", "admit", "select", "execute", "evaluate", "handoff", "pr")

# The complete, closed classification vocabulary for one executed (or not
# executed) command. Distinct from operator_task_packet.EVIDENCE_CLASSES
# (which classifies a whole packet's evidence, not one command) -- the two
# vocabularies are related but not the same closed set, so they are kept
# separate rather than silently unioned.
COMMAND_CLASSES = frozenset(
    {"executed", "passed", "failed", "unavailable", "not_run", "skipped", "malformed", "timed_out", "ci_unavailable"}
)

ALLOWLISTED_EXECUTABLES = frozenset({"python3", "python", "pytest", "ruff"})
ALLOWLISTED_MODULES = frozenset({"pytest", "compileall", "ruff", "scripts.ai.select_tests", "scripts.ai.session_finish"})
ALLOWLISTED_GIT_SUBCOMMANDS = frozenset({("diff", "--check"), ("status", "--porcelain"), ("rev-parse", "HEAD")})
DENYLIST_PATTERN = re.compile(
    r"(?i)(rm\s+-rf|--force\b|force-push|reset\s+--hard|credentials?/|\.env\b|curl\s|wget\s|[|;&`]|\$\()"
)
MAX_OUTPUT_CHARS = 20_000


class ExecutionBundleError(ValueError):
    """Fail-closed execution-bundle validation error."""


# ---------------------------------------------------------------------------
# Phase 1: prepare
# ---------------------------------------------------------------------------


def prepare(snapshot: Mapping[str, Any], task_packet_raw: Mapping[str, Any]) -> dict[str, Any]:
    """Admit a #252 snapshot by reference and validate the task packet against it."""
    if not isinstance(snapshot, Mapping) or snapshot.get("schema") != "MarketOS.AIContext.v1":
        raise ExecutionBundleError("prepare requires a MarketOS.AIContext.v1 snapshot")
    replay_hash = snapshot.get("replay_hash")
    if not replay_hash:
        raise ExecutionBundleError("snapshot is missing replay_hash")
    task_packet = validate_packet(dict(task_packet_raw))
    snapshot_refs = {str(snapshot.get("HEAD") or "").lower(), str(snapshot.get("origin_main") or "").lower()}
    warnings: list[str] = []
    if task_packet["base_sha"] not in snapshot_refs and any(snapshot_refs):
        warnings.append("task_packet_base_sha_not_in_snapshot")
    return {
        "phase": "prepare",
        "schema": SCHEMA,
        "task_packet": task_packet,
        "context_snapshot_replay_hash": replay_hash,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Phase 2: admit
# ---------------------------------------------------------------------------


def admit(
    root: Path,
    task_packet: Mapping[str, Any],
    *,
    other_pr_paths: dict[str, list[str]] | None = None,
    allowed_roots: list[str] | None = None,
    expected_branch: str | None = None,
) -> dict[str, Any]:
    document, code = worktree_safety.evaluate_safety(
        root,
        expected_branch=expected_branch,
        allowed_scope=list(task_packet.get("allowed_scope") or []),
        allowed_roots=allowed_roots,
        other_pr_paths=other_pr_paths,
    )
    return {"phase": "admit", "admitted": code == 0, "document": document}


# ---------------------------------------------------------------------------
# Phase 3: select
# ---------------------------------------------------------------------------


def select(task_packet: Mapping[str, Any]) -> dict[str, Any]:
    result = select_tests.select(list(task_packet.get("allowed_scope") or []))
    return {"phase": "select", "result": result}


# ---------------------------------------------------------------------------
# Phase 4: execute -- the one genuinely new, safety-critical surface
# ---------------------------------------------------------------------------


def validate_argv(argv: Sequence[str]) -> dict[str, Any]:
    """Fail-closed allowlist check. Returns {"classification": "ok"|"malformed", "reason"}."""
    if not argv or not all(isinstance(item, str) for item in argv):
        return {"classification": "malformed", "reason": "argv_must_be_a_nonempty_list_of_strings"}
    joined = " ".join(argv)
    if DENYLIST_PATTERN.search(joined):
        return {"classification": "malformed", "reason": "denylisted_pattern"}
    executable = argv[0]
    if executable != Path(executable).name:
        # argv[0] carries a path component (e.g. "/tmp/evil/git",
        # "./git", "..\\evil\\python3.exe"). The allowlist below only ever
        # checks a bare command name -- if this weren't rejected here, a
        # caller could pass an absolute/relative path to an
        # attacker-controlled binary merely *named* like an allowlisted
        # one, which would pass the basename check yet be the exact
        # string subprocess.run(argv, shell=False) later executes.
        # Requiring a bare name forces PATH-based resolution, so what was
        # validated is exactly what's run.
        return {"classification": "malformed", "reason": "executable_must_be_a_bare_command_name"}
    if executable in {"python", "python3"}:
        if len(argv) >= 3 and argv[1] == "-m" and argv[2] in ALLOWLISTED_MODULES:
            return {"classification": "ok"}
        return {"classification": "malformed", "reason": "module_not_allowlisted"}
    if executable == "git":
        if tuple(argv[1:]) in ALLOWLISTED_GIT_SUBCOMMANDS:
            return {"classification": "ok"}
        return {"classification": "malformed", "reason": "git_subcommand_not_allowlisted"}
    if executable in ALLOWLISTED_EXECUTABLES:
        return {"classification": "ok"}
    return {"classification": "malformed", "reason": "executable_not_allowlisted"}


def assert_valid_test_command(command: str) -> list[str]:
    """Parse a selected-test command string and reject anything not allowlisted."""
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise ExecutionBundleError(f"unparseable command: {command!r}") from exc
    verdict = validate_argv(argv)
    if verdict["classification"] != "ok":
        raise ExecutionBundleError(f"command not allowlisted ({verdict['reason']}): {command!r}")
    return argv


def _redact_output(text: str) -> str:
    if SECRET_SHAPED.search(text):
        return "[redacted: secret-shaped output]"
    return text[:MAX_OUTPUT_CHARS]


def _resolve_execution_argv(argv: Sequence[str]) -> list[str]:
    """Resolve a missing Python shim without weakening command validation.

    The command is validated before this helper runs.  On Windows, ``python3``
    is commonly absent even when the interpreter running this process is
    available.  Falling back only to that trusted interpreter keeps the
    allowlist portable while avoiding PATH-dependent false ``unavailable``
    results.  No caller-provided path is ever resolved here.
    """
    resolved = list(argv)
    # Windows App Execution Aliases can make ``shutil.which("python3")``
    # return a Microsoft Store shim that exits with 9009 instead of launching
    # Python.  Prefer the already-running trusted interpreter for that exact
    # portable command spelling.
    if resolved and resolved[0] == "python3" and sys.platform == "win32":
        resolved[0] = sys.executable
    elif resolved and resolved[0] in {"python", "python3"} and shutil.which(resolved[0]) is None:
        resolved[0] = sys.executable
    return resolved


def render_command(argv: Sequence[str]) -> dict[str, Any]:
    """One canonical argv plus informational POSIX/PowerShell renderings.

    Never executed by this function -- purely for a human (or another
    agent) to copy-paste.
    """
    posix = shlex.join(argv)
    powershell = " ".join(_powershell_quote(item) for item in argv)
    return {"argv": list(argv), "posix": posix, "powershell": powershell}


def _powershell_quote(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:=-]+", value):
        return value
    return "'" + value.replace("'", "''") + "'"


def run_allowlisted(
    command: str | Sequence[str],
    *,
    cwd: Path | None = None,
    timeout_s: float = 120.0,
    ci_only: bool = False,
    skip: bool = False,
) -> dict[str, Any]:
    """Run one command through the allowlist, or classify why it didn't run.

    Never uses ``shell=True``; the executed argv is always a list, never a
    shell string. Output is redacted for secret-shaped content and capped.
    """
    argv = list(command) if isinstance(command, (list, tuple)) else None
    command_text = shlex.join(argv) if argv is not None else str(command)
    record: dict[str, Any] = {"command": command_text}

    if skip:
        record.update({"argv": argv, "classification": "skipped", "reason": "caller_requested_skip"})
        return record

    if argv is None:
        try:
            argv = shlex.split(str(command))
        except ValueError:
            record.update({"argv": None, "classification": "malformed", "reason": "unparseable_command"})
            return record
    record["argv"] = argv

    verdict = validate_argv(argv)
    if verdict["classification"] == "malformed":
        record.update({"classification": "malformed", "reason": verdict["reason"]})
        return record

    if ci_only:
        record.update({"classification": "ci_unavailable", "reason": "ci_only_command_has_no_local_runner"})
        return record

    execution_argv = _resolve_execution_argv(argv)
    try:
        completed = subprocess.run(
            execution_argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout_s, cwd=str(cwd) if cwd else None, shell=False, check=False,
        )
    except FileNotFoundError:
        record.update({"classification": "unavailable", "reason": "executable_not_found"})
        return record
    except subprocess.TimeoutExpired:
        record.update({"classification": "timed_out", "reason": f"exceeded {timeout_s}s"})
        return record

    record.update({
        "classification": "passed" if completed.returncode == 0 else "failed",
        "exit_code": completed.returncode,
        "executed_argv": execution_argv,
        "stdout": _redact_output(completed.stdout or ""),
        "stderr": _redact_output(completed.stderr or ""),
    })
    return record


def execute(
    commands: Sequence[str | Sequence[str] | Mapping[str, Any]],
    *,
    cwd: Path | None = None,
    timeout_s: float = 120.0,
    skip_commands: set[str] | None = None,
) -> dict[str, Any]:
    skip_commands = skip_commands or set()
    results: list[dict[str, Any]] = []
    for item in commands:
        if isinstance(item, Mapping):
            command = item.get("argv") or item.get("command")
            ci_only = bool(item.get("ci_only"))
        else:
            command = item
            ci_only = False
        text = shlex.join(command) if isinstance(command, (list, tuple)) else str(command)
        results.append(run_allowlisted(command, cwd=cwd, timeout_s=timeout_s, ci_only=ci_only, skip=text in skip_commands))
    return {
        "phase": "execute",
        "results": results,
        "classifications": _merge_classifications(results),
    }


# Most-severe-wins ordering for collapsing duplicate commands in a batch
# into a single classifications map: a genuine "failed" must never be
# silently hidden behind a later "passed" for the same command string --
# this map feeds agent_output_eval's actual_check_classifications, whose
# whole purpose is catching exactly that kind of relabeling.
_CLASSIFICATION_SEVERITY = {
    "failed": 0,
    "timed_out": 1,
    "malformed": 2,
    "unavailable": 3,
    "not_run": 4,
    "ci_unavailable": 5,
    "skipped": 6,
    "passed": 7,
    "executed": 8,
}


def _merge_classifications(results: list[dict[str, Any]]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for item in results:
        name, classification = item["command"], item["classification"]
        current = merged.get(name)
        if current is None or _CLASSIFICATION_SEVERITY.get(classification, 99) < _CLASSIFICATION_SEVERITY.get(current, 99):
            merged[name] = classification
    return merged


# COMMAND_CLASSES (this module's per-command execution outcome) and
# operator_task_packet.EVIDENCE_CLASSES (a resume packet's per-test
# evidence_classification) are deliberately separate closed vocabularies --
# one describes what actually happened when a command ran, the other
# describes the epistemic status of a piece of evidence. They are not the
# same set ("passed"/"executed"/"skipped"/"timed_out" have no EVIDENCE_CLASSES
# equivalent), so a caller cannot pass one where the other is required.
# This is the one narrow, explicit translation between them -- without it,
# execute()'s real output could never be recorded in a handoff()'s
# tests_already_run at all.
_COMMAND_TO_EVIDENCE_CLASSIFICATION = {
    "executed": "actual",
    "passed": "actual",
    "failed": "failed",
    "unavailable": "unavailable",
    "not_run": "not_run",
    "skipped": "not_run",
    "malformed": "malformed",
    "timed_out": "blocked",
    "ci_unavailable": "ci_unavailable",
}


def to_evidence_classification(command_classification: str) -> str:
    """Translate one execute() COMMAND_CLASSES value into the
    operator_task_packet.EVIDENCE_CLASSES value a resume packet's
    tests_already_run entry requires. Raises on an unrecognized input
    rather than guessing."""
    try:
        return _COMMAND_TO_EVIDENCE_CLASSIFICATION[command_classification]
    except KeyError:
        raise ExecutionBundleError(f"unknown command classification: {command_classification!r}") from None


# ---------------------------------------------------------------------------
# Phase 5: evaluate
# ---------------------------------------------------------------------------


def evaluate(report: Mapping[str, Any], task_packet: Mapping[str, Any], *, commands: list[str] | None = None) -> dict[str, Any]:
    document, code = agent_output_eval.evaluate_report(dict(report), dict(task_packet), commands=commands)
    return {"phase": "evaluate", "document": document, "passed": code == 0}


# ---------------------------------------------------------------------------
# Phase 6: handoff
# ---------------------------------------------------------------------------


def handoff(
    task_packet: Mapping[str, Any],
    *,
    context_snapshot_replay_hash: str,
    worktree: str,
    branch: str,
    head_sha: str,
    base_sha: str,
    changed_files: list[str],
    tests_already_run: list[dict[str, str]],
    tests_still_required: list[str],
    open_blockers: list[str],
    pending_decisions: list[str],
    public_sources_inspected: list[str],
    claims_not_yet_proven: list[str],
    next_action: str,
    current_head_sha: str | None = None,
) -> dict[str, Any]:
    resume = build_resume_packet(
        dict(task_packet),
        context_snapshot_replay_hash=context_snapshot_replay_hash,
        worktree=worktree,
        branch=branch,
        head_sha=head_sha,
        base_sha=base_sha,
        changed_files=changed_files,
        tests_already_run=tests_already_run,
        tests_still_required=tests_still_required,
        open_blockers=open_blockers,
        pending_decisions=pending_decisions,
        public_sources_inspected=public_sources_inspected,
        claims_not_yet_proven=claims_not_yet_proven,
        next_action=next_action,
        current_head_sha=current_head_sha,
    )
    manifest = [render_command(shlex.split(cmd)) for cmd in tests_still_required]
    return {
        "phase": "handoff",
        "resume": resume,
        "command_manifest": manifest,
        "human_readable": _render_human_handoff(task_packet, resume, manifest),
    }


def _render_human_handoff(task_packet: Mapping[str, Any], resume: Mapping[str, Any], manifest: list[dict[str, Any]]) -> str:
    lines = [
        f"AGENT_ID: {task_packet.get('agent_id')}",
        f"LANE_ID: {task_packet.get('lane')}",
        f"WORKTREE: {resume['worktree']}",
        f"BRANCH: {resume['branch']}",
        f"HEAD: {resume['head_sha']}",
        f"BASE: {resume['base_sha']}",
        f"WARNINGS: {', '.join(resume['warnings']) or 'none'}",
        f"OPEN BLOCKERS: {', '.join(resume['open_blockers']) or 'none'}",
        f"NEXT ACTION: {resume['next_action']}",
        "TESTS STILL REQUIRED (copy-paste; not auto-executed):",
    ]
    for entry in manifest:
        lines.append(f"  posix:      {entry['posix']}")
        lines.append(f"  powershell: {entry['powershell']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase 7: pr
# ---------------------------------------------------------------------------


def pr_check(task_packet: Mapping[str, Any], *, pr_reference: str, pr_changed_files: Sequence[str]) -> dict[str, Any]:
    """Validate a PR reference exists and its changed paths match task scope.

    Makes no network call itself -- ``pr_changed_files`` is caller-supplied
    (e.g. from an already-completed ``gh pr diff`` or GitHub API read),
    matching this bundle's local-first design.
    """
    if not pr_reference:
        return {"phase": "pr", "valid": False, "reason": "missing_pr_reference", "out_of_scope_files": []}
    allowed = list(task_packet.get("allowed_scope") or [])
    normalized = [_normalize_path(str(item)) for item in pr_changed_files]
    out_of_scope = [item for item in normalized if item and not agent_output_eval._in_scope(item, allowed)]
    return {
        "phase": "pr",
        "pr_reference": pr_reference,
        "changed_files": normalized,
        "out_of_scope_files": out_of_scope,
        "valid": not out_of_scope,
    }


__all__ = [
    "SCHEMA",
    "PHASES",
    "COMMAND_CLASSES",
    "ExecutionBundleError",
    "prepare",
    "admit",
    "select",
    "validate_argv",
    "assert_valid_test_command",
    "render_command",
    "run_allowlisted",
    "execute",
    "to_evidence_classification",
    "evaluate",
    "handoff",
    "pr_check",
]

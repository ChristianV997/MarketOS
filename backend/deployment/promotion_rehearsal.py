"""backend.deployment.promotion_rehearsal -- Composed deployment promotion rehearsal
engine for MarketOS local-to-private-staging readiness.

Composes existing authorities without duplicating or replacing them:
- Environment Contract (backend.deployment.environment_contract)
- Failure Diagnostics (backend.deployment.diagnostics)
- High-Value-Path Harness (scripts.run_high_value_path_harness)
- Container Hardening static checks (Dockerfile & docker-compose)
- CoderOS status and CI evidence classification

Supports 6 environments:
1. local_dry_run
2. isolated_worktree
3. private_staging
4. authenticated_operator
5. public_client
6. live_provider_blocked
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.deployment.environment_contract import (
    DATABASE_KEYS,
    INSECURE_PASSWORDS,
    LIVE_PROVIDER_CREDENTIAL_KEYS,
    MUTATION_FLAG_KEYS,
    is_truthy,
    validate_environment,
)
from backend.deployment.diagnostics import run_all_diagnostics

VALID_PROMOTION_ENVIRONMENTS = frozenset({
    "local_dry_run",
    "isolated_worktree",
    "private_staging",
    "authenticated_operator",
    "public_client",
    "live_provider_blocked",
})

VALID_READINESS_STATES = frozenset({
    "passed",
    "failed",
    "unavailable",
    "not_run",
    "collection_failed",
    "blocked",
    "malformed",
    "timed_out",
    "ci_unavailable",
})

EVIDENCE_CLASSES = frozenset({
    "actual_executed",
    "fixture",
    "manual",
    "derived",
    "simulated_or_planned",
    "unavailable",
    "ci_unavailable",
})

_SECRET_SHAPED_RE = re.compile(
    r"(?is)("
    r"-----begin (?:rsa |ec |dsa |openssh )?private key-----"
    r"|ghp_[A-Za-z0-9_]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-(?:live|test)?-?[A-Za-z0-9]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|bearer [A-Za-z0-9._-]{10,}"
    r"|://[^:]+:[^@]+@"
    r")"
)
_SENSITIVE_KEY_RE = re.compile(r"(?i)(password|secret|token|api_key|private_key)")


def redact_secrets(val: Any, key_name: str | None = None) -> Any:
    """Recursively redacts secret-shaped strings or values associated with sensitive keys."""
    if key_name and _SENSITIVE_KEY_RE.search(key_name) and isinstance(val, str) and val:
        return "[REDACTED]"
    if isinstance(val, dict):
        return {k: redact_secrets(v, key_name=str(k)) for k, v in val.items()}
    elif isinstance(val, (list, tuple)):
        return [redact_secrets(item) for item in val]
    elif isinstance(val, str):
        if "://" in val and "@" in val:
            return "[REDACTED]"
        if _SECRET_SHAPED_RE.search(val):
            return _SECRET_SHAPED_RE.sub("[REDACTED]", val)
        return val
    return val


def get_repository_identity(root_path: Path | None = None) -> dict[str, Any]:
    """Inspect git repository identity and worktree state without mutating anything."""
    base = root_path or ROOT
    sha = "unknown"
    branch = "unknown"
    dirty_files: list[str] = []
    is_worktree = False

    try:
        res_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(base),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if res_sha.returncode == 0:
            sha = res_sha.stdout.strip()

        res_branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(base),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if res_branch.returncode == 0:
            branch = res_branch.stdout.strip()

        res_status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(base),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if res_status.returncode == 0:
            dirty_files = [line.strip() for line in res_status.stdout.splitlines() if line.strip()]

        # Worktree check
        git_path = base / ".git"
        if git_path.is_file():  # in worktrees, .git is a file referencing the main gitdir
            is_worktree = True
    except Exception:
        pass

    return {
        "commit_sha": sha,
        "branch": branch,
        "worktree_path": str(base),
        "is_isolated_worktree": is_worktree,
        "clean": len(dirty_files) == 0,
        "dirty_file_count": len(dirty_files),
    }


def get_runtime_versions() -> dict[str, Any]:
    """Capture sanitized runtime versions without calling live networks."""
    node_ver = "unavailable"
    docker_ver = "unavailable"

    if shutil.which("node"):
        try:
            res = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=3, check=False)
            if res.returncode == 0:
                node_ver = res.stdout.strip()
        except Exception:
            pass

    if shutil.which("docker"):
        try:
            res = subprocess.run(["docker", "--version"], capture_output=True, text=True, timeout=3, check=False)
            if res.returncode == 0:
                docker_ver = res.stdout.strip()
        except Exception:
            pass

    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "node": node_ver,
        "docker": docker_ver,
    }


def check_container_static_hardening(dockerfile_path: Path | None = None) -> dict[str, Any]:
    """Inspect Dockerfile and compose for container hardening standards."""
    df = dockerfile_path or (ROOT / "Dockerfile")
    if not df.exists():
        return {
            "status": "unavailable",
            "non_root_user": False,
            "healthcheck_present": False,
            "stopsignal_present": False,
            "port_3000": False,
        }

    content = df.read_text(encoding="utf-8")
    has_user = bool(re.search(r"^\s*USER\s+(?!root\b)[a-zA-Z0-9_-]+", content, re.MULTILINE))
    has_health = bool(re.search(r"^\s*HEALTHCHECK\b", content, re.MULTILINE))
    has_stopsignal = bool(re.search(r"^\s*STOPSIGNAL\s+(SIGTERM|SIGINT)", content, re.MULTILINE))
    has_port_3000 = "3000" in content

    return {
        "status": "passed" if (has_user and has_health and has_stopsignal and has_port_3000) else "failed",
        "non_root_user": has_user,
        "healthcheck_present": has_health,
        "stopsignal_present": has_stopsignal,
        "port_3000": has_port_3000,
    }


def inspect_coderos_status(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Inspect CoderOS availability and mode honestly without importing into runtime."""
    env = os.environ if environ is None else environ
    coderos_root = env.get("CODEROS_ROOT", "")
    mode = env.get("MARKETOS_AGENT_MODE", "plan_only")

    agents_dir = ROOT / ".agents"
    has_agents = agents_dir.is_dir()

    is_available = bool(coderos_root and Path(coderos_root).exists()) or has_agents

    return {
        "status": "available" if is_available else "unavailable",
        "mode": mode,
        "coderos_root_configured": bool(coderos_root),
        "agents_scaffold_present": has_agents,
        "runtime_imports_allowed": False,  # Architectural invariant
    }


def classify_ci_evidence(
    ci_status: str | None = None,
    total_steps: int = 0,
    runners_active: int = 0,
    logs_available: bool = True,
) -> dict[str, Any]:
    """Classify CI evidence state fail-closed. Zero-step CI is never passed."""
    if total_steps == 0 or runners_active == 0:
        state = "ci_unavailable"
        reason = "CI runners are inactive or the job reported zero executed steps."
    elif ci_status == "passed":
        if logs_available:
            state = "passed"
            reason = "All pipeline steps verified with accessible audit logs."
        else:
            state = "ci_unavailable"
            reason = "CI steps executed but success cannot be verified because logs are inaccessible."
    elif ci_status == "failed":
        state = "failed"
        reason = "One or more executed CI validation checks failed; log availability does not erase the failure."
    elif ci_status == "timed_out":
        state = "timed_out"
        reason = "An executed CI validation check timed out."
    else:
        state = "ci_unavailable"
        reason = f"CI status '{ci_status}' cannot be promoted without verified logs."

    return {
        "state": state,
        "total_steps": total_steps,
        "runners_active": runners_active,
        "logs_available": logs_available,
        "classification_reason": reason,
    }


_GITHUB_ACTIONS_CONCLUSION_TO_CI_STATUS = {
    "success": "passed",
    "failure": "failed",
    "timed_out": "timed_out",
}

# GitHub only ever sets a job's conclusion once status == "completed"; any
# other status (queued/in_progress/waiting) means the run has not finished
# and any conclusion value present is not yet trustworthy evidence.
_GITHUB_ACTIONS_INCOMPLETE_STATUSES = frozenset({"queued", "in_progress", "waiting", "requested", "pending"})


def _github_actions_unavailable(reason: str, *, pending: bool = False) -> dict[str, Any]:
    return {
        "state": "ci_unavailable",
        "total_steps": 0,
        "runners_active": 0,
        "logs_available": False,
        "runner_id": None,
        "steps_executed": 0,
        "runner_assigned": False,
        "pending": pending,
        "classification_reason": reason,
    }


def classify_github_actions_job(job: Mapping[str, Any] | None, *, logs_available: bool = False) -> dict[str, Any]:
    """Classify a real GitHub Actions job response (the exact shape the
    Jobs API returns: ``status``, ``runner_id``, and a ``steps`` list)
    fail-closed.

    A pure adapter over ``classify_ci_evidence`` -- it derives that
    function's abstract ``total_steps``/``runners_active``/``ci_status``
    parameters from the job's real fields and delegates to it, rather than
    creating a second CI-admissibility authority. ``runner_id == 0`` (the
    value GitHub reports when a workflow never actually started, before a
    runner was ever assigned), a negative or otherwise implausible
    ``runner_id``, and an empty/missing ``steps`` list are all treated as
    no execution occurred, never as zero passing steps. ``job=None`` (the
    run/job could not be fetched at all -- API error, no permission, or
    the run does not exist) and a non-mapping ``job`` both fail closed to
    ``ci_unavailable`` rather than raising or being silently ignored.

    A job whose ``status`` is not yet ``"completed"`` (queued/in_progress)
    is distinguished as *pending* (``result["pending"] is True``) rather
    than folded into the same ``ci_unavailable`` a permanently-missing
    runner produces: pending evidence may still arrive, so an
    administrator reading this should re-check later, not treat it as a
    dead end requiring intervention. The classification *state* still
    stays within the existing closed vocabulary (``ci_unavailable`` --
    conservative, since a pending run is not yet admissible evidence
    either); ``pending`` is what makes the two cases distinguishable, per
    the mission's explicit requirement to tell zero-step, executed
    failure, timeout, unavailable logs, pending, and pass apart.

    ``logs_available`` defaults to ``False``: unless a caller explicitly
    confirms it fetched the job's logs, this never assumes they exist --
    matching ``classify_ci_evidence``'s existing rule that an executed
    "success" conclusion without verified logs is not admissible evidence.
    """
    if job is None:
        return _github_actions_unavailable(
            "job_unavailable: the GitHub Actions job could not be fetched (missing run, no access, or an API error)."
        )
    if not isinstance(job, Mapping):
        return _github_actions_unavailable(f"job_malformed: expected a GitHub Actions job mapping, got {type(job).__name__}.")

    status = str(job.get("status", "") or "").strip().lower()
    if status in _GITHUB_ACTIONS_INCOMPLETE_STATUSES:
        return _github_actions_unavailable(
            f"job_pending: workflow status is '{status}' -- not yet completed, so any conclusion present is not admissible evidence.",
            pending=True,
        )

    steps = job.get("steps")
    steps_list = steps if isinstance(steps, list) else []
    steps_executed = len(steps_list)

    runner_id_raw = job.get("runner_id", 0)
    runner_id = int(runner_id_raw) if isinstance(runner_id_raw, (int, float)) and not isinstance(runner_id_raw, bool) else 0
    if runner_id < 0:
        # GitHub never reports a negative runner_id for real evidence;
        # treat an implausible value the same as "never assigned" rather
        # than trusting it as a real, active runner.
        runner_id = 0
    runner_assigned = runner_id != 0

    conclusion = job.get("conclusion")
    ci_status = _GITHUB_ACTIONS_CONCLUSION_TO_CI_STATUS.get(str(conclusion), "ci_unavailable")

    result = classify_ci_evidence(
        ci_status=ci_status,
        total_steps=steps_executed,
        runners_active=1 if runner_assigned else 0,
        logs_available=logs_available,
    )
    result["runner_id"] = runner_id
    result["steps_executed"] = steps_executed
    result["runner_assigned"] = runner_assigned
    result["pending"] = False
    return result


def _harness_status(summary: Mapping[str, Any]) -> str:
    """Reduce the existing harness counts without hiding an executed failure."""
    for status in ("failed", "timed_out", "collection_failed", "malformed", "blocked", "unavailable", "not_run"):
        if int(summary.get(status, 0) or 0) > 0:
            return status
    return "passed" if int(summary.get("total", 0) or 0) > 0 else "not_run"


def _run_high_value_path_harness() -> dict[str, Any]:
    """Execute the bounded offline harness; never synthesize a green result."""
    try:
        from scripts.run_high_value_path_harness import run_harness
    except ModuleNotFoundError:
        return {
            "status": "unavailable",
            "evidence_classification": "unavailable",
            "reason": "high_value_path_harness_unavailable",
            "paths_executed": 0,
            "all_paths_passed": False,
            "bit_identity_confirmed": False,
        }
    try:
        report = run_harness()
    except Exception as exc:  # noqa: BLE001 - classify the executed harness failure
        return {
            "status": "failed",
            "evidence_classification": "actual_executed",
            "reason": f"high_value_path_harness_failed:{type(exc).__name__}",
            "paths_executed": 0,
            "all_paths_passed": False,
            "bit_identity_confirmed": False,
        }
    summary = report.get("summary") if isinstance(report, Mapping) else None
    measurements = report.get("measurements") if isinstance(report, Mapping) else None
    if not isinstance(summary, Mapping) or not isinstance(measurements, list):
        return {
            "status": "malformed",
            "evidence_classification": "actual_executed",
            "reason": "high_value_path_harness_report_malformed",
            "paths_executed": 0,
            "all_paths_passed": False,
            "bit_identity_confirmed": False,
        }
    status = _harness_status(summary)
    replay_rows = [item for item in measurements if isinstance(item, Mapping) and item.get("replay_identity")]
    return {
        "schema": str(report.get("schema", "")),
        "status": status,
        "evidence_classification": "actual_executed",
        "paths_executed": len(measurements),
        "all_paths_passed": status == "passed",
        "bit_identity_confirmed": bool(replay_rows) and all(item.get("repeated_match") is True for item in replay_rows),
        "counts": {key: int(summary.get(key, 0) or 0) for key in ("passed", "failed", "unavailable", "not_run", "blocked", "malformed", "timed_out", "collection_failed", "total")},
    }


def _normalize_harness_results(value: Mapping[str, Any]) -> dict[str, Any]:
    """Accept only the small sanitized harness projection used by callers."""
    status = value.get("status")
    evidence_class = value.get("evidence_classification", "simulated_or_planned")
    if status not in VALID_READINESS_STATES or evidence_class not in EVIDENCE_CLASSES:
        return {
            "status": "malformed",
            "evidence_classification": "simulated_or_planned",
            "reason": "high_value_path_summary_malformed",
            "paths_executed": 0,
            "all_paths_passed": False,
            "bit_identity_confirmed": False,
        }
    if value.get("stale") is True:
        return {
            "status": "unavailable",
            "evidence_classification": evidence_class,
            "reason": "high_value_path_evidence_stale",
            "paths_executed": int(value.get("paths_executed", 0) or 0),
            "all_paths_passed": False,
            "bit_identity_confirmed": False,
        }
    if value.get("partial") is True:
        return {
            "status": "unavailable",
            "evidence_classification": evidence_class,
            "reason": "high_value_path_evidence_incomplete",
            "paths_executed": int(value.get("paths_executed", 0) or 0),
            "all_paths_passed": False,
            "bit_identity_confirmed": False,
        }
    if status == "passed" and value.get("all_paths_passed") is not True:
        status = "malformed"
    return {
        "status": status,
        "evidence_classification": evidence_class,
        "paths_executed": int(value.get("paths_executed", 0) or 0),
        "all_paths_passed": status == "passed",
        "bit_identity_confirmed": bool(value.get("bit_identity_confirmed")),
    }


def _phase1_summary(environ: Mapping[str, str]) -> dict[str, Any]:
    """Embed the canonical Phase 1 report without making it a new authority."""
    try:
        from evaluation.commerce.readiness import build_phase1_readiness

        value = build_phase1_readiness(environ=environ).to_dict()
    except Exception as exc:  # noqa: BLE001 - readiness evidence must fail closed
        return {"status": "unavailable", "reason": f"phase1_report_unavailable:{type(exc).__name__}"}
    deployment = value.get("deployment_readiness", {})
    events = value.get("event_readiness", {})
    return {
        "report_version": value.get("report_version"),
        "status": value.get("overall_status", "unknown"),
        "overall_score": value.get("overall_score"),
        "blocking_gates": list(value.get("blocking_gates", [])),
        "advisory_warnings": list(value.get("advisory_warnings", [])),
        "deployment_status": deployment.get("status", "unknown"),
        "event_status": events.get("status", "unknown"),
        "read_only": bool(value.get("read_only")),
        "mutated": bool(value.get("mutated")),
        "network_calls": bool(value.get("network_calls")),
    }


_OPERATOR_STACK_SCHEMA = "MarketOS.LocalOperatorStack.v1"
_OPERATOR_STACK_DEFAULT_TIMEOUT_S = 60.0


def _operator_stack_surfaces_summary(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract only the sanitized per-endpoint classification from the
    runner's real output -- name/classification/http_status/reason, never
    raw response bytes, and never the runner's own ``logs`` field (a real
    stdout/stderr capture, up to and including process tracebacks), which
    this bundle never emits (see ``test_raw_logs_are_never_emitted_into_
    promotion_bundles``, a pre-existing, still-binding invariant)."""
    surfaces = payload.get("surfaces")
    if not isinstance(surfaces, list):
        return []
    summary: list[dict[str, Any]] = []
    for item in surfaces:
        if not isinstance(item, Mapping):
            continue
        summary.append(
            {
                "name": item.get("name"),
                "plane": item.get("plane"),
                "classification": item.get("classification"),
                "http_status": item.get("http_status"),
                "reason": item.get("reason"),
            }
        )
    return summary


def _operator_stack_evidence(
    *,
    execute: bool = False,
    backend_only: bool = True,
    timeout_s: float = _OPERATOR_STACK_DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Report the existing operator-stack runner's real, bounded evidence
    when it is present on this branch -- never invented, never assumed.

    ``execute=False`` (the default) invokes the runner in its own default
    ``--dry-run`` mode: instant and safe, no process is ever started. This
    still proves the runner's preflight plan is valid without the cost or
    risk of a real subprocess. ``execute=True`` opts into the runner's
    ``--execute`` mode, which starts real fixture-only, loopback-only
    local processes and always cleans them up (that script's own
    documented guarantee, not reimplemented here) -- a caller must ask
    for that cost/risk explicitly; it is never the default for a function
    other code composes into a bundle.

    This never imports the runner as a module (it stays #290's exclusive
    authority) -- only ``subprocess``-invokes its CLI and parses its own
    sanitized JSON output, which is itself already the documented
    contract between this composition and that runner.
    """
    path = ROOT / "scripts" / "run_local_operator_stack.py"
    if not path.is_file():
        return {
            "status": "unavailable",
            "runner_present": False,
            "command": "python scripts/run_local_operator_stack.py --json",
            "reason": "runner_not_on_current_main",
            "network_calls": False,
            "mutated": False,
        }

    argv = [sys.executable, str(path), "--json", "--execute" if execute else "--dry-run"]
    if backend_only:
        argv.append("--backend-only")
    command_text = shlex.join(argv)

    try:
        completed = subprocess.run(
            argv, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout_s, check=False
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "timed_out",
            "runner_present": True,
            "command": command_text,
            "reason": f"operator_stack_exceeded_{int(timeout_s)}s",
            "network_calls": False,
            "mutated": False,
        }
    except OSError as exc:
        return {
            "status": "unavailable",
            "runner_present": True,
            "command": command_text,
            "reason": f"operator_stack_invocation_failed:{type(exc).__name__}",
            "network_calls": False,
            "mutated": False,
        }

    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, ValueError):
        return {
            "status": "malformed",
            "runner_present": True,
            "command": command_text,
            "reason": "operator_stack_output_not_json",
            "exit_code": completed.returncode,
            "network_calls": False,
            "mutated": False,
        }
    if not isinstance(payload, Mapping) or payload.get("schema") != _OPERATOR_STACK_SCHEMA:
        return {
            "status": "malformed",
            "runner_present": True,
            "command": command_text,
            "reason": "operator_stack_output_unexpected_schema",
            "exit_code": completed.returncode,
            "network_calls": False,
            "mutated": False,
        }

    classification = payload.get("classification")
    return {
        "status": classification if isinstance(classification, str) and classification else "malformed",
        "runner_present": True,
        "command": command_text,
        "dry_run": bool(payload.get("dry_run", not execute)),
        "mode": payload.get("mode"),
        "surfaces": _operator_stack_surfaces_summary(payload),
        "network_calls": bool(payload.get("external_network_calls", False)),
        "mutated": bool(payload.get("mutated", False)),
    }


def _event_read_path_evidence(environ: Mapping[str, str]) -> dict[str, Any]:
    """Validate only a bounded local JSONL read path; never emit event payloads."""
    raw_path = str(environ.get("MARKETOS_EVENT_READ_JSONL_PATH", "")).strip()
    if not raw_path:
        return {"status": "unavailable", "reason": "event_read_path_not_configured", "event_count": 0}
    try:
        path = Path(raw_path).resolve()
        artifacts = (ROOT / "artifacts").resolve()
        if path != artifacts and artifacts not in path.parents:
            return {"status": "blocked", "reason": "event_read_path_outside_artifacts", "event_count": 0}
        if not path.is_file():
            return {"status": "unavailable", "reason": "event_read_path_missing", "event_count": 0}
        if path.stat().st_size > 1_048_576:
            return {"status": "malformed", "reason": "event_read_path_too_large", "event_count": 0}
        from backend.events.query_service import load_events_from_jsonl

        events, warnings = load_events_from_jsonl(path)
        if warnings:
            return {"status": "malformed", "reason": "event_read_path_malformed", "event_count": len(events), "warning_count": len(warnings)}
        return {"status": "passed" if events else "not_run", "reason": "canonical_events_available" if events else "event_read_path_empty", "event_count": len(events)}
    except (OSError, ValueError):
        return {"status": "malformed", "reason": "event_read_path_unreadable", "event_count": 0}


def _rollback_evidence(repository: Mapping[str, Any]) -> dict[str, Any]:
    """Identify a prior revision without changing the worktree."""
    current = str(repository.get("commit_sha", ""))
    previous = ""
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD^"], cwd=repository.get("worktree_path"), capture_output=True, text=True, timeout=5, check=False)
        if result.returncode == 0:
            previous = result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {
        "status": "passed" if current and previous else "unavailable",
        "current_revision": current,
        "previous_revision": previous or None,
        "mutation_performed": False,
        "command": "git revert --no-commit <current_revision> (operator-reviewed only)",
    }


@dataclass
class PromotionRehearsalBundle:
    environment: str
    readiness_state: str
    repository: dict[str, Any]
    runtime: dict[str, Any]
    container_hardening: dict[str, Any]
    credential_classification: dict[str, Any]
    live_mutation_guard: dict[str, Any]
    diagnostics_summary: dict[str, Any]
    ci_evidence: dict[str, Any]
    ci_admissibility_diagnostic: dict[str, Any]
    coderos_status: dict[str, Any]
    high_value_path_summary: dict[str, Any]
    phase1_readiness: dict[str, Any]
    operator_stack: dict[str, Any]
    event_read_path: dict[str, Any]
    rollback_evidence: dict[str, Any]
    blockers: list[str] = field(default_factory=list)
    remediations: list[str] = field(default_factory=list)
    safe_next_action: str = ""
    rollback_path: str = ""
    deterministic_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {
            "environment": self.environment,
            "readiness_state": self.readiness_state,
            "repository": self.repository,
            "runtime": self.runtime,
            "container_hardening": self.container_hardening,
            "credential_classification": self.credential_classification,
            "live_mutation_guard": self.live_mutation_guard,
            "diagnostics_summary": self.diagnostics_summary,
            "ci_evidence": self.ci_evidence,
            "ci_admissibility_diagnostic": self.ci_admissibility_diagnostic,
            "coderos_status": self.coderos_status,
            "high_value_path_summary": self.high_value_path_summary,
            "phase1_readiness": self.phase1_readiness,
            "operator_stack": self.operator_stack,
            "event_read_path": self.event_read_path,
            "rollback_evidence": self.rollback_evidence,
            "blockers": list(self.blockers),
            "remediations": list(self.remediations),
            "safe_next_action": self.safe_next_action,
            "rollback_path": self.rollback_path,
            "deterministic_hash": self.deterministic_hash,
        }
        return redact_secrets(d)

    def compute_hash(self) -> str:
        """Compute stable SHA256 over deterministic fields only (excluding timestamps)."""
        deterministic_view = {
            "environment": self.environment,
            "readiness_state": self.readiness_state,
            "commit_sha": self.repository.get("commit_sha", ""),
            "container_hardening": self.container_hardening,
            "credential_classification": self.credential_classification,
            "live_mutation_guard": self.live_mutation_guard,
            "ci_evidence_state": self.ci_evidence.get("state", ""),
            "ci_admissibility_diagnostic_status": self.ci_admissibility_diagnostic.get("status", ""),
            "coderos_status": self.coderos_status.get("status", ""),
            "high_value_path_status": self.high_value_path_summary.get("status", ""),
            "phase1_status": self.phase1_readiness.get("status", ""),
            "operator_stack_status": self.operator_stack.get("status", ""),
            "event_read_path_status": self.event_read_path.get("status", ""),
            "rollback_status": self.rollback_evidence.get("status", ""),
            "blockers": sorted(self.blockers),
        }
        payload = json.dumps(deterministic_view, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def execute_promotion_rehearsal(
    environment: str = "local_dry_run",
    environ: Mapping[str, str] | None = None,
    harness_results: dict[str, Any] | None = None,
    ci_override: dict[str, Any] | None = None,
    github_actions_job: Mapping[str, Any] | None = None,
    logs_available: bool = False,
    dockerfile_path: Path | None = None,
    execute_operator_stack: bool = False,
    operator_stack_backend_only: bool = True,
    operator_stack_timeout_s: float = _OPERATOR_STACK_DEFAULT_TIMEOUT_S,
) -> PromotionRehearsalBundle:
    """Execute complete deployment promotion rehearsal across composed authorities.

    ``github_actions_job``, when supplied, is a real GitHub Actions Jobs
    API response (``{"runner_id": ..., "steps": [...], "conclusion": ...}``)
    classified via ``classify_github_actions_job`` -- it takes precedence
    over the abstract ``ci_override`` shape when both are supplied, since
    it carries more specific, directly-observed evidence. ``logs_available``
    applies only to the ``github_actions_job`` path (``ci_override`` already
    carries its own ``logs_available`` key).

    ``execute_operator_stack`` defaults to ``False``: the operator-stack
    evidence below is gathered via the existing runner's safe ``--dry-run``
    mode (instant, no process started). Passing ``True`` opts into that
    runner's ``--execute`` mode, which starts real fixture-only local
    processes -- an explicit, caller-requested cost/risk, never a default
    for this composition.
    """
    if environment not in VALID_PROMOTION_ENVIRONMENTS:
        raise ValueError(f"Invalid environment '{environment}'. Must be one of {sorted(VALID_PROMOTION_ENVIRONMENTS)}")

    env = os.environ if environ is None else environ
    blockers: list[str] = []
    remediations: list[str] = []

    # 1. Repository identity
    repo_info = get_repository_identity()
    if environment == "isolated_worktree" and not repo_info["is_isolated_worktree"]:
        blockers.append("isolated_worktree_required: Current execution is running in the primary repository instead of an isolated worktree.")
        remediations.append("Create and switch to an isolated worktree: `git worktree add ../MarketOS.worktrees/<name> <branch>`")

    # 2. Runtime inspection
    runtime_info = get_runtime_versions()

    # 3. Container static checks
    container_checks = check_container_static_hardening(dockerfile_path)
    if container_checks["status"] == "failed":
        blockers.append("container_hardening_failed: Dockerfile does not satisfy non-root, HEALTHCHECK, STOPSIGNAL, or port 3000 mapping.")
        remediations.append("Review and update Dockerfile to ensure USER marketos:marketos, HEALTHCHECK, and port 3000 are present.")

    # 4. Credential classification without reading values
    cred_class = {
        "live_credentials_present": [k for k in LIVE_PROVIDER_CREDENTIAL_KEYS if bool(env.get(k))],
        "database_credentials_configured": [k for k in DATABASE_KEYS if bool(env.get(k))],
        "no_credentials_required": environment in {"local_dry_run", "isolated_worktree"},
    }

    # 5. Live mutation guard
    active_mutations = [k for k in MUTATION_FLAG_KEYS if is_truthy(env.get(k))]
    live_guard = {
        "status": "blocked" if not active_mutations else "active",
        "active_flags": active_mutations,
        "all_flags_disabled": len(active_mutations) == 0,
    }
    if active_mutations and environment in {"local_dry_run", "isolated_worktree", "private_staging", "live_provider_blocked"}:
        blockers.append(f"live_mutations_forbidden in {environment}: Found active flags: {active_mutations}")
        remediations.append(f"Unset or disable live mutation flags: {active_mutations}")

    # 6. CI evidence classification. github_actions_job (real Jobs API
    # evidence: runner_id, steps) takes precedence over the abstract
    # ci_override shape when both are supplied, since it is the more
    # specific, directly-observed input. Whichever path runs, its
    # classified state/step-count feeds diagnose_zero_step_ci below
    # (via ci_evidence_for_diagnostics) so the administrator-facing
    # diagnostic always reflects what was actually observed rather than
    # only doing so for the github_actions_job path specifically.
    if github_actions_job is not None:
        ci_eval = classify_github_actions_job(github_actions_job, logs_available=logs_available)
        runner_id_for_diagnostics = ci_eval["runner_id"]
    elif ci_override is not None:
        ci_eval = classify_ci_evidence(**ci_override)
        runner_id_for_diagnostics = None
    else:
        # Default environment CI check: local worktrees have no active CI runners attached
        ci_eval = classify_ci_evidence(ci_status="ci_unavailable", total_steps=0, runners_active=0, logs_available=False)
        runner_id_for_diagnostics = None
    ci_evidence_for_diagnostics = {
        "ci_status": ci_eval["state"],
        "steps_executed": ci_eval["total_steps"],
        "runner_id": runner_id_for_diagnostics,
    }

    # 7. Diagnostics. ci_evidence_for_diagnostics threads the real
    # runner_id/steps evidence above into diagnose_zero_step_ci's
    # administrator-facing message when it is available; omitted
    # (None) reproduces the prior no-evidence behavior exactly.
    mode_mapping = {
        "local_dry_run": "local_dry_run",
        "isolated_worktree": "local_dry_run",
        "private_staging": "staging",
        "authenticated_operator": "staging",
        "public_client": "local_dry_run",
        "live_provider_blocked": "staging",
    }
    diag_mode = mode_mapping[environment]
    diag_report = run_all_diagnostics(environ=env, mode=diag_mode, ci_evidence=ci_evidence_for_diagnostics)

    diag_summary = {
        "status": diag_report["summary"]["status"],
        "detected_issues": diag_report["summary"]["detected_issues"],
        "total_checks": diag_report["summary"]["total_checks"],
    }
    ci_admissibility_diagnostic = next(
        (item for item in diag_report["diagnostics"] if item["code"] == "zero_step_ci"),
        {"code": "zero_step_ci", "category": "continuous_integration", "status": "unavailable", "message": "", "remediation": "", "failure_details": {}},
    )
    for item in diag_report["diagnostics"]:
        if item["status"] == "detected":
            remediations.append(f"[{item['code']}] {item['remediation']}")
            if item["category"] in {"environment_contract", "runtime_dependency"}:
                blockers.append(f"diagnostic_{item['code']}: {item['message']}")

    # 8. Environment contract check
    env_report = validate_environment(environ=env, mode=diag_mode)
    if not env_report.ready:
        for b in env_report.blockers:
            blockers.append(f"contract_{b}")
        for w in env_report.warnings:
            remediations.append(f"Warning: {w}")

    # 9. Password strength for private staging
    if environment in {"private_staging", "authenticated_operator"}:
        pwd = str(env.get("POSTGRES_PASSWORD", "")).strip().lower()
        if pwd in INSECURE_PASSWORDS:
            blockers.append(f"insecure_database_password: The supplied database credential is an insecure default for {environment}")
            remediations.append("Generate and configure a high-entropy database password (>= 16 characters).")

    # 10. CoderOS status
    coderos = inspect_coderos_status(environ=env)

    # 11. Execute the existing bounded harness when no sanitized result was supplied.
    if harness_results is None:
        hvp_summary = _run_high_value_path_harness()
    elif not isinstance(harness_results, Mapping):
        hvp_summary = {"status": "malformed", "evidence_classification": "simulated_or_planned", "reason": "high_value_path_summary_malformed", "paths_executed": 0, "all_paths_passed": False, "bit_identity_confirmed": False}
    else:
        hvp_summary = _normalize_harness_results(harness_results)

    # 12. Compose existing readiness authorities; these are evidence surfaces,
    # not a second gate or a substitute for the Phase 1 report.
    phase1 = _phase1_summary(env)
    operator_stack = _operator_stack_evidence(
        execute=execute_operator_stack,
        backend_only=operator_stack_backend_only,
        timeout_s=operator_stack_timeout_s,
    )
    event_read_path = _event_read_path_evidence(env)
    rollback = _rollback_evidence(repo_info)

    if phase1.get("status") == "blocked":
        blockers.append("phase1_readiness_blocked")
        remediations.append("Resolve the blocking gates in the canonical Phase 1 readiness report before release promotion.")
    if operator_stack["status"] != "passed":
        blockers.append(f"operator_stack_{operator_stack['status']}")
        remediations.append("Run the existing bounded local operator-stack rehearsal; do not infer runtime readiness from static configuration.")
    if event_read_path["status"] != "passed":
        blockers.append(f"event_read_path_{event_read_path['status']}")
        remediations.append("Configure a sanitized canonical event JSONL read path under artifacts/ and verify it through the existing read view.")
    if rollback["status"] != "passed":
        blockers.append("rollback_evidence_unavailable")
        remediations.append("Identify a prior known-good revision before any deployment promotion.")

    # Executed failures take precedence over unavailable evidence. Missing CI
    # evidence remains ci_unavailable and cannot be hidden by local passes.
    hvp_status = hvp_summary.get("status")
    if hvp_status != "passed":
        if hvp_status in VALID_READINESS_STATES:
            blockers.append(f"high_value_path_{hvp_status}")
        else:
            blockers.append("high_value_path_malformed")
    ci_state = ci_eval.get("state")
    if ci_state != "passed":
        blockers.append(f"ci_evidence_{ci_state}")

    # Final readiness state resolution
    if any("live_mutations_forbidden" in b for b in blockers):
        readiness_state = "blocked"
    elif any("insecure_database_password" in b for b in blockers):
        readiness_state = "blocked"
    elif any("contract_" in b for b in blockers):
        readiness_state = "blocked"
    elif any("container_hardening_failed" in b for b in blockers):
        readiness_state = "failed"
    elif any("missing_python_module" in b for b in blockers):
        readiness_state = "failed"
    elif hvp_status in {"failed", "timed_out", "collection_failed", "malformed", "blocked", "unavailable", "not_run"}:
        readiness_state = hvp_status
    elif ci_state in {"failed", "timed_out", "unavailable", "ci_unavailable"}:
        readiness_state = ci_state
    elif phase1.get("status") == "blocked" or len(blockers) > 0:
        readiness_state = "blocked"
    else:
        readiness_state = "passed"

    safe_next_action = (
        "Proceed to private staging dry-run rehearsal."
        if readiness_state == "passed"
        else f"Resolve {len(blockers)} promotion blockers before proceeding."
    )

    bundle = PromotionRehearsalBundle(
        environment=environment,
        readiness_state=readiness_state,
        repository=repo_info,
        runtime=runtime_info,
        container_hardening=container_checks,
        credential_classification=cred_class,
        live_mutation_guard=live_guard,
        diagnostics_summary=diag_summary,
        ci_evidence=ci_eval,
        ci_admissibility_diagnostic=ci_admissibility_diagnostic,
        coderos_status=coderos,
        high_value_path_summary=hvp_summary,
        phase1_readiness=phase1,
        operator_stack=operator_stack,
        event_read_path=event_read_path,
        rollback_evidence=rollback,
        blockers=sorted(set(blockers)),
        remediations=sorted(set(remediations)),
        safe_next_action=safe_next_action,
        rollback_path="Revert environment variables and container deployment to previous known-good revision.",
        deterministic_hash="",
    )
    bundle.deterministic_hash = bundle.compute_hash()
    return bundle

"""Build a bounded, read-only conformance matrix for the open PR portfolio.

This module consumes sanitized metadata rather than calling GitHub.  It is a
portfolio lens over existing authorities, not a replacement for the local
quality gate or PR-readiness report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "MarketOS.PortfolioConformanceMatrix.v1"
INPUT_SCHEMA = "MarketOS.PortfolioConformanceInput.v1"
REPORT_VERSION = "portfolio-conformance-v1"
MAX_INPUT_BYTES = 64 * 1024
MAX_OUTPUT_CHARS = 120_000
MAX_PRS = 50
MAX_FILES_PER_PR = 250
MAX_JOBS_PER_PR = 200
MAX_DEPENDENCIES_PER_PR = 50
MAX_STEPS_PER_JOB = 200
MAX_STRING = 240
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
SAFE_PATH_RE = re.compile(r"^[^\x00\r\n]+$")
SECRET_RE = re.compile(
    r"(?is)(-----begin .*?private key-----|ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"sk-(?:live|test)?-?[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|bearer\s+[A-Za-z0-9._-]{10,}|"
    r"(?:https?|postgres(?:ql)?|redis)://[^:]+:[^@]+@)"
)
SENSITIVE_KEY_RE = re.compile(r"(?i)(password|secret|token|api[_-]?key|private[_-]?key|authorization|credential)")
UNSAFE_TEXT_RE = re.compile(r"[\x00-\x1f\x7f\u200b\u200c\u200d\u202a-\u202e\u2060\u2066-\u2069\ufeff]")
SECRET_ASSIGNMENT_RE = re.compile(r"(?i)(password|secret|token|api[_-]?key|private[_-]?key|authorization|credential)\s*[:=]\s*\S+")

CI_STATUSES = frozenset({"completed", "queued", "in_progress", "pending", "waiting", "cancelled"})
CI_CONCLUSIONS = frozenset({"success", "passed", "failure", "failed", "timed_out", "cancelled", "skipped", "neutral"})
LOCAL_EVIDENCE_CLASSES = frozenset(
    {
        "actual_executed",
        "fixture",
        "manual",
        "derived",
        "simulated_or_planned",
        "unavailable",
        "ci_unavailable",
        "not_run",
        "failed",
        "malformed",
        "blocked",
    }
)
LOCAL_STATUSES = frozenset(
    {"passed", "failed", "unavailable", "timed_out", "not_run", "collection_failed", "blocked", "malformed", "ci_unavailable"}
)
AUTHORITY_PATHS = {
    "scripts/ai/run_local_quality_gate.py": "quality_gate",
    "scripts/ai/pr_readiness_report.py": "pr_readiness",
    ".github/workflows/agentic-quality-gate.yml": "quality_gate",
    "backend/economics/kernel.py": "financial_kernel",
    "evaluation/trustos/client_workspace_isolation.py": "trustos_export",
    "evaluation/companyos/resource_execution_governor.py": "companyos_governor",
}
FORBIDDEN_INPUT_KEYS = frozenset({"body", "comments", "logs", "raw_logs", "output", "private_notes", "notes", "payload"})


class MatrixInputError(ValueError):
    """A sanitized adapter input failed closed without retaining its value."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Mapping[str, Any]) -> str:
    copy = {key: item for key, item in value.items() if key != "fingerprint"}
    return hashlib.sha256(_canonical(copy).encode("utf-8")).hexdigest()


def _check_keys(value: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = set(value) - allowed
    if unknown or any(key in FORBIDDEN_INPUT_KEYS for key in value):
        raise MatrixInputError("unknown_or_forbidden_input_field")


def _text(value: Any, *, field: str, limit: int = MAX_STRING) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or UNSAFE_TEXT_RE.search(value):
        raise MatrixInputError(f"invalid_{field}")
    if SECRET_RE.search(value) or (SENSITIVE_KEY_RE.search(value) and SECRET_ASSIGNMENT_RE.search(value)):
        raise MatrixInputError("secret_shaped_input")
    return value


def _optional_text(value: Any, *, field: str, limit: int = MAX_STRING) -> str | None:
    if value is None:
        return None
    return _text(value, field=field, limit=limit)


def _sha(value: Any, *, field: str, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise MatrixInputError(f"invalid_{field}")
    return value.lower()


def _path(value: Any) -> str:
    result = _text(value, field="changed_path", limit=400).replace("\\", "/")
    path = Path(result)
    if result.startswith("/") or re.match(r"^[A-Za-z]:/", result) or ".." in path.parts:
        raise MatrixInputError("unsafe_changed_path")
    lowered = result.lower()
    if lowered.startswith(("artifacts/", ".env", "credentials/", "secrets/")) or any(
        marker in lowered for marker in ("/.env", "browser-trace", "playwright-report", ".cache")
    ):
        raise MatrixInputError("sensitive_changed_path")
    if not SAFE_PATH_RE.fullmatch(result):
        raise MatrixInputError("invalid_changed_path")
    return result


def _string_list(value: Any, *, field: str, limit: int, item_limit: int = MAX_STRING) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        raise MatrixInputError(f"invalid_{field}")
    return sorted({_text(item, field=field, limit=item_limit) for item in value})


def _normalize_dependency(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MatrixInputError("invalid_dependency")
    _check_keys(value, {"number", "head_sha", "available"})
    number = value.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        raise MatrixInputError("invalid_dependency_number")
    available = value.get("available", True)
    if not isinstance(available, bool):
        raise MatrixInputError("invalid_dependency_availability")
    return {"number": number, "head_sha": _sha(value.get("head_sha"), field="dependency_head_sha"), "available": available}


def _normalize_steps(value: Any) -> int:
    if not isinstance(value, list) or len(value) > MAX_STEPS_PER_JOB:
        raise MatrixInputError("invalid_ci_steps")
    for item in value:
        if isinstance(item, str):
            _text(item, field="ci_step", limit=120)
        elif isinstance(item, Mapping):
            _check_keys(item, {"name", "status"})
            _text(item.get("name"), field="ci_step_name", limit=120)
            if item.get("status") is not None:
                _text(item["status"], field="ci_step_status", limit=40)
        else:
            raise MatrixInputError("invalid_ci_step")
    return len(value)


def _normalize_ci_job(value: Any, required_names: set[str], expected_head_sha: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MatrixInputError("invalid_ci_job")
    _check_keys(value, {"name", "status", "conclusion", "required", "head_sha", "runner_id", "steps", "steps_executed", "logs_available"})
    name = _text(value.get("name"), field="ci_job_name", limit=160)
    status = _text(value.get("status"), field="ci_job_status", limit=40).lower()
    if status not in CI_STATUSES:
        raise MatrixInputError("invalid_ci_job_status")
    conclusion = value.get("conclusion")
    if conclusion is not None:
        conclusion = _text(conclusion, field="ci_job_conclusion", limit=40).lower()
        if conclusion not in CI_CONCLUSIONS:
            raise MatrixInputError("invalid_ci_job_conclusion")
    required = value.get("required", name in required_names)
    if not isinstance(required, bool):
        raise MatrixInputError("invalid_ci_required_flag")
    if required != (name in required_names):
        raise MatrixInputError("ci_required_flag_mismatch")
    head_sha = _sha(value.get("head_sha"), field="ci_head_sha")
    if head_sha != expected_head_sha:
        raise MatrixInputError("ci_head_sha_mismatch")
    runner_id = value.get("runner_id")
    if runner_id is not None and (not isinstance(runner_id, int) or isinstance(runner_id, bool) or runner_id < 0):
        raise MatrixInputError("invalid_runner_id")
    steps_present = "steps" in value
    count_present = "steps_executed" in value
    if not steps_present and not count_present:
        raise MatrixInputError("missing_ci_step_evidence")
    step_count = _normalize_steps(value["steps"]) if steps_present else None
    if count_present:
        raw_count = value["steps_executed"]
        if not isinstance(raw_count, int) or isinstance(raw_count, bool) or raw_count < 0 or raw_count > MAX_STEPS_PER_JOB:
            raise MatrixInputError("invalid_steps_executed")
        if step_count is not None and step_count != raw_count:
            raise MatrixInputError("ci_step_count_mismatch")
        step_count = raw_count
    logs_available = value.get("logs_available")
    if logs_available is not None and not isinstance(logs_available, bool):
        raise MatrixInputError("invalid_logs_available")
    if status in {"queued", "pending", "waiting"}:
        if conclusion is not None or step_count != 0 or runner_id not in {None, 0} or logs_available is True:
            raise MatrixInputError("contradictory_pending_ci_metadata")
    elif status == "in_progress":
        if conclusion is not None or runner_id in {None, 0}:
            raise MatrixInputError("contradictory_in_progress_ci_metadata")
    elif status == "completed":
        if conclusion is None:
            raise MatrixInputError("missing_completed_ci_conclusion")
    elif status == "cancelled":
        if conclusion != "cancelled":
            raise MatrixInputError("contradictory_cancelled_ci_metadata")
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "required": required,
        "head_sha": head_sha,
        "runner_id": runner_id,
        "steps_executed": step_count,
        "logs_available": logs_available,
    }


def _normalize_local_evidence(value: Any) -> dict[str, Any]:
    if value is None:
        return {"classification": "not_run", "status": "not_run", "fingerprint": None}
    if not isinstance(value, Mapping):
        raise MatrixInputError("invalid_local_evidence")
    _check_keys(value, {"classification", "status", "fingerprint"})
    classification = _text(value.get("classification"), field="local_evidence_class", limit=50)
    status = _text(value.get("status"), field="local_evidence_status", limit=40)
    if classification not in LOCAL_EVIDENCE_CLASSES or status not in LOCAL_STATUSES:
        raise MatrixInputError("invalid_local_evidence_state")
    fingerprint = value.get("fingerprint")
    if fingerprint is not None:
        fingerprint = _sha(fingerprint, field="local_evidence_fingerprint")
    return {"classification": classification, "status": status, "fingerprint": fingerprint}


def _normalize_pr(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MatrixInputError("invalid_pull_request")
    allowed = {
        "number",
        "title",
        "state",
        "is_draft",
        "base_ref",
        "base_sha",
        "head_ref",
        "head_sha",
        "merge_base_sha",
        "changed_files",
        "depends_on",
        "required_checks",
        "required_checks_source",
        "ci_jobs",
        "local_evidence",
        "authority_claims",
    }
    _check_keys(value, allowed)
    number = value.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        raise MatrixInputError("invalid_pull_request_number")
    state = _text(value.get("state"), field="pull_request_state", limit=20).lower()
    if state not in {"open", "closed", "merged"}:
        raise MatrixInputError("invalid_pull_request_state")
    required_checks = _string_list(value.get("required_checks", []), field="required_checks", limit=MAX_JOBS_PER_PR, item_limit=160)
    if not required_checks:
        raise MatrixInputError("empty_required_checks")
    required_checks_source = _text(value.get("required_checks_source"), field="required_checks_source", limit=60)
    if required_checks_source != "branch_protection_adapter":
        raise MatrixInputError("untrusted_required_checks_source")
    base_sha = _sha(value.get("base_sha"), field="base_sha")
    head_sha = _sha(value.get("head_sha"), field="head_sha")
    jobs_raw = value.get("ci_jobs", [])
    if not isinstance(jobs_raw, list) or len(jobs_raw) > MAX_JOBS_PER_PR:
        raise MatrixInputError("invalid_ci_jobs")
    jobs = [_normalize_ci_job(job, set(required_checks), head_sha) for job in jobs_raw]
    names = [job["name"] for job in jobs]
    if len(set(names)) != len(names):
        raise MatrixInputError("duplicate_ci_job")
    dependencies_raw = value.get("depends_on", [])
    if not isinstance(dependencies_raw, list) or len(dependencies_raw) > MAX_DEPENDENCIES_PER_PR:
        raise MatrixInputError("invalid_dependencies")
    dependencies = [_normalize_dependency(item) for item in dependencies_raw]
    dependency_numbers = [item["number"] for item in dependencies]
    if len(set(dependency_numbers)) != len(dependency_numbers):
        raise MatrixInputError("duplicate_dependency")
    is_draft = value.get("is_draft", False)
    if not isinstance(is_draft, bool):
        raise MatrixInputError("invalid_draft_flag")
    changed_files = value.get("changed_files", [])
    if not isinstance(changed_files, list) or len(changed_files) > MAX_FILES_PER_PR:
        raise MatrixInputError("invalid_changed_files")
    return {
        "number": number,
        "title": _text(value.get("title", f"PR #{number}"), field="pull_request_title"),
        "state": state,
        "is_draft": is_draft,
        "base_ref": _text(value.get("base_ref"), field="base_ref", limit=200),
        "base_sha": base_sha,
        "head_ref": _text(value.get("head_ref"), field="head_ref", limit=200),
        "head_sha": head_sha,
        "merge_base_sha": _sha(value.get("merge_base_sha"), field="merge_base_sha", required=False),
        "changed_files": sorted({_path(item) for item in changed_files}),
        "depends_on": dependencies,
        "required_checks": required_checks,
        "required_checks_source": required_checks_source,
        "ci_jobs": jobs,
        "local_evidence": _normalize_local_evidence(value.get("local_evidence")),
        "authority_claims": _string_list(value.get("authority_claims", []), field="authority_claims", limit=20, item_limit=100),
    }


def normalize_input(value: Any) -> dict[str, Any]:
    """Validate and normalize a sanitized adapter payload."""
    if not isinstance(value, Mapping):
        raise MatrixInputError("input_root_not_object")
    _check_keys(value, {"schema", "repository", "origin_main", "pull_requests"})
    if value.get("schema") != INPUT_SCHEMA:
        raise MatrixInputError("unsupported_input_schema")
    repository = _text(value.get("repository"), field="repository", limit=200)
    origin_main = _sha(value.get("origin_main"), field="origin_main")
    raw_prs = value.get("pull_requests")
    if not isinstance(raw_prs, list) or len(raw_prs) > MAX_PRS:
        raise MatrixInputError("invalid_pull_requests")
    prs = [_normalize_pr(item) for item in raw_prs]
    numbers = [item["number"] for item in prs]
    if len(set(numbers)) != len(numbers):
        raise MatrixInputError("duplicate_pull_request_number")
    return {"schema": INPUT_SCHEMA, "repository": repository, "origin_main": origin_main, "pull_requests": sorted(prs, key=lambda item: item["number"])}


def _run_git(root: Path, *args: str) -> tuple[str | None, str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
            shell=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None, "unavailable"
    output = (completed.stdout or "").strip()
    if completed.returncode != 0 or len(output) > 200:
        return None, "unavailable"
    return output, "actual"


def _remote_repository(remote: str | None) -> str | None:
    if not remote:
        return None
    value = remote.removesuffix(".git")
    match = re.search(r"github\.com[:/]([^/]+/[^/]+)$", value, flags=re.IGNORECASE)
    return match.group(1) if match else None


def collect_repository_state(root: Path = ROOT) -> dict[str, Any]:
    """Read only the local git identity needed for a matrix."""
    head, head_class = _run_git(root, "rev-parse", "HEAD")
    branch, branch_class = _run_git(root, "branch", "--show-current")
    origin_main, main_class = _run_git(root, "rev-parse", "origin/main")
    merge_base, merge_class = _run_git(root, "merge-base", "HEAD", "origin/main")
    remote, remote_class = _run_git(root, "config", "--get", "remote.origin.url")
    remote_repository = _remote_repository(remote)
    classifications = {"head": head_class, "branch": branch_class, "origin_main": main_class, "merge_base": merge_class, "remote_repository": "actual" if remote_repository else remote_class}
    overall = "actual" if all(item == "actual" for item in classifications.values()) else "unavailable"
    return {
        "classification": overall,
        "head": head,
        "branch": branch,
        "origin_main": origin_main,
        "merge_base": merge_base,
        "remote_repository": remote_repository,
        "field_classifications": classifications,
    }


def _authority_key(path: str) -> str | None:
    for known, authority in AUTHORITY_PATHS.items():
        if path == known or (known.endswith("/") and path.startswith(known)):
            return authority
    return None


def _dependency_projection(pr: Mapping[str, Any], by_number: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    dependencies = []
    blockers = []
    for item in pr["depends_on"]:
        target = by_number.get(item["number"])
        if not item["available"] or target is None:
            dependencies.append({"number": item["number"], "classification": "missing_dependency_head"})
            blockers.append(f"missing_dependency_head:{item['number']}")
            continue
        if target["head_sha"] != item["head_sha"]:
            dependencies.append({"number": item["number"], "classification": "stale_dependency_head"})
            blockers.append(f"stale_dependency_head:{item['number']}")
            continue
        dependencies.append(
            {
                "number": item["number"],
                "classification": "merged_dependency_satisfied" if target["state"] == "merged" else "dependency_satisfied",
            }
        )
    if pr["base_ref"] != "main" and not dependencies:
        blockers.append("missing_dependency_head:base_ref_not_main")
    if pr["base_ref"] != "main" and dependencies and not any(item["head_sha"] == pr["base_sha"] for item in pr["depends_on"]):
        blockers.append("stacked_base_sha_mismatch")
    return {"classification": "blocked" if blockers else "clear", "dependencies": dependencies, "blockers": sorted(blockers)}


def _ancestry_projection(pr: Mapping[str, Any], repo: Mapping[str, Any], dependency: Mapping[str, Any]) -> dict[str, Any]:
    merge_base = pr["merge_base_sha"]
    base_sha = pr["base_sha"]
    origin_main = repo.get("origin_main")
    if not merge_base:
        return {"classification": "unavailable", "base_matches_origin_main": base_sha == origin_main, "merge_base_matches_base": False}
    matches_base = merge_base == base_sha
    matches_origin = base_sha == origin_main
    if dependency["blockers"]:
        classification = "blocked"
    elif pr["base_ref"] != "main":
        classification = "stacked_aligned" if matches_base else "stale"
    elif matches_base and matches_origin:
        classification = "aligned"
    elif matches_base:
        classification = "base_not_current_origin_main"
    else:
        classification = "stale"
    return {"classification": classification, "base_matches_origin_main": matches_origin, "merge_base_matches_base": matches_base}


def _job_classification(job: Mapping[str, Any]) -> str:
    status = job["status"]
    conclusion = job["conclusion"]
    steps = job["steps_executed"] or 0
    runner = job["runner_id"]
    if status in {"queued", "in_progress", "pending", "waiting"}:
        return "pending"
    if steps == 0 or runner is None or runner == 0:
        return "zero_step_runnerless"
    if status not in {"completed", "cancelled"} or conclusion is None:
        return "malformed"
    if conclusion in {"timed_out"}:
        return "timed_out"
    if conclusion in {"failure", "failed", "cancelled"}:
        return "executed_failure"
    if conclusion in {"success", "passed"}:
        return "pass" if job["logs_available"] is True else "unavailable_logs"
    return "malformed"


def _ci_projection(pr: Mapping[str, Any]) -> dict[str, Any]:
    jobs = []
    for job in pr["ci_jobs"]:
        classification = _job_classification(job)
        jobs.append(
            {
                "name": job["name"],
                "required": job["required"],
                "status": job["status"],
                "conclusion": job["conclusion"],
                "head_sha": job["head_sha"],
                "classification": classification,
                "steps_executed": job["steps_executed"],
                "runner_assigned": bool(job["runner_id"] and job["runner_id"] > 0),
                "logs_available": job["logs_available"],
            }
        )
    names = {job["name"] for job in pr["ci_jobs"]}
    missing = sorted(set(pr["required_checks"]) - names)
    required = [job for job in jobs if job["required"]]
    required_classes = [job["classification"] for job in required]
    if any(item == "malformed" for item in required_classes):
        classification = "malformed"
    elif any(item in {"executed_failure", "timed_out"} for item in required_classes):
        classification = "executed_failure" if "executed_failure" in required_classes else "timed_out"
    elif any(item == "pending" for item in required_classes):
        classification = "pending"
    elif missing or any(item == "zero_step_runnerless" for item in required_classes):
        classification = "ci_unavailable"
    elif any(item == "unavailable_logs" for item in required_classes):
        classification = "unavailable_logs"
    elif required and all(item == "pass" for item in required_classes):
        classification = "pass"
    else:
        classification = "ci_unavailable"
    return {
        "classification": classification,
        "required_checks": sorted(pr["required_checks"]),
        "required_checks_source": pr["required_checks_source"],
        "missing_required": missing,
        "jobs": jobs,
    }


def _local_projection(pr: Mapping[str, Any]) -> dict[str, Any]:
    evidence = dict(pr["local_evidence"])
    evidence["execution_observed"] = evidence["classification"] == "actual_executed"
    evidence["live_validated"] = False
    return evidence


def _merge_order(prs: list[Mapping[str, Any]]) -> tuple[list[int], list[str]]:
    candidates = [pr for pr in prs if pr["state"] == "open"]
    numbers = {int(pr["number"]) for pr in candidates}
    edges: dict[int, set[int]] = {number: set() for number in numbers}
    indegree = {number: 0 for number in numbers}
    blockers: list[str] = []
    for pr in candidates:
        for dependency in pr["depends_on"]:
            if dependency["number"] not in numbers:
                continue
            if pr["number"] not in edges[dependency["number"]]:
                edges[dependency["number"]].add(pr["number"])
                indegree[pr["number"]] += 1
    ready = sorted(number for number, degree in indegree.items() if degree == 0)
    order: list[int] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for child in sorted(edges[current]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()
    if len(order) != len(numbers):
        blockers.append("merge_order_cycle")
        return [], blockers
    return order, blockers


def build_matrix(payload: Mapping[str, Any] | None, *, repository_state: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build a deterministic matrix from sanitized input and injected git state."""
    repo = dict(repository_state or collect_repository_state())
    base = {
        "schema": SCHEMA,
        "report_version": REPORT_VERSION,
        "generated_at": "deterministic",
        "repository": "unavailable",
        "origin_main": repo.get("origin_main"),
        "input_origin_main": None,
        "repository_state": {
            "classification": repo.get("classification", "unavailable"),
            "head": repo.get("head"),
            "branch": repo.get("branch"),
            "merge_base": repo.get("merge_base"),
            "remote_repository": repo.get("remote_repository"),
            "field_classifications": dict(repo.get("field_classifications", {})),
        },
        "input": {"classification": "unavailable", "schema": None},
        "pull_requests": [],
        "overlap": {"collisions": [], "changed_file_owner_count": 0},
        "duplicate_authority_indicators": [],
        "merge_order": [],
        "blockers": [],
        "evidence_classifications": {"ci": {}, "local": {}},
        "portfolio_status": "blocked",
        "merge_authority": "scripts/ai/pr_readiness_report.py",
        "merge_authorized": False,
        "next_action": "supply a sanitized portfolio metadata adapter input",
        "limits": {"max_input_bytes": MAX_INPUT_BYTES, "max_pull_requests": MAX_PRS, "max_files_per_pr": MAX_FILES_PER_PR, "max_jobs_per_pr": MAX_JOBS_PER_PR},
    }
    if payload is None:
        base["blockers"] = ["portfolio_input_not_supplied"]
        base["fingerprint"] = _fingerprint(base)
        return base
    try:
        data = normalize_input(payload)
    except MatrixInputError as exc:
        base["input"] = {"classification": "malformed", "schema": payload.get("schema") if isinstance(payload, Mapping) and isinstance(payload.get("schema"), str) else None, "error": exc.code}
        base["blockers"] = ["portfolio_input_malformed"]
        base["portfolio_status"] = "malformed"
        base["next_action"] = "repair the sanitized portfolio adapter input and rerun the matrix"
        base["fingerprint"] = _fingerprint(base)
        return base
    base["repository"] = data["repository"]
    base["input_origin_main"] = data["origin_main"]
    base["origin_main"] = repo.get("origin_main") or data["origin_main"]
    base["input"] = {"classification": "actual", "schema": data["schema"]}
    if repo.get("remote_repository") and data["repository"] != repo["remote_repository"]:
        base["blockers"].append("repository_mismatch")
    if repo.get("origin_main") and data["origin_main"] != repo["origin_main"]:
        base["blockers"].append("origin_main_mismatch")
    by_number = {int(pr["number"]): pr for pr in data["pull_requests"]}
    path_owners: dict[str, list[int]] = defaultdict(list)
    authority_owners: dict[str, list[int]] = defaultdict(list)
    result_prs = []
    for pr in data["pull_requests"]:
        dependency = _dependency_projection(pr, by_number)
        ancestry = _ancestry_projection(pr, repo, dependency)
        ci = _ci_projection(pr)
        local = _local_projection(pr)
        for path in pr["changed_files"]:
            path_owners[path].append(pr["number"])
            authority = _authority_key(path)
            if authority:
                authority_owners[authority].append(pr["number"])
        blockers = sorted(set(dependency["blockers"] + ci["missing_required"]))
        if ancestry["classification"] in {"unavailable", "stale", "blocked", "base_not_current_origin_main"}:
            blockers.append(f"ancestry:{ancestry['classification']}")
        if ci["classification"] != "pass":
            blockers.append(f"ci:{ci['classification']}")
        if local["classification"] in {"unavailable", "ci_unavailable", "not_run", "malformed", "failed", "blocked"}:
            blockers.append(f"local_evidence:{local['classification']}")
        elif local["status"] != "passed":
            blockers.append(f"local_evidence_status:{local['status']}")
        result_prs.append(
            {
                "number": pr["number"],
                "title": pr["title"],
                "state": pr["state"],
                "is_draft": pr["is_draft"],
                "base_ref": pr["base_ref"],
                "base_sha": pr["base_sha"],
                "head_ref": pr["head_ref"],
                "head_sha": pr["head_sha"],
                "merge_base_sha": pr["merge_base_sha"],
                "changed_files": pr["changed_files"],
                "ancestry": ancestry,
                "stacking": dependency,
                "ci": ci,
                "local_evidence": local,
                "blockers": sorted(set(blockers)),
            }
        )
    collisions = [{"path": path, "pull_requests": sorted(owners)} for path, owners in sorted(path_owners.items()) if len(set(owners)) > 1]
    base["overlap"] = {"collisions": collisions, "changed_file_owner_count": len(path_owners)}
    duplicate_indicators = []
    for collision in collisions:
        duplicate_indicators.append({"kind": "changed_file_overlap", "path": collision["path"], "pull_requests": collision["pull_requests"]})
    for authority, owners in sorted(authority_owners.items()):
        unique = sorted(set(owners))
        if len(unique) > 1:
            duplicate_indicators.append({"kind": "canonical_authority_overlap", "authority": authority, "pull_requests": unique})
    claimed: dict[str, list[int]] = defaultdict(list)
    for pr in data["pull_requests"]:
        for claim in pr["authority_claims"]:
            claimed[claim].append(pr["number"])
    for claim, owners in sorted(claimed.items()):
        if len(set(owners)) > 1:
            duplicate_indicators.append({"kind": "parallel_authority_claim", "authority": claim, "pull_requests": sorted(set(owners))})
    base["duplicate_authority_indicators"] = duplicate_indicators
    for item in result_prs:
        for collision in collisions:
            if item["number"] in collision["pull_requests"]:
                item["blockers"].append(f"overlap:{collision['path']}")
        for indicator in duplicate_indicators:
            if item["number"] in indicator["pull_requests"] and indicator["kind"] != "changed_file_overlap":
                item["blockers"].append(f"duplicate_authority:{indicator.get('authority', 'unknown')}")
        item["blockers"] = sorted(set(item["blockers"]))
    order, order_blockers = _merge_order(data["pull_requests"])
    base["pull_requests"] = result_prs
    base["merge_order"] = order
    base["blockers"].extend(order_blockers)
    base["blockers"].extend(f"pr:{pr['number']}:{blocker}" for pr in result_prs for blocker in pr["blockers"])
    base["blockers"] = sorted(set(base["blockers"]))
    ci_counts: dict[str, int] = defaultdict(int)
    local_counts: dict[str, int] = defaultdict(int)
    for pr in result_prs:
        ci_counts[pr["ci"]["classification"]] += 1
        local_counts[pr["local_evidence"]["classification"]] += 1
    base["evidence_classifications"] = {"ci": dict(sorted(ci_counts.items())), "local": dict(sorted(local_counts.items()))}
    if "portfolio_input_malformed" in base["blockers"]:
        base["portfolio_status"] = "malformed"
    elif base["blockers"]:
        base["portfolio_status"] = "blocked"
    else:
        base["portfolio_status"] = "ready_for_review"
    if any(item.startswith("portfolio_input") for item in base["blockers"]):
        base["next_action"] = "repair the sanitized portfolio adapter input and rerun the matrix"
    elif any("overlap" in item or "duplicate_authority" in item for item in base["blockers"]):
        base["next_action"] = "resolve changed-file and canonical-authority ownership overlaps before merging"
    elif any("dependency" in item or "stacked_base" in item for item in base["blockers"]):
        base["next_action"] = "refresh dependency heads and verify stacked ancestry before merging"
    elif any(":executed_failure" in item or ":timed_out" in item for item in base["blockers"]):
        base["next_action"] = "repair executed CI failures before merging"
    elif any(":ci_unavailable" in item or ":unavailable_logs" in item for item in base["blockers"]):
        base["next_action"] = "collect executed CI steps and logs; zero-step evidence cannot pass"
    elif any(":pending" in item for item in base["blockers"]):
        base["next_action"] = "wait for pending required checks and refresh the sanitized adapter input"
    elif any(item.startswith("pr:") and ":ancestry" in item for item in base["blockers"]):
        base["next_action"] = "refresh PR base/head and merge-base evidence"
    elif any("local_evidence" in item for item in base["blockers"]):
        base["next_action"] = "collect the existing local quality-gate evidence without upgrading fixture or simulated evidence"
    base["fingerprint"] = _fingerprint(base)
    return base


def load_input(path: Path) -> Mapping[str, Any]:
    """Read one bounded sanitized metadata file; never echo its contents on error."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise MatrixInputError("input_unavailable") from exc
    if len(raw) > MAX_INPUT_BYTES:
        raise MatrixInputError("input_exceeds_size_cap")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatrixInputError("input_not_json") from exc
    if not isinstance(value, Mapping):
        raise MatrixInputError("input_root_not_object")
    return value


def _safe_input_path(path: Path, *, root: Path = ROOT) -> Path:
    resolved = path.expanduser().resolve()
    worktree = root.expanduser().resolve()
    if path.expanduser().is_symlink():
        raise MatrixInputError("input_symlink_not_allowed")
    try:
        resolved.relative_to(worktree)
    except ValueError as exc:
        raise MatrixInputError("input_outside_worktree") from exc
    lowered = "/".join(part.lower() for part in resolved.parts)
    if any(marker in lowered for marker in ("/.env", "/credentials/", "/secrets/", "/artifacts/")):
        raise MatrixInputError("sensitive_input_path")
    if not resolved.is_file():
        raise MatrixInputError("input_unavailable")
    return resolved


def render_markdown(matrix: Mapping[str, Any]) -> str:
    def safe(value: Any) -> str:
        return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("`", "\\`").replace("<", "&lt;").replace(">", "&gt;")

    lines = [
        "# MarketOS Portfolio Conformance Matrix",
        "",
        f"- Schema: `{matrix['schema']}`",
        f"- Repository: `{safe(matrix['repository'])}`",
        f"- origin/main: `{safe(matrix.get('origin_main') or 'unavailable')}`",
        f"- Portfolio status: **{safe(matrix['portfolio_status'])}**",
        f"- Merge authority: `{safe(matrix['merge_authority'])}`",
        f"- Matrix fingerprint: `{safe(matrix['fingerprint'])}`",
        "",
        "## Proposed Order",
        "",
        " -> ".join(f"#{safe(number)}" for number in matrix.get("merge_order", [])) or "No safe order established.",
        "",
        "## Pull Requests",
        "",
        "| PR | State | Ancestry | CI | Local evidence | Blockers |",
        "|---:|---|---|---|---|---:|",
    ]
    for pr in matrix.get("pull_requests", []):
        blockers = ", ".join(safe(item) for item in pr["blockers"][:6]) or "none"
        lines.append(
            f"| #{safe(pr['number'])} | {safe(pr['state'])}{' (draft)' if pr['is_draft'] else ''} | "
            f"{safe(pr['ancestry']['classification'])} | {safe(pr['ci']['classification'])} | "
            f"{safe(pr['local_evidence']['classification'])} / {safe(pr['local_evidence']['status'])} | {blockers} |"
        )
    lines.extend(["", "## Overlap", "", f"Changed-file owners: `{matrix['overlap']['changed_file_owner_count']}`"])
    for collision in matrix["overlap"]["collisions"][:20]:
        lines.append(f"- `{safe(collision['path'])}`: {', '.join(f'#{safe(number)}' for number in collision['pull_requests'])}")
    lines.extend(["", "## Blockers", ""])
    lines.extend(f"- `{safe(item)}`" for item in matrix["blockers"][:80])
    lines.extend(["", f"**Next action:** {safe(matrix['next_action'])}", "", "This matrix is read-only evidence. It does not authorize merge or replace PR readiness.", ""])
    rendered = "\n".join(lines)
    if len(rendered) > MAX_OUTPUT_CHARS:
        rendered = rendered[: MAX_OUTPUT_CHARS - 40] + "\n\n[output bounded]\n"
    return rendered


def render_json(matrix: Mapping[str, Any]) -> str:
    """Render valid bounded JSON, reducing detail rather than truncating JSON."""
    rendered = json.dumps(matrix, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    if len(rendered) <= MAX_OUTPUT_CHARS:
        return rendered
    reduced = {
        "schema": matrix["schema"],
        "report_version": matrix["report_version"],
        "generated_at": matrix["generated_at"],
        "repository": matrix["repository"],
        "origin_main": matrix.get("origin_main"),
        "input_origin_main": matrix.get("input_origin_main"),
        "repository_state": matrix.get("repository_state", {}),
        "input": matrix.get("input", {}),
        "pull_request_count": len(matrix.get("pull_requests", [])),
        "pull_requests": [
            {
                "number": item["number"],
                "state": item["state"],
                "ancestry": item["ancestry"]["classification"],
                "ci": item["ci"]["classification"],
                "local_evidence": item["local_evidence"]["classification"],
                "blockers": item["blockers"][:6],
            }
            for item in matrix.get("pull_requests", [])
        ],
        "overlap": {"collision_count": len(matrix.get("overlap", {}).get("collisions", []))},
        "duplicate_authority_indicator_count": len(matrix.get("duplicate_authority_indicators", [])),
        "merge_order": matrix.get("merge_order", []),
        "blockers": matrix.get("blockers", [])[:80],
        "evidence_classifications": matrix.get("evidence_classifications", {}),
        "portfolio_status": matrix["portfolio_status"],
        "merge_authority": matrix["merge_authority"],
        "merge_authorized": False,
        "next_action": matrix["next_action"],
        "output_bounded": True,
        "output_omitted": "changed file lists and detailed per-job CI metadata",
    }
    reduced["fingerprint"] = _fingerprint(reduced)
    rendered = json.dumps(reduced, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    if len(rendered) <= MAX_OUTPUT_CHARS:
        return rendered
    minimal = {
        "schema": matrix["schema"],
        "report_version": matrix["report_version"],
        "generated_at": matrix["generated_at"],
        "repository": matrix["repository"],
        "origin_main": matrix.get("origin_main"),
        "portfolio_status": matrix["portfolio_status"],
        "merge_authority": matrix["merge_authority"],
        "merge_authorized": False,
        "pull_request_count": len(matrix.get("pull_requests", [])),
        "blocker_count": len(matrix.get("blockers", [])),
        "output_bounded": True,
        "output_omitted": "portfolio rows, changed files, CI jobs, and detailed blockers",
    }
    minimal["fingerprint"] = _fingerprint(minimal)
    return json.dumps(minimal, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"


def _error_payload(error: str, *, repository_state: Mapping[str, Any]) -> dict[str, Any]:
    report = build_matrix(None, repository_state={**repository_state, "classification": "unavailable"})
    report.update({
        "input": {"classification": "malformed", "schema": None, "error": error},
        "blockers": ["portfolio_input_malformed"],
        "portfolio_status": "malformed",
        "next_action": "repair the sanitized portfolio adapter input and rerun the matrix",
    })
    report["fingerprint"] = _fingerprint(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="bounded sanitized portfolio metadata JSON; no GitHub calls are made")
    parser.add_argument("--root", type=Path, default=ROOT, help="local worktree used only for read-only git identity")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true")
    output.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    repository_state = collect_repository_state(args.root.resolve())
    if args.input is None:
        matrix = build_matrix(None, repository_state=repository_state)
    else:
        try:
            payload = load_input(_safe_input_path(args.input, root=args.root))
        except MatrixInputError as exc:
            matrix = _error_payload(exc.code, repository_state=repository_state)
        else:
            matrix = build_matrix(payload, repository_state=repository_state)
    rendered = render_markdown(matrix) if args.markdown else render_json(matrix)
    sys.stdout.write(rendered)
    return 2 if matrix["portfolio_status"] == "malformed" else 0


if __name__ == "__main__":
    raise SystemExit(main())

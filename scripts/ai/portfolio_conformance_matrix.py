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
import unicodedata
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
    r"(?:(?<![A-Za-z0-9])|(?<=%[0-9A-Fa-f]{2})|(?<=\\[nrt]))sk-(?:live|test)?-?[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|bearer\s+[A-Za-z0-9._-]{10,}|"
    r"(?:https?|postgres(?:ql)?|redis)://[^:]+:[^@]+@)"
)
SENSITIVE_KEY_RE = re.compile(r"(?i)(password|secret|token|api[_-]?key|private[_-]?key|authorization|credential)")
UNSAFE_TEXT_RE = re.compile(r"[\x00-\x1f\x7f\u200b\u200c\u200d\u202a-\u202e\u2060\u2066-\u2069\ufeff]")
SECRET_ASSIGNMENT_RE = re.compile(r"(?i)(password|secret|token|api[_-]?key|private[_-]?key|authorization|credential)\s*[:=]\s*\S+")
NON_CI_MARKERS = ("netlify", "deploy-preview", "deploy_preview", "preview-deploy")

RUN_STATUSES = frozenset({"not_created", "queued", "in_progress", "completed", "waiting", "requested", "pending", "cancelled"})
CONCLUSIONS = frozenset({"success", "passed", "failure", "failed", "neutral", "cancelled", "skipped", "timed_out", "action_required", "stale", "startup_failure", "pending"})
CHECK_STATUSES = frozenset({"success", "passed", "failure", "failed", "neutral", "cancelled", "skipped", "pending", "timed_out"})
LOG_STATUSES = frozenset({"available", "missing", "not_found", "forbidden", "unavailable", "not_queried"})
PENDING_STATUSES = frozenset({"queued", "in_progress", "waiting", "requested", "pending"})
STEP_SUCCESS_STATUSES = frozenset({"completed", "success"})
STEP_INCOMPLETE_STATUSES = frozenset({"failure", "failed", "cancelled", "skipped", "timed_out", "action_required", "startup_failure"})
STEP_STATUSES = STEP_SUCCESS_STATUSES | STEP_INCOMPLETE_STATUSES | PENDING_STATUSES
CI_REPORT_CLASSIFICATIONS = frozenset(
    {
        "pass",
        "ci_unavailable",
        "executed_failure",
        "timed_out",
        "pending",
        "malformed",
    }
)
CI_REPORT_JOB_CLASSIFICATIONS = CI_REPORT_CLASSIFICATIONS | frozenset(
    {
        "zero_step_runnerless",
        "incomplete_steps",
        "unavailable_logs",
        "stale_metadata",
        "stale_job_metadata",
        "stale_worktree_metadata",
        "missing_workflow_context",
        "workflow_never_created",
        "non_ci_workflow",
        "required_job_missing",
        "unbound_check_metadata",
        "not_ci",
    }
)
CI_REPORT_JOB_KEYS = frozenset(
    {
        "name",
        "required",
        "status",
        "conclusion",
        "classification",
        "execution_classification",
        "identity_classification",
        "context_classification",
        "reason",
        "runner_assigned",
        "steps_executed",
        "step_outcome",
        "logs_available",
        "log_status",
        "log_http_status",
    }
)

CI_STATUSES = RUN_STATUSES
CI_CONCLUSIONS = CONCLUSIONS
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


def _normalized_marker_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


def _is_non_ci_name(value: str) -> bool:
    normalized = _normalized_marker_text(value)
    return any(marker in normalized for marker in NON_CI_MARKERS)


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


def _normalize_steps(value: Any) -> tuple[int, str]:
    if not isinstance(value, list) or len(value) > MAX_STEPS_PER_JOB:
        raise MatrixInputError("invalid_ci_steps")
    step_statuses: list[str] = []
    for item in value:
        if isinstance(item, str):
            _text(item, field="ci_step", limit=120)
            status = "completed"
        elif isinstance(item, Mapping):
            _check_keys(item, {"name", "status"})
            _text(item.get("name"), field="ci_step_name", limit=120)
            status = "completed"
            if item.get("status") is not None:
                status = _text(item["status"], field="ci_step_status", limit=40).lower()
        else:
            raise MatrixInputError("invalid_ci_step")
        if status not in STEP_STATUSES:
            raise MatrixInputError("invalid_ci_step_status")
        step_statuses.append(status)
    if any(status in STEP_INCOMPLETE_STATUSES for status in step_statuses):
        step_outcome = "incomplete"
    elif any(status in PENDING_STATUSES for status in step_statuses):
        step_outcome = "pending"
    else:
        step_outcome = "success"
    return len(value), step_outcome


def _normalize_ci_job(value: Any, required_names: set[str], expected_head_sha: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MatrixInputError("invalid_ci_job")
    _check_keys(
        value,
        {
            "name",
            "workflow_name",
            "workflow_conclusion",
            "kind",
            "status",
            "conclusion",
            "required",
            "head_sha",
            "runner_id",
            "steps",
            "steps_executed",
            "step_outcome",
            "logs_available",
            "log_status",
            "required_check_status",
        },
    )
    name = _text(value.get("name"), field="ci_job_name", limit=160)
    workflow_name = _optional_text(value.get("workflow_name"), field="ci_workflow_name", limit=180)
    workflow_conclusion = _optional_text(value.get("workflow_conclusion"), field="ci_workflow_conclusion", limit=40)
    if workflow_conclusion is not None:
        workflow_conclusion = workflow_conclusion.lower()
        if workflow_conclusion not in CONCLUSIONS:
            raise MatrixInputError("invalid_ci_workflow_conclusion")
    kind = _text(value.get("kind", "ci"), field="ci_job_kind", limit=40).lower()
    if kind == "ci" and (_is_non_ci_name(name) or (workflow_name and _is_non_ci_name(workflow_name))):
        kind = "deploy_preview"
    if kind not in {"ci", "deploy_preview", "non_ci"}:
        raise MatrixInputError("invalid_ci_job_kind")
    if kind != "ci" and value.get("required") is True:
        raise MatrixInputError("non_ci_job_cannot_be_required")
    status = _text(value.get("status"), field="ci_job_status", limit=40).lower()
    if status not in RUN_STATUSES:
        raise MatrixInputError("invalid_ci_job_status")
    conclusion = value.get("conclusion")
    if conclusion is not None:
        conclusion = _text(conclusion, field="ci_job_conclusion", limit=40).lower()
        if conclusion not in CONCLUSIONS:
            raise MatrixInputError("invalid_ci_job_conclusion")
    required = value.get("required", name in required_names and kind == "ci")
    if not isinstance(required, bool):
        raise MatrixInputError("invalid_ci_required_flag")
    if required != (name in required_names and kind == "ci"):
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
    step_count, derived_step_outcome = _normalize_steps(value["steps"]) if steps_present else (None, "success")
    if count_present:
        raw_count = value["steps_executed"]
        if not isinstance(raw_count, int) or isinstance(raw_count, bool) or raw_count < 0 or raw_count > MAX_STEPS_PER_JOB:
            raise MatrixInputError("invalid_steps_executed")
        if step_count is not None and step_count != raw_count:
            raise MatrixInputError("ci_step_count_mismatch")
        step_count = raw_count
    explicit_step_outcome = value.get("step_outcome")
    if explicit_step_outcome is not None:
        explicit_step_outcome = _text(explicit_step_outcome, field="step_outcome", limit=40).lower()
        if explicit_step_outcome not in {"success", "incomplete", "pending"}:
            raise MatrixInputError("invalid_step_outcome")
        if steps_present and explicit_step_outcome != derived_step_outcome:
            raise MatrixInputError("contradictory_step_outcome_metadata")
        step_outcome = explicit_step_outcome
    else:
        step_outcome = derived_step_outcome

    logs_available = value.get("logs_available")
    if logs_available is not None and not isinstance(logs_available, bool):
        raise MatrixInputError("invalid_logs_available")
    log_status = value.get("log_status")
    if log_status is not None:
        log_status = _text(log_status, field="log_status", limit=40).lower()
        if log_status not in LOG_STATUSES:
            raise MatrixInputError("invalid_log_status")
        if logs_available is not None and logs_available != (log_status == "available"):
            raise MatrixInputError("contradictory_log_metadata")
        if logs_available is None:
            logs_available = log_status == "available"

    required_check_status = value.get("required_check_status")
    if required_check_status is not None:
        required_check_status = _text(required_check_status, field="required_check_status", limit=40).lower()
        if required_check_status not in CHECK_STATUSES:
            raise MatrixInputError("invalid_required_check_status")

    if status in {"queued", "pending", "waiting"}:
        if conclusion is not None or step_count != 0 or runner_id not in {None, 0} or logs_available is True:
            raise MatrixInputError("contradictory_pending_ci_metadata")
        if required_check_status not in {None, "pending"}:
            raise MatrixInputError("contradictory_pending_ci_metadata")
    elif status == "in_progress":
        if conclusion is not None or runner_id in {None, 0} or logs_available is True:
            raise MatrixInputError("contradictory_in_progress_ci_metadata")
        if required_check_status not in {None, "pending"}:
            raise MatrixInputError("contradictory_in_progress_ci_metadata")
    elif status == "completed":
        if conclusion is None:
            raise MatrixInputError("missing_completed_ci_conclusion")
        if required_check_status == "pending":
            raise MatrixInputError("contradictory_completed_ci_metadata")
    elif status == "cancelled":
        if conclusion != "cancelled":
            raise MatrixInputError("contradictory_cancelled_ci_metadata")
    elif status == "not_created":
        if conclusion is not None or step_count != 0 or runner_id not in {None, 0} or logs_available is True:
            raise MatrixInputError("contradictory_not_created_ci_metadata")

    return {
        "name": name,
        "workflow_name": workflow_name,
        "workflow_conclusion": workflow_conclusion,
        "kind": kind,
        "status": status,
        "conclusion": conclusion,
        "required": required,
        "head_sha": head_sha,
        "runner_id": runner_id,
        "steps_executed": step_count,
        "step_outcome": step_outcome,
        "logs_available": logs_available,
        "log_status": log_status,
        "required_check_status": required_check_status,
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


def _normalize_economics(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise MatrixInputError("invalid_economics")
    _check_keys(value, {"gross_margin", "estimated_revenue", "estimated_cost", "currency", "evidence_state"})
    currency = _optional_text(value.get("currency"), field="economics_currency", limit=10)
    evidence_state = _text(value.get("evidence_state", "unknown"), field="economics_evidence_state", limit=30)
    margin = value.get("gross_margin")
    if margin is not None and (not isinstance(margin, (int, float, str)) or isinstance(margin, bool)):
        raise MatrixInputError("invalid_economics_margin")
    is_explicit_zero = False
    if margin is not None:
        try:
            is_explicit_zero = float(margin) == 0.0
        except ValueError:
            raise MatrixInputError("invalid_economics_margin") from None
    classification = "explicit_zero" if is_explicit_zero else ("provided" if margin is not None else "missing")
    return {
        "currency": currency,
        "gross_margin": str(margin) if margin is not None else None,
        "evidence_state": evidence_state,
        "classification": classification,
    }


def _normalize_workflow(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise MatrixInputError("invalid_workflow")
    _check_keys(value, {"name", "status", "conclusion", "run_id", "head_sha", "base_sha", "created_at", "updated_at", "url"})
    name = _text(value.get("name"), field="workflow_name", limit=180)
    status = _text(value.get("status"), field="workflow_status", limit=40).lower()
    if status not in RUN_STATUSES:
        raise MatrixInputError("invalid_workflow_status")
    conclusion = value.get("conclusion")
    if conclusion is not None:
        conclusion = _text(conclusion, field="workflow_conclusion", limit=40).lower()
        if conclusion not in CONCLUSIONS:
            raise MatrixInputError("invalid_workflow_conclusion")
    return {"name": name, "status": status, "conclusion": conclusion}


def _normalize_check(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MatrixInputError("invalid_check")
    _check_keys(value, {"name", "kind", "status", "conclusion", "url"})
    name = _text(value.get("name"), field="check_name", limit=180)
    kind = _text(value.get("kind", "ci"), field="check_kind", limit=40).lower()
    if kind == "ci" and _is_non_ci_name(name):
        kind = "deploy_preview"
    status = _text(value.get("status"), field="check_status", limit=40).lower()
    conclusion = value.get("conclusion")
    if conclusion is not None:
        conclusion = _text(conclusion, field="check_conclusion", limit=40).lower()
    return {"name": name, "kind": kind, "status": status, "conclusion": conclusion}


def _normalize_ci_report_jobs(value: Any, required_jobs: list[str], classification: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_JOBS_PER_PR:
        raise MatrixInputError("invalid_ci_report_jobs")
    normalized: list[dict[str, Any]] = []
    names: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise MatrixInputError("invalid_ci_report_job")
        _check_keys(item, set(CI_REPORT_JOB_KEYS))
        name = _text(item.get("name"), field="ci_report_job_name", limit=160)
        if name in names:
            raise MatrixInputError("duplicate_ci_report_job")
        names.add(name)
        job_classification = _text(item.get("classification"), field="ci_report_job_classification", limit=50)
        if job_classification not in CI_REPORT_JOB_CLASSIFICATIONS:
            raise MatrixInputError("invalid_ci_report_job_classification")
        required = item.get("required", False)
        if not isinstance(required, bool):
            raise MatrixInputError("invalid_ci_report_job_required_flag")
        normalized_item: dict[str, Any] = {
            "name": name,
            "required": required,
            "classification": job_classification,
        }
        for field in ("status", "conclusion", "execution_classification", "identity_classification", "context_classification", "reason", "step_outcome", "log_status"):
            if field in item and item[field] is not None:
                normalized_item[field] = _text(item[field], field=f"ci_report_{field}", limit=120)
        for field in ("runner_assigned", "logs_available"):
            if field in item:
                if not isinstance(item[field], bool):
                    raise MatrixInputError(f"invalid_ci_report_{field}")
                normalized_item[field] = item[field]
        if "steps_executed" in item:
            steps = item["steps_executed"]
            if not isinstance(steps, int) or isinstance(steps, bool) or steps < 0 or steps > MAX_STEPS_PER_JOB:
                raise MatrixInputError("invalid_ci_report_steps_executed")
            normalized_item["steps_executed"] = steps
        if "log_http_status" in item:
            status_code = item["log_http_status"]
            if not isinstance(status_code, int) or isinstance(status_code, bool) or not 100 <= status_code <= 599:
                raise MatrixInputError("invalid_ci_report_log_http_status")
            normalized_item["log_http_status"] = status_code
        normalized.append(normalized_item)

    return normalized


def _ci_report_jobs_admissible(jobs: list[Mapping[str, Any]], required_jobs: list[str]) -> bool:
    by_name = {item["name"]: item for item in jobs}
    for required_name in required_jobs:
        job = by_name.get(required_name)
        if job is None or (
            job["required"] is not True
            or job["classification"] != "pass"
            or job.get("execution_classification", "pass") != "pass"
            or job.get("runner_assigned") is not True
            or not isinstance(job.get("steps_executed"), int)
            or job["steps_executed"] <= 0
            or job.get("step_outcome", "success") != "success"
            or job.get("logs_available") is not True
            or job.get("log_status", "available") != "available"
            or job.get("status", "passed") != "passed"
            or job.get("conclusion", "success") != "success"
        ):
            return False
    return True


def _normalize_ci_report(value: Any, expected_head_sha: str, expected_base_sha: str | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MatrixInputError("invalid_ci_report")
    _check_keys(
        value,
        {
            "schema",
            "report_version",
            "generated_at",
            "source_schema",
            "repository",
            "candidate_head_sha",
            "target_head_sha",
            "target_base_sha",
            "workflow",
            "required_policy",
            "status",
            "classification",
            "reason",
            "diagnostic_state",
            "diagnostic_states",
            "context_classification",
            "required_jobs",
            "missing_required_jobs",
            "required_checks",
            "jobs",
            "non_ci_checks",
            "redacted_url_count",
            "admissible_evidence",
            "authority",
            "blockers",
            "operator_action",
            "fingerprint",
            "limits",
        },
    )
    schema = _text(value.get("schema"), field="ci_report_schema", limit=60)
    if schema != "MarketOS.CIAdmissibilityReport.v1":
        raise MatrixInputError("unsupported_ci_report_schema")
    candidate_head = value.get("candidate_head_sha")
    if candidate_head is not None and _sha(candidate_head, field="ci_report_candidate_head_sha") != expected_head_sha:
        raise MatrixInputError("ci_report_head_sha_mismatch")
    target_head = value.get("target_head_sha")
    if target_head is not None and _sha(target_head, field="ci_report_target_head_sha") != expected_head_sha:
        raise MatrixInputError("ci_report_head_sha_mismatch")
    target_base = value.get("target_base_sha")
    if target_base is not None and expected_base_sha is not None and _sha(target_base, field="ci_report_target_base_sha") != expected_base_sha:
        raise MatrixInputError("ci_report_base_sha_mismatch")
    classification = _text(value.get("classification"), field="ci_report_classification", limit=40)
    if classification not in CI_REPORT_CLASSIFICATIONS:
        raise MatrixInputError("invalid_ci_report_classification")
    status = _text(value.get("status"), field="ci_report_status", limit=40)
    admissible = value.get("admissible_evidence")
    if not isinstance(admissible, bool):
        raise MatrixInputError("invalid_ci_report_admissible_evidence")
    diagnostic_state = _optional_text(value.get("diagnostic_state"), field="ci_report_diagnostic_state", limit=60)
    diagnostic_states = value.get("diagnostic_states", [])
    if not isinstance(diagnostic_states, list):
        raise MatrixInputError("invalid_ci_report_diagnostic_states")

    # Audit for contradictions: diagnostic fields cannot contradict authoritative classification/status/admissibility
    if diagnostic_state == "pass" and classification != "pass":
        raise MatrixInputError("contradictory_ci_diagnostic_metadata")
    if "pass" in diagnostic_states and classification != "pass":
        raise MatrixInputError("contradictory_ci_diagnostic_metadata")
    if admissible is True and classification != "pass":
        raise MatrixInputError("contradictory_ci_diagnostic_metadata")
    if classification == "pass" and (status != "passed" or admissible is not True):
        raise MatrixInputError("contradictory_ci_diagnostic_metadata")
    workflow = value.get("workflow")
    if isinstance(workflow, Mapping):
        wf_conc = workflow.get("conclusion")
        if isinstance(wf_conc, str) and wf_conc.lower() in {"failure", "failed", "cancelled", "startup_failure"} and classification == "pass":
            raise MatrixInputError("contradictory_ci_diagnostic_metadata")

    required_jobs = _string_list(value.get("required_jobs", []), field="ci_report_required_jobs", limit=MAX_JOBS_PER_PR, item_limit=160)
    normalized_jobs = _normalize_ci_report_jobs(value.get("jobs", []), required_jobs, classification)
    return {
        "schema": schema,
        "classification": classification,
        "status": status,
        "admissible_evidence": admissible,
        "diagnostic_state": diagnostic_state or classification,
        "diagnostic_states": sorted({_text(s, field="diagnostic_state_item", limit=60) for s in diagnostic_states}) if diagnostic_states else [diagnostic_state or classification],
        "required_jobs": required_jobs,
        "missing_required_jobs": _string_list(value.get("missing_required_jobs", []), field="ci_report_missing_jobs", limit=MAX_JOBS_PER_PR, item_limit=160),
        "jobs": normalized_jobs,
        "non_ci_checks": value.get("non_ci_checks", []),
    }


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
        "ci_report",
        "workflow",
        "workflow_conclusion",
        "checks",
        "local_evidence",
        "authority_claims",
        "workspace_id",
        "candidate_id",
        "client_id",
        "economics",
    }
    _check_keys(value, allowed)
    number = value.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        raise MatrixInputError("invalid_pull_request_number")
    state = _text(value.get("state"), field="pull_request_state", limit=20).lower()
    if state not in {"open", "closed", "merged"}:
        raise MatrixInputError("invalid_pull_request_state")
    head_sha = _sha(value.get("head_sha"), field="head_sha")
    base_sha = _sha(value.get("base_sha"), field="base_sha")

    ci_report = _normalize_ci_report(value["ci_report"], head_sha, base_sha) if "ci_report" in value else None

    raw_required = value.get("required_checks")
    if raw_required is None and ci_report is not None and ci_report.get("required_jobs"):
        required_checks = sorted(ci_report["required_jobs"])
    else:
        required_checks = _string_list(raw_required or [], field="required_checks", limit=MAX_JOBS_PER_PR, item_limit=160)
    if not required_checks:
        raise MatrixInputError("empty_required_checks")
    for item in required_checks:
        if _is_non_ci_name(item):
            raise MatrixInputError("non_ci_check_in_required_checks")
    required_checks_source = _text(value.get("required_checks_source", "branch_protection_adapter"), field="required_checks_source", limit=60)
    if required_checks_source != "branch_protection_adapter":
        raise MatrixInputError("untrusted_required_checks_source")

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
    workspace_id = _optional_text(value.get("workspace_id"), field="workspace_id", limit=100)
    candidate_id = _optional_text(value.get("candidate_id"), field="candidate_id", limit=100)
    client_id = _optional_text(value.get("client_id"), field="client_id", limit=100)
    economics = _normalize_economics(value.get("economics")) if "economics" in value else None
    workflow = _normalize_workflow(value.get("workflow")) if "workflow" in value else None
    workflow_conclusion = value.get("workflow_conclusion")
    if workflow_conclusion is not None:
        workflow_conclusion = _text(workflow_conclusion, field="workflow_conclusion", limit=40).lower()
        if workflow_conclusion not in CONCLUSIONS:
            raise MatrixInputError("invalid_workflow_conclusion")
    checks_raw = value.get("checks", [])
    if not isinstance(checks_raw, list) or len(checks_raw) > MAX_JOBS_PER_PR:
        raise MatrixInputError("invalid_checks")
    checks = [_normalize_check(c) for c in checks_raw]

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
        "workspace_id": workspace_id,
        "candidate_id": candidate_id,
        "client_id": client_id,
        "economics": economics,
        "changed_files": sorted({_path(item) for item in changed_files}),
        "depends_on": dependencies,
        "required_checks": required_checks,
        "required_checks_source": required_checks_source,
        "ci_jobs": jobs,
        "ci_report": ci_report,
        "workflow": workflow,
        "workflow_conclusion": workflow_conclusion,
        "checks": checks,
        "local_evidence": _normalize_local_evidence(value.get("local_evidence")),
        "authority_claims": _string_list(value.get("authority_claims", []), field="authority_claims", limit=20, item_limit=100),
    }


def normalize_input(value: Any) -> dict[str, Any]:
    """Validate and normalize a sanitized adapter payload."""
    if not isinstance(value, Mapping):
        raise MatrixInputError("input_root_not_object")
    _check_keys(value, {"schema", "repository", "origin_main", "pull_requests", "workspace_id", "client_id"})
    if value.get("schema") != INPUT_SCHEMA:
        raise MatrixInputError("unsupported_input_schema")
    repository = _text(value.get("repository"), field="repository", limit=200)
    origin_main = _sha(value.get("origin_main"), field="origin_main")
    root_workspace = _optional_text(value.get("workspace_id"), field="workspace_id", limit=100)
    root_client = _optional_text(value.get("client_id"), field="client_id", limit=100)
    raw_prs = value.get("pull_requests")
    if not isinstance(raw_prs, list) or len(raw_prs) > MAX_PRS:
        raise MatrixInputError("invalid_pull_requests")
    prs = [_normalize_pr(item) for item in raw_prs]
    numbers = [item["number"] for item in prs]
    if len(set(numbers)) != len(numbers):
        raise MatrixInputError("duplicate_pull_request_number")

    workspaces = {pr["workspace_id"] for pr in prs if pr.get("workspace_id")}
    if root_workspace:
        workspaces.add(root_workspace)
    if len(workspaces) > 1:
        raise MatrixInputError("cross_workspace_portfolio_rows")

    clients = {pr["client_id"] for pr in prs if pr.get("client_id")}
    if root_client:
        clients.add(root_client)
    if len(clients) > 1:
        raise MatrixInputError("cross_client_portfolio_rows")

    result = {
        "schema": INPUT_SCHEMA,
        "repository": repository,
        "origin_main": origin_main,
        "pull_requests": sorted(prs, key=lambda item: item["number"]),
    }
    if root_workspace:
        result["workspace_id"] = root_workspace
    if root_client:
        result["client_id"] = root_client
    return result



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
    step_outcome = job.get("step_outcome", "success")
    required_check_status = job.get("required_check_status")

    if status == "not_created":
        return "zero_step_runnerless"
    if status in PENDING_STATUSES or required_check_status in PENDING_STATUSES or step_outcome == "pending":
        return "pending"
    if steps == 0 or runner is None or runner == 0:
        return "zero_step_runnerless"
    if status not in {"completed", "cancelled"} or conclusion is None:
        return "malformed"
    if conclusion in {"timed_out"} or required_check_status == "timed_out":
        return "timed_out"
    if conclusion in {"failure", "failed", "cancelled"} or required_check_status in {"failure", "failed", "cancelled"}:
        return "executed_failure"
    if step_outcome == "incomplete":
        return "incomplete_steps"
    if conclusion in {"success", "passed"}:
        if required_check_status is not None and required_check_status not in {"success", "passed"}:
            return "executed_failure" if required_check_status in {"failure", "failed", "cancelled"} else "ci_unavailable"
        return "pass" if job["logs_available"] is True else "unavailable_logs"
    return "malformed"


def _ci_projection(pr: Mapping[str, Any]) -> dict[str, Any]:
    if pr.get("ci_report"):
        report = pr["ci_report"]
        classification = report["classification"]
        status = report["status"]
        admissible = report["admissible_evidence"]
        diagnostic_state = report["diagnostic_state"]
        diagnostic_states = list(report["diagnostic_states"])
        report_required = set(report.get("required_jobs", []))
        pr_required = set(pr["required_checks"])
        missing_from_report = pr_required - report_required
        missing = sorted(set(report.get("missing_required_jobs", [])) | missing_from_report)
        required_checks = sorted(pr_required | report_required)

        workflow_conclusion = pr.get("workflow_conclusion")
        if not workflow_conclusion and pr.get("workflow"):
            workflow_conclusion = pr["workflow"].get("conclusion")

        check_failures = False
        check_timeouts = False
        check_pending = False
        for check in pr.get("checks", []):
            if check.get("name") in required_checks and check.get("kind", "ci") == "ci":
                c_status = check.get("status")
                c_conc = check.get("conclusion")
                if c_status in PENDING_STATUSES or c_conc in PENDING_STATUSES:
                    check_pending = True
                elif c_conc in {"failure", "failed", "cancelled"}:
                    check_failures = True
                elif c_conc == "timed_out":
                    check_timeouts = True

        if classification == "malformed":
            pass
        elif classification in {"executed_failure", "timed_out"} or check_failures or (workflow_conclusion in {"failure", "failed", "cancelled", "startup_failure"}):
            classification = "executed_failure" if (classification == "executed_failure" or check_failures or (workflow_conclusion in {"failure", "failed", "cancelled", "startup_failure"})) else "timed_out"
            status = "failed" if classification == "executed_failure" else "timed_out"
            admissible = False
        elif classification == "pending" or check_pending or (workflow_conclusion in PENDING_STATUSES):
            classification = "pending"
            status = "pending"
            admissible = False
        elif missing or (workflow_conclusion and workflow_conclusion != "success"):
            classification = "ci_unavailable"
            status = "unavailable"
            admissible = False
        elif classification == "pass" and _ci_report_jobs_admissible(report["jobs"], sorted(report_required)):
            classification = "pass"
            status = "passed"
            admissible = True
        else:
            classification = "ci_unavailable"
            status = "unavailable"
            admissible = False

        if classification != "pass":
            diagnostic_states = [s for s in diagnostic_states if s != "pass"]
            for m in missing:
                diagnostic_states.append(f"missing_required:{m}")
            if workflow_conclusion and workflow_conclusion != "success":
                diagnostic_states.append(f"workflow_{workflow_conclusion}")
            if check_failures:
                diagnostic_states.append("required_check_failure")
            if check_timeouts:
                diagnostic_states.append("required_check_timeout")
            if check_pending:
                diagnostic_states.append("required_check_pending")
            diagnostic_states = sorted(set(diagnostic_states)) or [classification]
            diagnostic_state = diagnostic_states[0] if len(diagnostic_states) == 1 else "mixed"
        else:
            diagnostic_state = "pass"
            diagnostic_states = ["pass"]

        return {
            "classification": classification,
            "status": status,
            "admissible_evidence": admissible,
            "diagnostic_state": diagnostic_state,
            "diagnostic_states": diagnostic_states,
            "required_checks": required_checks,
            "required_checks_source": pr["required_checks_source"],
            "missing_required": missing,
            "jobs": report["jobs"],
            "non_ci_checks": report["non_ci_checks"],
        }

    jobs = []
    for job in pr["ci_jobs"]:
        classification = _job_classification(job)
        jobs.append(
            {
                "name": job["name"],
                "workflow_name": job.get("workflow_name"),
                "kind": job.get("kind", "ci"),
                "required": job["required"],
                "status": job["status"],
                "conclusion": job["conclusion"],
                "head_sha": job["head_sha"],
                "classification": classification,
                "steps_executed": job["steps_executed"],
                "step_outcome": job.get("step_outcome"),
                "runner_assigned": bool(job["runner_id"] and job["runner_id"] > 0),
                "logs_available": job["logs_available"],
                "required_check_status": job.get("required_check_status"),
            }
        )
    ci_jobs_only = [job for job in jobs if job.get("kind") == "ci"]
    non_ci_checks = [job for job in jobs if job.get("kind") in {"deploy_preview", "non_ci"}]
    names = {job["name"] for job in ci_jobs_only}
    missing = sorted(set(pr["required_checks"]) - names)
    required = [job for job in ci_jobs_only if job["required"]]
    required_classes = [job["classification"] for job in required]

    workflow_conclusion = pr.get("workflow_conclusion")
    if not workflow_conclusion and pr.get("workflow"):
        workflow_conclusion = pr["workflow"].get("conclusion")

    check_failures = False
    check_timeouts = False
    check_pending = False
    for check in pr.get("checks", []):
        if check.get("name") in pr["required_checks"] and check.get("kind", "ci") == "ci":
            c_status = check.get("status")
            c_conc = check.get("conclusion")
            if c_status in PENDING_STATUSES or c_conc in PENDING_STATUSES:
                check_pending = True
            elif c_conc in {"failure", "failed", "cancelled"}:
                check_failures = True
            elif c_conc == "timed_out":
                check_timeouts = True

    if any(item == "malformed" for item in required_classes):
        classification = "malformed"
    elif any(item in {"executed_failure", "timed_out"} for item in required_classes) or check_failures or (workflow_conclusion in {"failure", "failed", "cancelled", "startup_failure"}):
        classification = "executed_failure" if (any(item == "executed_failure" for item in required_classes) or check_failures or (workflow_conclusion in {"failure", "failed", "cancelled", "startup_failure"})) else "timed_out"
    elif any(item == "pending" for item in required_classes) or check_pending or (workflow_conclusion in PENDING_STATUSES):
        classification = "pending"
    elif missing or any(item in {"zero_step_runnerless", "incomplete_steps"} for item in required_classes):
        classification = "ci_unavailable"
    elif any(item == "unavailable_logs" for item in required_classes):
        classification = "unavailable_logs"
    elif workflow_conclusion and workflow_conclusion != "success":
        classification = "ci_unavailable"
    elif required and all(item == "pass" for item in required_classes):
        classification = "pass"
    else:
        classification = "ci_unavailable"

    status = (
        "passed" if classification == "pass"
        else "failed" if classification == "executed_failure"
        else "timed_out" if classification == "timed_out"
        else "pending" if classification == "pending"
        else "malformed" if classification == "malformed"
        else "unavailable"
    )
    admissible = classification == "pass"

    non_pass_states = [c for c in required_classes if c != "pass"]
    if missing:
        non_pass_states.extend(f"missing_required:{name}" for name in missing)
    if workflow_conclusion and workflow_conclusion != "success":
        non_pass_states.append(f"workflow_{workflow_conclusion}")
    if check_failures:
        non_pass_states.append("required_check_failure")
    if check_timeouts:
        non_pass_states.append("required_check_timeout")
    if check_pending:
        non_pass_states.append("required_check_pending")

    if classification == "pass":
        diagnostic_state = "pass"
        diagnostic_states = ["pass"]
    elif len(set(non_pass_states)) == 1:
        diagnostic_state = non_pass_states[0]
        diagnostic_states = sorted(set(non_pass_states))
    elif non_pass_states:
        diagnostic_state = "mixed"
        diagnostic_states = sorted(set(non_pass_states))
    else:
        diagnostic_state = classification
        diagnostic_states = [classification]

    return {
        "classification": classification,
        "status": status,
        "admissible_evidence": admissible,
        "diagnostic_state": diagnostic_state,
        "diagnostic_states": diagnostic_states,
        "required_checks": sorted(pr["required_checks"]),
        "required_checks_source": pr["required_checks_source"],
        "missing_required": missing,
        "jobs": jobs,
        "non_ci_checks": non_ci_checks,
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
    if data.get("workspace_id"):
        base["workspace_id"] = data["workspace_id"]
    if data.get("client_id"):
        base["client_id"] = data["client_id"]
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
                "workspace_id": pr.get("workspace_id"),
                "candidate_id": pr.get("candidate_id"),
                "client_id": pr.get("client_id"),
                "economics": pr.get("economics"),
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

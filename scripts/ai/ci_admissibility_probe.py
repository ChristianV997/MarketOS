"""Classify sanitized CI evidence without querying GitHub or authorizing release.

The existing local quality gate owns ``MarketOS.CIEvidence.v1`` and readiness
semantics.  This module is a reusable evidence projection for operators and
portfolio tools: it preserves execution, runner, log, workflow-identity, and
non-CI distinctions without becoming another merge or deployment authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
INPUT_SCHEMA = "MarketOS.CIAdmissibilityEvidence.v1"
CANONICAL_INPUT_SCHEMA = "MarketOS.CIEvidence.v1"
REPORT_SCHEMA = "MarketOS.CIAdmissibilityReport.v1"
REPORT_VERSION = "ci-admissibility-v1"
MAX_INPUT_BYTES = 64 * 1024
MAX_OUTPUT_CHARS = 120_000
MAX_JOBS = 100
MAX_CHECKS = 100
MAX_STEPS = 200
MAX_NESTING = 64
MAX_STRING = 240

SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
UNSAFE_TEXT_RE = re.compile(r"[\x00-\x1f\x7f\u200b\u200c\u200d\u202a-\u202e\u2060\u2066-\u2069\ufeff]")
SECRET_RE = re.compile(
    r"(?is)(-----begin .*?private key-----|ghp_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,}|"
    r"glpat-[A-Za-z0-9_-]{16,}|xox[baprs]-[A-Za-z0-9-]{12,}|npm_[A-Za-z0-9]{20,}|"
    r"pypi-[A-Za-z0-9_-]{16,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}|"
    r"(?:https?|postgres(?:ql)?|redis|mysql(?:s)?)://[^:/\s]+:[^@\s]+@|"
    r"(?:AKIA|ASIA)[A-Z0-9]{16}|AIza[0-9A-Za-z_-]{20,}|(?:sk|gho|hf)_[A-Za-z0-9_-]{16,}|(?:sk|gho|hf)-[A-Za-z0-9_-]{16,}|"
    r"Bearer\s+[A-Za-z0-9._~+/=-]{16,})"
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(password|secret|token|api[_-]?key|private[_-]?key|authorization|credential|aws_secret_access_key)\s*[:=]\s*\S+"
)

RUN_STATUSES = frozenset({"not_created", "queued", "in_progress", "completed", "waiting", "requested", "pending"})
CONCLUSIONS = frozenset({"success", "failure", "neutral", "cancelled", "skipped", "timed_out", "action_required", "stale", "startup_failure", "pending"})
CHECK_STATUSES = frozenset({"success", "failure", "neutral", "cancelled", "skipped", "pending", "timed_out"})
LOG_STATUSES = frozenset({"available", "missing", "not_found", "forbidden", "unavailable", "not_queried"})
PENDING_STATUSES = frozenset({"queued", "in_progress", "waiting", "requested", "pending"})
NON_CI_MARKERS = ("netlify", "deploy-preview", "deploy_preview", "preview-deploy")
FORBIDDEN_KEYS = frozenset({"body", "comments", "credentials", "environment", "logs", "raw_logs", "stdout", "stderr", "payload", "private_notes"})


class EvidenceInputError(ValueError):
    """A sanitized evidence input failed closed without retaining its value."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceInputError("duplicate_json_key")
        result[key] = value
    return result


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "fingerprint"}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _bounded_input_bytes(value: Any) -> bytes:
    """Bound nesting before canonicalization so hostile structures fail closed."""
    stack: list[tuple[Any, int]] = [(value, 0)]
    seen: set[int] = set()
    while stack:
        current, depth = stack.pop()
        if depth > MAX_NESTING:
            raise EvidenceInputError("input_nesting_exceeds_limit")
        if isinstance(current, Mapping):
            identity = id(current)
            if identity in seen:
                raise EvidenceInputError("input_nesting_exceeds_limit")
            seen.add(identity)
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            identity = id(current)
            if identity in seen:
                raise EvidenceInputError("input_nesting_exceeds_limit")
            seen.add(identity)
            stack.extend((item, depth + 1) for item in current)
    try:
        encoded = _canonical(value).encode("utf-8")
    except (RecursionError, TypeError, ValueError) as exc:
        raise EvidenceInputError("input_nesting_exceeds_limit") from exc
    if len(encoded) > MAX_INPUT_BYTES:
        raise EvidenceInputError("input_exceeds_size_cap")
    return encoded


def _check_keys(value: Mapping[str, Any], allowed: set[str]) -> None:
    if set(value) - allowed or any(key in FORBIDDEN_KEYS for key in value):
        raise EvidenceInputError("unknown_or_forbidden_field")


def _text(value: Any, *, field: str, limit: int = MAX_STRING, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or (not allow_empty and not value) or UNSAFE_TEXT_RE.search(value):
        raise EvidenceInputError(f"invalid_{field}")
    if SECRET_RE.search(value) or SECRET_ASSIGNMENT_RE.search(value):
        raise EvidenceInputError("secret_shaped_input")
    return value


def _optional_text(value: Any, *, field: str, limit: int = MAX_STRING) -> str | None:
    if value is None:
        return None
    return _text(value, field=field, limit=limit)


def _sha(value: Any, *, field: str, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise EvidenceInputError(f"invalid_{field}")
    return value.lower()


def _digest(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise EvidenceInputError(f"invalid_{field}")
    return value.lower()


def _positive_int(value: Any, *, field: str, required: bool = True) -> int | None:
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EvidenceInputError(f"invalid_{field}")
    return value


def _timestamp(value: Any, *, field: str, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    text = _text(value, field=field, limit=80)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T[^\s]+(?:Z|[+-]\d{2}:\d{2})", text):
        raise EvidenceInputError(f"invalid_{field}")
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceInputError(f"invalid_{field}") from exc
    return text


def _redact_url(value: Any) -> tuple[str, bool]:
    if not isinstance(value, str) or not value or len(value) > 800 or UNSAFE_TEXT_RE.search(value):
        raise EvidenceInputError("invalid_url")
    text = value
    try:
        parts = urlsplit(text)
    except ValueError:
        return "[redacted-url]", True
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise EvidenceInputError("invalid_url")
    try:
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        has_credentials = parts.username is not None or parts.password is not None
    except ValueError:
        return "[redacted-url]", True
    query_keys = {name.casefold() for name, _ in parse_qsl(parts.query, keep_blank_values=True)}
    sensitive_query = any(
        key in {"token", "access_token", "api_key", "x-api-key", "key", "sig", "signature", "client_secret", "password", "secret"}
        or key.endswith(("_token", "_key", "_secret", "_signature"))
        for key in query_keys
    )
    sensitive_path = bool(re.search(r"/(?:token|key|secret|password|credential|signature|sig)(?:/|$)", parts.path.casefold()))
    if has_credentials or sensitive_query or sensitive_path or parts.fragment:
        return "[redacted-url]", True
    return urlunsplit((parts.scheme, host + port, parts.path, "", "")), False


def _log_metadata(value: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    _check_keys(value, {"status", "http_status", "url"})
    status = _text(value.get("status"), field="log_status", limit=30).lower()
    if status not in LOG_STATUSES:
        raise EvidenceInputError("invalid_log_status")
    http_status = value.get("http_status")
    if http_status is not None and (isinstance(http_status, bool) or not isinstance(http_status, int) or not 100 <= http_status <= 599):
        raise EvidenceInputError("invalid_log_http_status")
    redacted = False
    url = None
    if value.get("url") is not None:
        url, redacted = _redact_url(value["url"])
    if http_status == 404 and status == "available":
        raise EvidenceInputError("contradictory_log_metadata")
    if http_status == 404:
        status = "not_found"
    if status == "available" and http_status is not None and http_status >= 400:
        raise EvidenceInputError("contradictory_log_metadata")
    return {"status": status, "http_status": http_status, "url": url}, redacted


def _normalize_steps(value: Any, count: Any) -> int:
    list_count = None
    if value is not None:
        if not isinstance(value, list) or len(value) > MAX_STEPS:
            raise EvidenceInputError("invalid_steps")
        for item in value:
            if isinstance(item, Mapping):
                _check_keys(item, {"name", "status"})
                _text(item.get("name"), field="step_name", limit=160)
                if item.get("status") is not None:
                    _text(item["status"], field="step_status", limit=40)
            else:
                _text(item, field="step_name", limit=160)
        list_count = len(value)
    if count is None and list_count is None:
        raise EvidenceInputError("missing_step_evidence")
    if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0 or count > MAX_STEPS):
        raise EvidenceInputError("invalid_steps_executed")
    if list_count is not None and count is not None and list_count != count:
        raise EvidenceInputError("step_count_mismatch")
    return list_count if list_count is not None else count


def _normalize_workflow(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise EvidenceInputError("invalid_workflow_context")
    _check_keys(value, {"name", "run_id", "status", "conclusion", "head_sha", "base_sha", "created_at", "updated_at", "url"})
    status = _text(value.get("status"), field="workflow_status", limit=30).lower()
    conclusion = value.get("conclusion")
    if conclusion is not None:
        conclusion = _text(conclusion, field="workflow_conclusion", limit=30).lower()
        if conclusion not in CONCLUSIONS:
            raise EvidenceInputError("invalid_workflow_conclusion")
    if status not in RUN_STATUSES:
        raise EvidenceInputError("invalid_workflow_status")
    if status == "completed" and conclusion in {None, "pending"}:
        raise EvidenceInputError("contradictory_workflow_metadata")
    if status != "completed" and conclusion not in {None, "pending"}:
        raise EvidenceInputError("contradictory_workflow_metadata")
    url = None
    redacted = False
    if value.get("url") is not None:
        url, redacted = _redact_url(value["url"])
    return {
        "name": _text(value.get("name"), field="workflow_name", limit=180),
        "run_id": _positive_int(
            value.get("run_id"),
            field="workflow_run_id",
            required=status != "not_created",
        ),
        "status": status,
        "conclusion": conclusion,
        "head_sha": _sha(value.get("head_sha"), field="workflow_head_sha", required=False),
        "base_sha": _sha(value.get("base_sha"), field="workflow_base_sha", required=False),
        "created_at": _timestamp(value.get("created_at"), field="workflow_created_at"),
        "updated_at": _timestamp(value.get("updated_at"), field="workflow_updated_at"),
        "url": url,
        "redacted_url": redacted,
    }


def _normalize_job(value: Any, *, expected_head_sha: str | None, canonical: bool) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EvidenceInputError("invalid_job")
    allowed = {
        "name", "kind", "required", "status", "conclusion", "head_sha", "run_id", "workflow_name",
        "runner_id", "runner_name", "steps", "steps_executed", "logs_available", "log_status",
        "log_http_status", "log_url", "required_check_status", "updated_at",
    }
    _check_keys(value, allowed)
    name = _text(value.get("name"), field="job_name", limit=180)
    kind = _text(value.get("kind", "ci"), field="job_kind", limit=30).lower()
    if kind not in {"ci", "deploy_preview", "non_ci"}:
        raise EvidenceInputError("invalid_job_kind")
    status = _text(value.get("status"), field="job_status", limit=30).lower()
    conclusion = value.get("conclusion")
    if conclusion is not None:
        conclusion = _text(conclusion, field="job_conclusion", limit=30).lower()
        if conclusion not in CONCLUSIONS:
            raise EvidenceInputError("invalid_job_conclusion")
    if status not in RUN_STATUSES:
        raise EvidenceInputError("invalid_job_status")
    if status in PENDING_STATUSES and conclusion not in {None, "pending"}:
        raise EvidenceInputError("contradictory_pending_job_metadata")
    if status == "completed" and conclusion in {None, "pending"}:
        raise EvidenceInputError("contradictory_completed_job_metadata")
    required = value.get("required", name not in NON_CI_MARKERS)
    if not isinstance(required, bool):
        raise EvidenceInputError("invalid_job_required_flag")
    head_sha = _sha(value.get("head_sha"), field="job_head_sha", required=not canonical)
    run_id = _positive_int(value.get("run_id"), field="job_run_id", required=False)
    workflow_name = _optional_text(value.get("workflow_name"), field="job_workflow_name", limit=180)
    runner_id = value.get("runner_id")
    if runner_id is not None and (isinstance(runner_id, bool) or not isinstance(runner_id, int) or runner_id < 0):
        raise EvidenceInputError("invalid_runner_id")
    runner_name = _optional_text(value.get("runner_name"), field="runner_name", limit=120)
    if not canonical and status != "not_created" and (run_id is None or workflow_name is None):
        raise EvidenceInputError("missing_job_workflow_identity")
    steps = _normalize_steps(value.get("steps"), value.get("steps_executed"))
    if steps > 0 and runner_id in {None, 0}:
        raise EvidenceInputError("contradictory_runner_steps")
    logs_available = value.get("logs_available")
    if logs_available is not None and not isinstance(logs_available, bool):
        raise EvidenceInputError("invalid_logs_available")
    log_value = value.get("log_status")
    if log_value is None and logs_available is not None:
        log_value = "available" if logs_available else "unavailable"
    if log_value is None:
        log_value = "not_queried"
    log_metadata, redacted_url = _log_metadata(
        {"status": log_value, "http_status": value.get("log_http_status"), "url": value.get("log_url")}
    )
    if logs_available is not None and logs_available != (log_metadata["status"] == "available"):
        raise EvidenceInputError("contradictory_log_metadata")
    required_check_status = value.get("required_check_status", conclusion if conclusion in CHECK_STATUSES else "pending")
    if required_check_status not in CHECK_STATUSES:
        raise EvidenceInputError("invalid_required_check_status")
    if status in PENDING_STATUSES and required_check_status != "pending":
        raise EvidenceInputError("contradictory_pending_job_metadata")
    if status == "completed" and required_check_status == "pending":
        raise EvidenceInputError("contradictory_required_check_status")
    updated_at = _timestamp(value.get("updated_at"), field="job_updated_at")
    if expected_head_sha and head_sha and head_sha != expected_head_sha:
        identity = "stale"
    else:
        identity = "bound" if head_sha else "unbound"
    return {
        "name": name,
        "kind": kind,
        "required": required,
        "status": status,
        "conclusion": conclusion,
        "head_sha": head_sha,
        "run_id": run_id,
        "workflow_name": workflow_name,
        "runner_id": runner_id,
        "runner_name_present": bool(runner_name),
        "steps_executed": steps,
        "log_status": log_metadata["status"],
        "log_http_status": log_metadata["http_status"],
        "log_url": log_metadata["url"],
        "logs_available": log_metadata["status"] == "available",
        "log_url_redacted": redacted_url,
        "required_check_status": required_check_status,
        "updated_at": updated_at,
        "identity": identity,
    }


def _normalize_check(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EvidenceInputError("invalid_check")
    _check_keys(value, {"name", "kind", "status", "conclusion", "url"})
    name = _text(value.get("name"), field="check_name", limit=180)
    kind = _text(value.get("kind", "ci"), field="check_kind", limit=30).lower()
    normalized_name = name.casefold().replace("_", "-")
    if kind == "ci" and any(marker in normalized_name for marker in NON_CI_MARKERS):
        kind = "deploy_preview"
    if kind not in {"ci", "deploy_preview", "non_ci"}:
        raise EvidenceInputError("invalid_check_kind")
    status = _text(value.get("status"), field="check_status", limit=30).lower()
    conclusion = value.get("conclusion")
    if conclusion is not None:
        conclusion = _text(conclusion, field="check_conclusion", limit=30).lower()
    if status not in RUN_STATUSES or (conclusion is not None and conclusion not in CONCLUSIONS):
        raise EvidenceInputError("invalid_check_state")
    if status in PENDING_STATUSES and conclusion not in {None, "pending"}:
        raise EvidenceInputError("contradictory_pending_check_metadata")
    if status == "completed" and conclusion in {None, "pending"}:
        raise EvidenceInputError("contradictory_completed_check_metadata")
    url = None
    redacted = False
    if value.get("url") is not None:
        url, redacted = _redact_url(value["url"])
    return {"name": name, "kind": kind, "status": status, "conclusion": conclusion, "url": url, "url_redacted": redacted}


def _adapt_canonical(value: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt existing CIEvidence.v1 without changing its canonical contract."""
    _check_keys(value, {"schema", "run", "required_jobs", "jobs"})
    run = value.get("run")
    if not isinstance(run, Mapping):
        raise EvidenceInputError("invalid_workflow_context")
    _check_keys(run, {"status", "conclusion"})
    jobs = value.get("jobs")
    required_jobs = value.get("required_jobs")
    if not isinstance(required_jobs, list) or not required_jobs or len(required_jobs) > MAX_JOBS:
        raise EvidenceInputError("required_jobs_expected")
    if not isinstance(jobs, list) or len(jobs) > MAX_JOBS:
        raise EvidenceInputError("jobs_expected")
    normalized = {
        "schema": INPUT_SCHEMA,
        "repository": "unavailable",
        "candidate_head_sha": None,
        "target_head_sha": None,
        "target_base_sha": None,
        "workflow": None,
        "required_jobs": required_jobs,
        "jobs": jobs,
        "checks": [],
        "source_schema": CANONICAL_INPUT_SCHEMA,
    }
    return normalized


def normalize_input(value: Any) -> dict[str, Any]:
    """Validate and normalize a rich or canonical sanitized evidence payload."""
    if not isinstance(value, Mapping):
        raise EvidenceInputError("input_root_not_object")
    schema = value.get("schema")
    if schema == CANONICAL_INPUT_SCHEMA:
        return _normalize_rich(_adapt_canonical(value), trusted_source_schema=CANONICAL_INPUT_SCHEMA)
    if schema != INPUT_SCHEMA:
        raise EvidenceInputError("unsupported_input_schema")
    return _normalize_rich(value, trusted_source_schema=INPUT_SCHEMA)


def _normalize_rich(value: Mapping[str, Any], *, trusted_source_schema: str) -> dict[str, Any]:
    allowed = {"schema", "repository", "candidate_head_sha", "target_head_sha", "target_base_sha", "workflow", "required_policy", "required_jobs", "jobs", "checks", "collected_at"}
    if trusted_source_schema == CANONICAL_INPUT_SCHEMA:
        allowed.add("source_schema")
    _check_keys(value, allowed)
    repository = _text(value.get("repository"), field="repository", limit=200)
    source_schema = trusted_source_schema
    candidate_head_sha = _sha(
        value.get("candidate_head_sha"),
        field="candidate_head_sha",
        required=source_schema != CANONICAL_INPUT_SCHEMA,
    )
    workflow = _normalize_workflow(value.get("workflow"))
    target_head_sha = _sha(value.get("target_head_sha"), field="target_head_sha", required=source_schema != CANONICAL_INPUT_SCHEMA)
    target_base_sha = _sha(
        value.get("target_base_sha"),
        field="target_base_sha",
        required=source_schema != CANONICAL_INPUT_SCHEMA,
    )
    required_policy = value.get("required_policy")
    if source_schema == INPUT_SCHEMA:
        if not isinstance(required_policy, Mapping):
            raise EvidenceInputError("required_policy_expected")
        _check_keys(required_policy, {"source", "revision", "jobs", "fingerprint"})
        if required_policy.get("source") != "repository_policy":
            raise EvidenceInputError("untrusted_required_policy_source")
        policy_jobs = required_policy.get("jobs")
        if not isinstance(policy_jobs, list) or not policy_jobs:
            raise EvidenceInputError("required_policy_jobs_expected")
        required_policy_jobs = [_text(item, field="required_policy_job", limit=180) for item in policy_jobs]
        policy_revision = _text(required_policy.get("revision"), field="required_policy_revision", limit=80)
        policy_fingerprint = _digest(required_policy.get("fingerprint"), field="required_policy_fingerprint")
        expected_policy_fingerprint = hashlib.sha256(
            _canonical({"jobs": sorted(required_policy_jobs), "revision": policy_revision}).encode("utf-8")
        ).hexdigest()
        if policy_fingerprint != expected_policy_fingerprint:
            raise EvidenceInputError("required_policy_fingerprint_mismatch")
        required_policy = {
            "source": "repository_policy",
            "revision": policy_revision,
            "jobs": sorted(required_policy_jobs),
            "fingerprint": policy_fingerprint,
            "provenance": "declared_sanitized",
        }
    else:
        required_policy_jobs = []
    required_jobs = value.get("required_jobs")
    if not isinstance(required_jobs, list) or not required_jobs or len(required_jobs) > MAX_JOBS:
        raise EvidenceInputError("required_jobs_expected")
    required_names = []
    for name in required_jobs:
        item = _text(name, field="required_job_name", limit=180)
        normalized = item.casefold().replace("_", "-")
        if any(marker in normalized for marker in NON_CI_MARKERS):
            raise EvidenceInputError("non_ci_check_in_required_jobs")
        required_names.append(item)
    if len(set(required_names)) != len(required_names):
        raise EvidenceInputError("duplicate_required_job")
    if required_policy_jobs and sorted(required_policy_jobs) != sorted(required_names):
        raise EvidenceInputError("required_policy_job_mismatch")
    raw_jobs = value.get("jobs")
    if not isinstance(raw_jobs, list) or len(raw_jobs) > MAX_JOBS:
        raise EvidenceInputError("jobs_expected")
    canonical = source_schema == CANONICAL_INPUT_SCHEMA
    normalized_jobs = [_normalize_job(item, expected_head_sha=candidate_head_sha, canonical=canonical) for item in raw_jobs]
    if len({job["name"] for job in normalized_jobs}) != len(normalized_jobs):
        raise EvidenceInputError("duplicate_job_name")
    if any(job["required"] != (job["name"] in required_names) for job in normalized_jobs if job["kind"] == "ci"):
        raise EvidenceInputError("job_required_flag_mismatch")
    raw_checks = value.get("checks", [])
    if not isinstance(raw_checks, list) or len(raw_checks) > MAX_CHECKS:
        raise EvidenceInputError("checks_expected")
    checks = [_normalize_check(item) for item in raw_checks]
    if len({item["name"] for item in checks}) != len(checks):
        raise EvidenceInputError("duplicate_check_name")
    collected_at = _timestamp(value.get("collected_at"), field="collected_at")
    return {
        "schema": INPUT_SCHEMA,
        "source_schema": source_schema,
        "repository": repository,
        "candidate_head_sha": candidate_head_sha,
        "target_head_sha": target_head_sha,
        "target_base_sha": target_base_sha,
        "workflow": workflow,
        "required_policy": required_policy,
        "required_jobs": sorted(required_names),
        "jobs": sorted(normalized_jobs, key=lambda item: item["name"]),
        "checks": sorted(checks, key=lambda item: item["name"]),
        "collected_at": collected_at,
    }


def _context_classification(data: Mapping[str, Any]) -> str:
    workflow = data.get("workflow")
    if not workflow or workflow.get("name") == "unavailable":
        return "missing_workflow_context"
    if workflow.get("status") == "not_created":
        return "workflow_never_created"
    if workflow.get("run_id") is None or workflow.get("head_sha") is None:
        return "missing_workflow_context"
    candidate = data.get("candidate_head_sha")
    target = data.get("target_head_sha")
    if not candidate or not target or workflow.get("head_sha") != target or candidate != target:
        return "stale_worktree_metadata"
    target_base = data.get("target_base_sha")
    if target_base and workflow.get("base_sha") != target_base:
        return "stale_worktree_metadata"
    return "complete_workflow_context"


def _job_identity_state(job: Mapping[str, Any], data: Mapping[str, Any]) -> str:
    workflow = data.get("workflow") or {}
    candidate = data.get("candidate_head_sha")
    target = data.get("target_head_sha")
    if candidate and job.get("head_sha") and candidate != job["head_sha"]:
        return "stale_job_metadata"
    if target and job.get("head_sha") and target != job["head_sha"]:
        return "stale_job_metadata"
    if workflow.get("head_sha") and job.get("head_sha") and workflow["head_sha"] != job["head_sha"]:
        return "stale_job_metadata"
    if workflow.get("run_id") and job.get("run_id") and workflow["run_id"] != job["run_id"]:
        return "stale_job_metadata"
    if workflow.get("name") and workflow["name"] != "unavailable" and job.get("workflow_name") and workflow["name"] != job["workflow_name"]:
        return "stale_job_metadata"
    return "bound" if job.get("head_sha") else "unbound"


def _execution_projection(job: Mapping[str, Any], *, context: str, identity: str) -> dict[str, Any]:
    status = job["status"]
    conclusion = job["conclusion"]
    steps = job["steps_executed"]
    runner_assigned = job["runner_id"] is not None and job["runner_id"] > 0
    log_status = job["log_status"]
    if status in PENDING_STATUSES:
        execution = "pending"
        job_status = "pending"
        reason = "ci_job_not_completed"
    elif steps == 0 or not runner_assigned:
        execution = "zero_step_runnerless"
        job_status = "unavailable"
        reason = "ci_report_has_no_admissible_execution"
    elif conclusion == "timed_out" or job["required_check_status"] == "timed_out":
        execution = "timed_out"
        job_status = "timed_out"
        reason = "ci_job_timed_out"
    elif conclusion != "success" or job["required_check_status"] != "success":
        execution = "executed_failure"
        job_status = "failed"
        reason = "ci_job_failed_after_execution"
    elif log_status != "available":
        execution = "unavailable_logs"
        job_status = "unavailable"
        reason = "ci_logs_unavailable"
    else:
        execution = "pass"
        job_status = "passed"
        reason = "ci_job_executed_successfully"
    classification = execution
    if identity == "stale_job_metadata":
        classification = "stale_metadata"
        job_status = "unavailable"
        reason = "ci_job_identity_does_not_match_candidate"
    elif context != "complete_workflow_context" and execution == "pass":
        classification = context
        job_status = "unavailable"
        reason = "workflow_identity_required_to_admit_success"
    return {
        "name": job["name"],
        "required": job["required"],
        "status": job_status,
        "classification": classification,
        "execution_classification": execution,
        "identity_classification": identity,
        "context_classification": context,
        "conclusion": conclusion,
        "runner_assigned": runner_assigned,
        "steps_executed": steps,
        "logs_available": job["logs_available"],
        "log_status": log_status,
        "log_http_status": job["log_http_status"],
        "reason": reason,
    }


def _overall_projection(data: Mapping[str, Any]) -> dict[str, Any]:
    context = _context_classification(data)
    workflow = data.get("workflow") or {}
    expected = set(data["required_jobs"])
    jobs_by_name = {job["name"]: job for job in data["jobs"] if job["kind"] == "ci"}
    missing = sorted(expected - set(jobs_by_name))
    projections = []
    states: list[str] = []
    redacted_urls = 0
    for job in data["jobs"]:
        if job["log_url_redacted"]:
            redacted_urls += 1
        if job["kind"] != "ci":
            projections.append({"name": job["name"], "required": False, "status": "not_ci", "classification": "not_ci", "reason": "non_ci_job_excluded"})
            continue
        identity = _job_identity_state(job, data)
        projection = _execution_projection(job, context=context, identity=identity)
        projections.append(projection)
        if projection["classification"] != "pass":
            states.append("stale_job_metadata" if identity == "stale_job_metadata" else projection["classification"])
    for name in missing:
        projections.append({"name": name, "required": True, "status": "unavailable", "classification": "required_job_missing", "reason": "required_ci_job_missing"})
        states.append("required_job_missing")
    if context != "complete_workflow_context":
        states.append(context)
    required = [item for item in projections if item.get("required")]
    required_states = [item["classification"] for item in required]
    if not states and required:
        states.append("pass")
    executed_steps = sum(int(item.get("steps_executed", 0) or 0) for item in required)
    workflow_failure = workflow.get("conclusion") in {"failure", "cancelled", "startup_failure"} and executed_steps > 0
    workflow_timeout = workflow.get("conclusion") == "timed_out" and executed_steps > 0
    if any(item == "malformed" for item in required_states):
        classification, status, reason = "malformed", "malformed", "malformed_required_ci_evidence"
    elif any(item == "executed_failure" for item in required_states) or workflow_failure:
        classification, status, reason = "executed_failure", "failed", "required_ci_job_failed_after_execution"
    elif any(item == "timed_out" for item in required_states) or workflow_timeout:
        classification, status, reason = "timed_out", "timed_out", "required_ci_job_timed_out"
    elif any(item == "pending" for item in required_states):
        classification, status, reason = "pending", "pending", "required_ci_job_not_complete"
    elif any(item in {"zero_step_runnerless", "unavailable_logs", "required_job_missing", "stale_metadata", "missing_workflow_context", "stale_worktree_metadata", "workflow_never_created"} for item in required_states) or context != "complete_workflow_context" or missing:
        classification, status, reason = "ci_unavailable", "unavailable", "required_ci_evidence_not_admissible"
    elif required and all(item == "pass" for item in required_states) and workflow.get("conclusion") == "success":
        classification, status, reason = "pass", "passed", "all_required_ci_jobs_executed"
    else:
        classification, status, reason = "ci_unavailable", "unavailable", "required_ci_evidence_incomplete"
    return {
        "status": status,
        "classification": classification,
        "reason": reason,
        "diagnostic_state": states[0] if len(set(states)) == 1 and states else "mixed" if states else "evidence_not_queried",
        "diagnostic_states": sorted(set(states)) or ["evidence_not_queried"],
        "context_classification": context,
        "required_jobs": sorted(expected),
        "missing_required_jobs": missing,
        "jobs": sorted(projections, key=lambda item: item["name"]),
        "non_ci_checks": [item for item in data["checks"] if item["kind"] in {"deploy_preview", "non_ci"}],
        "redacted_url_count": redacted_urls + sum(1 for item in data["checks"] if item["url_redacted"]),
        "admissible_evidence": classification == "pass",
        "operator_action": _operator_action(classification, context),
    }


def _operator_action(classification: str, context: str) -> str:
    if context == "missing_workflow_context":
        return "collect sanitized workflow name, run ID, candidate head SHA, and conclusion before admitting CI success"
    if context == "workflow_never_created":
        return "confirm the workflow was created for this candidate before collecting CI evidence"
    if context == "stale_worktree_metadata":
        return "recollect evidence whose workflow, candidate, target, and base identities match"
    return {
        "pass": "no CI evidence remediation is required; existing readiness authority still decides merge",
        "executed_failure": "inspect the executed failure and repair the tested defect before rerunning CI",
        "timed_out": "inspect the executed timeout and rerun after addressing its cause",
        "pending": "wait for required jobs to complete, then recollect sanitized evidence",
        "ci_unavailable": "recollect runner, step, log, and workflow-identity evidence; unavailable execution cannot pass",
        "malformed": "repair the sanitized evidence contract and rerun the diagnostic",
    }.get(classification, "collect complete sanitized CI evidence before final attestation")


def build_report(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "report_version": REPORT_VERSION,
        "generated_at": "deterministic",
        "source_schema": None,
        "repository": "unavailable",
        "candidate_head_sha": None,
        "workflow": None,
        "status": "unavailable",
        "classification": "ci_unavailable",
        "diagnostic_state": "evidence_not_queried",
        "diagnostic_states": ["evidence_not_queried"],
        "jobs": [],
        "required_jobs": [],
        "missing_required_jobs": [],
        "non_ci_checks": [],
        "redacted_url_count": 0,
        "admissible_evidence": False,
        "authority": {
            "kind": "evidence_classifier_only",
            "merge_authorized": False,
            "deployment_authorized": False,
            "external_actions_authorized": False,
            "integrated_consumers": [],
            "intended_consumers": ["scripts/ai/run_local_quality_gate.py", "scripts/ai/pr_readiness_report.py"],
        },
        "blockers": ["evidence_not_queried"],
        "operator_action": _operator_action("ci_unavailable", "missing_workflow_context"),
        "limits": {"max_input_bytes": MAX_INPUT_BYTES, "max_jobs": MAX_JOBS, "max_checks": MAX_CHECKS, "max_steps": MAX_STEPS, "max_nesting": MAX_NESTING},
    }
    if payload is None:
        base["fingerprint"] = _fingerprint(base)
        return base
    try:
        _bounded_input_bytes(payload)
        data = normalize_input(payload)
    except EvidenceInputError as exc:
        base.update({"status": "malformed", "classification": "malformed", "diagnostic_state": "malformed_metadata", "diagnostic_states": ["malformed_metadata"], "blockers": ["malformed_metadata"], "operator_action": _operator_action("malformed", "complete_workflow_context"), "error": exc.code})
        base["source_schema"] = "unknown"
        base["fingerprint"] = _fingerprint(base)
        return base
    projection = _overall_projection(data)
    base.update({
        "source_schema": data["source_schema"],
        "repository": data["repository"],
        "candidate_head_sha": data["candidate_head_sha"],
        "target_head_sha": data["target_head_sha"],
        "target_base_sha": data["target_base_sha"],
        "required_policy": data["required_policy"],
        "workflow": data["workflow"],
        **projection,
    })
    base["blockers"] = [] if projection["classification"] == "pass" else sorted(set(projection["diagnostic_states"] + [projection["reason"]]))
    base["fingerprint"] = _fingerprint(base)
    return base


def load_input(path: Path, *, root: Path = ROOT) -> Mapping[str, Any]:
    resolved = path.expanduser().resolve()
    worktree = root.expanduser().resolve()
    if path.expanduser().is_symlink():
        raise EvidenceInputError("input_symlink_not_allowed")
    try:
        resolved.relative_to(worktree)
    except ValueError as exc:
        raise EvidenceInputError("input_outside_worktree") from exc
    if not resolved.is_file():
        raise EvidenceInputError("input_unavailable")
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        raise EvidenceInputError("input_unavailable") from exc
    if len(raw) > MAX_INPUT_BYTES:
        raise EvidenceInputError("input_exceeds_size_cap")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceInputError("input_not_json") from exc
    except RecursionError as exc:
        raise EvidenceInputError("input_nesting_exceeds_limit") from exc
    if not isinstance(value, Mapping):
        raise EvidenceInputError("input_root_not_object")
    return value


def _safe_markdown(value: Any) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("`", "\\`")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# CI Admissibility Evidence",
        "",
        f"- Schema: `{_safe_markdown(report['schema'])}`",
        f"- Repository: `{_safe_markdown(report['repository'])}`",
        f"- Classification: **{_safe_markdown(report['classification'])}**",
        f"- Diagnostic state: `{_safe_markdown(report['diagnostic_state'])}`",
        f"- Candidate head: `{_safe_markdown(report.get('candidate_head_sha') or 'unavailable')}`",
        f"- Fingerprint: `{_safe_markdown(report['fingerprint'])}`",
        f"- Merge authorized: `{report['authority']['merge_authorized']}`",
        f"- Deployment authorized: `{report['authority']['deployment_authorized']}`",
        "",
        "## Required Jobs",
        "",
        "| Job | Status | Classification | Steps | Runner | Logs |",
        "|---|---|---|---:|---|---|",
    ]
    for job in report.get("jobs", []):
        if not job.get("required"):
            continue
        lines.append(
            f"| {_safe_markdown(job['name'])} | {_safe_markdown(job['status'])} | "
            f"{_safe_markdown(job['classification'])} | {_safe_markdown(job.get('steps_executed', 'n/a'))} | "
            f"{_safe_markdown('yes' if job.get('runner_assigned') else 'no')} | {_safe_markdown(job.get('log_status', 'n/a'))} |"
        )
    lines.extend(["", "## Non-CI Checks", ""])
    for check in report.get("non_ci_checks", []):
        lines.append(f"- `{_safe_markdown(check['name'])}`: `{_safe_markdown(check['conclusion'] or check['status'])}` excluded from CI admissibility")
    lines.extend(["", "## Blockers", ""])
    lines.extend(f"- `{_safe_markdown(item)}`" for item in report.get("blockers", []))
    lines.extend(["", f"**Next action:** {_safe_markdown(report['operator_action'])}", "", "Evidence classifier only. Existing readiness and merge authorities remain canonical.", ""])
    rendered = "\n".join(lines)
    if len(rendered) <= MAX_OUTPUT_CHARS:
        return rendered
    footer = "\n\n[output bounded]\n"
    preserved = "\n\n**Next action:** " + _safe_markdown(report["operator_action"]) + "\n\nEvidence classifier only.\n"
    limit = MAX_OUTPUT_CHARS - len(footer) - len(preserved)
    return rendered[: max(0, limit)] + footer + preserved


def render_json(report: Mapping[str, Any]) -> str:
    rendered = json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    if len(rendered) <= MAX_OUTPUT_CHARS:
        return rendered
    reduced = {
        "schema": report["schema"],
        "report_version": report["report_version"],
        "generated_at": report["generated_at"],
        "repository": report["repository"],
        "candidate_head_sha": report.get("candidate_head_sha"),
        "target_head_sha": report.get("target_head_sha"),
        "target_base_sha": report.get("target_base_sha"),
        "classification": report["classification"],
        "status": report["status"],
        "diagnostic_state": report["diagnostic_state"],
        "diagnostic_states": report.get("diagnostic_states", []),
        "context_classification": report.get("context_classification"),
        "required_job_count": len(report.get("required_jobs", [])),
        "missing_required_jobs": report.get("missing_required_jobs", [])[:40],
        "required_policy_fingerprint": (report.get("required_policy") or {}).get("fingerprint"),
        "job_count": len(report.get("jobs", [])),
        "non_ci_check_count": len(report.get("non_ci_checks", [])),
        "redacted_url_count": report.get("redacted_url_count", 0),
        "admissible_evidence": report.get("admissible_evidence", False),
        "authority": report["authority"],
        "blockers": report.get("blockers", [])[:40],
        "operator_action": report["operator_action"],
        "output_bounded": True,
        "output_omitted": "per-job metadata and non-CI check details",
    }
    reduced["fingerprint"] = report["fingerprint"]
    return json.dumps(reduced, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"


def _error_report(error: str) -> dict[str, Any]:
    report = build_report(None)
    report.update({"status": "malformed", "classification": "malformed", "diagnostic_state": "malformed_metadata", "diagnostic_states": ["malformed_metadata"], "blockers": ["malformed_metadata"], "error": error, "operator_action": _operator_action("malformed", "complete_workflow_context")})
    report["fingerprint"] = _fingerprint(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="repository-local sanitized CI evidence JSON")
    parser.add_argument("--root", type=Path, default=ROOT, help="worktree containing the input file")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="render deterministic JSON (default)")
    output.add_argument("--markdown", action="store_true", help="render bounded operator Markdown")
    args = parser.parse_args(argv)
    if args.input is None:
        report = build_report(None)
    else:
        try:
            payload = load_input(args.input, root=args.root)
        except EvidenceInputError as exc:
            report = _error_report(exc.code)
        else:
            report = build_report(payload)
    sys.stdout.write(render_markdown(report) if args.markdown else render_json(report))
    return {
        "pass": 0,
        "executed_failure": 1,
        "timed_out": 1,
        "malformed": 3,
    }.get(report["classification"], 2)


if __name__ == "__main__":
    raise SystemExit(main())

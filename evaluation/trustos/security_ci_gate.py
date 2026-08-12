"""Fail-closed, allowlisted local security-scanner execution for TrustOS.

The gate is deliberately small: it plans commands, optionally executes only
known local binaries with bounded arguments/time/output, and delegates all
finding normalization to :mod:`security_scanner_adapter`. It never enables
network access, reads credentials, uploads reports, or persists raw output.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .control_plane import ACTION_CATEGORIES, TrustEvidenceRecord, TrustGateResult, _clean
from .security_scanner_adapter import (
    GATE_ACTIONS as SCANNER_GATE_ACTIONS,
    SCANNER_IDS,
    SecurityGateImpact,
    SecurityScanFinding,
    SecurityScannerAdapterReport,
    _secret_like,
    build_security_scanner_report,
    parse_security_fixture,
)

GATE_ACTIONS = tuple(dict.fromkeys((*SCANNER_GATE_ACTIONS, *ACTION_CATEGORIES)))

COMMAND_MODES = ("fixture_only", "ingest_existing_output", "plan_only", "run_local_if_available", "run_ci_if_available_later", "blocked")
COMMAND_STATUSES = ("planned_not_run", "skipped_unavailable", "executed_sanitized", "blocked_output_too_large", "redacted_or_rejected", "blocked_unsafe", "failed", "ingested_fixture")
DECISIONS = ("pass", "warn", "soft_block", "hard_block", "skipped_unavailable", "planned_not_run", "blocked_unsafe")
COMMAND_IDS = (
    "gitleaks_detect", "trufflehog_filesystem", "osv_scanner_lockfiles", "trivy_filesystem",
    "codeql_sarif_ingest", "semgrep_json_ingest", "semgrep_sarif_ingest",
    "openssf_scorecard_reference", "manual_security_review_ingest",
)
RUNNABLE_COMMANDS = {"gitleaks_detect", "trufflehog_filesystem", "osv_scanner_lockfiles", "trivy_filesystem"}
SCANNER_FOR_COMMAND = {
    "gitleaks_detect": "gitleaks", "trufflehog_filesystem": "trufflehog", "osv_scanner_lockfiles": "osv_scanner",
    "trivy_filesystem": "trivy", "codeql_sarif_ingest": "codeql_sarif", "semgrep_json_ingest": "semgrep_json",
    "semgrep_sarif_ingest": "semgrep_sarif", "openssf_scorecard_reference": "openssf_scorecard", "manual_security_review_ingest": "manual_security_review",
}
EXECUTABLES = {
    "gitleaks_detect": "gitleaks", "trufflehog_filesystem": "trufflehog", "osv_scanner_lockfiles": "osv-scanner", "trivy_filesystem": "trivy",
    "codeql_sarif_ingest": "codeql", "semgrep_json_ingest": "semgrep", "semgrep_sarif_ingest": "semgrep",
    "openssf_scorecard_reference": "scorecard", "manual_security_review_ingest": "manual-review",
}
DEFAULT_FORBIDDEN = ("artifacts", ".git", ".env", "credentials", "secrets", "node_modules")


def _safe_path(value: str | Path, *, root: Path) -> Path:
    candidate = Path(value)
    normalized = str(value).replace("\\", "/")
    if any(part == ".." for part in candidate.parts) or any(part == ".." for part in Path(normalized).parts):
        raise ValueError("path traversal is not accepted")
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if root.resolve() not in resolved.parents and resolved != root.resolve():
        raise ValueError("path must remain inside the repository")
    return resolved


def _bounded_args(command_id: str, root: Path) -> tuple[str, ...]:
    source = str(root.resolve())
    if command_id == "gitleaks_detect":
        return ("detect", "--source", source, "--no-banner", "--report-format", "json", "--report-path", "-", "--exclude", "(^|/)(artifacts|.git|node_modules|.env)(/|$)")
    if command_id == "trufflehog_filesystem":
        return ("filesystem", source, "--json", "--no-update")
    if command_id == "osv_scanner_lockfiles":
        return ("scan", "source", "-r", source, "--format", "json")
    if command_id == "trivy_filesystem":
        return ("fs", "--scanners", "vuln,secret,misconfig", "--format", "json", "--no-progress", "--skip-dirs", ".git", "--skip-dirs", "artifacts", "--skip-dirs", "node_modules", source)
    return ()


@dataclass(frozen=True)
class SecurityCIGateConfig:
    mode: str = "fixture_only"
    root_path: str = "."
    max_output_bytes: int = 1_000_000
    default_timeout_seconds: int = 60
    network_allowed: bool = False
    credentials_required: bool = False
    writes_artifacts: bool = False
    raw_output_allowed: bool = False
    follow_symlinks: bool = False
    shell_allowed: bool = False
    require_scanners: bool = False
    read_only: bool = True

    def __post_init__(self) -> None:
        if self.mode not in COMMAND_MODES or self.network_allowed or self.credentials_required or self.writes_artifacts or self.raw_output_allowed or self.follow_symlinks or self.shell_allowed or not self.read_only:
            raise ValueError("Security CI Gate config must be offline, read-only, and bounded")
        if self.max_output_bytes <= 0 or self.default_timeout_seconds <= 0:
            raise ValueError("output and timeout caps must be positive")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityScannerCommand:
    command_id: str
    scanner_id: str
    description: str
    executable_name: str
    safe_args: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    timeout_seconds: int
    max_output_bytes: int
    network_allowed: bool
    credentials_required: bool
    writes_artifacts: bool
    artifact_policy: str
    redaction_required: bool
    normalizer_scanner_id: str
    trustos_controls_covered: tuple[str, ...]
    mode: str = "fixture_only"

    def __post_init__(self) -> None:
        if self.command_id not in COMMAND_IDS or self.scanner_id not in SCANNER_IDS or self.mode not in COMMAND_MODES:
            raise ValueError("unsupported scanner command")
        if not self.safe_args and self.mode == "run_local_if_available":
            raise ValueError("runnable command requires bounded args")
        if self.network_allowed or self.credentials_required or self.writes_artifacts or not self.redaction_required:
            raise ValueError("scanner command is unsafe")
        if self.timeout_seconds <= 0 or self.max_output_bytes <= 0 or not self.forbidden_paths:
            raise ValueError("scanner command limits are required")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityScannerAllowlist:
    allowlist_id: str
    commands: tuple[SecurityScannerCommand, ...]
    shell_execution_allowed: bool = False
    network_allowed: bool = False
    credential_access_allowed: bool = False
    artifact_upload_allowed: bool = False

    def __post_init__(self) -> None:
        if self.shell_execution_allowed or self.network_allowed or self.credential_access_allowed or self.artifact_upload_allowed:
            raise ValueError("allowlist cannot permit unsafe execution")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityScannerExecutionPlan:
    command_id: str
    scanner_id: str
    mode: str
    executable_name: str
    args: tuple[str, ...]
    target_path: str
    status: str
    approval_required: bool
    network_allowed: bool
    credentials_required: bool
    writes_artifacts: bool
    timeout_seconds: int
    max_output_bytes: int
    forbidden_paths: tuple[str, ...]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityScannerAvailability:
    command_id: str
    executable_name: str
    available: bool
    path_placeholder: str
    checked: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityScannerTimeoutPolicy:
    timeout_seconds: int
    action: str
    notes: str

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout must be positive")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityScannerOutputPolicy:
    max_output_bytes: int
    raw_output_retained: bool
    raw_stdout_printed: bool
    raw_stderr_printed: bool
    oversized_action: str
    notes: str

    def __post_init__(self) -> None:
        if self.max_output_bytes <= 0 or self.raw_output_retained or self.raw_stdout_printed or self.raw_stderr_printed:
            raise ValueError("raw scanner output cannot be retained or printed")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityScannerArtifactPolicy:
    write_enabled: bool
    allowed_files: tuple[str, ...]
    raw_files_forbidden: bool
    temp_raw_deleted: bool
    upload_enabled: bool

    def __post_init__(self) -> None:
        if self.write_enabled or not self.raw_files_forbidden or not self.temp_raw_deleted or self.upload_enabled:
            raise ValueError("artifact policy must be sanitized-only")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityScannerExecutionResult:
    command_id: str
    scanner_id: str
    status: str
    exit_code: int | None
    output_bytes: int
    normalized_finding_count: int
    output_redacted: bool
    raw_output_stored: bool
    stderr_stored: bool
    network_calls: bool
    credentials_read: bool
    temp_files_deleted: bool
    error_code: str
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in COMMAND_STATUSES or self.raw_output_stored or self.stderr_stored or self.network_calls or self.credentials_read or not self.temp_files_deleted:
            raise ValueError("unsafe execution result")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityCIRedactionResult:
    command_id: str
    status: str
    redacted_fields: tuple[str, ...]
    rejected_fields: tuple[str, ...]
    output_summary: str
    secret_like_detected: bool
    raw_html_detected: bool
    exploit_payload_detected: bool

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityCINormalizationResult:
    command_id: str
    scanner_id: str
    status: str
    finding_count: int
    evidence_records: tuple[TrustEvidenceRecord, ...]
    gate_impacts: tuple[SecurityGateImpact, ...]
    adapter_report_version: str
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityCIGateDecision:
    action: str
    decision: str
    reason: str
    finding_ids: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    next_action: str

    def __post_init__(self) -> None:
        if self.action not in GATE_ACTIONS or self.decision not in DECISIONS:
            raise ValueError("unsupported CI gate decision")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityCISafetySummary:
    read_only: bool = True
    network_calls: bool = False
    scanner_execution: bool = False
    github_api_calls: bool = False
    credentials_read: bool = False
    raw_outputs_stored: bool = False
    raw_html_stored: bool = False
    external_services_called: bool = False
    artifacts_written: bool = False
    uploads_performed: bool = False
    fail_closed: bool = True

    def __post_init__(self) -> None:
        if not self.read_only or any((self.network_calls, self.github_api_calls, self.credentials_read, self.raw_outputs_stored, self.raw_html_stored, self.external_services_called, self.artifacts_written, self.uploads_performed)):
            raise ValueError("Security CI Gate must remain read-only and offline")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityCIGateReport:
    report_version: str
    generated_at: str
    config: SecurityCIGateConfig
    allowlist: SecurityScannerAllowlist
    execution_plans: tuple[SecurityScannerExecutionPlan, ...]
    availability: tuple[SecurityScannerAvailability, ...]
    execution_results: tuple[SecurityScannerExecutionResult, ...]
    redaction_results: tuple[SecurityCIRedactionResult, ...]
    normalization_results: tuple[SecurityCINormalizationResult, ...]
    evidence_records: tuple[TrustEvidenceRecord, ...]
    gate_impacts: tuple[SecurityGateImpact, ...]
    decisions: tuple[SecurityCIGateDecision, ...]
    output_policy: SecurityScannerOutputPolicy
    artifact_policy: SecurityScannerArtifactPolicy
    timeout_policy: SecurityScannerTimeoutPolicy
    safety_summary: SecurityCISafetySummary
    overall_decision: str
    next_best_action: str

    def __post_init__(self) -> None:
        if self.overall_decision not in DECISIONS:
            raise ValueError("unsupported overall decision")

    def to_dict(self) -> dict[str, Any]:
        data = _clean(self)
        data.update({
            "command_count": len(self.execution_plans),
            "finding_count": sum(item.finding_count for item in self.normalization_results),
            "evidence_count": len(self.evidence_records),
            "hard_block_count": sum(item.decision == "hard_block" for item in self.decisions),
            "skipped_count": sum(item.status == "skipped_unavailable" for item in self.execution_results),
        })
        return data

    def to_markdown(self) -> str:
        lines = ["# Security CI Gate", "", "## Executive Summary", "", f"- Overall decision: **{self.overall_decision}**", f"- Commands: **{len(self.execution_plans)}**", f"- Findings: **{sum(item.finding_count for item in self.normalization_results)}**", f"- Evidence records: **{len(self.evidence_records)}**", "- Default: **no scanner execution**", "", "## Scanner Allowlist", "", "| Command | Scanner | Mode | Status |", "|---|---|---|---|"]
        lines.extend(f"| {item.command_id} | {item.scanner_id} | {item.mode} | {item.status} |" for item in self.execution_plans)
        lines += ["", "## Availability", "", "| Command | Available | Reason |", "|---|---|---|"]
        lines.extend(f"| {item.command_id} | {item.available} | {item.reason} |" for item in self.availability)
        lines += ["", "## Execution Results", "", "| Command | Status | Bytes | Findings |", "|---|---|---:|---:|"]
        lines.extend(f"| {item.command_id} | {item.status} | {item.output_bytes} | {item.normalized_finding_count} |" for item in self.execution_results)
        lines += ["", "## Redaction and Normalization", "", f"- Redaction records: **{len(self.redaction_results)}**", f"- Normalization records: **{len(self.normalization_results)}**", f"- Raw outputs retained: **{self.safety_summary.raw_outputs_stored}**", "", "## TrustOS Gate Impacts", "", "| Action | Decision | Reason |", "|---|---|---|"]
        lines.extend(f"| {item.action} | {item.decision} | {item.reason} |" for item in self.gate_impacts)
        lines += ["", "## Decisions", "", "| Action | Decision | Next action |", "|---|---|---|"]
        lines.extend(f"| {item.action} | {item.decision} | {item.next_action} |" for item in self.decisions)
        lines += ["", "## Safety Boundaries", "", "No network, GitHub API, external service, credentials, uploads, raw scanner output, or unbounded command execution is permitted.", "", "## Next Best Action", "", self.next_best_action, ""]
        return "\n".join(lines)


def build_scanner_allowlist(*, root_path: str = ".", config: SecurityCIGateConfig | None = None) -> SecurityScannerAllowlist:
    config = config or SecurityCIGateConfig(root_path=root_path)
    root = Path(config.root_path).resolve()
    descriptions = {
        "gitleaks_detect": "Bounded secret-exposure scan over the repository.",
        "trufflehog_filesystem": "Bounded filesystem secret-pattern scan.",
        "osv_scanner_lockfiles": "Bounded dependency scan over repository manifests.",
        "trivy_filesystem": "Bounded filesystem vulnerability, secret, and misconfiguration reference scan.",
        "codeql_sarif_ingest": "Ingest an existing sanitized CodeQL SARIF file; never configure or run CodeQL.",
        "semgrep_json_ingest": "Ingest an existing sanitized Semgrep JSON file.",
        "semgrep_sarif_ingest": "Ingest an existing sanitized Semgrep SARIF file.",
        "openssf_scorecard_reference": "Reference an existing sanitized Scorecard result; never run Scorecard by default.",
        "manual_security_review_ingest": "Ingest a sanitized security-owner manual review form.",
    }
    commands = []
    for command_id in COMMAND_IDS:
        scanner_id = SCANNER_FOR_COMMAND[command_id]
        mode = "run_local_if_available" if command_id in RUNNABLE_COMMANDS else "ingest_existing_output" if command_id.endswith("ingest") else "plan_only"
        commands.append(SecurityScannerCommand(command_id, scanner_id, descriptions[command_id], EXECUTABLES[command_id], _bounded_args(command_id, root), (str(root),), DEFAULT_FORBIDDEN, config.default_timeout_seconds, config.max_output_bytes, False, False, False, "sanitized_outputs_only", True, scanner_id, ("security_baseline", "public_launch_readiness"), mode))
    return SecurityScannerAllowlist("security-ci-gate-v1", tuple(commands), False, False, False, False)


def _plan(command: SecurityScannerCommand, *, config: SecurityCIGateConfig, run_local: bool) -> SecurityScannerExecutionPlan:
    should_run = run_local and command.command_id in RUNNABLE_COMMANDS and config.mode == "run_local_if_available"
    status = "planned_not_run" if not should_run else "planned_not_run"
    notes = ("Explicit --run-local-scanners is required.",) if not should_run else ("Execution is allowlisted, bounded, and optional.",)
    return SecurityScannerExecutionPlan(command.command_id, command.scanner_id, command.mode, command.executable_name, command.safe_args, command.allowed_paths[0], status, True, False, False, False, command.timeout_seconds, command.max_output_bytes, command.forbidden_paths, notes)


def _availability(command: SecurityScannerCommand, *, run_local: bool) -> SecurityScannerAvailability:
    if command.command_id not in RUNNABLE_COMMANDS or not run_local:
        return SecurityScannerAvailability(command.command_id, command.executable_name, False, "not_checked", False, "Execution not requested; fixture/plan mode only.")
    path = shutil.which(command.executable_name)
    return SecurityScannerAvailability(command.command_id, command.executable_name, bool(path), "available_executable" if path else "not_found", True, "Allowlisted executable found." if path else "Executable unavailable; skipped safely.")


def _fixture_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"fixture could not be read as JSON: {exc.__class__.__name__}") from exc
    if not isinstance(payload, dict):
        raise ValueError("fixture root must be an object")
    return payload


def _infer_scanner(path: Path) -> str:
    name = path.stem.lower().replace("-", "_")
    for command_id, scanner_id in SCANNER_FOR_COMMAND.items():
        if scanner_id in name or command_id.replace("_", "") in name.replace("_", ""):
            return scanner_id
    raise ValueError("scanner must be specified when fixture name is ambiguous")


def _execute(command: SecurityScannerCommand, *, config: SecurityCIGateConfig, available: SecurityScannerAvailability) -> tuple[SecurityScannerExecutionResult, Any | None]:
    if not available.available:
        return SecurityScannerExecutionResult(command.command_id, command.scanner_id, "skipped_unavailable", None, 0, 0, False, False, False, False, False, True, "executable_unavailable", ("Scanner is not installed; no execution occurred.",)), None
    try:
        completed = subprocess.run([command.executable_name, *command.safe_args], cwd=str(Path(config.root_path).resolve()), shell=False, capture_output=True, timeout=command.timeout_seconds, check=False)
    except subprocess.TimeoutExpired:
        return SecurityScannerExecutionResult(command.command_id, command.scanner_id, "failed", None, 0, 0, False, False, False, False, False, True, "timeout", ("Scanner timed out; raw output was discarded.",)), None
    except OSError:
        return SecurityScannerExecutionResult(command.command_id, command.scanner_id, "skipped_unavailable", None, 0, 0, False, False, False, False, False, True, "executable_unavailable", ("Scanner could not be started; raw output was discarded.",)), None
    output = completed.stdout or b""
    stderr = completed.stderr or b""
    size = len(output) + len(stderr)
    if size > command.max_output_bytes:
        return SecurityScannerExecutionResult(command.command_id, command.scanner_id, "blocked_output_too_large", completed.returncode, size, 0, False, False, False, False, False, True, "output_cap_exceeded", ("Output exceeded the cap and was discarded.",)), None
    try:
        payload = json.loads(output.decode("utf-8", errors="replace")) if output else {}
    except json.JSONDecodeError:
        return SecurityScannerExecutionResult(command.command_id, command.scanner_id, "failed", completed.returncode, size, 0, False, False, False, False, False, True, "unexpected_schema", ("Scanner output was not valid JSON and was discarded.",)), None
    if not isinstance(payload, Mapping) or _secret_like(payload):
        return SecurityScannerExecutionResult(command.command_id, command.scanner_id, "redacted_or_rejected", completed.returncode, size, 0, True, False, False, False, False, True, "secret_like_or_unsafe_output", ("Unsafe output was rejected without persistence.",)), None
    payload = dict(payload)
    payload["fixture_mode"] = True
    try:
        normalized = parse_security_fixture(payload, scanner_id=command.normalizer_scanner_id, source_file=f"ci://{command.command_id}")
    except ValueError:
        return SecurityScannerExecutionResult(command.command_id, command.scanner_id, "redacted_or_rejected", completed.returncode, size, 0, True, False, False, False, False, True, "normalization_rejected", ("Output failed the normalized safety contract.",)), None
    return SecurityScannerExecutionResult(command.command_id, command.scanner_id, "executed_sanitized", completed.returncode, size, len(normalized.findings), True, False, False, False, False, True, "", ("Only normalized summaries were retained.",)), normalized


def _decision(action: str, impacts: Sequence[SecurityGateImpact], *, ran_any: bool, unavailable: bool) -> SecurityCIGateDecision:
    relevant = [item for item in impacts if item.action == action]
    if relevant:
        rank = {"hard_block": 5, "soft_block": 4, "needs_security_owner": 3, "warn": 2, "allow": 1}
        strongest = max(relevant, key=lambda item: rank.get(item.decision, 0))
        decision = strongest.decision if strongest.decision in DECISIONS else "warn"
        return SecurityCIGateDecision(action, decision, strongest.reason, strongest.finding_ids, (), strongest.next_action)
    if unavailable and not ran_any:
        return SecurityCIGateDecision(action, "skipped_unavailable", "No requested scanner was available.", (), ("security_scan_evidence",), "Install/configure an approved scanner later or ingest a sanitized result.")
    if not ran_any:
        return SecurityCIGateDecision(action, "soft_block" if action in {"public_beta_launch", "activate_provider"} else "planned_not_run", "Security scanner evidence is missing because execution was not requested.", (), ("security_scan_evidence",), "Run an explicit allowlisted scan or ingest a sanitized output.")
    return SecurityCIGateDecision(action, "pass", "No normalized blocking finding was observed.", (), (), "Continue with the applicable TrustOS approval gate.")


def build_security_ci_gate_report(*, generated_at: str = "offline-deterministic", root_path: str = ".", command_id: str | None = None, fixture_payload: Mapping[str, Any] | None = None, fixture_source: str = "fixture://security-ci", action: str | None = None, plan_only: bool = False, run_local_scanners: bool = False, require_scanners: bool = False, config: SecurityCIGateConfig | None = None) -> SecurityCIGateReport:
    if action and action not in GATE_ACTIONS:
        raise ValueError("unsupported TrustOS action")
    raw_root = Path(root_path)
    normalized_root = str(root_path).replace("\\", "/")
    if any(part == ".." for part in raw_root.parts) or any(part == ".." for part in Path(normalized_root).parts):
        raise ValueError("root path traversal is not accepted")
    resolved_root = raw_root.resolve()
    if not resolved_root.is_dir():
        raise ValueError("root path must be an existing directory")
    config = config or SecurityCIGateConfig(root_path=str(resolved_root), mode="plan_only" if plan_only else "run_local_if_available" if run_local_scanners else "fixture_only", require_scanners=require_scanners)
    if run_local_scanners and plan_only:
        raise ValueError("--plan-only and --run-local-scanners cannot be combined")
    allowlist = build_scanner_allowlist(root_path=root_path, config=config)
    selected = tuple(item for item in allowlist.commands if command_id is None or item.command_id == command_id)
    if not selected:
        raise ValueError("unsupported or unknown scanner command")
    plans = tuple(_plan(item, config=config, run_local=run_local_scanners) for item in selected)
    availability = tuple(_availability(item, run_local=run_local_scanners) for item in selected)
    if require_scanners and run_local_scanners and any(not item.available for item in availability if item.command_id in RUNNABLE_COMMANDS):
        raise ValueError("required scanner executable unavailable")
    execution_results: list[SecurityScannerExecutionResult] = []
    redactions: list[SecurityCIRedactionResult] = []
    normalizations: list[SecurityCINormalizationResult] = []
    evidence: list[TrustEvidenceRecord] = []
    impacts: list[SecurityGateImpact] = []
    if fixture_payload is not None:
        scanner_id = SCANNER_FOR_COMMAND[selected[0].command_id]
        normalized = parse_security_fixture(fixture_payload, scanner_id=scanner_id, source_file=fixture_source)
        execution_results.append(SecurityScannerExecutionResult(selected[0].command_id, scanner_id, "ingested_fixture", 0, 0, len(normalized.findings), True, False, False, False, False, True, "", ("Sanitized fixture ingested; no scanner executed.",)))
        redactions.append(SecurityCIRedactionResult(selected[0].command_id, "allowed_metadata", (), (), "Sanitized fixture summary accepted.", False, False, False))
        normalizations.append(SecurityCINormalizationResult(selected[0].command_id, scanner_id, "normalized", len(normalized.findings), normalized.evidence_records, normalized.gate_impacts, "security-scanner-evidence-adapter-v1", normalized.summary.notes))
        evidence.extend(normalized.evidence_records)
        impacts.extend(normalized.gate_impacts)
    elif run_local_scanners:
        for plan, available_item, command in zip(plans, availability, selected):
            result, normalized = _execute(command, config=config, available=available_item)
            execution_results.append(result)
            if normalized is not None:
                normalizations.append(SecurityCINormalizationResult(command.command_id, command.scanner_id, "normalized", len(normalized.findings), normalized.evidence_records, normalized.gate_impacts, "security-scanner-evidence-adapter-v1", normalized.summary.notes))
                evidence.extend(normalized.evidence_records)
                impacts.extend(normalized.gate_impacts)
            if result.status == "executed_sanitized":
                redactions.append(SecurityCIRedactionResult(command.command_id, "safe_summary_only", (), (), "Sanitized normalized output only.", False, False, False))
            elif result.status in {"redacted_or_rejected", "blocked_output_too_large"}:
                redactions.append(SecurityCIRedactionResult(command.command_id, "rejected", ("stdout", "stderr"), (result.error_code,), "Unsafe or oversized output was discarded.", result.status == "redacted_or_rejected", False, False))
    impacts_tuple = tuple(impacts)
    ran_any = any(item.status in {"executed_sanitized", "ingested_fixture"} for item in execution_results)
    unavailable = any(item.status == "skipped_unavailable" for item in execution_results)
    decisions = tuple(_decision(item, impacts_tuple, ran_any=ran_any, unavailable=unavailable) for item in (action,) if item)
    if not decisions:
        decisions = tuple(_decision(item, impacts_tuple, ran_any=ran_any, unavailable=unavailable) for item in ("public_beta_launch", "activate_provider", "enable_live_model_calls"))
    rank = {"hard_block": 6, "soft_block": 5, "blocked_unsafe": 5, "warn": 4, "skipped_unavailable": 3, "planned_not_run": 2, "pass": 1}
    overall = max(decisions, key=lambda item: rank.get(item.decision, 0)).decision if decisions else "planned_not_run"
    if not ran_any and overall == "pass":
        overall = "warn"
    return SecurityCIGateReport("security-ci-gate-v1", generated_at, config, allowlist, plans, availability, tuple(execution_results), tuple(redactions), tuple(normalizations), tuple(evidence), impacts_tuple, decisions, SecurityScannerOutputPolicy(config.max_output_bytes, False, False, False, "blocked_output_too_large", "Transient command streams are never printed or written."), SecurityScannerArtifactPolicy(False, ("security_ci_gate_report.json", "security_ci_gate_report.md"), True, True, False), SecurityScannerTimeoutPolicy(config.default_timeout_seconds, "blocked", "Timeout discards scanner output."), SecurityCISafetySummary(scanner_execution=run_local_scanners), overall, "Keep default execution disabled; use sanitized fixtures or an explicit allowlisted scanner run with a security-owner review.")


__all__ = ["COMMAND_IDS", "COMMAND_MODES", "COMMAND_STATUSES", "DECISIONS", "SecurityCIGateConfig", "SecurityScannerCommand", "SecurityScannerAllowlist", "SecurityScannerExecutionPlan", "SecurityScannerAvailability", "SecurityScannerTimeoutPolicy", "SecurityScannerOutputPolicy", "SecurityScannerArtifactPolicy", "SecurityScannerExecutionResult", "SecurityCIRedactionResult", "SecurityCINormalizationResult", "SecurityCIGateDecision", "SecurityCISafetySummary", "SecurityCIGateReport", "build_scanner_allowlist", "build_security_ci_gate_report"]

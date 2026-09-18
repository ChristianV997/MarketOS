"""Evaluate an AI-chat report against a MarketOS.AITask.v1 packet.

This is a claim checker, not a quality gate or PR-readiness authority.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.ai.operator_task_packet import (
    SCHEMA as TASK_SCHEMA,
    SECRET_SHAPED,
    TaskPacketError,
    _normalize_path,
    _secret_like,
    validate_packet,
)

SCHEMA = "MarketOS.AgentEval.v1"
PASSED_CLASSES = frozenset({"passed", "pass", "green", "success", "ok"})
LIVE_CLASSES = frozenset({"live", "live_validated", "live_proof", "production_ready"})
FIXTURE_CLASSES = frozenset({"fixture", "simulated", "manual", "dry_run"})
UNAVAILABLE_CLASSES = frozenset({"unavailable", "not_run", "ci_unavailable", "blocked"})
FULL_SUITE_HINT = re.compile(r"(?i)(full suite|entire suite|all tests passed|pytest -q(?! tests/))")
FULL_SUITE_CMD = re.compile(r"(?i)(pytest(\s+-q)?\s+(tests)?\s*$|pytest\s+tests\s*$|npm test && .*pytest)")
SOURCE_MINING_HINT = re.compile(r"(?i)(reviewed|mined|adapted|inspired by).{0,40}(public source|oss pattern|github\.com|open.?source)")
SOURCE_REQUIRED_KEYS = ("url", "version", "license", "pattern")
TOOL_USE_HINT = re.compile(r"(?i)(used|invoked|ran|called)\s+(the\s+)?[\w.-]*\s*(sub ?agent|skill|tool|gstack|hermes|coderos)\b")
CI_GREEN_CLASSES = frozenset({"success", "green", "passed"})
FAILURE_CLASSES = frozenset({"failed", "failure", "red"})
RESERVED_REWRITE = (
    "run_local_quality_gate.py",
    "resource_execution_governor.py",
    "client_workspace_isolation.py",
    "operator_context_snapshot.py",
)


def _load_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must be an object")
    return value


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _in_scope(path: str, allowed: list[str]) -> bool:
    normalized = _normalize_path(path)
    for prefix in allowed:
        target = _normalize_path(prefix)
        if normalized == target or normalized.startswith(target.rstrip("/") + "/") or target.startswith(normalized.rstrip("/") + "/"):
            return True
    return False


def evaluate_report(
    report: dict[str, Any],
    packet: dict[str, Any],
    *,
    commands: list[str] | None = None,
) -> tuple[dict[str, Any], int]:
    findings: list[dict[str, str]] = []
    executed = [str(item) for item in (commands or report.get("executed_commands") or [])]
    claims = _as_list(report.get("claims") or report.get("results") or [])
    ci_status = str(report.get("ci_status") or "").lower()
    ci_steps = report.get("ci_steps")
    try:
        ci_steps_int = int(ci_steps) if ci_steps is not None else None
    except (TypeError, ValueError):
        ci_steps_int = None  # non-numeric ci_steps is treated the same as absent, never as a crash
    changed = [_normalize_path(item) for item in _as_list(report.get("changed_files"))]
    evidence = str(report.get("evidence_classification") or report.get("evidence") or "")
    pr_ref = report.get("pr") or report.get("pull_request")
    rollback = str(report.get("rollback") or "")
    classification_map = report.get("check_classifications") or {}

    if _secret_like(report) or SECRET_SHAPED.search(json.dumps(report)):
        findings.append({"rule": "raw_secrets", "status": "failed", "detail": "secret-shaped text in report"})

    for claim in claims:
        lowered = claim.lower()
        if "passed" in lowered or "green" in lowered:
            if not executed:
                findings.append({"rule": "claims_match_commands", "status": "failed", "detail": claim})
        if FULL_SUITE_HINT.search(claim):
            if not any("pytest" in cmd and "tests/" not in cmd for cmd in executed) and not any(
                re.search(r"pytest\s*$", cmd.strip()) for cmd in executed
            ):
                findings.append({"rule": "full_suite_requires_command", "status": "failed", "detail": claim})

    for name, klass in classification_map.items():
        label = str(klass).lower()
        if label in UNAVAILABLE_CLASSES and str(report.get("upgraded", "")).lower() in PASSED_CLASSES:
            findings.append({"rule": "unavailable_not_passed", "status": "failed", "detail": str(name)})
        if label in UNAVAILABLE_CLASSES and str(report.get("status", "")).lower() in PASSED_CLASSES:
            findings.append({"rule": "unavailable_not_passed", "status": "failed", "detail": f"status vs {name}"})

    # actual_check_classifications, when supplied, is ground truth (e.g. from
    # execution_bundle.py's real executor) -- claims must not relabel a
    # genuinely executed failure as unavailable/not_run/blocked, nor the
    # reverse (a check that never ran claimed as a real failure).
    actual_map = report.get("actual_check_classifications") or {}
    for name, actual in actual_map.items():
        actual_label = str(actual).lower()
        claimed_label = str(classification_map.get(name, "")).lower()
        if actual_label == "failed" and claimed_label in UNAVAILABLE_CLASSES:
            findings.append({"rule": "executed_failure_not_unavailable", "status": "failed", "detail": str(name)})
        if actual_label in UNAVAILABLE_CLASSES and claimed_label == "failed":
            findings.append({"rule": "executed_failure_not_unavailable", "status": "failed", "detail": f"{name}:reverse"})

    if evidence.lower() in FIXTURE_CLASSES and str(report.get("live_label") or report.get("supplier_proof") or "").lower() in LIVE_CLASSES:
        findings.append({"rule": "fixture_not_live", "status": "failed", "detail": "fixture evidence labeled live"})

    ci_failure_claimed = ci_status in FAILURE_CLASSES
    if ci_failure_claimed and ci_steps_int is not None and ci_steps_int <= 0:
        findings.append({"rule": "zero_step_ci_not_failure", "status": "failed", "detail": f"ci_status={report.get('ci_status')} ci_steps={ci_steps!r}"})

    allowed = packet.get("allowed_scope") or []
    out_of_scope = [path for path in changed if path and not _in_scope(path, allowed)]
    if out_of_scope:
        findings.append({"rule": "changed_files_match_scope", "status": "failed", "detail": ",".join(out_of_scope[:8])})

    if not pr_ref:
        findings.append({"rule": "pr_must_exist", "status": "failed", "detail": "report omits PR reference"})
    if not rollback:
        findings.append({"rule": "rollback_must_exist", "status": "failed", "detail": "report omits rollback"})

    owned = [_normalize_path(item) for item in _as_list(report.get("owned_files"))]
    undeclared = [path for path in owned if path and path not in changed]
    if undeclared:
        findings.append({"rule": "undeclared_files", "status": "failed", "detail": ",".join(undeclared[:8])})

    rewritten = " ".join(changed + owned)
    if any(name in rewritten for name in RESERVED_REWRITE):
        findings.append({"rule": "duplicate_authority_rejected", "status": "failed", "detail": "reserved authority path rewritten"})

    sources_reviewed = report.get("sources_reviewed") or report.get("public_sources") or []
    claims_source_mining = any(SOURCE_MINING_HINT.search(claim) for claim in claims) or any(
        SOURCE_MINING_HINT.search(str(report.get(field, ""))) for field in ("summary", "notes")
    )
    if claims_source_mining:
        if not sources_reviewed:
            findings.append({"rule": "source_mining_requires_metadata", "status": "failed", "detail": "source-mining claimed with no sources_reviewed entries"})
        else:
            incomplete = [
                str(item.get("url", item)) for item in sources_reviewed
                if not isinstance(item, dict) or any(not item.get(key) for key in SOURCE_REQUIRED_KEYS)
            ]
            if incomplete:
                findings.append({"rule": "source_mining_requires_metadata", "status": "failed", "detail": ",".join(incomplete[:5])})

    tools_used = _as_list(report.get("tools_used") or report.get("skills_used"))
    tool_output = report.get("tool_output") or report.get("skill_output") or {}
    claims_tool_use = any(TOOL_USE_HINT.search(claim) for claim in claims) or bool(tools_used)
    if claims_tool_use:
        if not tools_used:
            findings.append({"rule": "tool_use_requires_output", "status": "failed", "detail": "tool/subagent use claimed with no tools_used entries"})
        else:
            missing_output = [name for name in tools_used if not (isinstance(tool_output, dict) and tool_output.get(name))]
            if missing_output:
                findings.append({"rule": "tool_use_requires_output", "status": "failed", "detail": ",".join(missing_output[:5])})

    if ci_status in CI_GREEN_CLASSES and (ci_steps_int is None or ci_steps_int <= 0):
        findings.append({"rule": "ci_green_requires_steps", "status": "failed", "detail": f"ci_status={ci_status} ci_steps={ci_steps!r}"})

    rules = (
        "claims_match_commands",
        "unavailable_not_passed",
        "fixture_not_live",
        "changed_files_match_scope",
        "pr_must_exist",
        "rollback_must_exist",
        "undeclared_files",
        "duplicate_authority_rejected",
        "raw_secrets",
        "full_suite_requires_command",
        "source_mining_requires_metadata",
        "tool_use_requires_output",
        "ci_green_requires_steps",
        "executed_failure_not_unavailable",
        "zero_step_ci_not_failure",
    )
    failed_rules = {item["rule"] for item in findings}
    checks = []
    for rule in rules:
        status = "failed" if rule in failed_rules else "passed"
        checks.append({"rule": rule, "status": status})
    overall = "failed" if findings else "passed"
    document = {
        "schema": SCHEMA,
        "task_schema": packet.get("schema", TASK_SCHEMA),
        "read_only": True,
        "overall": overall,
        "checks": checks,
        "findings": findings,
        "executed_commands": executed,
        "changed_files": changed,
    }
    return document, 0 if overall == "passed" else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--command", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        packet = validate_packet(_load_json(args.packet))
        report = _load_json(args.report)
    except (OSError, ValueError, TaskPacketError) as exc:
        print(json.dumps({"schema": SCHEMA, "overall": "malformed", "error": str(exc)}), file=sys.stderr)
        return 2
    document, code = evaluate_report(report, packet, commands=args.command)
    print(json.dumps(document, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

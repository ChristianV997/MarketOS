"""Evaluate an AI-chat report against a MarketOS.AITask.v1 packet.

``evaluate_report`` is a structured claim checker, not a quality gate or
PR-readiness authority. ``audit_handoff`` and ``audit_handoff_batch`` parse
ordinary prose handoffs into sanitized completeness metadata. They fail
closed on merge-readiness claims and never store the source text.
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
    SECRET_KEY_HINT,
    SECRET_SHAPED,
    TaskPacketError,
    _in_scope,
    _normalize_path,
    _secret_like,
    assert_safe_path,
    validate_packet,
)

SCHEMA = "MarketOS.AgentEval.v1"
HANDOFF_SCHEMA = "MarketOS.AgentHandoffAudit.v1"
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


_HANDOFF_LABEL = re.compile(
    r"(?i)^(?:changed paths?|changed files?|files changed|write scope)\b"
)
_NONE_INVENTORY = re.compile(r"(?i)^(?:none|no files(?: changed)?|unchanged|\[\])\.?$")
_PATH_RE = re.compile(
    r"`([^`\n]+)`|(?<![\w./-])((?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+/?|[A-Za-z0-9_.-]+\.(?:py|ya?ml|json|toml|md|txt|ini))"
)
_AGENT_ID = re.compile(r"(?im)^[ \t>*-]*AGENT_ID:\s*(\S(?:.*\S)?)\s*$")
_LANE = re.compile(r"(?im)^[ \t>*-]*(?:LANE_ID|LANE):\s*(\S(?:.*\S)?)\s*$")
_BASE_SHA = re.compile(
    r"(?im)^[ \t>*-]*base(?:[_\s-]*sha)?\s*:\s*([0-9a-f]{7,40})\s*$"
)
_HEAD_SHA = re.compile(
    r"(?im)^[ \t>*-]*head(?:[_\s-]*sha)?\s*:\s*([0-9a-f]{7,40})\s*$"
)
_MERGE_READY = re.compile(r"(?i)\b(?:merge[- ]ready|ready to merge|ready for merge)\b")
_PASS_LINE = re.compile(
    r"(?i)(?<!not )(?<!n't )\b(?:[1-9]\d*\s+passed|all checks passed|all tests passed|checks passed|tests? passed|(?<!\d )passed)\b"
)
_PROOF = re.compile(
    r"(?i)(\bpytest\b|\bruff\b|\bcompileall\b|git diff --check|session_finish(?:\.py)?)"
)
_SKIP_WORD = re.compile(r"(?i)\b(?:skipped|not[_ ]run|unavailable|ci_unavailable|did not run|not executed)\b")
_FAILED_COUNT = re.compile(r"(?i)\b[1-9]\d*\s+failed\b")
_ZERO_SKIP = re.compile(r"(?i)\b0\s+(?:skipped|failed)\b")
_CHECK_NAME = re.compile(
    r"(?i)(\btests?/[A-Za-z0-9_./-]+\.py\b|\b[\w.-]+\.py\b|`[^`\n]{3,80}`|\bjob\s+\S+|\b[A-Za-z][\w ./-]{2,60}:)"
)
_BLANKET_PASS = re.compile(r"(?i)\b(?:all checks passed|all tests passed|everything passed|ci (?:is )?green|ci passed)\b")
_NO_CONFLICT = re.compile(r"(?i)\bno ownership conflict\b|\bownership conflict:\s*none\b|\bno path overlap\b")
_NAMED_CONFLICT = re.compile(
    r"(?i)\bownership conflict:\s*`?([A-Za-z0-9_./\\-]+)`?\s+owned by\s+(\S(?:.*\S)?)"
)
_CANARY = re.compile(r"(?i)\bcanary(?:[-_][A-Za-z0-9]+)+\b")
_PROVIDER_PAYLOAD = re.compile(r"(?i)\"(?:access_token|refresh_token|id_token|raw_provider|provider_payload)\"")
_SINGLE_RULES = (
    "missing_agent_id",
    "missing_lane",
    "missing_base_sha",
    "missing_head_sha",
    "missing_changed_paths",
    "unproven_test_claim",
    "false_passed_claim",
    "unclear_skipped_check",
    "ownership_unreported",
    "unsafe_changed_path",
    "missing_test_evidence",
    "unclosed_fence",
    "raw_secrets",
    "canary_content",
    "provider_payload",
)
_HARD_FAIL = frozenset({
    "false_passed_claim",
    "raw_secrets",
    "canary_content",
    "provider_payload",
    "overlapping_write_scope",
    "unreported_ownership_conflict",
    "unsafe_changed_path",
})


def _clean_text(value: str, limit: int = 160) -> str:
    text = " ".join(value.split())
    if SECRET_SHAPED.search(text) or _CANARY.search(text) or SECRET_KEY_HINT.search(text) or _PROVIDER_PAYLOAD.search(text):
        return "[redacted]"
    return text[:limit]


def _finding(rule: str, detail: str) -> dict[str, str]:
    return {"rule": rule, "status": "failed", "detail": _clean_text(detail)}


def _checks_for(findings: list[dict[str, str]], rules: tuple[str, ...]) -> list[dict[str, str]]:
    failed = {item["rule"] for item in findings}
    return [{"rule": rule, "status": "failed" if rule in failed else "passed"} for rule in rules]


def _dedupe(findings: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    ordered: list[dict[str, str]] = []
    for item in findings:
        key = (item["rule"], item["detail"])
        if key in seen:
            continue
        seen.add(key)
        ordered.append(item)
    return ordered[:40]


def _extract_paths(blob: str) -> list[str]:
    found: list[str] = []
    for match in _PATH_RE.finditer(blob):
        raw = (match.group(1) or match.group(2) or "").strip().strip("`").rstrip(",.;")
        if not raw or " " in raw or raw.startswith(("http://", "https://")):
            continue
        if "/" not in raw and "." not in raw:
            continue
        found.append(raw)
    return found


def _changed_header(line: str) -> tuple[bool, str]:
    stripped = re.sub(r"^[>#*\-\s]+", "", line.strip())
    stripped = re.sub(r"^#{1,3}\s+", "", stripped)
    match = _HANDOFF_LABEL.match(stripped)
    if not match:
        return False, ""
    rest = stripped[match.end() :].strip()
    if rest.startswith(":"):
        rest = rest[1:].strip()
    elif rest and not _NONE_INVENTORY.match(rest) and not _extract_paths(rest):
        return False, ""
    if rest and not _NONE_INVENTORY.match(rest) and not _extract_paths(rest):
        return False, ""
    return True, rest


def _is_exact_inventory_line(line: str) -> bool:
    """True when a line is only a path list, not prose that mentions a path."""
    stripped = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", line.strip())
    if not stripped:
        return False
    residual = _PATH_RE.sub(" ", stripped)
    residual = re.sub(r"[`,;]", " ", residual)
    return not residual.split()


def _inventory(text: str) -> tuple[bool, list[str], bool, bool]:
    lines = text.splitlines()
    present = False
    explicit_none = False
    unsafe = False
    found: list[str] = []
    index = 0
    while index < len(lines):
        header, inline = _changed_header(lines[index])
        if not header:
            index += 1
            continue
        present = True
        block = [inline] if inline else []
        index += 1
        while index < len(lines):
            current = lines[index]
            if not current.strip():
                break
            if current.lstrip().startswith("#") and not _changed_header(current)[0]:
                break
            block.append(current)
            index += 1
        blob = "\n".join(block)
        exact_lines = [line for line in block if line and _is_exact_inventory_line(line)]
        paths = [path for line in exact_lines for path in _extract_paths(line)]
        none_bits = [bit.strip() for bit in re.split(r"[\n,]", blob) if bit.strip()]
        if any(_NONE_INVENTORY.match(bit.strip("` ")) for bit in none_bits) and not paths:
            explicit_none = True
            continue
        for path in paths:
            if SECRET_SHAPED.search(path) or _CANARY.search(path):
                unsafe = True
                continue
            try:
                found.append(assert_safe_path(path, "changed_path").rstrip("/"))
            except TaskPacketError:
                unsafe = True
    return present, sorted(set(found)), explicit_none, unsafe


def _real_skip(line: str) -> bool:
    if not _SKIP_WORD.search(line):
        return False
    if _ZERO_SKIP.search(line) and not re.search(r"(?i)\b[1-9]\d*\s+skipped\b", line):
        return bool(re.search(r"(?i)\b(?:unavailable|not[_ ]run|ci_unavailable|did not run|not executed)\b", line))
    return True


def _claims_merge_ready(text: str) -> bool:
    for match in _MERGE_READY.finditer(text):
        window = text[max(0, match.start() - 40) : match.start()]
        if re.search(r"(?i)\b(?:not|never|no|n't|without)\b", window):
            continue
        return True
    return False


def _ownership(text: str) -> str:
    if _NAMED_CONFLICT.search(text):
        return "named"
    if _NO_CONFLICT.search(text):
        return "none"
    return "absent"


def _claim_findings(lines: list[str]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    blanket = False
    saw_gap = False
    for index, line in enumerate(lines):
        previous = lines[index - 1] if index else ""
        if _BLANKET_PASS.search(line):
            blanket = True
        if _real_skip(line):
            saw_gap = True
            if not _CHECK_NAME.search(line):
                findings.append(_finding("unclear_skipped_check", "skipped or unavailable check is unnamed"))
        if _FAILED_COUNT.search(line):
            saw_gap = True
        if not _PASS_LINE.search(line):
            continue
        if _FAILED_COUNT.search(line) or (_real_skip(line) and _PASS_LINE.search(line)):
            findings.append(_finding("false_passed_claim", "pass claim shares a line with failed or skipped evidence"))
            continue
        if not (_PROOF.search(line) or _PROOF.search(previous)):
            findings.append(_finding("unproven_test_claim", line))
    if blanket and saw_gap:
        findings.append(_finding("false_passed_claim", "blanket pass contradicts skipped, unavailable, or failed evidence"))
    return findings


def _overall(findings: list[dict[str, str]], *, merge_ready: bool) -> str:
    if merge_ready or any(item["rule"] in _HARD_FAIL for item in findings):
        return "failed"
    if findings:
        return "incomplete"
    return "passed"


def _strip_fences(text: str) -> tuple[str, bool]:
    """Drop fenced markdown so examples cannot satisfy the contract.

    A fence is a line of three or more backticks or tildes. The interior is
    discarded, and a blank line is left behind so a command cannot prove a
    claim across the fence. An opening fence without a closer is unclosed.
    """
    kept: list[str] = []
    marker: str | None = None
    for line in text.splitlines():
        opener = re.match(r"^[ \t]*(`{3,}|~{3,})[ \t]*([^`\n]*)$", line)
        if marker is None:
            if opener and not opener.group(2).strip().startswith(opener.group(1)[0]):
                marker = opener.group(1)
                continue
            kept.append(line)
            continue
        if (
            opener
            and opener.group(1)[0] == marker[0]
            and len(opener.group(1)) >= len(marker)
            and not opener.group(2).strip()
        ):
            marker = None
            kept.append("")
            continue
    return "\n".join(kept), marker is not None


def _proven_pass(lines: list[str]) -> bool:
    for index, line in enumerate(lines):
        previous = lines[index - 1] if index else ""
        if not _PASS_LINE.search(line):
            continue
        if _FAILED_COUNT.search(line) or _real_skip(line):
            continue
        if _PROOF.search(line) or _PROOF.search(previous):
            return True
    return False


def audit_handoff(text: str) -> tuple[dict[str, Any], int]:
    """Return sanitized completeness metadata for one prose handoff.

    Ordinary prose is parsed, not rejected as malformed. The source text is
    not copied into the result. A passed result means the handoff evidence
    is complete. ``merge_authority`` is always false; this does not approve
    a merge, and a merge-ready claim is failed even when the other evidence
    is complete. Fenced markdown is not evidence. Inventory entries are
    exact path lines and stop at the next heading. A pass claim is backed
    only by pytest, ruff, compileall, git diff --check, or session_finish
    on that line or the line immediately above it. Changed paths need one
    positive command-backed pass count; an explicit empty inventory does not.
    """
    source = text if isinstance(text, str) else ""
    findings: list[dict[str, str]] = []
    if _secret_like(source) or SECRET_SHAPED.search(source):
        findings.append(_finding("raw_secrets", "secret-shaped text redacted"))
    if _CANARY.search(source):
        findings.append(_finding("canary_content", "canary-shaped text redacted"))
    if _PROVIDER_PAYLOAD.search(source):
        findings.append(_finding("provider_payload", "provider payload redacted"))

    parsed, unclosed = _strip_fences(source)
    if unclosed:
        findings.append(_finding("unclosed_fence", "unclosed markdown fence"))

    agent_match = _AGENT_ID.search(parsed)
    lane_match = _LANE.search(parsed)
    base_match = _BASE_SHA.search(parsed)
    head_match = _HEAD_SHA.search(parsed)
    agent_id = _clean_text(agent_match.group(1)) if agent_match else ""
    lane = _clean_text(lane_match.group(1)) if lane_match else ""
    base_sha = base_match.group(1).lower() if base_match else ""
    head_sha = head_match.group(1).lower() if head_match else ""
    if not agent_id or agent_id == "[redacted]":
        findings.append(_finding("missing_agent_id", "AGENT_ID is missing"))
        agent_id = ""
    if not lane or lane == "[redacted]":
        findings.append(_finding("missing_lane", "lane is missing"))
        lane = ""
    if not base_sha:
        findings.append(_finding("missing_base_sha", "base SHA is missing"))
    if not head_sha:
        findings.append(_finding("missing_head_sha", "head SHA is missing"))

    present, paths, explicit_none, unsafe = _inventory(parsed)
    if unsafe:
        findings.append(_finding("unsafe_changed_path", "unsafe changed-path entry omitted"))
    if not present or (not paths and not explicit_none):
        findings.append(_finding("missing_changed_paths", "changed-path inventory is missing"))
    if _ownership(parsed) == "absent":
        findings.append(_finding("ownership_unreported", "ownership conflict was not reported"))
    parsed_lines = parsed.splitlines()
    findings.extend(_claim_findings(parsed_lines))
    if paths and not _proven_pass(parsed_lines):
        findings.append(_finding("missing_test_evidence", "changed paths have no command-backed passing test count"))
    findings = _dedupe(findings)
    merge_ready = _claims_merge_ready(parsed)
    overall = _overall(findings, merge_ready=merge_ready)
    document = {
        "schema": HANDOFF_SCHEMA,
        "read_only": True,
        "overall": overall,
        "merge_ready_claim": merge_ready,
        "merge_authority": False,
        "agent_id": agent_id or None,
        "lane": lane or None,
        "base_sha": base_sha or None,
        "head_sha": head_sha or None,
        "changed_paths": paths,
        "ownership_statement": _ownership(parsed),
        "checks": _checks_for(findings, _SINGLE_RULES),
        "findings": findings,
    }
    return document, 0 if overall == "passed" else 2


def _paths_overlap(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return left == right or _in_scope(left, [right]) or _in_scope(right, [left])


def audit_handoff_batch(texts: list[str]) -> tuple[dict[str, Any], int]:
    """Audit several prose handoffs and flag overlapping write scopes.

    Path comparison uses the task-packet scope boundary, so ``tests/ai``
    overlaps ``tests/ai/x.py`` and does not overlap ``tests/ai_evil``.
    Source reports are not stored.
    """
    audits: list[dict[str, Any]] = []
    for index, text in enumerate(texts):
        document, _code = audit_handoff(text)
        item = dict(document)
        item["index"] = index
        audits.append(item)
    findings: list[dict[str, str]] = []
    overlaps: list[dict[str, Any]] = []
    for left_index, left in enumerate(audits):
        for right in audits[left_index + 1 :]:
            shared: list[str] = []
            for left_path in left["changed_paths"]:
                for right_path in right["changed_paths"]:
                    if _paths_overlap(left_path, right_path):
                        shared.extend([left_path, right_path])
            if not shared:
                continue
            left_id = left.get("agent_id")
            right_id = right.get("agent_id")
            if left_id and right_id and left_id == right_id:
                continue
            agents = [left_id or f"report-{left['index']}", right_id or f"report-{right['index']}"]
            paths = sorted(set(shared))
            overlaps.append({"agents": agents, "paths": paths})
            findings.append(_finding("overlapping_write_scope", f"{agents[0]} overlaps {agents[1]} on {', '.join(paths[:8])}"))
            if left.get("ownership_statement") == "none" or right.get("ownership_statement") == "none":
                findings.append(_finding("unreported_ownership_conflict", f"{agents[0]} and {agents[1]} claimed no conflict"))
            elif left.get("ownership_statement") == "absent" or right.get("ownership_statement") == "absent":
                findings.append(_finding("unreported_ownership_conflict", f"{agents[0]} and {agents[1]} did not report the overlap"))
    findings = _dedupe(findings)
    child_failed = any(item["overall"] == "failed" for item in audits)
    child_open = any(item["overall"] != "passed" for item in audits)
    if findings or child_failed:
        overall = "failed"
    elif child_open:
        overall = "incomplete"
    else:
        overall = "passed"
    document = {
        "schema": HANDOFF_SCHEMA,
        "mode": "batch",
        "read_only": True,
        "overall": overall,
        "reports": audits,
        "overlaps": overlaps,
        "checks": _checks_for(findings, ("overlapping_write_scope", "unreported_ownership_conflict")),
        "findings": findings,
    }
    return document, 0 if overall == "passed" else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--handoff", type=Path, action="append", default=[])
    parser.add_argument("--command", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.handoff:
            texts = [path.read_text(encoding="utf-8") for path in args.handoff]
            if len(texts) == 1:
                document, code = audit_handoff(texts[0])
            else:
                document, code = audit_handoff_batch(texts)
        else:
            if args.packet is None or args.report is None:
                raise ValueError("packet and report are required unless --handoff is used")
            packet = validate_packet(_load_json(args.packet))
            report = _load_json(args.report)
            document, code = evaluate_report(report, packet, commands=args.command)
    except (OSError, ValueError, TaskPacketError) as exc:
        schema = HANDOFF_SCHEMA if args.handoff else SCHEMA
        print(json.dumps({"schema": schema, "overall": "malformed", "error": _clean_text(str(exc))}), file=sys.stderr)
        return 2
    print(json.dumps(document, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

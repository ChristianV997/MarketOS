"""Bounded MarketOS.AITask.v1 packet for AI-chat handoff and resume.

Does not replace session_start, generate_session_handoff, quality-gate,
PR-readiness, Governor, TrustOS, or #252 MarketOS.AIContext.v1.
Default mode is validate-and-print. Disk writes require --output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "MarketOS.AITask.v1"
MAX_PACKET_BYTES = 32_768
MAX_TEXT = 400
MAX_LIST = 40
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
SECRET_SHAPED = re.compile(
    r"(?is)("
    r"-----begin (?:rsa |ec |dsa |openssh )?private key-----"
    r"|ghp_[A-Za-z0-9_]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-(?:live|test)?-?[A-Za-z0-9]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|bearer [A-Za-z0-9._-]{10,}"
    r")"
)
SECRET_KEY_HINT = re.compile(
    r"(?i)(api[_-]?key|secret|password|token|authorization|private_key|credential)"
)
EVIDENCE_CLASSES = frozenset(
    {
        "actual",
        "simulated",
        "unavailable",
        "not_run",
        "failed",
        "malformed",
        "blocked",
        "fixture",
        "ci_unavailable",
    }
)
REQUIRED = (
    "agent_id",
    "source_chat",
    "lane",
    "objective",
    "allowed_scope",
    "prohibited_scope",
    "base_sha",
    "worktree",
    "dependencies",
    "acceptance_criteria",
    "selected_tests",
    "evidence_classification",
    "rollback",
    "next_action",
)
PROHIBITED_PATH_MARKERS = (
    "artifacts/",
    ".env",
    "credentials/",
    "secrets/",
    "node_modules/",
    ".git/",
    "browser-trace",
    "playwright-report",
    "customer",
)
RESERVED_AUTHORITIES = (
    "run_local_quality_gate.py",
    "pr_readiness_report.py",
    "resource_execution_governor.py",
    "client_workspace_isolation.py",
    "opportunity_synthesis.py",
    "product_validation_report.py",
    "backend/contracts/events.py",
    "operator_context_snapshot.py",
)
DUPLICATE_AUTHORITY_PHRASES = (
    "second quality gate",
    "second governor",
    "replace trustos",
    "second event spine",
    "second scoring authority",
    "replace operator_context_snapshot",
)


class TaskPacketError(ValueError):
    """Malformed or unsafe AI task packet."""


def _text(value: Any, field: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise TaskPacketError(f"{field} must be a string")
    result = " ".join(value.split())
    if required and not result:
        raise TaskPacketError(f"{field} is required")
    if len(result) > MAX_TEXT:
        raise TaskPacketError(f"{field} exceeds {MAX_TEXT} characters")
    if SECRET_SHAPED.search(result):
        raise TaskPacketError(f"{field} contains secret-shaped text")
    return result


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise TaskPacketError(f"{field} must be a list")
    if len(value) > MAX_LIST:
        raise TaskPacketError(f"{field} exceeds {MAX_LIST} items")
    return [_text(item, f"{field}[]", required=True) for item in value]


def _normalize_path(path: str) -> str:
    value = path.replace("\\", "/")
    if value.startswith("./"):
        value = value[2:]
    return value


def assert_safe_path(path: str, field: str) -> str:
    value = _normalize_path(_text(path, field))
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise TaskPacketError(f"{field} must stay relative without '..'")
    lowered = value.lower()
    if any(marker in lowered for marker in PROHIBITED_PATH_MARKERS):
        raise TaskPacketError(f"{field} targets a sensitive or excluded path")
    return value


def _secret_like(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if SECRET_KEY_HINT.search(str(key).replace("-", "_")) or _secret_like(item):
                return True
        return False
    if isinstance(value, list):
        return any(_secret_like(item) for item in value)
    if isinstance(value, str):
        return bool(SECRET_SHAPED.search(value))
    return False


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if SECRET_KEY_HINT.search(str(key).replace("-", "_")):
                out[key] = "[redacted]"
            else:
                out[key] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str) and SECRET_SHAPED.search(value):
        return "[redacted]"
    return value


def _reject_duplicate_authority(text: str) -> None:
    lowered = text.lower()
    if any(phrase in lowered for phrase in DUPLICATE_AUTHORITY_PHRASES):
        raise TaskPacketError("packet claims a duplicate MarketOS authority")


def validate_packet(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TaskPacketError("packet root must be an object")
    encoded = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_PACKET_BYTES:
        raise TaskPacketError("packet exceeds output cap")
    if _secret_like(raw):
        raise TaskPacketError("packet contains secret-shaped values")
    missing = [key for key in REQUIRED if key not in raw]
    if missing:
        raise TaskPacketError(f"missing fields: {missing}")
    schema = raw.get("schema", SCHEMA)
    if schema != SCHEMA:
        raise TaskPacketError(f"unsupported schema: {schema}")
    packet = {
        "schema": SCHEMA,
        "agent_id": _text(raw["agent_id"], "agent_id"),
        "source_chat": _text(raw["source_chat"], "source_chat"),
        "lane": _text(raw["lane"], "lane"),
        "objective": _text(raw["objective"], "objective"),
        "allowed_scope": [assert_safe_path(item, "allowed_scope") for item in _string_list(raw["allowed_scope"], "allowed_scope")],
        "prohibited_scope": _string_list(raw["prohibited_scope"], "prohibited_scope"),
        "base_sha": _text(raw["base_sha"], "base_sha").lower(),
        "worktree": _text(raw["worktree"], "worktree"),
        "dependencies": _string_list(raw["dependencies"], "dependencies"),
        "acceptance_criteria": _string_list(raw["acceptance_criteria"], "acceptance_criteria"),
        "selected_tests": _string_list(raw["selected_tests"], "selected_tests"),
        "evidence_classification": _text(raw["evidence_classification"], "evidence_classification"),
        "rollback": _text(raw["rollback"], "rollback"),
        "next_action": _text(raw["next_action"], "next_action"),
        "read_only": True,
    }
    if not SHA_RE.fullmatch(packet["base_sha"]):
        raise TaskPacketError("base_sha must be a git SHA")
    if packet["evidence_classification"] not in EVIDENCE_CLASSES:
        raise TaskPacketError("unknown evidence_classification")
    if not packet["allowed_scope"]:
        raise TaskPacketError("allowed_scope must list at least one path")
    blob = " ".join(
        [
            packet["objective"],
            packet["next_action"],
            " ".join(packet["acceptance_criteria"]),
            " ".join(packet["dependencies"]),
        ]
    )
    _reject_duplicate_authority(blob)
    reserved_hits = [
        name
        for name in RESERVED_AUTHORITIES
        if any(name in path for path in packet["allowed_scope"])
    ]
    if reserved_hits:
        raise TaskPacketError(f"allowed_scope collides with reserved authority: {reserved_hits}")
    return packet


def load_packet(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise TaskPacketError("packet file does not exist")
    if path.stat().st_size > MAX_PACKET_BYTES:
        raise TaskPacketError("packet file exceeds output cap")
    text = path.read_text(encoding="utf-8")
    if text.lstrip().lower().startswith(("<", "<!doctype")):
        raise TaskPacketError("HTML packets are rejected")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TaskPacketError("malformed JSON packet") from exc
    return validate_packet(raw)


def build_packet_from_args(args: argparse.Namespace) -> dict[str, Any]:
    raw = {
        "schema": SCHEMA,
        "agent_id": args.agent_id,
        "source_chat": args.source_chat,
        "lane": args.lane,
        "objective": args.objective,
        "allowed_scope": args.allowed_scope,
        "prohibited_scope": args.prohibited_scope or ["artifacts/", ".env", "live providers"],
        "base_sha": args.base_sha,
        "worktree": args.worktree,
        "dependencies": args.dependencies or ["MarketOS.AIContext.v1"],
        "acceptance_criteria": args.acceptance or ["packet validates", "PR exists", "rollback exists"],
        "selected_tests": args.selected_tests or ["python -m pytest -q tests/ai/test_operator_task_packet.py"],
        "evidence_classification": args.evidence,
        "rollback": args.rollback,
        "next_action": args.next_action,
    }
    return validate_packet(raw)


def safe_output_path(root: Path, raw: str) -> Path:
    relative = assert_safe_path(raw, "output")
    resolved = (root / relative).resolve()
    if root.resolve() not in resolved.parents and resolved != root.resolve():
        raise TaskPacketError("output escapes repository root")
    if resolved.suffix.lower() not in {".json", ".md"}:
        raise TaskPacketError("output must be .json or .md")
    return resolved


# ---------------------------------------------------------------------------
# MarketOS.AIResume.v1 -- resume-after-compaction protocol.
#
# A distinct schema from MarketOS.AITask.v1 on purpose: a task packet
# describes intent before work starts, a resume packet describes proven
# state after a compaction/interruption. It reuses every validation helper
# above (_text, _string_list, assert_safe_path, _secret_like, EVIDENCE_CLASSES)
# rather than re-implementing text/secret/path safety, and references #252's
# MarketOS.AIContext.v1 "replay_hash" field by name instead of inventing a
# second snapshot-identity concept.
# ---------------------------------------------------------------------------

RESUME_SCHEMA = "MarketOS.AIResume.v1"
RESUME_REQUIRED = (
    "task_packet_digest",
    "context_snapshot_replay_hash",
    "worktree",
    "branch",
    "head_sha",
    "base_sha",
    "changed_files",
    "tests_already_run",
    "tests_still_required",
    "open_blockers",
    "pending_decisions",
    "public_sources_inspected",
    "claims_not_yet_proven",
    "next_action",
)


class ResumePacketError(ValueError):
    """Malformed or unsafe AI resume packet."""


def _test_record_list(value: Any, field: str) -> list[dict[str, str]]:
    """Each test record must carry its own evidence classification.

    This is what stops a resumed agent from inventing prior test results or
    silently treating an unavailable/not_run check as passed: a bare string
    like "tests passed" is rejected outright.
    """
    if not isinstance(value, list):
        raise ResumePacketError(f"{field} must be a list of {{command, evidence_classification}} records")
    if len(value) > MAX_LIST:
        raise ResumePacketError(f"{field} exceeds {MAX_LIST} items")
    records: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or "command" not in item or "evidence_classification" not in item:
            raise ResumePacketError(f"{field}[] must be {{command, evidence_classification}}")
        command = _text(item["command"], f"{field}.command")
        classification = _text(item["evidence_classification"], f"{field}.evidence_classification")
        if classification not in EVIDENCE_CLASSES:
            raise ResumePacketError(f"{field}.evidence_classification unknown: {classification}")
        records.append({"command": command, "evidence_classification": classification})
    return records


def _packet_digest(packet: dict[str, Any]) -> str:
    encoded = json.dumps(packet, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_resume_packet(
    task_packet: dict[str, Any],
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
    """Build a resume packet tied to an already-validated task packet.

    ``current_head_sha``, when supplied by the caller from a live ``git
    rev-parse HEAD``, is compared against ``head_sha`` -- a mismatch means
    someone else has committed since this snapshot was taken, so the resume
    packet is flagged rather than silently trusted (guards against
    "overwriting newer commits").
    """
    validated_task = validate_packet(task_packet)
    warnings: list[str] = []
    if base_sha.lower() != validated_task["base_sha"]:
        warnings.append("resume_base_sha_differs_from_task_packet_base_sha")
    if not SHA_RE.fullmatch(head_sha.lower()):
        raise ResumePacketError("head_sha must be a git SHA")
    if not SHA_RE.fullmatch(base_sha.lower()):
        raise ResumePacketError("base_sha must be a git SHA")
    if current_head_sha and current_head_sha.lower() != head_sha.lower():
        warnings.append("resume_head_sha_stale_possible_overwrite_by_newer_commit")

    resume = {
        "schema": RESUME_SCHEMA,
        "task_schema": validated_task["schema"],
        "task_packet_digest": _packet_digest(validated_task),
        "agent_id": validated_task["agent_id"],
        "lane": validated_task["lane"],
        "context_snapshot_replay_hash": _text(context_snapshot_replay_hash, "context_snapshot_replay_hash"),
        "worktree": _text(worktree, "worktree"),
        "branch": _text(branch, "branch"),
        "head_sha": head_sha.lower(),
        "base_sha": base_sha.lower(),
        "changed_files": [assert_safe_path(item, "changed_files") for item in _string_list(changed_files, "changed_files")],
        "tests_already_run": _test_record_list(tests_already_run, "tests_already_run"),
        "tests_still_required": _string_list(tests_still_required, "tests_still_required"),
        "open_blockers": _string_list(open_blockers, "open_blockers"),
        "pending_decisions": _string_list(pending_decisions, "pending_decisions"),
        "public_sources_inspected": _string_list(public_sources_inspected, "public_sources_inspected"),
        "claims_not_yet_proven": _string_list(claims_not_yet_proven, "claims_not_yet_proven"),
        "next_action": _text(next_action, "next_action"),
        "warnings": warnings,
        "read_only": True,
    }
    if _secret_like(resume):
        raise ResumePacketError("resume packet contains secret-shaped values")
    return resume


def validate_resume_packet(raw: Any, *, expected_task_packet: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate a previously-built resume packet, e.g. loaded from disk.

    ``expected_task_packet``, when supplied, must match the resume packet's
    recorded ``agent_id``/``lane`` -- a mismatch means ownership changed
    mid-task, which is rejected rather than silently accepted.
    """
    if not isinstance(raw, dict):
        raise ResumePacketError("resume packet root must be an object")
    if raw.get("schema") != RESUME_SCHEMA:
        raise ResumePacketError(f"unsupported schema: {raw.get('schema')}")
    missing = [key for key in RESUME_REQUIRED if key not in raw]
    if missing:
        raise ResumePacketError(f"missing fields: {missing}")
    if _secret_like(raw):
        raise ResumePacketError("resume packet contains secret-shaped values")
    for record in raw.get("tests_already_run", []):
        if not isinstance(record, dict) or record.get("evidence_classification") not in EVIDENCE_CLASSES:
            raise ResumePacketError("tests_already_run entries must carry a known evidence_classification")
    if expected_task_packet is not None:
        validated_expected = validate_packet(expected_task_packet)
        if raw.get("agent_id") != validated_expected["agent_id"] or raw.get("lane") != validated_expected["lane"]:
            raise ResumePacketError("resume packet ownership does not match the expected task packet")
    return raw


def diff_resume_state(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Flag when a resumed agent is about to repeat already-completed edits."""
    same_head = previous.get("head_sha") == current.get("head_sha")
    same_changes = sorted(previous.get("changed_files", [])) == sorted(current.get("changed_files", []))
    return {
        "no_new_edits_detected": same_head and same_changes,
        "head_advanced": previous.get("head_sha") != current.get("head_sha"),
        "newly_completed_tests": [
            item for item in current.get("tests_already_run", [])
            if item not in previous.get("tests_already_run", [])
        ],
    }


def verify_replay_hash(resume: dict[str, Any], *, recomputed_replay_hash: str) -> bool:
    """True when a resume packet's recorded snapshot hash matches an
    independently recomputed one (e.g. #252's ``context_replay_hash``).

    A resume packet's ``context_snapshot_replay_hash`` is only ever as
    trustworthy as whoever wrote it; this lets a caller who has re-run
    #252's own ``context_replay_hash`` over the live repository state
    detect a tampered or stale resume packet rather than trusting the
    recorded value at face value.
    """
    return resume.get("context_snapshot_replay_hash") == recomputed_replay_hash


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--validate", type=Path)
    parser.add_argument("--agent-id")
    parser.add_argument("--source-chat")
    parser.add_argument("--lane")
    parser.add_argument("--objective")
    parser.add_argument("--allowed-scope", action="append", default=[])
    parser.add_argument("--prohibited-scope", action="append", default=[])
    parser.add_argument("--base-sha")
    parser.add_argument("--worktree")
    parser.add_argument("--dependencies", action="append", default=[])
    parser.add_argument("--acceptance", action="append", default=[])
    parser.add_argument("--selected-tests", action="append", default=[])
    parser.add_argument("--evidence", default="not_run")
    parser.add_argument("--rollback")
    parser.add_argument("--next-action")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.validate:
            packet = load_packet(args.validate)
        else:
            required_cli = (
                args.agent_id,
                args.source_chat,
                args.lane,
                args.objective,
                args.base_sha,
                args.worktree,
                args.rollback,
                args.next_action,
            )
            if not all(required_cli) or not args.allowed_scope:
                raise TaskPacketError("construct mode requires identity, scope, base SHA, worktree, rollback, next action")
            packet = build_packet_from_args(args)
        if args.output:
            target = safe_output_path(args.repository.resolve(), str(args.output))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
        payload = json.dumps(packet, indent=2)
        if args.json or True:
            print(payload)
        return 0
    except TaskPacketError as exc:
        print(json.dumps({"schema": SCHEMA, "classification": "malformed", "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

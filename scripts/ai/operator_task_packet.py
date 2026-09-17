"""Bounded MarketOS.AITask.v1 packet for AI-chat handoff and resume.

Does not replace session_start, generate_session_handoff, quality-gate,
PR-readiness, Governor, TrustOS, or #252 MarketOS.AIContext.v1.
Default mode is validate-and-print. Disk writes require --output.
"""
from __future__ import annotations

import argparse
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

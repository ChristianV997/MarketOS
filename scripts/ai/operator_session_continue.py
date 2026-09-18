"""Fail-closed AI-chat session continuation for MarketOS.AIContext.v1.

Owned by PR #252. This is not MarketOS.AITask.v1 (#254), not a quality gate,
and it never executes provider/payment/order/ads/messaging/publish/deploy
commands. It records and resumes operator steps against a snapshot identity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ai.operator_context_snapshot import (  # noqa: E402
    SCHEMA as CONTEXT_SCHEMA,
    SECRET_SHAPED,
    _posix_path,
    _secret_like,
    _validate_root,
    context_replay_hash,
)

SCHEMA = "MarketOS.AISession.v1"
MAX_PACKET_BYTES = 32_768
MAX_TEXT = 400
LIFECYCLES = (
    "unset",
    "running",
    "interrupted",
    "timed_out",
    "failed",
    "completed",
    "blocked",
    "not_run",
)
OTEL_STATUS = ("unset", "ok", "error")
LIVE_TOKENS = (
    "allow-network",
    "allow-public-network",
    "write-supabase",
    "use-live-provider",
    "claim-live-execution",
    "live-validated",
    "allow-start",
)
FORBIDDEN_OUTPUT = ("artifacts/", ".env", "credentials/", "secrets/")
TASK_SCHEMAS = {"MarketOS.AITask.v1", "MarketOS.AgentEval.v1", "MarketOS.WorktreeSafety.v1"}


class SessionContinueError(ValueError):
    def __init__(self, message: str, classification: str = "malformed") -> None:
        super().__init__(message)
        self.classification = classification


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise SessionContinueError(f"{field} must be a string")
    result = " ".join(value.replace("\r", " ").split())
    if len(result) > MAX_TEXT:
        raise SessionContinueError(f"{field} exceeds {MAX_TEXT} characters")
    if SECRET_SHAPED.search(result):
        raise SessionContinueError(f"{field} contains secret-shaped text", "blocked")
    return result


def output_digest(raw: str, *, cap: int = 200_000) -> dict[str, Any]:
    data = raw.replace("\r\n", "\n").encode("utf-8", errors="replace")
    partial = len(data) > cap
    clipped = data[:cap]
    return {
        "sha256": hashlib.sha256(clipped).hexdigest(),
        "bytes": len(data),
        "partial": partial,
        "classification": "malformed" if partial else "actual",
    }


def _otel_for(lifecycle: str) -> str:
    if lifecycle == "completed":
        return "ok"
    if lifecycle in {"failed", "timed_out", "interrupted", "blocked"}:
        return "error"
    return "unset"


def empty_session(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "schema_version": "1",
        "context_schema": CONTEXT_SCHEMA,
        "read_only": True,
        "mutated": False,
        "task_packet_authority": "PR #254 MarketOS.AITask.v1; this packet does not replace it",
        "replay_hash": identity.get("replay_hash"),
        "worktree": identity.get("worktree"),
        "head": identity.get("head"),
        "origin_main": identity.get("origin_main"),
        "merge_base": identity.get("merge_base"),
        "branch": identity.get("branch"),
        "resume_count": 0,
        "step": {
            "id": "none",
            "command": "",
            "lifecycle": "unset",
            "otel_status": "unset",
            "classification": "not_run",
            "claimed_status": "not_run",
            "exit_code": None,
            "output": {"sha256": None, "bytes": 0, "partial": False, "classification": "not_run"},
        },
        "next_action": "record_or_resume_step",
        "blockers": [],
    }


def identity_from_context(document: dict[str, Any]) -> dict[str, Any]:
    worktree = document.get("worktree") or {}
    return {
        "replay_hash": document.get("replay_hash"),
        "worktree": (worktree.get("path") if isinstance(worktree, dict) else None) or (document.get("repository") or {}).get("path"),
        "head": document.get("HEAD") or document.get("head_sha"),
        "origin_main": document.get("origin_main") or document.get("origin_main_sha"),
        "merge_base": (worktree.get("drift") or {}).get("merge_base") if isinstance(worktree, dict) else None,
        "branch": document.get("branch") or document.get("current_branch"),
        "changed_paths": list(document.get("changed_paths") or []),
    }


def validate_session(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SessionContinueError("session root must be an object")
    encoded = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_PACKET_BYTES:
        raise SessionContinueError("session exceeds output cap")
    if _secret_like(raw):
        raise SessionContinueError("session contains secret-shaped values", "blocked")
    schema = raw.get("schema")
    if schema in TASK_SCHEMAS:
        raise SessionContinueError("refuses #254 schemas; use operator_task_packet.py", "blocked")
    if schema != SCHEMA:
        raise SessionContinueError(f"unsupported schema: {schema}", "blocked")
    if raw.get("context_schema") not in {None, CONTEXT_SCHEMA}:
        raise SessionContinueError("unsupported context schema", "blocked")
    step = raw.get("step") or {}
    if not isinstance(step, dict):
        raise SessionContinueError("step must be an object")
    lifecycle = str(step.get("lifecycle") or "unset")
    if lifecycle not in LIFECYCLES:
        raise SessionContinueError("unknown lifecycle", "blocked")
    command = _text(str(step.get("command") or ""), "command")
    lowered = command.lower()
    if any(token in lowered for token in LIVE_TOKENS):
        raise SessionContinueError("live/network/provider flag rejected", "blocked")
    packet = {
        "schema": SCHEMA,
        "schema_version": "1",
        "context_schema": CONTEXT_SCHEMA,
        "read_only": True,
        "mutated": False,
        "task_packet_authority": raw.get("task_packet_authority")
        or "PR #254 MarketOS.AITask.v1; this packet does not replace it",
        "replay_hash": _text(str(raw.get("replay_hash") or ""), "replay_hash") or None,
        "worktree": _text(str(raw.get("worktree") or ""), "worktree") or None,
        "head": raw.get("head"),
        "origin_main": raw.get("origin_main"),
        "merge_base": raw.get("merge_base"),
        "branch": raw.get("branch"),
        "resume_count": int(raw.get("resume_count") or 0),
        "step": {
            "id": _text(str(step.get("id") or "none"), "step.id") or "none",
            "command": command,
            "lifecycle": lifecycle,
            "otel_status": step.get("otel_status") if step.get("otel_status") in OTEL_STATUS else _otel_for(lifecycle),
            "classification": step.get("classification") or "not_run",
            "claimed_status": step.get("claimed_status") or "not_run",
            "exit_code": step.get("exit_code"),
            "output": step.get("output")
            or {"sha256": None, "bytes": 0, "partial": False, "classification": "not_run"},
        },
        "next_action": _text(str(raw.get("next_action") or "record_or_resume_step"), "next_action"),
        "blockers": list(raw.get("blockers") or []),
    }
    claimed = str(packet["step"]["claimed_status"]).lower()
    exit_code = packet["step"]["exit_code"]
    if claimed in {"passed", "ok", "actual"} and exit_code not in {0, None}:
        raise SessionContinueError("claimed success does not match exit code", "blocked")
    return packet


def load_session(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SessionContinueError("session file does not exist", "unavailable")
    if path.stat().st_size > MAX_PACKET_BYTES:
        raise SessionContinueError("session file exceeds output cap")
    text = path.read_text(encoding="utf-8")
    if text.lstrip().lower().startswith(("<", "<!doctype")):
        raise SessionContinueError("HTML session packets are rejected", "blocked")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SessionContinueError("malformed JSON session") from exc
    return validate_session(raw)


def safe_output_path(root: Path, raw: str) -> Path:
    relative = _posix_path(raw)
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise SessionContinueError("output must stay relative without '..'", "blocked")
    lowered = relative.lower()
    if any(marker in lowered for marker in FORBIDDEN_OUTPUT):
        raise SessionContinueError("output targets a sensitive path", "blocked")
    resolved = (root / relative).resolve()
    if root.resolve() not in resolved.parents and resolved != root.resolve():
        raise SessionContinueError("output escapes repository root", "blocked")
    if resolved.suffix.lower() != ".json":
        raise SessionContinueError("output must be .json", "blocked")
    return resolved


def record_step(
    session: dict[str, Any],
    *,
    command: str,
    lifecycle: str,
    exit_code: int | None,
    stdout: str = "",
    claimed_status: str = "not_run",
    step_id: str = "step",
) -> dict[str, Any]:
    if lifecycle not in LIFECYCLES:
        raise SessionContinueError("unknown lifecycle", "blocked")
    digest = output_digest(stdout)
    if digest["partial"]:
        lifecycle = "interrupted" if lifecycle == "running" else lifecycle
    packet = dict(session)
    packet["step"] = {
        "id": step_id,
        "command": _text(command, "command"),
        "lifecycle": lifecycle,
        "otel_status": _otel_for(lifecycle),
        "classification": digest["classification"] if lifecycle == "completed" else lifecycle.replace("timed_out", "unavailable"),
        "claimed_status": claimed_status,
        "exit_code": exit_code,
        "output": digest,
    }
    if lifecycle == "completed":
        packet["next_action"] = "already_completed"
    elif lifecycle in {"failed", "timed_out", "interrupted"}:
        packet["next_action"] = "safe_retry_same_step"
    else:
        packet["next_action"] = "resume_or_record"
    packet["blockers"] = [] if lifecycle == "completed" else [lifecycle]
    return validate_session(packet)


def resume(session: dict[str, Any], current: dict[str, Any]) -> tuple[dict[str, Any], int]:
    packet = validate_session(session)
    worktree = current.get("worktree")
    if not worktree or not Path(str(worktree)).exists():
        packet["step"]["lifecycle"] = "blocked"
        packet["step"]["otel_status"] = "error"
        packet["step"]["classification"] = "unavailable"
        packet["blockers"] = ["missing_worktree"]
        packet["next_action"] = "reserve_exclusive_worktree"
        return packet, 2
    if packet.get("head") and current.get("head") and packet["head"] != current["head"]:
        packet["step"]["lifecycle"] = "blocked"
        packet["step"]["otel_status"] = "error"
        packet["step"]["classification"] = "blocked"
        packet["blockers"] = ["changed_branch_head"]
        packet["next_action"] = "refresh_snapshot_before_resume"
        return packet, 2
    if packet.get("merge_base") and current.get("merge_base") and packet["merge_base"] != current["merge_base"]:
        packet["step"]["lifecycle"] = "blocked"
        packet["step"]["otel_status"] = "error"
        packet["step"]["classification"] = "blocked"
        packet["blockers"] = ["stale_merge_base"]
        packet["next_action"] = "refresh_snapshot_before_resume"
        return packet, 2
    if packet.get("replay_hash") and current.get("replay_hash") and packet["replay_hash"] != current["replay_hash"]:
        packet["step"]["lifecycle"] = "blocked"
        packet["step"]["otel_status"] = "error"
        packet["step"]["classification"] = "blocked"
        packet["blockers"] = ["replay_hash_mismatch"]
        packet["next_action"] = "refresh_snapshot_before_resume"
        return packet, 2

    packet["resume_count"] = int(packet.get("resume_count") or 0) + 1
    lifecycle = packet["step"]["lifecycle"]
    if lifecycle == "completed":
        packet["next_action"] = "already_completed"
        return packet, 0
    if lifecycle == "running":
        packet["step"]["lifecycle"] = "interrupted"
        packet["step"]["otel_status"] = "error"
        packet["step"]["classification"] = "interrupted"
        packet["blockers"] = ["interrupted_command"]
        packet["next_action"] = "safe_retry_same_step"
        return packet, 2
    if lifecycle in {"failed", "timed_out", "interrupted"}:
        packet["next_action"] = "safe_retry_same_step"
        return packet, 2
    packet["next_action"] = "record_or_resume_step"
    return packet, 0


def write_session(root: Path, relative: str, packet: dict[str, Any]) -> Path:
    target = safe_output_path(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _error_payload(exc: SessionContinueError) -> dict[str, Any]:
    return {"schema": SCHEMA, "classification": exc.classification, "error": str(exc), "read_only": True, "mutated": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--session", type=Path)
    parser.add_argument("--context", type=Path)
    parser.add_argument("--record")
    parser.add_argument("--command", default="")
    parser.add_argument("--lifecycle", default="unset")
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--claimed-status", default="not_run")
    parser.add_argument("--stdout-file", type=Path)
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = args.repository.resolve()
    try:
        validated, reason = _validate_root(root)
        if validated is None:
            raise SessionContinueError(reason or "invalid_repository_path", "blocked")
        if args.session:
            session = load_session(args.session)
        else:
            identity = {
                "replay_hash": None,
                "worktree": str(validated),
                "head": None,
                "origin_main": None,
                "merge_base": None,
                "branch": None,
            }
            if args.context:
                context = json.loads(args.context.read_text(encoding="utf-8"))
                if not isinstance(context, dict) or context.get("schema") != CONTEXT_SCHEMA:
                    raise SessionContinueError("context is not MarketOS.AIContext.v1", "blocked")
                identity = identity_from_context(context)
                if not identity.get("replay_hash"):
                    identity["replay_hash"] = context_replay_hash(
                        head=identity.get("head"),
                        origin_main=identity.get("origin_main"),
                        merge_base=identity.get("merge_base"),
                        branch=str(identity.get("branch") or "detached"),
                        worktree=str(identity.get("worktree") or validated),
                        changed_paths=list(identity.get("changed_paths") or []),
                    )
            session = empty_session(identity)
        if args.record:
            stdout = ""
            if args.stdout_file:
                stdout = args.stdout_file.read_text(encoding="utf-8", errors="replace")
            session = record_step(
                session,
                command=args.command,
                lifecycle=args.lifecycle,
                exit_code=args.exit_code,
                stdout=stdout,
                claimed_status=args.claimed_status,
                step_id=args.record,
            )
        else:
            current = {
                "worktree": session.get("worktree") or str(validated),
                "head": session.get("head"),
                "merge_base": session.get("merge_base"),
                "replay_hash": session.get("replay_hash"),
            }
            if args.context:
                context = json.loads(args.context.read_text(encoding="utf-8"))
                current = identity_from_context(context)
            session, code = resume(session, current)
            if args.output:
                write_session(validated, args.output, session)
            print(json.dumps(session, indent=2, sort_keys=True, ensure_ascii=False))
            return code
        if args.output:
            write_session(validated, args.output, session)
        print(json.dumps(session, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except SessionContinueError as exc:
        print(json.dumps(_error_payload(exc), indent=2), file=sys.stderr)
        return 2
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps(_error_payload(SessionContinueError(str(exc)))), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

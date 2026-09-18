from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ai.operator_context_snapshot import SCHEMA as CONTEXT_SCHEMA, context_replay_hash
from scripts.ai.operator_session_continue import (
    SCHEMA,
    SessionContinueError,
    empty_session,
    load_session,
    main,
    output_digest,
    record_step,
    resume,
    validate_session,
    write_session,
)


def _identity(**overrides):
    base = {
        "replay_hash": "abc123",
        "worktree": str(Path.cwd()),
        "head": "aaa111",
        "origin_main": "bbb222",
        "merge_base": "ccc333",
        "branch": "cursor/ai-chat-operator-context-v1",
    }
    base.update(overrides)
    return base


def test_schema_does_not_duplicate_pr254():
    assert SCHEMA == "MarketOS.AISession.v1"
    assert SCHEMA != "MarketOS.AITask.v1"
    assert CONTEXT_SCHEMA == "MarketOS.AIContext.v1"


def test_replay_hash_is_stable():
    first = context_replay_hash(head="a", origin_main="b", merge_base="c", branch="x", worktree="wt", changed_paths=["b.py", "a.py"])
    second = context_replay_hash(head="a", origin_main="b", merge_base="c", branch="x", worktree="wt", changed_paths=["a.py", "b.py"])
    assert first == second
    third = context_replay_hash(head="z", origin_main="b", merge_base="c", branch="x", worktree="wt", changed_paths=["a.py", "b.py"])
    assert first != third


def test_clean_repository_session(tmp_path: Path):
    packet = empty_session(_identity(worktree=str(tmp_path)))
    assert packet["step"]["lifecycle"] == "unset"
    assert packet["step"]["otel_status"] == "unset"


def test_protected_and_unrelated_dirty_disclosed_by_snapshot(tmp_path: Path, monkeypatch):
    from scripts.ai import operator_context_snapshot as snapshot

    assert snapshot._protected_dirty_summary([".env", "artifacts/x.json", "scripts/ai/foo.py"])["count"] == 2
    assert snapshot._protected_dirty_summary([".env"])["paths_disclosed"] is False
    assert snapshot._unrelated_dirty(["scripts/ai/foo.py", "fix_catalog.py"]) == ["fix_catalog.py"]


def test_timeout_and_malformed_and_secret():
    digest = output_digest("x" * 200_001)
    assert digest["partial"] is True
    assert digest["classification"] == "malformed"
    with pytest.raises(SessionContinueError):
        validate_session({"schema": "MarketOS.AITask.v1", "step": {}})
    with pytest.raises(SessionContinueError, match="secret"):
        validate_session(empty_session(_identity()) | {"step": {"id": "s", "command": "ghp_abcdefghijklmnopqrstuvwxyz1234", "lifecycle": "unset"}})


def test_unsupported_schema():
    with pytest.raises(SessionContinueError, match="unsupported schema"):
        validate_session({"schema": "MarketOS.AISession.v0", "step": {}})


def test_successful_and_failed_resumable_steps(tmp_path: Path):
    session = empty_session(_identity(worktree=str(tmp_path)))
    ok = record_step(session, command="python scripts/ai/select_tests.py --json", lifecycle="completed", exit_code=0, claimed_status="actual", stdout="{}")
    assert ok["step"]["lifecycle"] == "completed"
    assert ok["step"]["otel_status"] == "ok"
    resumed, code = resume(ok, _identity(worktree=str(tmp_path), replay_hash="abc123", head="aaa111", merge_base="ccc333"))
    assert code == 0
    assert resumed["next_action"] == "already_completed"
    failed = record_step(session, command="python -m pytest -q tests/ai/test_operator_session_continue.py", lifecycle="failed", exit_code=1, claimed_status="failed")
    again, code = resume(failed, _identity(worktree=str(tmp_path), replay_hash="abc123", head="aaa111", merge_base="ccc333"))
    assert code == 2
    assert again["next_action"] == "safe_retry_same_step"


def test_interrupted_timeout_partial_stale_and_missing(tmp_path: Path):
    session = empty_session(_identity(worktree=str(tmp_path)))
    running = record_step(session, command="python scripts/ai/operator_context_snapshot.py --json", lifecycle="running", exit_code=None)
    interrupted, code = resume(running, _identity(worktree=str(tmp_path), replay_hash="abc123", head="aaa111", merge_base="ccc333"))
    assert code == 2
    assert interrupted["step"]["lifecycle"] == "interrupted"
    timed = record_step(session, command="python scripts/ai/operator_context_snapshot.py --json", lifecycle="timed_out", exit_code=None)
    assert timed["step"]["otel_status"] == "error"
    missing, code = resume(session, _identity(worktree=str(tmp_path / "gone"), replay_hash="abc123", head="aaa111", merge_base="ccc333"))
    assert code == 2
    assert "missing_worktree" in missing["blockers"]
    stale_head, code = resume(
        {**session, "head": "aaa111", "replay_hash": "abc123", "merge_base": "ccc333", "worktree": str(tmp_path)},
        _identity(worktree=str(tmp_path), replay_hash="abc123", head="ddd444", merge_base="ccc333"),
    )
    assert "changed_branch_head" in stale_head["blockers"]
    stale_base, code = resume(
        {**session, "head": "aaa111", "replay_hash": "abc123", "merge_base": "ccc333", "worktree": str(tmp_path)},
        _identity(worktree=str(tmp_path), replay_hash="abc123", head="aaa111", merge_base="eee555"),
    )
    assert "stale_merge_base" in stale_base["blockers"]


def test_repeated_replay_increments_resume_count(tmp_path: Path):
    session = empty_session(_identity(worktree=str(tmp_path), replay_hash="abc123"))
    session["head"] = "aaa111"
    session["merge_base"] = "ccc333"
    first, _ = resume(session, _identity(worktree=str(tmp_path), replay_hash="abc123", head="aaa111", merge_base="ccc333"))
    second, _ = resume(first, _identity(worktree=str(tmp_path), replay_hash="abc123", head="aaa111", merge_base="ccc333"))
    assert second["resume_count"] == first["resume_count"] + 1


def test_claimed_success_mismatch_and_live_flag():
    session = empty_session(_identity())
    with pytest.raises(SessionContinueError, match="claimed success"):
        record_step(session, command="python -m pytest -q tests/ai", lifecycle="completed", exit_code=1, claimed_status="passed")
    with pytest.raises(SessionContinueError, match="live"):
        record_step(session, command="python x.py --allow-network", lifecycle="running", exit_code=None)


def test_persisted_packet_roundtrip(tmp_path: Path):
    repo = tmp_path / "MarketOS"
    (repo / "scripts" / "ai").mkdir(parents=True)
    (repo / "AGENTS.md").write_text("#\n", encoding="utf-8")
    (repo / ".git").mkdir()
    (repo / "scripts" / "ai" / "operator_context_snapshot.py").write_text("#\n", encoding="utf-8")
    session = empty_session(_identity(worktree=str(repo)))
    recorded = record_step(session, command="python scripts/ai/select_tests.py --json", lifecycle="completed", exit_code=0, stdout="{}", claimed_status="actual")
    path = write_session(repo, "docs/ai/session-continue.json", recorded)
    loaded = load_session(path)
    assert loaded["schema"] == SCHEMA
    assert loaded["step"]["lifecycle"] == "completed"
    assert "artifacts" not in str(path)


def test_malformed_resume_artifact(tmp_path: Path):
    repo = tmp_path / "MarketOS"
    (repo / "scripts" / "ai").mkdir(parents=True)
    (repo / "AGENTS.md").write_text("#\n", encoding="utf-8")
    (repo / ".git").mkdir()
    (repo / "scripts" / "ai" / "operator_context_snapshot.py").write_text("#\n", encoding="utf-8")
    path = repo / "bad.json"
    path.write_text("{", encoding="utf-8")
    assert main(["--repository", str(repo), "--session", str(path)]) == 2


def test_crlf_and_non_ascii_digest():
    digest = output_digest("café\r\nready")
    assert digest["partial"] is False
    assert len(digest["sha256"]) == 64


def test_compaction_resume_without_events(tmp_path: Path):
    session = empty_session(_identity(worktree=str(tmp_path), replay_hash="abc123"))
    session["head"] = "aaa111"
    session["merge_base"] = "ccc333"
    packet, code = resume(session, _identity(worktree=str(tmp_path), replay_hash="abc123", head="aaa111", merge_base="ccc333"))
    assert code == 0
    assert packet["step"]["lifecycle"] == "unset"
    assert packet["next_action"] == "record_or_resume_step"

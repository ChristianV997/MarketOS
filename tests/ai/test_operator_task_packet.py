from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ai.operator_task_packet import (
    SCHEMA,
    TaskPacketError,
    assert_safe_path,
    load_packet,
    main,
    validate_packet,
)


def _valid(**overrides):
    packet = {
        "schema": SCHEMA,
        "agent_id": "grok-ai-development-tooling-engineer",
        "source_chat": "Grok Chat",
        "lane": "AI-CHAT-DEVELOPER-TOOLING-RETROFIT-V1",
        "objective": "Add task packet validation",
        "allowed_scope": ["scripts/ai/operator_task_packet.py", "tests/ai/test_operator_task_packet.py"],
        "prohibited_scope": ["artifacts/", ".env", "live providers"],
        "base_sha": "df59a0609897907c1565d7d5f78e20959095d430",
        "worktree": "MarketOS.worktrees/ai-chat-tooling",
        "dependencies": ["MarketOS.AIContext.v1", "PR #252"],
        "acceptance_criteria": ["packet validates", "no reserved authority rewrite"],
        "selected_tests": ["python -m pytest -q tests/ai/test_operator_task_packet.py"],
        "evidence_classification": "actual",
        "rollback": "close draft PR and delete branch",
        "next_action": "human review",
    }
    packet.update(overrides)
    return packet


def test_schema_constant():
    assert SCHEMA == "MarketOS.AITask.v1"


def test_validate_accepts_bounded_packet():
    assert validate_packet(_valid())["read_only"] is True


def test_malformed_missing_field():
    raw = _valid()
    del raw["rollback"]
    with pytest.raises(TaskPacketError, match="missing fields"):
        validate_packet(raw)


def test_redaction_and_secret_rejection():
    with pytest.raises(TaskPacketError, match="secret"):
        validate_packet(_valid(objective="use ghp_abcdefghijklmnopqrstuvwxyz1234"))


def test_path_safety_rejects_artifacts_and_traversal():
    with pytest.raises(TaskPacketError):
        assert_safe_path("artifacts/out.json", "allowed_scope")
    with pytest.raises(TaskPacketError):
        assert_safe_path("../secrets/key", "allowed_scope")
    with pytest.raises(TaskPacketError):
        assert_safe_path(".env", "allowed_scope")


def test_reserved_authority_collision():
    with pytest.raises(TaskPacketError, match="reserved authority"):
        validate_packet(_valid(allowed_scope=["scripts/ai/operator_context_snapshot.py"]))


def test_duplicate_authority_phrase():
    with pytest.raises(TaskPacketError, match="duplicate"):
        validate_packet(_valid(objective="Create a second quality gate"))


def test_unknown_evidence_class():
    with pytest.raises(TaskPacketError, match="unknown evidence"):
        validate_packet(_valid(evidence_classification="passed"))


def test_load_packet_and_cli_validate(tmp_path: Path):
    path = tmp_path / "packet.json"
    path.write_text(json.dumps(_valid()), encoding="utf-8")
    loaded = load_packet(path)
    assert loaded["schema"] == SCHEMA
    assert main(["--validate", str(path), "--json"]) == 0


def test_cli_malformed_exit_code(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text("{", encoding="utf-8")
    assert main(["--validate", str(path)]) == 2


def test_output_write_is_explicit_and_safe(tmp_path: Path):
    source = tmp_path / "packet.json"
    source.write_text(json.dumps(_valid()), encoding="utf-8")
    target = Path("docs/ai/generated-task-packet.json")
    code = main(["--repository", str(tmp_path), "--validate", str(source), "--output", str(target)])
    assert code == 0
    written = tmp_path / target
    assert written.is_file()
    assert "AITask" in written.read_text(encoding="utf-8")


def test_no_mutation_without_output(tmp_path: Path):
    before = list(tmp_path.rglob("*"))
    assert main(["--validate", str(tmp_path)]) == 2
    after = list(tmp_path.rglob("*"))
    assert before == after

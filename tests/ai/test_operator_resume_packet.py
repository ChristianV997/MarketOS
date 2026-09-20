import pytest

from scripts.ai.operator_task_packet import (
    ResumePacketError,
    build_resume_packet,
    diff_resume_state,
    validate_resume_packet,
    verify_replay_hash,
)

TASK_PACKET = {
    "schema": "MarketOS.AITask.v1",
    "agent_id": "claude-ai-chat-operator-reconciler",
    "source_chat": "Claude",
    "lane": "AI-CHAT-DEVELOPER-OPERATOR-RECONCILIATION-V4",
    "objective": "reconcile 252 and 254",
    "allowed_scope": ["scripts/ai/native_agent_capability.py"],
    "prohibited_scope": ["artifacts/"],
    "base_sha": "df59a0609897907c1565d7d5f78e20959095d430",
    "worktree": ".claude/worktrees/ai-chat-operator-reconciliation-v4",
    "dependencies": ["MarketOS.AIContext.v1"],
    "acceptance_criteria": ["tests pass"],
    "selected_tests": ["pytest tests/ai"],
    "evidence_classification": "not_run",
    "rollback": "revert the commit",
    "next_action": "continue",
}
HEAD_SHA = "481aeeb7" + "0" * 32


def _resume_kwargs(**overrides):
    base = dict(
        context_snapshot_replay_hash="deadbeef" * 8,
        worktree=".claude/worktrees/ai-chat-operator-reconciliation-v4",
        branch="claude/ai-chat-operator-reconciliation-v4",
        head_sha=HEAD_SHA,
        base_sha=TASK_PACKET["base_sha"],
        changed_files=["scripts/ai/native_agent_capability.py"],
        tests_already_run=[{"command": "pytest tests/ai/test_native_agent_capability.py", "evidence_classification": "actual"}],
        tests_still_required=["pytest tests/ai/test_worktree_safety.py"],
        open_blockers=[],
        pending_decisions=[],
        public_sources_inspected=[],
        claims_not_yet_proven=[],
        next_action="run remaining tests",
    )
    base.update(overrides)
    return base


def test_build_and_validate_round_trip():
    resume = build_resume_packet(TASK_PACKET, **_resume_kwargs())
    assert resume["schema"] == "MarketOS.AIResume.v1"
    assert resume["warnings"] == []
    validate_resume_packet(resume, expected_task_packet=TASK_PACKET)


def test_stale_base_sha_is_flagged_not_silently_accepted():
    resume = build_resume_packet(TASK_PACKET, **_resume_kwargs(base_sha="1" * 40))
    assert "resume_base_sha_differs_from_task_packet_base_sha" in resume["warnings"]


def test_head_sha_drift_warns_of_possible_overwrite():
    resume = build_resume_packet(
        TASK_PACKET, **_resume_kwargs(current_head_sha="9" * 40),
    )
    assert "resume_head_sha_stale_possible_overwrite_by_newer_commit" in resume["warnings"]


def test_ownership_change_between_task_packet_and_resume_is_rejected():
    resume = build_resume_packet(TASK_PACKET, **_resume_kwargs())
    hijacked_task = dict(TASK_PACKET, agent_id="a-different-agent")
    with pytest.raises(ResumePacketError, match="ownership"):
        validate_resume_packet(resume, expected_task_packet=hijacked_task)


def test_scope_widened_after_resume_is_rejected_even_with_matching_agent_and_lane():
    """A resumed session must not be able to swap in a task packet with a
    wider allowed_scope (same agent_id/lane) than the one the resume
    packet's task_packet_digest actually committed to -- that would let a
    resumed run silently expand its approved paths. The ownership check
    alone (agent_id/lane match) does not catch this; the recorded
    task_packet_digest must be re-verified against expected_task_packet."""
    resume = build_resume_packet(TASK_PACKET, **_resume_kwargs())
    widened_task = dict(TASK_PACKET, allowed_scope=[*TASK_PACKET["allowed_scope"], "backend/"])
    with pytest.raises(ResumePacketError, match="digest"):
        validate_resume_packet(resume, expected_task_packet=widened_task)


def test_test_records_must_carry_a_known_evidence_classification():
    with pytest.raises(ResumePacketError):
        build_resume_packet(TASK_PACKET, **_resume_kwargs(tests_already_run=["pytest ran and passed, trust me"]))
    with pytest.raises(ResumePacketError):
        build_resume_packet(
            TASK_PACKET,
            **_resume_kwargs(tests_already_run=[{"command": "pytest x", "evidence_classification": "definitely_passed"}]),
        )


def test_secret_shaped_field_is_rejected():
    with pytest.raises(ValueError):
        build_resume_packet(TASK_PACKET, **_resume_kwargs(next_action="use token ghp_" + "a" * 30))


def test_invalid_shas_are_rejected():
    with pytest.raises(ResumePacketError):
        build_resume_packet(TASK_PACKET, **_resume_kwargs(head_sha="not-a-sha"))


def test_diff_resume_state_detects_repeat_vs_progress():
    first = build_resume_packet(TASK_PACKET, **_resume_kwargs())
    same = build_resume_packet(TASK_PACKET, **_resume_kwargs())
    assert diff_resume_state(first, same)["no_new_edits_detected"] is True

    advanced = build_resume_packet(
        TASK_PACKET,
        **_resume_kwargs(
            head_sha="c0ffee00" + "0" * 32,
            changed_files=["scripts/ai/native_agent_capability.py", "scripts/ai/worktree_safety.py"],
            tests_already_run=[
                {"command": "pytest tests/ai/test_native_agent_capability.py", "evidence_classification": "actual"},
                {"command": "pytest tests/ai/test_worktree_safety.py", "evidence_classification": "actual"},
            ],
        ),
    )
    diff = diff_resume_state(first, advanced)
    assert diff["no_new_edits_detected"] is False
    assert diff["head_advanced"] is True
    assert len(diff["newly_completed_tests"]) == 1


def test_missing_required_field_on_a_loaded_resume_packet_is_rejected():
    resume = build_resume_packet(TASK_PACKET, **_resume_kwargs())
    incomplete = dict(resume)
    del incomplete["open_blockers"]
    with pytest.raises(ResumePacketError, match="missing fields"):
        validate_resume_packet(incomplete)


def test_verify_replay_hash_detects_a_tampered_resume_bundle():
    resume = build_resume_packet(TASK_PACKET, **_resume_kwargs())
    genuine_replay_hash = resume["context_snapshot_replay_hash"]
    assert verify_replay_hash(resume, recomputed_replay_hash=genuine_replay_hash) is True

    tampered = dict(resume, context_snapshot_replay_hash="f" * 64)
    assert verify_replay_hash(tampered, recomputed_replay_hash=genuine_replay_hash) is False

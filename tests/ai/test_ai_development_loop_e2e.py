"""True end-to-end integration test for the AI-development loop.

Unlike tests/ai/test_execution_bundle.py (which tests each phase in
isolation), this file chains one realistic scenario through all seven
phases -- prepare -> admit -> select -> execute -> evaluate -> handoff ->
pr -- feeding each phase's real output into the next, using the real
#252 snapshot builder (no GitHub call) and real subprocess execution
(no mocking). It proves the loop actually composes, not just that each
link works alone.

    context snapshot (#252)
            |
            v
        prepare  ---------------------------------------------+
            |                                                  |
            v                                                  |
         admit (worktree_safety)                               |
            |                                                  |
            v                                                  |
        select (select_tests)                                  |
            |                                                  |
            v                                                  |
        execute (allowlisted commands) --> to_evidence_classification
            |                                                  |
            v                                                  |
        evaluate (agent_output_eval)                           |
            |                                                  |
            v                                                  |
        handoff (resume packet + command manifest) <-----------+
            |
            v
        pr_check (scope match)
"""
from __future__ import annotations

from pathlib import Path

from scripts.ai import execution_bundle as bundle
from scripts.ai import operator_context_snapshot
from scripts.ai.operator_task_packet import validate_packet


def _real_snapshot() -> dict:
    document, _ = operator_context_snapshot.build_snapshot(Path.cwd(), include_github=False)
    return document


def test_the_complete_loop_runs_end_to_end_with_real_snapshot_and_real_commands():
    # --- context snapshot (#252) --------------------------------------
    snapshot = _real_snapshot()
    assert snapshot["schema"] == "MarketOS.AIContext.v1"
    assert snapshot.get("replay_hash")

    # --- prepare --------------------------------------------------------
    task_packet_raw = {
        "agent_id": "claude-ai-development-loop-consolidation",
        "source_chat": "Claude",
        "lane": "marketos-ai-development-loop-consolidation-v1",
        "objective": "prove the complete loop composes end to end",
        "allowed_scope": ["tests/ai/test_ai_development_loop_e2e.py"],
        "prohibited_scope": ["artifacts/", ".env"],
        "base_sha": snapshot["HEAD"] or snapshot["origin_main"] or "0" * 40,
        "worktree": snapshot["repository"]["path"],
        "dependencies": ["MarketOS.AIContext.v1"],
        "acceptance_criteria": ["the loop test passes"],
        "selected_tests": ["python3 -m pytest tests/ai/test_ai_development_loop_e2e.py -q"],
        "evidence_classification": "not_run",
        "rollback": "revert the commit that added this test",
        "next_action": "run the remaining selected tests",
    }
    prepared = bundle.prepare(snapshot, task_packet_raw)
    task_packet = prepared["task_packet"]
    assert prepared["context_snapshot_replay_hash"] == snapshot["replay_hash"]
    assert prepared["warnings"] == []  # base_sha genuinely matches the real snapshot

    # --- admit ------------------------------------------------------------
    admitted = bundle.admit(Path.cwd(), task_packet)
    assert admitted["document"]["schema"] == "MarketOS.WorktreeSafety.v1"
    # Whatever this sandbox's actual safety verdict is, it must be a real,
    # structured verdict -- not silently skipped.
    assert isinstance(admitted["admitted"], bool)

    # --- select -----------------------------------------------------------
    selection = bundle.select(task_packet)
    assert "lanes" in selection["result"]

    # --- execute (real subprocesses, no mocking) --------------------------
    ok_command = "python3 -m pytest tests/ai/test_native_agent_capability.py -q"
    bad_command = "python3 -m pytest tests/ai/test_this_file_does_not_exist.py -q"
    execution = bundle.execute(
        [
            ok_command,
            {"argv": ["python3", "-m", "pytest", "tests/ai"], "ci_only": True},
            bad_command,
        ],
        skip_commands={bad_command},
    )
    assert execution["classifications"][ok_command] == "passed"
    assert execution["classifications"]["python3 -m pytest tests/ai"] == "ci_unavailable"
    assert execution["classifications"][bad_command] == "skipped"
    # Distinctness (requirement 7): passed, ci_unavailable, and skipped are
    # three different values, not silently collapsed into one another.
    assert len({execution["classifications"][c] for c in (ok_command, "python3 -m pytest tests/ai", bad_command)}) == 3

    # --- evaluate -----------------------------------------------------------
    report = {
        "claims": [f"ran {ok_command} and it passed"],
        "executed_commands": [ok_command],
        "changed_files": ["tests/ai/test_ai_development_loop_e2e.py"],
        "pr": "https://example.invalid/pr/consolidation",
        "rollback": task_packet["rollback"],
        "check_classifications": {ok_command: execution["classifications"][ok_command]},
        "actual_check_classifications": {ok_command: execution["classifications"][ok_command]},
    }
    evaluation = bundle.evaluate(report, task_packet, commands=[ok_command])
    assert evaluation["passed"] is True, evaluation["document"]["findings"]

    # --- handoff: execute()'s output feeds directly into the resume packet -
    tests_already_run = [
        {"command": ok_command, "evidence_classification": bundle.to_evidence_classification(execution["classifications"][ok_command])},
    ]
    handoff = bundle.handoff(
        task_packet,
        context_snapshot_replay_hash=prepared["context_snapshot_replay_hash"],
        worktree=task_packet["worktree"],
        branch=snapshot.get("branch") or "detached",
        head_sha=task_packet["base_sha"],
        base_sha=task_packet["base_sha"],
        changed_files=["tests/ai/test_ai_development_loop_e2e.py"],
        tests_already_run=tests_already_run,
        tests_still_required=["python3 -m pytest tests/ai -q"],
        open_blockers=list(admitted["document"].get("blockers", [])),
        pending_decisions=[],
        public_sources_inspected=[],
        claims_not_yet_proven=[],
        next_action="open the PR",
    )
    assert handoff["resume"]["schema"] == "MarketOS.AIResume.v1"
    assert handoff["resume"]["tests_already_run"] == tests_already_run
    assert "AGENT_ID:" in handoff["human_readable"]

    # --- pr -----------------------------------------------------------------
    pr_result = bundle.pr_check(
        task_packet, pr_reference=report["pr"], pr_changed_files=["tests/ai/test_ai_development_loop_e2e.py"]
    )
    assert pr_result["valid"] is True


def test_a_genuine_failure_survives_the_whole_pipeline_without_being_hidden():
    """The specific defect class this loop must never produce: a real
    failure quietly becoming a "passed" claim by the time it reaches
    evaluate() or handoff()."""
    failing_command = "python3 -m pytest tests/ai/test_this_file_does_not_exist_either.py -q"
    execution = bundle.execute([failing_command])
    assert execution["classifications"][failing_command] == "failed"

    task_packet = validate_packet(
        {
            "agent_id": "claude-ai-development-loop-consolidation",
            "source_chat": "Claude",
            "lane": "marketos-ai-development-loop-consolidation-v1",
            "objective": "prove a real failure is never hidden",
            "allowed_scope": ["tests/ai/test_ai_development_loop_e2e.py"],
            "prohibited_scope": ["artifacts/"],
            "base_sha": "0" * 40,
            "worktree": ".",
            "dependencies": [],
            "acceptance_criteria": [],
            "selected_tests": [failing_command],
            "evidence_classification": "not_run",
            "rollback": "revert",
            "next_action": "fix the failure",
        }
    )

    # A dishonest report claims the check is merely "unavailable".
    dishonest_report = {
        "claims": [],
        "pr": "https://example.invalid/pr/1",
        "rollback": "revert",
        "check_classifications": {failing_command: "unavailable"},
        "actual_check_classifications": {failing_command: execution["classifications"][failing_command]},
    }
    evaluation = bundle.evaluate(dishonest_report, task_packet, commands=[failing_command])
    assert evaluation["passed"] is False
    assert any(item["rule"] == "executed_failure_not_unavailable" for item in evaluation["document"]["findings"])

    # And an honest report, using to_evidence_classification directly on
    # execute()'s real output, is what handoff() actually requires.
    evidence_classification = bundle.to_evidence_classification(execution["classifications"][failing_command])
    assert evidence_classification == "failed"

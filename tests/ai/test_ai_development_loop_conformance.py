"""Conformance regression suite for the composed AI-development loop.

PROMPT 6 (AI-DEVELOPMENT-LOOP-CONFORMANCE-V2) requires proving the full
11-step chain --

    snapshot -> task packet -> worktree safety -> dependency/scope
    admission -> selected-test selection -> allowlisted execution ->
    execution result classification -> evidence-class translation ->
    output evaluation -> resumable handoff -> PR-readiness evidence

-- with real subprocess execution where meaningful, plus substantial
regression coverage for 16 named scenarios. This file does not introduce a
second task schema, snapshot authority, quality gate, event spine, or
autonomous runtime; every scenario below drives the real, already-merged
surfaces in ``scripts/ai/execution_bundle.py``, ``worktree_safety.py``,
``operator_task_packet.py``, ``agent_output_eval.py``, and
``native_agent_capability.py``.

Scenario -> real code path:

 1. passed                              -- run_allowlisted() real success
 2. skipped                             -- execute(skip_commands=...)
 3. timed_out                           -- run_allowlisted() real timeout
 4. executed failure                    -- run_allowlisted() real failure,
                                            never relabeled by evaluate()
 5. unavailable                         -- run_allowlisted()'s own
                                            FileNotFoundError catch
 6. not_run                             -- to_evidence_classification() /
                                            EVIDENCE_CLASSES
 7. fixture/simulated                   -- agent_output_eval.fixture_not_live
 8. malformed                           -- validate_argv() rejection paths
 9. secret rejection                    -- SECRET_SHAPED / _secret_like
10. path traversal rejection            -- assert_safe_path() / unsafe_target()
11. changed-file scope violation        -- changed_files_match_scope / pr_check
12. missing rollback                    -- rollback_must_exist
13. stale base                          -- worktree_safety stale_branch_base
14. duplicate authority                 -- RESERVED_AUTHORITIES /
                                            duplicate_authority_rejected
15. missing PR                          -- pr_must_exist / pr_check
16. incomplete handoff                  -- validate_resume_packet missing
                                            fields / ownership mismatch
    (bonus) invalid CoderOS vocabulary  -- worktree_safety's coderos field
                                            never leaks native_agent_capability's
                                            own state vocabulary

An additional agent-eval-style harness runs a deterministic real command
three times and records pass rate, consistency, runtime, and evidence
classification -- without fabricating any external agent's availability.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from scripts.ai import agent_output_eval, execution_bundle as bundle, native_agent_capability, worktree_safety
from scripts.ai.operator_task_packet import (
    EVIDENCE_CLASSES,
    RESERVED_AUTHORITIES,
    ResumePacketError,
    TaskPacketError,
    build_resume_packet,
    validate_packet,
    validate_resume_packet,
)

SNAPSHOT = {
    "schema": "MarketOS.AIContext.v1",
    "HEAD": "d" * 40,
    "origin_main": "d" * 40,
    "replay_hash": "b" * 64,
}


def _task_packet(**overrides):
    raw = {
        "agent_id": "claude-ai-development-loop-conformance-owner",
        "source_chat": "Claude",
        "lane": "AI-DEVELOPMENT-LOOP-CONFORMANCE-V2",
        "objective": "prove the composed loop's 16 named scenarios",
        "allowed_scope": ["tests/ai/test_ai_development_loop_conformance.py"],
        "prohibited_scope": ["artifacts/", ".env"],
        "base_sha": "d" * 40,
        "worktree": ".claude/worktrees/marketos-ai-development-loop-consolidation-v1",
        "dependencies": ["MarketOS.AIContext.v1"],
        "acceptance_criteria": ["all 16 named scenarios are covered"],
        "selected_tests": ["python3 -m pytest tests/ai/test_ai_development_loop_conformance.py -q"],
        "evidence_classification": "not_run",
        "rollback": "revert the commit that added this test",
        "next_action": "run the remaining selected tests",
    }
    raw.update(overrides)
    return raw


# ---------------------------------------------------------------------------
# 1. passed
# ---------------------------------------------------------------------------


def test_passed_is_a_real_subprocess_success_not_a_fabricated_claim():
    result = bundle.run_allowlisted(["python3", "-m", "pytest", "tests/ai/test_native_agent_capability.py", "-q"])
    assert result["classification"] == "passed"
    assert result["exit_code"] == 0
    assert bundle.to_evidence_classification("passed") == "actual"


# ---------------------------------------------------------------------------
# 2. skipped
# ---------------------------------------------------------------------------


def test_skipped_is_an_explicit_caller_requested_skip_not_a_silent_drop():
    command = "python3 -m pytest tests/ai/test_this_file_does_not_exist.py -q"
    execution = bundle.execute([command], skip_commands={command})
    assert execution["classifications"][command] == "skipped"
    assert bundle.to_evidence_classification("skipped") == "not_run"


# ---------------------------------------------------------------------------
# 3. timed_out
# ---------------------------------------------------------------------------


def test_timed_out_is_a_real_subprocess_timeout_not_a_simulated_value():
    started = time.monotonic()
    result = bundle.run_allowlisted(["python3", "-m", "pytest", "tests/ai", "-q"], timeout_s=0.05)
    elapsed = time.monotonic() - started
    assert result["classification"] == "timed_out"
    assert elapsed < 30  # the process was actually killed, not left running
    assert bundle.to_evidence_classification("timed_out") == "blocked"


# ---------------------------------------------------------------------------
# 4. executed failure (never relabeled "unavailable")
# ---------------------------------------------------------------------------


def test_executed_failure_is_a_real_nonzero_exit_never_hidden_as_unavailable():
    failing_command = "python3 -m pytest tests/ai/test_this_file_genuinely_does_not_exist.py -q"
    execution = bundle.execute([failing_command])
    assert execution["classifications"][failing_command] == "failed"

    task_packet = validate_packet(_task_packet(selected_tests=[failing_command]))
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
    assert bundle.to_evidence_classification("failed") == "failed"


# ---------------------------------------------------------------------------
# 5. unavailable
# ---------------------------------------------------------------------------


def test_unavailable_is_the_executors_own_missing_executable_catch(monkeypatch):
    # python3/pytest/git are all genuinely installed in this sandbox, so a
    # real "command not found" cannot be produced by starving PATH (the
    # executor's own Windows-shim fallback would resolve to sys.executable
    # instead). Exercising the real except FileNotFoundError branch this way
    # matches the precedent already used for this exact classification in
    # tests/ai/test_execution_bundle.py -- it proves the executor's own
    # error handling, not a fabricated external agent's availability.
    def fake_run(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(bundle.subprocess, "run", fake_run)
    result = bundle.run_allowlisted(["ruff", "check", "."])
    assert result["classification"] == "unavailable"
    assert bundle.to_evidence_classification("unavailable") == "unavailable"


# ---------------------------------------------------------------------------
# 6. not_run
# ---------------------------------------------------------------------------


def test_not_run_is_reachable_only_through_evidence_translation_or_explicit_record():
    # run_allowlisted() itself never literally returns "not_run" -- it is
    # reached via the skipped->not_run translation and as a legitimate
    # resume-packet evidence_classification value in its own right.
    assert "not_run" in EVIDENCE_CLASSES
    assert bundle.to_evidence_classification("skipped") == "not_run"
    resume = build_resume_packet(
        validate_packet(_task_packet()),
        context_snapshot_replay_hash=SNAPSHOT["replay_hash"],
        worktree=".",
        branch="claude/marketos-ai-development-loop-consolidation-v1",
        head_sha="e" * 40,
        base_sha="d" * 40,
        changed_files=[],
        tests_already_run=[{"command": "python3 -m pytest tests/ai -q", "evidence_classification": "not_run"}],
        tests_still_required=["python3 -m pytest tests/ai -q"],
        open_blockers=[],
        pending_decisions=[],
        public_sources_inspected=[],
        claims_not_yet_proven=["full suite result"],
        next_action="run the remaining selected tests",
    )
    assert resume["tests_already_run"][0]["evidence_classification"] == "not_run"


# ---------------------------------------------------------------------------
# 7. fixture / simulated
# ---------------------------------------------------------------------------


def test_fixture_evidence_can_never_be_claimed_as_live():
    packet = validate_packet(_task_packet())
    report = {
        "evidence_classification": "fixture",
        "live_label": "live_validated",
        "pr": "https://example.invalid/pr/1",
        "rollback": "revert",
    }
    document, code = agent_output_eval.evaluate_report(report, packet)
    assert code != 0
    assert any(item["rule"] == "fixture_not_live" for item in document["findings"])


# ---------------------------------------------------------------------------
# 8. malformed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv,expected_reason",
    [
        (["/tmp/evil/git", "diff", "--check"], "executable_must_be_a_bare_command_name"),
        (["python3", "-c", "import os"], "module_not_allowlisted"),
        (["git", "push", "--force"], "denylisted_pattern"),
        (["git", "reset", "--hard"], "denylisted_pattern"),
        (["node", "--version"], "executable_not_allowlisted"),
        (["git", "commit", "-am", "x"], "git_subcommand_not_allowlisted"),
        ([], "argv_must_be_a_nonempty_list_of_strings"),
    ],
)
def test_malformed_covers_every_distinct_real_rejection_reason(argv, expected_reason):
    verdict = bundle.validate_argv(argv)
    assert verdict["classification"] == "malformed"
    assert verdict["reason"] == expected_reason


def test_malformed_classification_is_never_silently_executed(monkeypatch):
    calls = []
    monkeypatch.setattr(bundle.subprocess, "run", lambda *a, **k: calls.append((a, k)))
    result = bundle.run_allowlisted(["/tmp/evil/python3", "-m", "pytest"])
    assert result["classification"] == "malformed"
    assert calls == []


# ---------------------------------------------------------------------------
# 9. secret rejection
# ---------------------------------------------------------------------------


def test_secret_shaped_task_packet_field_is_rejected():
    with pytest.raises(TaskPacketError):
        validate_packet(_task_packet(objective="use ghp_" + "a" * 36 + " to authenticate"))


def test_secret_shaped_report_fails_the_raw_secrets_rule():
    packet = validate_packet(_task_packet())
    report = {
        "claims": ["token: sk-live-" + "b" * 24],
        "pr": "https://example.invalid/pr/1",
        "rollback": "revert",
    }
    document, code = agent_output_eval.evaluate_report(report, packet)
    assert code != 0
    assert any(item["rule"] == "raw_secrets" for item in document["findings"])


def test_secret_shaped_resume_packet_is_rejected():
    with pytest.raises(TaskPacketError):
        build_resume_packet(
            validate_packet(_task_packet()),
            context_snapshot_replay_hash=SNAPSHOT["replay_hash"],
            worktree=".",
            branch="b",
            head_sha="e" * 40,
            base_sha="d" * 40,
            changed_files=[],
            tests_already_run=[],
            tests_still_required=[],
            open_blockers=[],
            pending_decisions=[],
            public_sources_inspected=[],
            claims_not_yet_proven=["AKIA" + "A" * 16],
            next_action="continue",
        )


# ---------------------------------------------------------------------------
# 10. path traversal rejection
# ---------------------------------------------------------------------------


def test_path_traversal_in_allowed_scope_is_rejected_at_the_packet_boundary():
    with pytest.raises(TaskPacketError):
        validate_packet(_task_packet(allowed_scope=["../../etc/passwd"]))


def test_path_traversal_in_changed_files_is_rejected_at_the_resume_boundary():
    with pytest.raises(TaskPacketError):
        build_resume_packet(
            validate_packet(_task_packet()),
            context_snapshot_replay_hash=SNAPSHOT["replay_hash"],
            worktree=".",
            branch="b",
            head_sha="e" * 40,
            base_sha="d" * 40,
            changed_files=["../../etc/passwd"],
            tests_already_run=[],
            tests_still_required=[],
            open_blockers=[],
            pending_decisions=[],
            public_sources_inspected=[],
            claims_not_yet_proven=[],
            next_action="continue",
        )


def test_path_traversal_in_a_worktree_scope_target_is_flagged_unsafe():
    assert worktree_safety.unsafe_target("../outside/repo.py") is True
    assert worktree_safety.unsafe_target("/etc/passwd") is True
    assert worktree_safety.unsafe_target("tests/ai/test_execution_bundle.py") is False


# ---------------------------------------------------------------------------
# 11. changed-file scope violation
# ---------------------------------------------------------------------------


def test_changed_file_outside_allowed_scope_fails_evaluation():
    packet = validate_packet(_task_packet())
    report = {
        "changed_files": ["evaluation/commerce/canonical.py"],
        "pr": "https://example.invalid/pr/1",
        "rollback": "revert",
    }
    document, code = agent_output_eval.evaluate_report(report, packet)
    assert code != 0
    assert any(item["rule"] == "changed_files_match_scope" for item in document["findings"])


def test_changed_file_outside_allowed_scope_also_fails_pr_check():
    packet = validate_packet(_task_packet())
    result = bundle.pr_check(
        packet, pr_reference="https://example.invalid/pr/1", pr_changed_files=["evaluation/commerce/canonical.py"]
    )
    assert result["valid"] is False
    assert "evaluation/commerce/canonical.py" in result["out_of_scope_files"]


# ---------------------------------------------------------------------------
# 12. missing rollback
# ---------------------------------------------------------------------------


def test_missing_rollback_fails_evaluation():
    packet = validate_packet(_task_packet())
    report = {"pr": "https://example.invalid/pr/1", "rollback": ""}
    document, code = agent_output_eval.evaluate_report(report, packet)
    assert code != 0
    assert any(item["rule"] == "rollback_must_exist" for item in document["findings"])


# ---------------------------------------------------------------------------
# 13. stale base
# ---------------------------------------------------------------------------


def test_stale_branch_base_is_a_real_blocker_from_worktree_safety():
    def fake_git_runner(root, *args, timeout_s=None):
        stdout_by_args = {
            ("rev-parse", "--show-toplevel"): str(root),
            ("rev-parse", "--is-inside-work-tree"): "true",
            ("rev-parse", "HEAD"): "e" * 40,
            ("rev-parse", "--abbrev-ref", "HEAD"): "claude/marketos-ai-development-loop-consolidation-v1",
            ("rev-parse", "origin/main"): "f" * 40,
            ("merge-base", "HEAD", "origin/main"): "0" * 40,
            ("status", "--porcelain"): "",
            ("worktree", "list", "--porcelain"): f"worktree {root}\nHEAD e\nbranch refs/heads/x\n",
            ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): "",
        }
        stdout = stdout_by_args.get(tuple(args), "")
        classification = "actual" if tuple(args) in stdout_by_args else "not_run"
        return {"classification": classification, "reason": None, "stdout": stdout, "exit_code": 0}

    document, code = worktree_safety.evaluate_safety(Path("."), git_runner=fake_git_runner)
    assert document["stale_branch_base"] is True
    assert "stale_branch_base" in document["blockers"]
    assert document["safe_to_edit"] is False
    assert document["next_best_action"] == "rebase_or_recreate_from_origin_main"


# ---------------------------------------------------------------------------
# 14. duplicate authority
# ---------------------------------------------------------------------------


def test_reserved_authority_in_allowed_scope_is_rejected_at_the_packet_boundary():
    assert RESERVED_AUTHORITIES  # sanity: the reserved list itself is real
    with pytest.raises(TaskPacketError):
        validate_packet(_task_packet(allowed_scope=["scripts/ai/run_local_quality_gate.py"]))


def test_duplicate_authority_phrase_in_objective_is_rejected():
    with pytest.raises(TaskPacketError):
        validate_packet(_task_packet(objective="build a second quality gate for AI-chat reports"))


def test_duplicate_authority_rewrite_fails_evaluation():
    packet = validate_packet(_task_packet())
    report = {
        "changed_files": [],
        "owned_files": ["scripts/ai/run_local_quality_gate.py"],
        "pr": "https://example.invalid/pr/1",
        "rollback": "revert",
    }
    document, code = agent_output_eval.evaluate_report(report, packet)
    assert code != 0
    assert any(item["rule"] == "duplicate_authority_rejected" for item in document["findings"])


# ---------------------------------------------------------------------------
# 15. missing PR
# ---------------------------------------------------------------------------


def test_missing_pr_fails_evaluation():
    packet = validate_packet(_task_packet())
    report = {"pr": "", "rollback": "revert"}
    document, code = agent_output_eval.evaluate_report(report, packet)
    assert code != 0
    assert any(item["rule"] == "pr_must_exist" for item in document["findings"])


def test_missing_pr_reference_fails_pr_check_without_a_network_call():
    packet = validate_packet(_task_packet())
    result = bundle.pr_check(packet, pr_reference="", pr_changed_files=[])
    assert result["valid"] is False
    assert result["reason"] == "missing_pr_reference"


# ---------------------------------------------------------------------------
# 16. incomplete handoff
# ---------------------------------------------------------------------------


def test_resume_packet_missing_required_fields_is_rejected():
    with pytest.raises(ResumePacketError):
        validate_resume_packet({"schema": "MarketOS.AIResume.v1"})


def test_resume_packet_with_unknown_test_evidence_classification_is_rejected():
    valid = build_resume_packet(
        validate_packet(_task_packet()),
        context_snapshot_replay_hash=SNAPSHOT["replay_hash"],
        worktree=".",
        branch="b",
        head_sha="e" * 40,
        base_sha="d" * 40,
        changed_files=[],
        tests_already_run=[],
        tests_still_required=[],
        open_blockers=[],
        pending_decisions=[],
        public_sources_inspected=[],
        claims_not_yet_proven=[],
        next_action="continue",
    )
    tampered = dict(valid)
    tampered["tests_already_run"] = [{"command": "pytest -q", "evidence_classification": "definitely_passed"}]
    with pytest.raises(ResumePacketError):
        validate_resume_packet(tampered)


def test_resume_packet_ownership_mismatch_is_rejected():
    packet_a = validate_packet(_task_packet(agent_id="agent-a", lane="lane-a"))
    packet_b = validate_packet(_task_packet(agent_id="agent-b", lane="lane-b"))
    resume_a = build_resume_packet(
        packet_a,
        context_snapshot_replay_hash=SNAPSHOT["replay_hash"],
        worktree=".",
        branch="b",
        head_sha="e" * 40,
        base_sha="d" * 40,
        changed_files=[],
        tests_already_run=[],
        tests_still_required=[],
        open_blockers=[],
        pending_decisions=[],
        public_sources_inspected=[],
        claims_not_yet_proven=[],
        next_action="continue",
    )
    with pytest.raises(ResumePacketError):
        validate_resume_packet(resume_a, expected_task_packet=packet_b)


# ---------------------------------------------------------------------------
# bonus: invalid CoderOS classification vocabulary must never leak
# ---------------------------------------------------------------------------


def test_coderos_classification_never_leaks_native_agent_capabilitys_own_vocabulary(monkeypatch):
    def fake_build_capability_record(*, commands=None, observed=None):
        return {
            "schema": native_agent_capability.SCHEMA,
            "agents": [{"command": "coderos", "state": "installed"}],
            "coderos": {"command": "coderos", "state": "installed"},
        }

    monkeypatch.setattr(native_agent_capability, "build_capability_record", fake_build_capability_record)
    document, _ = worktree_safety.evaluate_safety(Path("."))
    # "installed" is a real, valid native_agent_capability.STATES member --
    # the regression this guards is that member leaking into
    # document["coderos"]["classification"], whose own closed vocabulary is
    # {"actual", "unavailable"} (see worktree_safety.evaluate_safety's
    # inline comment on this field).
    assert "installed" in native_agent_capability.STATES
    assert document["coderos"]["classification"] in {"actual", "unavailable"}
    assert document["coderos"]["classification"] != "installed"


# ---------------------------------------------------------------------------
# Agent-eval-style repeated-trials harness (>=3 trials), real commands only.
#
# This is not a fabricated "external agent" -- it repeatedly drives this
# repository's own real allowlisted executor over a deterministic command,
# the same surface every other test in this file exercises, and records
# the same fields an agent-eval report would: pass rate, consistency,
# runtime, and evidence classification.
# ---------------------------------------------------------------------------

TRIAL_COUNT = 3


def _run_trial(argv: list[str]) -> dict:
    started = time.monotonic()
    result = bundle.run_allowlisted(argv)
    runtime_s = time.monotonic() - started
    return {
        "classification": result["classification"],
        "evidence_classification": bundle.to_evidence_classification(result["classification"]),
        "runtime_s": runtime_s,
        "passed": result["classification"] == "passed",
    }


def test_repeated_trials_capture_pass_rate_consistency_runtime_and_evidence_classification():
    argv = ["python3", "-m", "pytest", "tests/ai/test_native_agent_capability.py", "-q"]
    trials = [_run_trial(argv) for _ in range(TRIAL_COUNT)]

    pass_rate = sum(1 for trial in trials if trial["passed"]) / len(trials)
    classifications = {trial["classification"] for trial in trials}
    evidence_classifications = {trial["evidence_classification"] for trial in trials}
    runtimes = [trial["runtime_s"] for trial in trials]

    assert len(trials) == TRIAL_COUNT
    assert pass_rate == 1.0
    assert classifications == {"passed"}  # consistency: no flake across trials
    assert evidence_classifications == {"actual"}
    assert all(runtime > 0 for runtime in runtimes)


def test_repeated_trials_on_a_deterministic_failure_are_also_consistent():
    argv = ["python3", "-m", "pytest", "tests/ai/test_a_file_that_never_exists_anywhere", "-q"]
    trials = [_run_trial(argv) for _ in range(TRIAL_COUNT)]

    pass_rate = sum(1 for trial in trials if trial["passed"]) / len(trials)
    classifications = {trial["classification"] for trial in trials}

    assert pass_rate == 0.0
    assert classifications == {"failed"}  # a real, repeatable failure -- not a flake, not "unavailable"

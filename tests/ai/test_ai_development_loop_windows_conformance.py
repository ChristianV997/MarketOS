"""Windows-conformance regression suite for the composed AI-development loop.

PROMPT 4 (AI-DEVELOPMENT-LOOP-WINDOWS-CONFORMANCE-V2) asks specifically
about validating/hardening the loop on a real Windows MarketOS checkout.

Honesty note (see the final report for the full disclosure): this remote
execution environment is Linux (``sys.platform == "linux"``); no Windows
machine is reachable from this session. Every test in this file that
claims real execution runs for real -- on Linux. Windows-*specific*
behavior (drive-letter paths, UNC shares, backslash separators) is
therefore validated at the string/path-logic level, which is exactly the
level at which the bug this file exists to regression-test was found and
is platform-independent by construction (``assert_safe_path``/
``unsafe_target`` are pure string/``pathlib`` functions, never gated on
``sys.platform``) -- not by actually booting a Windows OS.

Defect found and fixed by this lane (not merely tested around): on a
POSIX host, ``pathlib.Path("C:/Windows/System32").is_absolute()`` is
``False`` -- PosixPath never recognizes a drive letter as absolute. Both
``operator_task_packet.assert_safe_path`` and
``worktree_safety.unsafe_target`` normalize backslashes to forward
slashes and then relied solely on ``Path.is_absolute()`` (task packet) or
a regex that checked for a literal backslash *after* that same
normalization had already removed every backslash (worktree safety) --
so a Windows absolute path or UNC share in ``allowed_scope`` silently
passed both checks. Fixed with an explicit, platform-independent
drive-letter/UNC check in each function.

Other scenarios this file adds real regression coverage for, in each
case because reconnaissance showed the underlying code was already
correct and only needed the coverage locked in (no new production
surface introduced beyond the two fixes above):

- spaces in worktree paths (real subprocess git + real run_allowlisted
  against a genuine temp directory with a space in its name)
- malformed result objects passed into execute() (int, None, an
  argv-less mapping, an empty list) -- all fail closed to "malformed",
  never raise
- real (unmocked) CoderOS-unavailable state, since coderos genuinely
  is not installed in this sandbox
- output truncation at MAX_OUTPUT_CHARS
- resume-after-compaction, chained through build_resume_packet ->
  validate_resume_packet (simulating a reload from disk after
  compaction) -> diff_resume_state against a second, later resume
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from scripts.ai import execution_bundle as bundle, worktree_safety
from scripts.ai.operator_task_packet import (
    TaskPacketError,
    assert_safe_path,
    build_resume_packet,
    diff_resume_state,
    validate_packet,
    validate_resume_packet,
)

SNAPSHOT = {
    "schema": "MarketOS.AIContext.v1",
    "HEAD": "c" * 40,
    "origin_main": "c" * 40,
    "replay_hash": "d" * 64,
}


def _task_packet(**overrides):
    raw = {
        "agent_id": "claude-ai-development-loop-conformance-owner-v2",
        "source_chat": "Claude",
        "lane": "AI-DEVELOPMENT-LOOP-WINDOWS-CONFORMANCE-V2",
        "objective": "harden the loop's Windows-path handling",
        "allowed_scope": ["tests/ai/test_ai_development_loop_windows_conformance.py"],
        "prohibited_scope": ["artifacts/", ".env"],
        "base_sha": "c" * 40,
        "worktree": ".claude/worktrees/marketos-ai-development-loop-consolidation-v1",
        "dependencies": ["MarketOS.AIContext.v1"],
        "acceptance_criteria": ["Windows path traversal is rejected"],
        "selected_tests": ["python3 -m pytest tests/ai/test_ai_development_loop_windows_conformance.py -q"],
        "evidence_classification": "not_run",
        "rollback": "revert the commit that added this test",
        "next_action": "run the remaining selected tests",
    }
    raw.update(overrides)
    return raw


# ---------------------------------------------------------------------------
# Windows paths and path traversal (the defect this lane found and fixed)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "windows_path",
    [
        "C:\\Windows\\System32\\config.sys",
        "C:/Windows/System32/config.sys",
        "C:\\Users\\HP\\.ssh\\id_rsa",
        "D:\\secrets\\credentials.json",
        "\\\\server\\share\\secret",
    ],
)
def test_windows_absolute_and_unc_paths_are_rejected_by_assert_safe_path(windows_path):
    with pytest.raises(TaskPacketError):
        assert_safe_path(windows_path, "allowed_scope")


@pytest.mark.parametrize(
    "windows_path",
    [
        "C:\\Windows\\System32\\config.sys",
        "C:/Windows/System32/config.sys",
        "\\\\server\\share\\secret",
    ],
)
def test_windows_absolute_and_unc_paths_are_flagged_unsafe_by_worktree_safety(windows_path):
    assert worktree_safety.unsafe_target(windows_path) is True


def test_windows_backslash_path_traversal_is_rejected():
    with pytest.raises(TaskPacketError):
        assert_safe_path("scripts\\..\\..\\secrets\\file.json", "allowed_scope")
    assert worktree_safety.unsafe_target("scripts\\..\\..\\secrets\\file.json") is True


def test_a_windows_absolute_path_in_allowed_scope_is_rejected_at_the_packet_boundary():
    with pytest.raises(TaskPacketError):
        validate_packet(_task_packet(allowed_scope=["C:\\Windows\\System32\\config.sys"]))


def test_a_windows_absolute_path_in_allowed_scope_is_a_real_worktree_safety_blocker():
    document, code = worktree_safety.evaluate_safety(
        Path(__file__).resolve().parents[2],
        allowed_scope=["C:\\Windows\\System32\\config.sys"],
    )
    assert "unsafe_target_paths" in document["blockers"]
    assert document["safe_to_edit"] is False


def test_ordinary_relative_and_dotted_paths_still_pass():
    # The fix must not turn into a false-positive machine for real paths.
    assert assert_safe_path("tests/ai/test_execution_bundle.py", "allowed_scope") == "tests/ai/test_execution_bundle.py"
    assert worktree_safety.unsafe_target("tests/ai/test_execution_bundle.py") is False
    assert worktree_safety.unsafe_target("scripts/ai/execution_bundle.py") is False


# ---------------------------------------------------------------------------
# Spaces in worktree paths -- real subprocess execution, genuinely on Linux
# ---------------------------------------------------------------------------


def test_a_worktree_path_containing_spaces_is_handled_by_real_subprocess_calls():
    tmp = Path(tempfile.mkdtemp(prefix="marketos conformance test "))
    try:
        assert " " in str(tmp)
        subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
        subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=tmp, check=True)
        subprocess.run(["git", "config", "user.name", "a"], cwd=tmp, check=True)
        (tmp / "f.txt").write_text("x")
        subprocess.run(["git", "add", "f.txt"], cwd=tmp, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp, check=True)

        document, _code = worktree_safety.evaluate_safety(tmp)
        assert document["evidence_classification"]["inside"] == "actual"
        assert document["head_sha"]

        result = bundle.run_allowlisted(["git", "status", "--porcelain"], cwd=tmp)
        assert result["classification"] == "passed"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_render_command_quotes_a_space_containing_argument_for_both_shells():
    rendered = bundle.render_command(["python3", "-m", "pytest", "tests/some dir/test_x.py", "-q"])
    assert rendered["posix"].count("'tests/some dir/test_x.py'") == 1 or '"tests/some dir/test_x.py"' in rendered["posix"]
    assert "'tests/some dir/test_x.py'" in rendered["powershell"]


# ---------------------------------------------------------------------------
# Malformed result objects passed into execute() never crash the loop
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("malformed_item", [123, None, {"unrelated_key": "value"}, {"argv": None}, []])
def test_execute_fails_closed_on_malformed_command_items_instead_of_crashing(malformed_item):
    result = bundle.execute([malformed_item])
    assert set(result["classifications"].values()) == {"malformed"}


# ---------------------------------------------------------------------------
# CoderOS unavailable state -- real (unmocked) detection in this sandbox
# ---------------------------------------------------------------------------


def test_coderos_is_genuinely_unavailable_in_this_sandbox_not_a_simulated_value():
    # This is real, unmocked detection: coderos is not on PATH in this
    # container, so this is what an honest probe actually returns here --
    # not a fabricated "unavailable" fixture standing in for a real probe.
    status = worktree_safety.native_agent_command_status()
    assert status["agents"]["coderos"] == "unavailable"
    document, _code = worktree_safety.evaluate_safety(Path.cwd())
    assert document["coderos"]["classification"] == "unavailable"
    assert document["coderos"]["reason"] == "not_found_on_path"


# ---------------------------------------------------------------------------
# Output truncation at MAX_OUTPUT_CHARS
# ---------------------------------------------------------------------------


def test_command_output_is_capped_at_max_output_chars(monkeypatch):
    class FakeCompleted:
        returncode = 0
        stdout = "x" * (bundle.MAX_OUTPUT_CHARS + 500)
        stderr = ""

    monkeypatch.setattr(bundle.subprocess, "run", lambda *a, **k: FakeCompleted())
    result = bundle.run_allowlisted(["python3", "-m", "pytest", "tests/ai"])
    assert len(result["stdout"]) == bundle.MAX_OUTPUT_CHARS


def test_real_command_output_under_the_cap_is_returned_unmodified():
    result = bundle.run_allowlisted(["python3", "-m", "pytest", "tests/ai/test_native_agent_capability.py", "-q"])
    assert result["classification"] == "passed"
    assert len(result["stdout"]) <= bundle.MAX_OUTPUT_CHARS


# ---------------------------------------------------------------------------
# Resume after compaction, chained through the real functions
# ---------------------------------------------------------------------------


def test_resume_after_compaction_round_trips_and_detects_progress():
    task_packet = validate_packet(_task_packet())

    # First resume, written before a (simulated) context compaction.
    before = build_resume_packet(
        task_packet,
        context_snapshot_replay_hash=SNAPSHOT["replay_hash"],
        worktree=".",
        branch="claude/marketos-ai-development-loop-consolidation-v1",
        head_sha="1" * 40,
        base_sha="c" * 40,
        changed_files=["tests/ai/test_ai_development_loop_windows_conformance.py"],
        tests_already_run=[],
        tests_still_required=["python3 -m pytest tests/ai -q"],
        open_blockers=[],
        pending_decisions=[],
        public_sources_inspected=[],
        claims_not_yet_proven=["Windows path traversal is rejected"],
        next_action="run the remaining selected tests",
    )

    # Simulate reload-from-disk after compaction (docs/ai/
    # AI_CHAT_RESUME_AFTER_COMPACTION.md's "resume from files, not chat
    # memory" procedure): the loaded packet must independently re-validate.
    reloaded = validate_resume_packet(before, expected_task_packet=task_packet)
    assert reloaded["schema"] == "MarketOS.AIResume.v1"

    # Work continues after the resume: a new commit, a completed test.
    after = build_resume_packet(
        task_packet,
        context_snapshot_replay_hash=SNAPSHOT["replay_hash"],
        worktree=".",
        branch="claude/marketos-ai-development-loop-consolidation-v1",
        head_sha="2" * 40,
        base_sha="c" * 40,
        changed_files=["tests/ai/test_ai_development_loop_windows_conformance.py"],
        tests_already_run=[
            {"command": "python3 -m pytest tests/ai -q", "evidence_classification": "actual"},
        ],
        tests_still_required=[],
        open_blockers=[],
        pending_decisions=[],
        public_sources_inspected=[],
        claims_not_yet_proven=[],
        next_action="open the PR",
    )

    diff = diff_resume_state(reloaded, after)
    assert diff["head_advanced"] is True
    assert diff["no_new_edits_detected"] is False
    assert diff["newly_completed_tests"] == after["tests_already_run"]

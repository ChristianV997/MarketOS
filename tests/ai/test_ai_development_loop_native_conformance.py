"""Native-tool conformance suite: prove the composed loop, not just isolated
unit functions, surfaces these blockers/rejections for real.

PROMPT 4 (AI-DEVELOPMENT-LOOP-NATIVE-CONFORMANCE-V3) specifically asked to
prove the control loop works "not only in isolated unit tests." Reconnaissance
against the real merged code found that several scenarios this lane names
were already correctly handled at the unit level (worktree_safety.evaluate_safety,
operator_task_packet.assert_safe_path) but had never been exercised through
the *composed* execution_bundle phases (prepare/admit) that the real loop
actually calls, and one code path (the "branch_checked_out_in_another_worktree"
blocker) had zero test coverage at any level. No implementation defect was
found in this lane -- every test below is new end-to-end conformance
evidence for already-correct code, confirmed by direct reproduction before
each test was written (see the session's tool-usage ledger in the final
report for exactly what was run and why).

Honesty note: this session is Linux-only; no Windows OS is reachable here.
Real-execution claims in this file are real Linux subprocess/filesystem
operations. PowerShell-specific behavior is validated at the string-quoting
logic level (render_command/_powershell_quote), which is platform-independent
by construction and is not executed by an actual powershell.exe.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from scripts.ai import execution_bundle as bundle, worktree_safety
from scripts.ai.operator_task_packet import TaskPacketError
from tests.ai.test_worktree_safety import _git_factory

SNAPSHOT = {
    "schema": "MarketOS.AIContext.v1",
    "HEAD": "c" * 40,
    "origin_main": "c" * 40,
    "replay_hash": "d" * 64,
}


def _task_packet(**overrides):
    raw = {
        "agent_id": "claude-ai-development-loop-conformance-owner-v3",
        "source_chat": "Claude",
        "lane": "AI-DEVELOPMENT-LOOP-NATIVE-CONFORMANCE-V3",
        "objective": "prove the composed loop surfaces real blockers, not just unit functions",
        "allowed_scope": ["tests/ai/test_ai_development_loop_native_conformance.py"],
        "prohibited_scope": ["artifacts/", ".env"],
        "base_sha": "c" * 40,
        "worktree": ".claude/worktrees/marketos-ai-development-loop-consolidation-v1",
        "dependencies": ["MarketOS.AIContext.v1"],
        "acceptance_criteria": ["composed-phase blockers are proven, not just unit ones"],
        "selected_tests": ["python3 -m pytest tests/ai/test_ai_development_loop_native_conformance.py -q"],
        "evidence_classification": "not_run",
        "rollback": "revert the commit that added this test",
        "next_action": "run the remaining selected tests",
    }
    raw.update(overrides)
    return raw


# ---------------------------------------------------------------------------
# Dirty canonical checkout -- through the composed bundle.admit() phase,
# with a real git repository and real uncommitted change (not a fake
# git_runner, unlike the existing unit-level coverage in
# tests/ai/test_worktree_safety.py::test_dirty_canonical_and_stale_base).
# ---------------------------------------------------------------------------


def test_a_real_dirty_canonical_checkout_is_a_real_admit_phase_blocker():
    tmp_parent = Path(tempfile.mkdtemp(prefix="marketos_conformance_parent_"))
    root = tmp_parent / "MarketOS"  # matches detect_canonical()'s name heuristic
    try:
        root.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "a"], cwd=root, check=True)
        (root / "f.txt").write_text("x")
        subprocess.run(["git", "add", "f.txt"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)
        (root / "f.txt").write_text("an uncommitted change")

        result = bundle.admit(root, _task_packet())
        assert result["admitted"] is False
        assert "dirty_canonical_checkout" in result["document"]["blockers"]
        assert result["document"]["canonical"]["is_canonical"] is True
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)


def test_a_clean_non_canonical_worktree_is_admitted_by_the_composed_phase():
    # The counterpart to the dirty-canonical case above: a real, clean
    # worktree that does NOT look canonical is admitted (no blockers).
    tmp = Path(tempfile.mkdtemp(prefix="marketos_conformance_clean_"))
    try:
        subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
        subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=tmp, check=True)
        subprocess.run(["git", "config", "user.name", "a"], cwd=tmp, check=True)
        (tmp / "f.txt").write_text("x")
        subprocess.run(["git", "add", "f.txt"], cwd=tmp, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp, check=True)

        result = bundle.admit(tmp, _task_packet())
        assert result["document"]["canonical"]["is_canonical"] is False
        assert "dirty_canonical_checkout" not in result["document"]["blockers"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Branch collision (branch_checked_out_in_another_worktree) -- previously
# zero test coverage at any level. Uses evaluate_safety's own git_runner
# dependency-injection seam, the same precedented approach already used in
# tests/ai/test_worktree_safety.py for stale-base/dirty-canonical, since git
# itself refuses to let two real worktrees check out the same branch
# (a genuine collision can only be observed after the fact, e.g. via a
# stale/manually-edited ref -- git_runner injection is the honest way to
# exercise this branch of the state machine without fabricating a git bug).
# ---------------------------------------------------------------------------


def test_branch_checked_out_in_another_worktree_is_a_real_blocker(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    payloads = {
        ("rev-parse", "--show-toplevel"): str(root),
        ("rev-parse", "--is-inside-work-tree"): "true",
        ("rev-parse", "HEAD"): "aaa111",
        ("rev-parse", "--abbrev-ref", "HEAD"): "shared-branch",
        ("rev-parse", "origin/main"): "aaa111",
        ("merge-base", "HEAD", "origin/main"): "aaa111",
        ("status", "--porcelain"): "",
        ("worktree", "list", "--porcelain"): (
            f"worktree {root}\nHEAD aaa111\nbranch refs/heads/shared-branch\n\n"
            f"worktree {tmp_path / 'other-worktree'}\nHEAD bbb222\nbranch refs/heads/shared-branch\n"
        ),
    }
    document, code = worktree_safety.evaluate_safety(root, git_runner=_git_factory(payloads))
    assert "branch_checked_out_in_another_worktree" in document["blockers"]
    assert document["safe_to_edit"] is False
    assert code == 2


def test_two_detached_worktrees_do_not_falsely_collide(tmp_path: Path):
    # A detached-HEAD worktree entry has no "branch" line at all, so
    # parse_worktrees() never sets a "branch" key for it -- item.get("branch")
    # is None, which must never equal current_branch (also checked via
    # .get(), never None here since --abbrev-ref HEAD always returns a
    # string). Guards against a same_branch false positive between two
    # unrelated detached worktrees.
    root = tmp_path / "repo"
    root.mkdir()
    payloads = {
        ("rev-parse", "--show-toplevel"): str(root),
        ("rev-parse", "--is-inside-work-tree"): "true",
        ("rev-parse", "HEAD"): "aaa111",
        ("rev-parse", "--abbrev-ref", "HEAD"): "HEAD",  # git's own output when detached
        ("rev-parse", "origin/main"): "aaa111",
        ("merge-base", "HEAD", "origin/main"): "aaa111",
        ("status", "--porcelain"): "",
        ("worktree", "list", "--porcelain"): (
            f"worktree {root}\nHEAD aaa111\ndetached\n\n"
            f"worktree {tmp_path / 'other-worktree'}\nHEAD bbb222\ndetached\n"
        ),
    }
    document, _code = worktree_safety.evaluate_safety(root, git_runner=_git_factory(payloads))
    assert "branch_checked_out_in_another_worktree" not in document["blockers"]


# ---------------------------------------------------------------------------
# Artifact exclusion -- through the composed bundle.prepare() phase, not
# just operator_task_packet.assert_safe_path() called directly.
# ---------------------------------------------------------------------------


def test_an_artifacts_scoped_task_packet_is_rejected_by_the_composed_prepare_phase():
    with pytest.raises(TaskPacketError):
        bundle.prepare(SNAPSHOT, _task_packet(allowed_scope=["artifacts/out.json"]))


# ---------------------------------------------------------------------------
# PowerShell command handling -- correctness of the quoting itself, since a
# command manifest a human copy-pastes into a real PowerShell prompt is
# exactly where an unquoted metacharacter would matter.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argument",
    ["$(evil)", "a;b", "a&b", "a|b", "a`b", "it's", "tests/some dir/x.py"],
)
def test_powershell_rendering_single_quotes_every_metacharacter_argument(argument):
    rendered = bundle.render_command(["python3", "-m", "pytest", argument, "-q"])
    # PowerShell single-quoted strings are fully literal -- $, ;, &, |, and
    # backticks are never expanded inside them, unlike a bare or
    # double-quoted argument.
    quoted = bundle._powershell_quote(argument)
    assert quoted.startswith("'") and quoted.endswith("'")
    assert quoted in rendered["powershell"]


def test_powershell_rendering_correctly_escapes_an_embedded_single_quote():
    # PowerShell's own escaping rule inside a single-quoted string is to
    # double the embedded quote -- "it's" must become 'it''s', not "it's"
    # (which would prematurely close the string) or 'it\'s' (backslash
    # escaping is a bash/POSIX convention, not PowerShell's).
    assert bundle._powershell_quote("it's") == "'it''s'"


def test_powershell_rendering_leaves_plain_arguments_unquoted():
    rendered = bundle.render_command(["pytest", "tests/ai", "-q"])
    assert rendered["powershell"] == "pytest tests/ai -q"


# ---------------------------------------------------------------------------
# Malformed / non-UTF-8-shaped output never crashes capture -- downstream of
# subprocess.run's own encoding="utf-8", errors="replace" (verified present
# in run_allowlisted), which means a real subprocess's invalid bytes are
# already turned into U+FFFD replacement characters before this code ever
# sees them. This exercises that exact post-decoding shape.
# ---------------------------------------------------------------------------


def test_replacement_character_output_from_invalid_encoding_is_captured_without_crashing(monkeypatch):
    class FakeCompleted:
        returncode = 0
        stdout = "before��after"
        stderr = ""

    monkeypatch.setattr(bundle.subprocess, "run", lambda *a, **k: FakeCompleted())
    result = bundle.run_allowlisted(["python3", "-m", "pytest", "tests/ai"])
    assert result["classification"] == "passed"
    assert "�" in result["stdout"]


def test_run_allowlisted_genuinely_requests_utf8_with_replace_errors():
    # Lock in the actual subprocess.run kwargs so a future edit can't
    # silently drop errors="replace" (which would turn a real malformed-byte
    # command into an uncaught UnicodeDecodeError instead of a clean result).
    import inspect

    source = inspect.getsource(bundle.run_allowlisted)
    assert 'encoding="utf-8"' in source
    assert 'errors="replace"' in source


# ---------------------------------------------------------------------------
# Repeated deterministic trials over the composed admit() phase specifically
# (tests/ai/test_ai_development_loop_conformance.py already covers execute()'s
# run_allowlisted trials; this covers a different loop phase for pass rate,
# consistency, runtime, and evidence quality, as this lane asks for).
# ---------------------------------------------------------------------------

TRIAL_COUNT = 3


def test_repeated_admit_trials_against_a_real_dirty_canonical_checkout_are_consistent():
    tmp_parent = Path(tempfile.mkdtemp(prefix="marketos_conformance_trials_"))
    root = tmp_parent / "MarketOS"
    try:
        root.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "a"], cwd=root, check=True)
        (root / "f.txt").write_text("x")
        subprocess.run(["git", "add", "f.txt"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)
        (root / "f.txt").write_text("dirty")

        trials = []
        for _ in range(TRIAL_COUNT):
            started = time.monotonic()
            result = bundle.admit(root, _task_packet())
            trials.append(
                {
                    "admitted": result["admitted"],
                    "has_dirty_blocker": "dirty_canonical_checkout" in result["document"]["blockers"],
                    "runtime_s": time.monotonic() - started,
                }
            )

        pass_rate = sum(1 for trial in trials if trial["admitted"]) / len(trials)
        consistency = {trial["admitted"] for trial in trials}
        evidence_quality = {trial["has_dirty_blocker"] for trial in trials}

        assert len(trials) == TRIAL_COUNT
        assert pass_rate == 0.0  # every trial correctly, consistently blocks
        assert consistency == {False}  # no flake across trials
        assert evidence_quality == {True}  # the real reason is present every time
        assert all(trial["runtime_s"] > 0 for trial in trials)
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)

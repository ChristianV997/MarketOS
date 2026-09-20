from pathlib import Path

import pytest

from scripts.ai.operator_task_packet import (
    ResumePacketError,
    _in_scope,
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


def test_loaded_resume_packet_with_path_traversal_in_changed_files_is_rejected():
    """A resume packet's changed_files was only ever path-checked at
    build_resume_packet() time; a hand-crafted/tampered packet loaded from
    disk or handed off between sessions must be re-checked, not trusted."""
    resume = build_resume_packet(TASK_PACKET, **_resume_kwargs())
    tampered = dict(resume, changed_files=["../../../etc/passwd"])
    with pytest.raises(ResumePacketError, match="stay relative"):
        validate_resume_packet(tampered)


def test_loaded_resume_packet_with_malformed_head_sha_is_rejected():
    resume = build_resume_packet(TASK_PACKET, **_resume_kwargs())
    tampered = dict(resume, head_sha="; rm -rf ~")
    with pytest.raises(ResumePacketError, match="git SHA"):
        validate_resume_packet(tampered)


def test_loaded_resume_packet_with_wrong_field_types_is_rejected_not_silently_accepted():
    """Adversarial handoff: every RESUME_REQUIRED field except the ones
    already covered by schema/missing-key/evidence-classification checks
    must still fail closed with a typed ResumePacketError when its type is
    wrong -- never silently pass through unvalidated."""
    resume = build_resume_packet(TASK_PACKET, **_resume_kwargs())
    for bad_field, bad_value in (
        ("worktree", 123),
        ("branch", None),
        ("changed_files", "not-a-list"),
        ("open_blockers", {}),
        ("next_action", 42),
        ("tests_still_required", "pytest tests/ai"),
    ):
        tampered = dict(resume, **{bad_field: bad_value})
        with pytest.raises(ResumePacketError):
            validate_resume_packet(tampered)


def test_resumed_changed_files_outside_allowed_scope_is_rejected():
    """The concrete gap: task_packet_digest equality proves the resume
    packet was built from this exact task packet, but says nothing about
    whether the resume packet's own changed_files stayed inside that task
    packet's allowed_scope. A resumed agent handing back edits to a file
    it was never authorized to touch must be rejected here, not silently
    accepted because every other check (schema, ownership, digest,
    per-entry path safety) happened to pass."""
    resume = build_resume_packet(TASK_PACKET, **_resume_kwargs())
    out_of_scope = dict(resume, changed_files=["backend/commerce/checkout.py"])
    with pytest.raises(ResumePacketError, match="allowed_scope"):
        validate_resume_packet(out_of_scope, expected_task_packet=TASK_PACKET)


def test_resumed_changed_files_within_allowed_scope_still_resumes():
    resume = build_resume_packet(TASK_PACKET, **_resume_kwargs())
    assert validate_resume_packet(resume, expected_task_packet=TASK_PACKET) == resume


def test_resumed_changed_directory_cannot_expand_a_narrow_file_scope():
    resume = build_resume_packet(TASK_PACKET, **_resume_kwargs())
    broadened = dict(resume, changed_files=["scripts/ai"])
    with pytest.raises(ResumePacketError, match="allowed_scope"):
        validate_resume_packet(broadened, expected_task_packet=TASK_PACKET)


def test_scope_check_is_skipped_without_an_expected_task_packet():
    """Without expected_task_packet, there is no allowed_scope to compare
    against -- this must not crash, only the identity/digest/scope checks
    that require it are skipped (unchanged from before this fix)."""
    resume = build_resume_packet(TASK_PACKET, **_resume_kwargs(changed_files=["backend/commerce/checkout.py"]))
    assert validate_resume_packet(resume) == resume


@pytest.mark.parametrize(
    ("path", "allowed", "expected"),
    [
        # -- prefix confusion: a sibling directory that merely shares a
        # string prefix must never be treated as inside scope.
        ("tests/ai/foo.py", ["tests/ai"], True),
        ("tests/ai_evil/malicious.py", ["tests/ai"], False),
        ("tests/aiEVIL/x.py", ["tests/ai"], False),
        ("tests/ai", ["tests/ai/foo.py"], False),  # an ancestor is broader than the allowed file
        # -- exact match
        ("tests/ai/foo.py", ["tests/ai/foo.py"], True),
        # -- case sensitivity: must fail closed (deny), never fail open.
        ("TESTS/AI/foo.py", ["tests/ai"], False),
        # -- traversal: never admitted regardless of allowed_scope content
        # (assert_safe_path rejects it earlier in the real flow; _in_scope
        # itself must also never treat it as in-scope on its own).
        ("../../../etc/passwd", ["tests/ai"], False),
        # -- degenerate allowed_scope entries never act as a wildcard.
        ("anything/at/all.py", [""], False),
        ("anything/at/all.py", ["."], False),
        # -- unrelated top-level directories.
        ("backend/commerce/checkout.py", ["tests/ai"], False),
    ],
)
def test_in_scope_property_table(path, allowed, expected):
    assert _in_scope(path, allowed) is expected


def test_genuine_resume_packet_survives_full_field_revalidation():
    """The new field-level revalidation must not reject a packet that
    build_resume_packet() itself produced -- only tampered/malformed ones."""
    resume = build_resume_packet(TASK_PACKET, **_resume_kwargs())
    assert validate_resume_packet(resume) == resume
    assert validate_resume_packet(resume, expected_task_packet=TASK_PACKET) == resume


def test_verify_replay_hash_detects_a_tampered_resume_bundle():
    resume = build_resume_packet(TASK_PACKET, **_resume_kwargs())
    genuine_replay_hash = resume["context_snapshot_replay_hash"]
    assert verify_replay_hash(resume, recomputed_replay_hash=genuine_replay_hash) is True

    tampered = dict(resume, context_snapshot_replay_hash="f" * 64)
    assert verify_replay_hash(tampered, recomputed_replay_hash=genuine_replay_hash) is False


# ---------------------------------------------------------------------------
# Filesystem-aware scope containment (validate_resume_packet(root=...)).
#
# _in_scope is pure string prefix matching by design (see its own
# docstring); it cannot see that a lexically in-scope path is actually a
# symlink -- or has a symlinked ancestor directory -- resolving somewhere
# else. These tests build a synthetic worktree under tmp_path (never the
# real shared checkout) and exercise _assert_filesystem_contained through
# validate_resume_packet(root=...) with real filesystem entries, including
# real symlinks.
# ---------------------------------------------------------------------------


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this platform/filesystem")


def _fs_task_packet(tmp_path: Path, *, allowed_scope: str = "scope") -> dict:
    return dict(
        TASK_PACKET,
        allowed_scope=[allowed_scope],
        worktree=str(tmp_path),
    )


def _fs_resume(task_packet: dict, changed_files: list[str]) -> dict:
    return build_resume_packet(task_packet, **_resume_kwargs(changed_files=changed_files))


def test_filesystem_check_allows_an_ordinary_in_scope_file(tmp_path: Path):
    (tmp_path / "scope").mkdir()
    (tmp_path / "scope" / "a.py").write_text("x = 1\n", encoding="utf-8")
    task_packet = _fs_task_packet(tmp_path)
    resume = _fs_resume(task_packet, ["scope/a.py"])
    assert validate_resume_packet(resume, expected_task_packet=task_packet, root=tmp_path) == resume


def test_filesystem_check_preserves_a_deleted_file_with_an_existing_in_scope_parent(tmp_path: Path):
    (tmp_path / "scope").mkdir()
    task_packet = _fs_task_packet(tmp_path)
    resume = _fs_resume(task_packet, ["scope/deleted.py"])
    # scope/deleted.py itself does not exist -- a legitimate deletion -- but
    # its parent "scope" exists and is in allowed_scope, so it is preserved.
    assert validate_resume_packet(resume, expected_task_packet=task_packet, root=tmp_path) == resume


def test_filesystem_check_rejects_deleted_file_whose_nearest_ancestor_is_out_of_scope(tmp_path: Path):
    task_packet = _fs_task_packet(tmp_path, allowed_scope="scope/sub")
    resume = _fs_resume(task_packet, ["scope/sub/deleted.py"])
    # Neither "scope/sub" nor "scope" exists -- the walk-up lands on the
    # worktree root itself, which is never in allowed_scope, so this fails
    # closed rather than treating "no real ancestor found yet" as in-scope.
    with pytest.raises(ResumePacketError, match="resolves outside allowed_scope"):
        validate_resume_packet(resume, expected_task_packet=task_packet, root=tmp_path)


def test_filesystem_check_rejects_a_changed_file_that_is_itself_a_symlink_to_outside_the_root(tmp_path: Path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside-elsewhere.txt"
    outside.write_text("outside content\n", encoding="utf-8")
    (tmp_path / "scope").mkdir()
    link = tmp_path / "scope" / "a.py"
    _symlink_or_skip(link, outside)
    task_packet = _fs_task_packet(tmp_path)
    resume = _fs_resume(task_packet, ["scope/a.py"])
    with pytest.raises(ResumePacketError, match="escapes the worktree root"):
        validate_resume_packet(resume, expected_task_packet=task_packet, root=tmp_path)


def test_filesystem_check_rejects_an_ancestor_directory_symlinked_outside_the_root(tmp_path: Path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside-dir"
    outside.mkdir()
    (outside / "a.py").write_text("x = 1\n", encoding="utf-8")
    task_packet = _fs_task_packet(tmp_path)
    link = tmp_path / "scope"
    _symlink_or_skip(link, outside)
    resume = _fs_resume(task_packet, ["scope/a.py"])
    with pytest.raises(ResumePacketError, match="escapes the worktree root"):
        validate_resume_packet(resume, expected_task_packet=task_packet, root=tmp_path)


def test_filesystem_check_rejects_an_in_root_symlink_that_crosses_allowed_scope(tmp_path: Path):
    """The symlink itself never leaves the worktree root, so a containment
    check against the root alone would miss this -- it must also cross
    back through _in_scope after resolution."""
    (tmp_path / "scope").mkdir()
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "elsewhere.py").write_text("marker = 1\n", encoding="utf-8")
    link = tmp_path / "scope" / "a.py"
    _symlink_or_skip(link, tmp_path / "other" / "elsewhere.py")
    task_packet = _fs_task_packet(tmp_path)
    resume = _fs_resume(task_packet, ["scope/a.py"])
    with pytest.raises(ResumePacketError, match="resolves outside allowed_scope"):
        validate_resume_packet(resume, expected_task_packet=task_packet, root=tmp_path)


def test_filesystem_check_rejects_prefix_confusion_via_symlink(tmp_path: Path):
    """allowed_scope=["scope"] must never be fooled by a same-prefixed
    sibling directory name like "scope_evil" -- proven structurally via
    Path.relative_to, not string startswith."""
    (tmp_path / "scope").mkdir()
    (tmp_path / "scope_evil").mkdir()
    (tmp_path / "scope_evil" / "a.py").write_text("x = 1\n", encoding="utf-8")
    link = tmp_path / "scope" / "a.py"
    _symlink_or_skip(link, tmp_path / "scope_evil" / "a.py")
    task_packet = _fs_task_packet(tmp_path)
    resume = _fs_resume(task_packet, ["scope/a.py"])
    with pytest.raises(ResumePacketError, match="resolves outside allowed_scope"):
        validate_resume_packet(resume, expected_task_packet=task_packet, root=tmp_path)


def test_filesystem_check_still_rejects_lexical_traversal_before_reaching_the_filesystem(tmp_path: Path):
    """A ".."-bearing changed_files entry is caught by assert_safe_path
    inside _revalidate_resume_fields, before _assert_filesystem_contained
    ever runs -- confirm supplying `root` does not bypass or duplicate
    that earlier rejection."""
    (tmp_path / "scope").mkdir()
    task_packet = _fs_task_packet(tmp_path)
    resume = dict(_fs_resume(task_packet, ["scope/a.py"]), changed_files=["scope/../../../etc/passwd"])
    with pytest.raises(ResumePacketError, match="relative"):
        validate_resume_packet(resume, expected_task_packet=task_packet, root=tmp_path)


def test_filesystem_check_requires_root_to_be_a_real_directory(tmp_path: Path):
    (tmp_path / "scope").mkdir()
    task_packet = _fs_task_packet(tmp_path)
    resume = _fs_resume(task_packet, ["scope/a.py"])
    with pytest.raises(ResumePacketError, match="does not exist"):
        validate_resume_packet(resume, expected_task_packet=task_packet, root=tmp_path / "does-not-exist")


def test_filesystem_check_is_skipped_entirely_when_root_is_omitted(tmp_path: Path):
    """Backward compatibility: a caller with no real filesystem context
    (root=None, the default) gets exactly the prior lexical-only
    behavior, even for a path that would fail the filesystem check --
    the new check is additive, never mandatory."""
    (tmp_path / "scope").mkdir()
    outside = tmp_path.parent / f"{tmp_path.name}-outside2.txt"
    outside.write_text("x\n", encoding="utf-8")
    link = tmp_path / "scope" / "a.py"
    _symlink_or_skip(link, outside)
    task_packet = _fs_task_packet(tmp_path)
    resume = _fs_resume(task_packet, ["scope/a.py"])
    # No root supplied: lexical check only, this passes (a real filesystem
    # check would have rejected it -- see the symlink test above).
    assert validate_resume_packet(resume, expected_task_packet=task_packet) == resume


def test_filesystem_check_windows_drive_letter_changed_file_still_rejected_pre_filesystem(tmp_path: Path):
    """Windows drive-letter/UNC paths are rejected by assert_safe_path's
    existing WINDOWS_DRIVE_ABSOLUTE check regardless of host OS (see that
    function's own comment on why PosixPath alone would miss this on a
    non-Windows validator host); confirm supplying `root` does not change
    that earlier, OS-independent outcome. True Windows case-insensitive
    filesystem semantics cannot be exercised on this POSIX sandbox -- this
    codebase's path checks are case-sensitive by construction, matching a
    POSIX filesystem's real behavior, and that is a documented limitation
    for a real Windows worktree, not something this check can fake here."""
    (tmp_path / "scope").mkdir()
    task_packet = _fs_task_packet(tmp_path)
    resume = dict(_fs_resume(task_packet, ["scope/a.py"]), changed_files=["C:/scope/a.py"])
    with pytest.raises(ResumePacketError, match="relative"):
        validate_resume_packet(resume, expected_task_packet=task_packet, root=tmp_path)


def test_filesystem_check_normalizes_backslash_separators_like_every_other_scope_check(tmp_path: Path):
    """Regression: _assert_filesystem_contained must normalize backslashes
    exactly like _in_scope and assert_safe_path already do -- joining a
    raw backslash-separated entry onto `root` without normalizing first
    would produce one bogus filename component instead of nested
    directories, falsely rejecting a legitimate, already-validated,
    genuinely in-scope file the moment a real filesystem root is
    supplied."""
    (tmp_path / "scope").mkdir()
    (tmp_path / "scope" / "a.py").write_text("x = 1\n", encoding="utf-8")
    task_packet = _fs_task_packet(tmp_path)
    resume = dict(_fs_resume(task_packet, ["scope/a.py"]), changed_files=["scope\\a.py"])
    assert validate_resume_packet(resume, expected_task_packet=task_packet, root=tmp_path) == resume

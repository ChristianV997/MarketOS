from __future__ import annotations

from pathlib import Path

from scripts.ai.worktree_safety import (
    SCHEMA,
    detect_canonical,
    evaluate_safety,
    parse_worktrees,
    sensitive_untracked,
    unsafe_target,
)


def test_schema_constant():
    assert SCHEMA == "MarketOS.WorktreeSafety.v1"


def test_parse_worktrees_and_branch_conflict():
    porcelain = """worktree /tmp/MarketOS
HEAD abc
branch refs/heads/main

worktree /tmp/MarketOS.worktrees/lane
HEAD def
branch refs/heads/grok/marketos-ai-chat-tooling-retrofit-v1
"""
    entries = parse_worktrees(porcelain)
    assert entries[0]["branch"] == "main"
    assert entries[1]["path"].endswith("lane")


def test_sensitive_file_exclusion():
    status = "?? .env\n?? scripts/ai/foo.py\n?? credentials/token.txt\n"
    found = sensitive_untracked(status)
    assert ".env" in found
    assert "credentials/token.txt" in found
    assert "scripts/ai/foo.py" not in found


def test_unsafe_target_paths():
    assert unsafe_target("../etc/passwd") is True
    assert unsafe_target("artifacts/out.json") is True
    assert unsafe_target("scripts/ai/operator_task_packet.py") is False


def test_canonical_detection(tmp_path: Path):
    market = tmp_path / "MarketOS"
    market.mkdir()
    info = detect_canonical(market, str(market))
    assert info["is_canonical"] is True
    work = tmp_path / "MarketOS.worktrees" / "lane"
    work.mkdir(parents=True)
    other = detect_canonical(work, str(market))
    assert other["matches_declared"] is False


def _git_factory(payloads):
    def runner(root, *args, timeout_s=15.0):
        stdout = payloads.get(args, "")
        return {"classification": "actual", "reason": None, "stdout": stdout, "exit_code": 0}

    return runner


def test_dirty_canonical_and_stale_base(tmp_path: Path):
    root = tmp_path / "MarketOS"
    root.mkdir()
    payloads = {
        ("rev-parse", "--show-toplevel"): str(root),
        ("rev-parse", "--is-inside-work-tree"): "true",
        ("rev-parse", "HEAD"): "aaa111",
        ("rev-parse", "--abbrev-ref", "HEAD"): "grok/demo",
        ("rev-parse", "origin/main"): "bbb222",
        ("merge-base", "HEAD", "origin/main"): "ccc333",
        ("status", "--porcelain"): " M scripts/ai/x.py\n?? .env",
        ("worktree", "list", "--porcelain"): f"worktree {root}\nHEAD aaa111\nbranch refs/heads/grok/demo\n",
    }
    document, code = evaluate_safety(
        root,
        declared_canonical=str(root),
        expected_branch="other",
        allowed_scope=["artifacts/secret.json"],
        git_runner=_git_factory(payloads),
    )
    assert code == 2
    assert "dirty_canonical_checkout" in document["blockers"]
    assert "stale_branch_base" in document["blockers"]
    assert "untracked_sensitive_files" in document["blockers"]
    assert "unsafe_target_paths" in document["blockers"]
    assert "branch_conflict" in document["blockers"]
    assert document["safe_to_edit"] is False
    # A "branch_conflict" blocker is useless as evidence in a resume/handoff
    # packet unless the document also records what was actually expected --
    # found by an independent state-machine review, not by the primary diff.
    assert document["expected_branch"] == "other"
    assert document["branch"] == "grok/demo"


def test_expected_branch_is_recorded_even_when_it_matches(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    payloads = {
        ("rev-parse", "--show-toplevel"): str(root),
        ("rev-parse", "--is-inside-work-tree"): "true",
        ("rev-parse", "HEAD"): "aaa111",
        ("rev-parse", "--abbrev-ref", "HEAD"): "main",
        ("rev-parse", "origin/main"): "aaa111",
        ("merge-base", "HEAD", "origin/main"): "aaa111",
        ("status", "--porcelain"): "",
        ("worktree", "list", "--porcelain"): f"worktree {root}\nHEAD aaa111\nbranch refs/heads/main\n",
    }
    document, _code = evaluate_safety(root, expected_branch="main", git_runner=_git_factory(payloads))
    assert "branch_conflict" not in document["blockers"]
    assert document["expected_branch"] == "main"


def test_expected_branch_is_none_when_not_supplied(tmp_path: Path):
    document, _code = evaluate_safety(tmp_path, git_runner=_git_factory({}))
    assert document["expected_branch"] is None


def test_unavailable_git(monkeypatch, tmp_path: Path):
    def boom(root, *args, timeout_s=15.0):
        return {"classification": "unavailable", "reason": "git_missing", "stdout": "", "exit_code": None}

    document, code = evaluate_safety(tmp_path, git_runner=boom)
    assert code == 2
    assert document["coderos"]["classification"] == "unavailable"
    assert document["evidence_classification"]["head"] == "unavailable"


def test_git_argv_block():
    from scripts.ai import worktree_safety as module

    result = module._run_git(Path("."), "push", "origin", "main")
    assert result["classification"] == "blocked"


def test_prunable_worktrees_detects_missing_directory(tmp_path: Path):
    from scripts.ai.worktree_safety import prunable_worktrees

    current = tmp_path / "current"
    current.mkdir()
    ghost = tmp_path / "ghost-worktree"  # never created on disk
    worktrees = [{"path": str(current)}, {"path": str(ghost)}]
    assert prunable_worktrees(worktrees, current_root=current) == [str(ghost)]


def test_outside_allowed_roots_flags_stray_worktree_path():
    from scripts.ai.worktree_safety import outside_allowed_roots

    assert outside_allowed_roots(Path("/tmp/random/worktrees/lane")) is True
    assert outside_allowed_roots(Path("/home/user/MarketOS/.claude/worktrees/lane")) is False
    assert outside_allowed_roots(Path("/home/user/MarketOS")) is False  # plain canonical checkout


def test_overlapping_pr_paths_reports_the_colliding_pr():
    from scripts.ai.worktree_safety import overlapping_pr_paths

    overlaps = overlapping_pr_paths(["scripts/ai/x.py", "docs/y.md"], {"#999": ["scripts/ai/x.py"]})
    assert overlaps == {"#999": ["scripts/ai/x.py"]}
    assert overlapping_pr_paths(["scripts/ai/x.py"], {"#999": ["docs/y.md"]}) == {}


def test_protected_paths_hit_reuses_reserved_authorities():
    from scripts.ai.worktree_safety import protected_paths_hit

    hits = protected_paths_hit(["scripts/ai/operator_context_snapshot.py"])
    assert "operator_context_snapshot.py" in hits
    assert protected_paths_hit(["scripts/ai/native_agent_capability.py"]) == []


def _git_factory_with_codes(payloads, codes):
    def runner(root, *args, timeout_s=15.0):
        stdout = payloads.get(args, "")
        code = codes.get(args, 0)
        classification = "actual" if code in (0, 1) and args and args[0] == "merge-base" and "--is-ancestor" in args else ("actual" if code == 0 else "unavailable")
        return {"classification": classification, "reason": None if code == 0 else "git_nonzero", "stdout": stdout, "exit_code": code}

    return runner


def test_force_push_risk_when_upstream_diverged():
    from scripts.ai.worktree_safety import force_push_risk

    payloads = {}
    codes = {
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): 0,
        ("merge-base", "--is-ancestor", "@{u}", "HEAD"): 1,
    }
    payloads[("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")] = "origin/lane"
    result = force_push_risk(Path("."), git_runner=_git_factory_with_codes(payloads, codes))
    assert result["force_push_required"] is True


def test_force_push_risk_when_fast_forwardable():
    from scripts.ai.worktree_safety import force_push_risk

    payloads = {("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): "origin/lane"}
    codes = {
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): 0,
        ("merge-base", "--is-ancestor", "@{u}", "HEAD"): 0,
    }
    result = force_push_risk(Path("."), git_runner=_git_factory_with_codes(payloads, codes))
    assert result["force_push_required"] is False


def test_force_push_risk_not_run_without_upstream():
    from scripts.ai.worktree_safety import force_push_risk

    codes = {("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): 128}
    result = force_push_risk(Path("."), git_runner=_git_factory_with_codes({}, codes))
    assert result["classification"] == "not_run"


def test_coderos_classification_stays_in_the_original_vocabulary_when_installed(monkeypatch, tmp_path: Path):
    """document['coderos']['classification'] must stay in
    {actual, unavailable, blocked, malformed} even when the coderos command
    is actually present -- native_agent_capability's own state vocabulary
    ('installed') must never leak into this field."""
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/coderos" if cmd == "coderos" else None)
    root = tmp_path / "MarketOS"
    root.mkdir()
    payloads = {
        ("rev-parse", "--show-toplevel"): str(root),
        ("rev-parse", "--is-inside-work-tree"): "true",
        ("rev-parse", "HEAD"): "aaa111",
        ("rev-parse", "--abbrev-ref", "HEAD"): "grok/demo",
        ("rev-parse", "origin/main"): "aaa111",
        ("merge-base", "HEAD", "origin/main"): "aaa111",
        ("status", "--porcelain"): "",
        ("worktree", "list", "--porcelain"): f"worktree {root}\nHEAD aaa111\nbranch refs/heads/grok/demo\n",
    }
    document, _ = evaluate_safety(root, git_runner=_git_factory(payloads))
    assert document["coderos"]["classification"] in {"actual", "unavailable", "blocked", "malformed"}
    assert document["coderos"]["classification"] == "actual"
    assert document["native_agent_commands"]["coderos"] == "installed"


def test_evaluate_safety_surfaces_new_blockers(tmp_path: Path):
    root = tmp_path / "MarketOS"
    root.mkdir()
    payloads = {
        ("rev-parse", "--show-toplevel"): str(root),
        ("rev-parse", "--is-inside-work-tree"): "true",
        ("rev-parse", "HEAD"): "aaa111",
        ("rev-parse", "--abbrev-ref", "HEAD"): "grok/demo",
        ("rev-parse", "origin/main"): "aaa111",
        ("merge-base", "HEAD", "origin/main"): "aaa111",
        ("status", "--porcelain"): "",
        ("worktree", "list", "--porcelain"): f"worktree {root}\nHEAD aaa111\nbranch refs/heads/grok/demo\n",
    }
    document, code = evaluate_safety(
        root,
        allowed_scope=["scripts/ai/operator_context_snapshot.py"],
        other_pr_paths={"#999": ["scripts/ai/operator_context_snapshot.py"]},
        git_runner=_git_factory(payloads),
    )
    assert "protected_path_in_scope" in document["blockers"]
    assert "overlapping_pr_paths" in document["blockers"]
    assert document["overlapping_pr_paths"] == {"#999": ["scripts/ai/operator_context_snapshot.py"]}
    assert document["protected_paths_in_scope"] == ["operator_context_snapshot.py"]
    assert code == 2

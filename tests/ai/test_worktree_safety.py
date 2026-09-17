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

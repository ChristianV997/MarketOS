"""Hermetic Git evidence-integrity regressions for promotion rehearsal."""
from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path

import pytest

from backend.deployment.promotion_rehearsal import _rollback_evidence, get_repository_identity


def _git_env(**overrides: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"})
    env.update(overrides)
    return env


def _git(
    repo: Path,
    *args: str,
    input_text: str | None = None,
    extra_env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = _git_env(**(extra_env or {}))
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        input=input_text,
        timeout=15,
        check=False,
        env=env,
    )
    if check and result.returncode:
        pytest.fail(f"git {args!r} failed ({result.returncode}): {result.stderr}")
    return result


def _make_repo(root: Path, name: str = "repo", *, commits: int = 2) -> Path:
    repo = root / name
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Promotion Rehearsal Test")
    _git(repo, "config", "user.email", "promotion-test@example.invalid")
    _git(repo, "config", "commit.gpgsign", "false")
    for index in range(commits):
        (repo / "tracked.txt").write_text(f"commit-{index}\n", encoding="utf-8")
        _git(repo, "add", "tracked.txt")
        _git(repo, "commit", "-q", "-m", f"commit-{index}")
    return repo


def _raw_parent(repo: Path, commit: str) -> str | None:
    raw = _git(repo, "cat-file", "commit", commit, extra_env={"GIT_NO_REPLACE_OBJECTS": "1"}).stdout
    return next((line.removeprefix("parent ") for line in raw.splitlines() if line.startswith("parent ")), None)


def _index_digest(repo: Path) -> str:
    return hashlib.sha256((repo / ".git" / "index").read_bytes()).hexdigest()


def test_rollback_evidence_uses_raw_parent_when_replace_ref_rewrites_ancestry(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    raw_parent = _raw_parent(repo, head)
    assert raw_parent is not None
    tree = _git(repo, "rev-parse", "HEAD^{tree}").stdout.strip()
    replacement_parent = _git(repo, "commit-tree", tree, "-m", "replacement-parent").stdout.strip()
    replacement_head = _git(repo, "commit-tree", tree, "-p", replacement_parent, "-m", "replacement-head").stdout.strip()
    _git(repo, "replace", head, replacement_head)

    evidence = _rollback_evidence(get_repository_identity(repo))

    assert evidence["status"] == "passed"
    assert evidence["current_revision"] == head
    assert evidence["previous_revision"] == raw_parent
    assert evidence["mutation_performed"] is False


def test_rollback_evidence_uses_raw_parent_when_graft_rewrites_ancestry(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    raw_parent = _raw_parent(repo, head)
    assert raw_parent is not None
    tree = _git(repo, "rev-parse", "HEAD^{tree}").stdout.strip()
    graft_parent = _git(repo, "commit-tree", tree, "-m", "graft-parent").stdout.strip()
    (repo / ".git" / "info" / "grafts").write_text(f"{head} {graft_parent}\n", encoding="ascii")

    evidence = _rollback_evidence(get_repository_identity(repo))

    assert evidence["status"] == "passed"
    assert evidence["current_revision"] == head
    assert evidence["previous_revision"] == raw_parent
    assert evidence["mutation_performed"] is False


def test_rollback_evidence_does_not_use_a_missing_parent_object_as_proof(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, commits=1)
    tree = _git(repo, "rev-parse", "HEAD^{tree}").stdout.strip()
    missing_parent = "deadbeef" * 5
    raw_commit = (
        f"tree {tree}\nparent {missing_parent}\n"
        "author Probe <promotion-test@example.invalid> 1700000000 +0000\n"
        "committer Probe <promotion-test@example.invalid> 1700000000 +0000\n\n"
        "missing parent object\n"
    )
    head = _git(repo, "hash-object", "--literally", "-w", "-t", "commit", "--stdin", input_text=raw_commit).stdout.strip()
    (repo / ".git" / "HEAD").write_text(f"{head}\n", encoding="ascii")
    missing_object = _git(repo, "cat-file", "-e", f"{missing_parent}^{{commit}}", check=False)
    assert missing_object.returncode != 0

    evidence = _rollback_evidence({"commit_sha": head, "worktree_path": str(repo)})

    assert evidence["status"] == "unavailable"
    assert evidence["previous_revision"] is None
    assert evidence["mutation_performed"] is False


@pytest.mark.parametrize("claim_kind", ["unknown", "non_head"])
def test_rollback_evidence_rejects_unverified_or_non_head_current_revision(claim_kind: str, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    parent = _git(repo, "rev-parse", "HEAD^").stdout.strip()
    claimed_revision = "unknown" if claim_kind == "unknown" else parent

    evidence = _rollback_evidence({"commit_sha": claimed_revision, "worktree_path": str(repo)})

    assert claimed_revision != head
    assert evidence["status"] == "unavailable"
    assert evidence["mutation_performed"] is False


def test_repository_identity_and_rollback_ignore_inherited_git_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = _make_repo(tmp_path, "target")
    decoy = _make_repo(tmp_path, "decoy", commits=3)
    target_head = _git(target, "rev-parse", "HEAD").stdout.strip()
    target_parent = _git(target, "rev-parse", "HEAD^").stdout.strip()
    decoy_head = _git(decoy, "rev-parse", "HEAD").stdout.strip()
    assert target_head != decoy_head

    for key in tuple(os.environ):
        if key.upper().startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))

    identity = get_repository_identity(target)
    evidence = _rollback_evidence({"commit_sha": target_head, "worktree_path": str(target)})

    assert identity["commit_sha"] == target_head
    assert evidence["status"] == "passed"
    assert evidence["current_revision"] == target_head
    assert evidence["previous_revision"] == target_parent


def test_repository_identity_status_does_not_refresh_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _make_repo(tmp_path, commits=1)
    tracked = repo / "tracked.txt"
    stat_result = tracked.stat()
    os.utime(tracked, ns=(stat_result.st_atime_ns, time.time_ns() + 5_000_000_000))
    monkeypatch.setenv("GIT_OPTIONAL_LOCKS", "1")
    before = _index_digest(repo)

    identity = get_repository_identity(repo)

    after = _index_digest(repo)
    assert identity["clean"] is True
    assert before == after


def test_repository_identity_does_not_claim_clean_when_git_status_is_unavailable(tmp_path: Path) -> None:
    non_repository = tmp_path / "not-a-git-repository"
    non_repository.mkdir()

    identity = get_repository_identity(non_repository)

    assert identity["worktree_status_available"] is False
    assert identity["clean"] is False

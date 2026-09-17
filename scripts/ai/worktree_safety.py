"""Read-only worktree and canonical-checkout safety probe.

Adapted conceptually from git worktree isolation used by coding-agent
harnesses. Does not create or remove worktrees. Does not replace
session_start ownership checks.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "MarketOS.WorktreeSafety.v1"
DEFAULT_TIMEOUT_S = 15.0
MAX_OUTPUT_BYTES = 50_000
SENSITIVE_NAME = re.compile(
    r"(?i)(\.env($|\.)|credentials|id_rsa|id_ed25519|\.pem$|\.p12$|secrets?/)"
)
UNSAFE_TARGET = re.compile(r"(^/)|(^[A-Za-z]:\\)|(\.\.)|(artifacts/)|(\.git/)")
ALLOWED_GIT = {
    ("rev-parse", "--show-toplevel"),
    ("rev-parse", "--is-inside-work-tree"),
    ("rev-parse", "HEAD"),
    ("rev-parse", "origin/main"),
    ("rev-parse", "--abbrev-ref", "HEAD"),
    ("status", "--porcelain"),
    ("worktree", "list", "--porcelain"),
    ("merge-base", "HEAD", "origin/main"),
}


def _run_git(root: Path, *args: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    key = tuple(args)
    if key not in ALLOWED_GIT and not (args and args[0] == "rev-parse"):
        return {"classification": "blocked", "reason": "git_argv_not_allowlisted", "stdout": "", "exit_code": None}
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
            shell=False,
        )
    except FileNotFoundError:
        return {"classification": "unavailable", "reason": "git_missing", "stdout": "", "exit_code": None}
    except subprocess.TimeoutExpired:
        return {"classification": "unavailable", "reason": "git_timed_out", "stdout": "", "exit_code": None}
    stdout = completed.stdout or ""
    if len(stdout.encode("utf-8", errors="replace")) > MAX_OUTPUT_BYTES:
        return {"classification": "malformed", "reason": "output_exceeds_cap", "stdout": "", "exit_code": completed.returncode}
    classification = "actual" if completed.returncode == 0 else "unavailable"
    return {
        "classification": classification,
        "reason": None if completed.returncode == 0 else "git_nonzero",
        "stdout": stdout.strip(),
        "exit_code": completed.returncode,
    }


def parse_worktrees(porcelain: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in porcelain.splitlines():
        if not line.strip():
            if current:
                entries.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            if current:
                entries.append(current)
            current = {"path": line.split(" ", 1)[1]}
        elif line.startswith("HEAD "):
            current["head"] = line.split(" ", 1)[1]
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1].removeprefix("refs/heads/")
        elif line == "bare":
            current["bare"] = "true"
        elif line == "detached":
            current["detached"] = "true"
    if current:
        entries.append(current)
    return entries


def detect_canonical(path: Path, declared_canonical: str | None) -> dict[str, Any]:
    resolved = path.resolve()
    name = resolved.name.lower()
    looks_canonical = name in {"marketos", "github"} or resolved.as_posix().endswith("/Documents/MarketOS")
    env_canonical = os.environ.get("MARKETOS_CANONICAL_CHECKOUT")
    declared = Path(declared_canonical).resolve() if declared_canonical else None
    is_declared = declared is not None and resolved == declared
    is_env = bool(env_canonical) and Path(env_canonical).resolve() == resolved
    return {
        "path": str(resolved),
        "looks_like_canonical_name": looks_canonical,
        "matches_declared": is_declared,
        "matches_env": is_env,
        "is_canonical": is_declared or is_env or (looks_canonical and ".worktrees" not in resolved.as_posix()),
    }


def sensitive_untracked(status_porcelain: str) -> list[str]:
    found: list[str] = []
    for line in status_porcelain.splitlines():
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:].split(" -> ")[-1].replace("\\", "/")
        if code == "??" and SENSITIVE_NAME.search(path):
            found.append(path)
    return found[:40]


def unsafe_target(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return bool(UNSAFE_TARGET.search(normalized))


def evaluate_safety(
    root: Path,
    *,
    declared_canonical: str | None = None,
    expected_branch: str | None = None,
    allowed_scope: list[str] | None = None,
    git_runner=_run_git,
) -> tuple[dict[str, Any], int]:
    toplevel = git_runner(root, "rev-parse", "--show-toplevel")
    inside = git_runner(root, "rev-parse", "--is-inside-work-tree")
    head = git_runner(root, "rev-parse", "HEAD")
    branch = git_runner(root, "rev-parse", "--abbrev-ref", "HEAD")
    origin_main = git_runner(root, "rev-parse", "origin/main")
    merge_base = git_runner(root, "merge-base", "HEAD", "origin/main")
    status = git_runner(root, "status", "--porcelain")
    worktrees_raw = git_runner(root, "worktree", "list", "--porcelain")

    blockers: list[str] = []
    classifications: dict[str, str] = {}
    for name, result in (
        ("toplevel", toplevel),
        ("inside", inside),
        ("head", head),
        ("branch", branch),
        ("origin_main", origin_main),
        ("merge_base", merge_base),
        ("status", status),
        ("worktrees", worktrees_raw),
    ):
        classifications[name] = result["classification"]
        if result["classification"] in {"unavailable", "blocked", "malformed"}:
            blockers.append(f"{name}:{result.get('reason') or result['classification']}")

    worktrees = parse_worktrees(worktrees_raw.get("stdout") or "")
    current = detect_canonical(root, declared_canonical)
    dirty = bool(status.get("stdout"))
    if current["is_canonical"] and dirty:
        blockers.append("dirty_canonical_checkout")

    current_branch = branch.get("stdout") or ""
    same_branch = [
        item
        for item in worktrees
        if item.get("branch") == current_branch and Path(item.get("path", ".")).resolve() != root.resolve()
    ]
    if same_branch:
        blockers.append("branch_checked_out_in_another_worktree")
    if expected_branch and current_branch and expected_branch != current_branch:
        blockers.append("branch_conflict")

    head_sha = head.get("stdout") or ""
    main_sha = origin_main.get("stdout") or ""
    base_sha = merge_base.get("stdout") or ""
    stale = bool(main_sha and base_sha and main_sha != base_sha)
    if stale:
        blockers.append("stale_branch_base")

    untracked_sensitive = sensitive_untracked(status.get("stdout") or "")
    if untracked_sensitive:
        blockers.append("untracked_sensitive_files")

    scope_conflicts: list[str] = []
    for path in allowed_scope or []:
        if unsafe_target(path):
            scope_conflicts.append(path)
    if scope_conflicts:
        blockers.append("unsafe_target_paths")

    duplicate_ownership = [
        item["path"]
        for item in worktrees
        if item.get("path") and Path(item["path"]).resolve() != root.resolve()
    ]

    document = {
        "schema": SCHEMA,
        "read_only": True,
        "repository": str(root.resolve()),
        "head_sha": head_sha or None,
        "origin_main_sha": main_sha or None,
        "merge_base_sha": base_sha or None,
        "branch": current_branch or None,
        "dirty": dirty,
        "canonical": current,
        "worktrees": worktrees,
        "other_worktree_paths": duplicate_ownership,
        "same_branch_worktrees": same_branch,
        "stale_branch_base": stale,
        "untracked_sensitive_files": untracked_sensitive,
        "unsafe_target_paths": scope_conflicts,
        "evidence_classification": classifications,
        "blockers": blockers,
        "safe_to_edit": not blockers and classifications.get("inside") == "actual",
        "coderos": {"classification": "unavailable", "reason": "coderos_not_probed_by_this_utility"},
        "next_best_action": (
            "use_exclusive_worktree_off_canonical"
            if "dirty_canonical_checkout" in blockers
            else ("rebase_or_recreate_from_origin_main" if stale else "continue_in_current_worktree")
        ),
    }
    exit_code = 0 if document["safe_to_edit"] else 2
    return document, exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--canonical")
    parser.add_argument("--expected-branch")
    parser.add_argument("--allowed-scope", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    document, code = evaluate_safety(
        args.repository.resolve(),
        declared_canonical=args.canonical,
        expected_branch=args.expected_branch,
        allowed_scope=args.allowed_scope,
    )
    print(json.dumps(document, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

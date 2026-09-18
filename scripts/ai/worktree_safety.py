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
    ("merge-base", "--is-ancestor", "@{u}", "HEAD"),
}
# NOTE: _run_git's own allowlist check treats every ("rev-parse", ...) argv
# as allowed regardless of membership above -- do not add rev-parse entries
# here expecting them to be enforced; add non-rev-parse subcommands only.


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


def prunable_worktrees(worktrees: list[dict[str, str]], *, current_root: Path) -> list[str]:
    """Worktree entries git still lists whose directory no longer exists on disk."""
    missing: list[str] = []
    for item in worktrees:
        path = item.get("path")
        if not path:
            continue
        candidate = Path(path)
        if candidate.resolve() == current_root.resolve():
            continue
        if not candidate.exists():
            missing.append(path)
    return missing


def outside_allowed_roots(root: Path, *, allowed_roots: list[str] | None = None) -> bool:
    """True when this worktree's own path is not under any declared-safe root.

    Default allowed roots match how EnterWorktree provisions isolated
    worktrees (``.claude/worktrees/``) and how a plain canonical checkout is
    used directly; a worktree created somewhere else (e.g. a stray path
    outside the repository the agent was handed) is flagged rather than
    silently trusted.
    """
    resolved = root.resolve().as_posix()
    roots = allowed_roots or [".claude/worktrees/"]
    if any(marker in resolved for marker in roots):
        return False
    # A bare canonical checkout (no worktrees/ segment at all) is allowed --
    # only a path that looks like it escaped an expected worktrees root is
    # flagged, e.g. a sibling directory a caller manually copied files into.
    return "worktrees" in resolved and not any(marker.strip("/") in resolved for marker in roots)


def overlapping_pr_paths(allowed_scope: list[str], other_pr_paths: dict[str, list[str]] | None) -> dict[str, list[str]]:
    """Flag allowed_scope paths another open PR already declares changed.

    ``other_pr_paths`` is caller-supplied (e.g. from a prior ``gh``/GitHub
    API read elsewhere) -- this utility makes no network call itself.
    """
    overlaps: dict[str, list[str]] = {}
    for pr_ref, paths in (other_pr_paths or {}).items():
        hit = sorted(set(allowed_scope) & set(paths))
        if hit:
            overlaps[pr_ref] = hit
    return overlaps


def protected_paths_hit(allowed_scope: list[str]) -> list[str]:
    """Reuse #254's own reserved-authority list rather than a second one."""
    try:
        from scripts.ai.operator_task_packet import RESERVED_AUTHORITIES
    except ImportError:
        return []
    return [name for name in RESERVED_AUTHORITIES if any(name in path for path in allowed_scope)]


def force_push_risk(root: Path, *, git_runner=_run_git) -> dict[str, Any]:
    """Detect whether pushing HEAD would require a force-push.

    Only meaningful when an upstream is configured; absent that this is
    honestly ``not_run`` rather than a false "safe".
    """
    upstream = git_runner(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if upstream["classification"] != "actual":
        return {"classification": "not_run", "reason": "no_upstream_configured", "force_push_required": False}
    ancestor = git_runner(root, "merge-base", "--is-ancestor", "@{u}", "HEAD")
    # --is-ancestor: exit 0 = upstream is an ancestor of HEAD (safe,
    # fast-forwardable); exit 1 = it is not (a normal push would need
    # --force); any other exit code is a real git failure, not a verdict.
    if ancestor["exit_code"] == 0:
        return {"classification": "actual", "reason": None, "force_push_required": False}
    if ancestor["exit_code"] == 1:
        return {"classification": "actual", "reason": "upstream_diverged", "force_push_required": True}
    return {"classification": "unavailable", "reason": "merge_base_check_failed", "force_push_required": None}


def native_agent_command_status() -> dict[str, Any]:
    """Delegate command-presence detection to the one capability catalog."""
    try:
        from scripts.ai.native_agent_capability import build_capability_record
    except ImportError:
        return {"classification": "unavailable", "reason": "native_agent_capability_module_missing"}
    record = build_capability_record()
    return {
        "classification": "actual",
        "agents": {item["command"]: item["state"] for item in record["agents"]},
        "coderos": record["coderos"]["state"],
    }


def evaluate_safety(
    root: Path,
    *,
    declared_canonical: str | None = None,
    expected_branch: str | None = None,
    allowed_scope: list[str] | None = None,
    allowed_roots: list[str] | None = None,
    other_pr_paths: dict[str, list[str]] | None = None,
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

    prunable = prunable_worktrees(worktrees, current_root=root)
    if prunable:
        blockers.append("deleted_worktree_still_registered")

    outside_roots = outside_allowed_roots(root, allowed_roots=allowed_roots)
    if outside_roots:
        blockers.append("worktree_path_outside_allowed_roots")

    pr_overlap = overlapping_pr_paths(allowed_scope or [], other_pr_paths)
    if pr_overlap:
        blockers.append("overlapping_pr_paths")

    protected_hits = protected_paths_hit(allowed_scope or [])
    if protected_hits:
        blockers.append("protected_path_in_scope")

    push_risk = force_push_risk(root, git_runner=git_runner)
    if push_risk.get("force_push_required"):
        blockers.append("force_push_risk")

    agent_commands = native_agent_command_status()

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
        "prunable_worktrees": prunable,
        "worktree_outside_allowed_roots": outside_roots,
        "overlapping_pr_paths": pr_overlap,
        "protected_paths_in_scope": protected_hits,
        "force_push_risk": push_risk,
        "native_agent_commands": agent_commands,
        "evidence_classification": classifications,
        "blockers": blockers,
        "safe_to_edit": not blockers and classifications.get("inside") == "actual",
        # Shape AND classification vocabulary preserved from the original
        # stub ({"classification": one of "actual"/"unavailable"/"blocked"/
        # "malformed", "reason": ...}) -- native_agent_capability's own
        # richer state vocabulary ("installed"/"configured"/...) must never
        # leak into this field; it lives in "native_agent_commands" above.
        "coderos": (
            {
                "classification": "actual" if agent_commands["coderos"] == "installed" else "unavailable",
                "reason": None if agent_commands["coderos"] == "installed" else "not_found_on_path",
            }
            if agent_commands.get("classification") == "actual"
            else {"classification": "unavailable", "reason": "coderos_not_probed_by_this_utility"}
        ),
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
    parser.add_argument("--allowed-root", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    document, code = evaluate_safety(
        args.repository.resolve(),
        declared_canonical=args.canonical,
        expected_branch=args.expected_branch,
        allowed_scope=args.allowed_scope,
        allowed_roots=args.allowed_root or None,
    )
    print(json.dumps(document, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

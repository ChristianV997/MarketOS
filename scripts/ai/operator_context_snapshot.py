"""Read-only bounded AI-chat repository context snapshot.

Reuses existing MarketOS AI scripts. Does not recreate quality-gate,
phase-1, PR-readiness, CoderOS, cockpit, or deployment-engine logic.
Default is dry-run / read-only.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = "MarketOS.AIContext.v1"
DEFAULT_TIMEOUT_S = 45.0
MAX_OUTPUT_BYTES = 200_000
MAX_CHANGED_FILES = 80
MAX_WORKTREES = 20
MAX_OPEN_PRS = 10

REQUIRED_KEYS = (
    "schema",
    "repository",
    "branch",
    "HEAD",
    "origin_main",
    "worktree",
    "changed_paths",
    "open_prs",
    "selected_tests",
    "phase1_readiness",
    "local_quality_gate",
    "development_stack",
    "deployment_readiness",
    "blockers",
    "next_best_action",
    "evidence_classifications",
)

SECRET_SHAPED = re.compile(
    r"(?is)("
    r"-----begin (?:rsa |ec |dsa |openssh )?private key-----"
    r"|ghp_[A-Za-z0-9_]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-(?:live|test)?-?[A-Za-z0-9]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|bearer [A-Za-z0-9._-]{10,}"
    r")"
)
SECRET_KEY_HINT = re.compile(r"(?i)(api[_-]?key|secret|password|token|authorization|private_key|credential)")
EXCLUDED_PATH_PREFIXES = (
    "artifacts/",
    ".env",
    "credentials/",
    "secrets/",
    "node_modules/",
    ".git/",
)
EXCLUDED_PATH_MARKERS = (
    ".env",
    "browser-trace",
    "playwright-report",
    ".cache",
    "customer",
)

ALLOWED_GIT = {
    ("rev-parse", "HEAD"),
    ("rev-parse", "origin/main"),
    ("rev-parse", "--show-toplevel"),
    ("branch", "--show-current"),
    ("status", "--porcelain"),
    ("remote", "get-url", "origin"),
    ("worktree", "list", "--porcelain"),
    ("merge-base", "origin/main", "HEAD"),
}
ALLOWED_GH = {
    ("pr", "view", "--json", "number,title,state,isDraft,url,headRefOid,baseRefName"),
    ("pr", "list", "--state", "open", "--limit", "10", "--json", "number,title,state,isDraft,headRefName,url"),
}
ACTUAL_LOCAL_CHECKS = frozenset({"session_start", "development_stack"})
EVIDENCE_CLASSES = ("actual", "simulated", "unavailable", "not_run", "failed", "malformed", "blocked")


def _secret_like(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if SECRET_KEY_HINT.search(str(key).replace("-", "_")) or _secret_like(item):
                return True
        return False
    if isinstance(value, list):
        return any(_secret_like(item) for item in value)
    if isinstance(value, str):
        return bool(SECRET_SHAPED.search(value))
    return False


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if SECRET_KEY_HINT.search(str(key).replace("-", "_")):
                out[key] = "[redacted]"
            else:
                out[key] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str) and SECRET_SHAPED.search(value):
        return "[redacted]"
    return value


def _excluded_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if any(normalized.startswith(prefix) or f"/{prefix}" in f"/{normalized}" for prefix in EXCLUDED_PATH_PREFIXES):
        return True
    lowered = normalized.lower()
    if lowered.endswith(".env") or "/.env." in lowered:
        return True
    return any(marker in lowered for marker in EXCLUDED_PATH_MARKERS)


def _validate_root(root: Path) -> tuple[Path | None, str | None]:
    raw = str(root)
    if ".." in Path(raw).parts or ".." in raw.replace("\\", "/"):
        return None, "path_traversal"
    try:
        resolved = root.expanduser().resolve()
    except OSError:
        return None, "unresolvable_path"
    if not resolved.exists() or not resolved.is_dir():
        return None, "not_a_directory"
    if not (resolved / "AGENTS.md").is_file():
        return None, "missing_agents_md"
    if not (resolved / "scripts" / "ai").is_dir():
        return None, "missing_scripts_ai"
    if not (resolved / ".git").exists():
        return None, "not_a_git_worktree"
    return resolved, None


def _is_canonical_checkout(path: Path) -> bool:
    text = str(path).replace("\\", "/").rstrip("/")
    return text.endswith("/MarketOS") and ".worktrees" not in text and ".validation" not in text


def _worktree_safe_metadata(path: str | None) -> bool:
    if not path:
        return False
    normalized = path.replace("\\", "/").lower()
    if any(marker in normalized for marker in (".env", "/artifacts/", "customer", "/credentials/", "/secrets/")):
        return False
    return "marketos" in normalized


def _run_allowlisted(
    argv: list[str],
    *,
    cwd: Path,
    timeout_s: float,
    classification_name: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": classification_name,
        "classification": "not_run",
        "exit_code": None,
        "parsed": None,
        "reason": None,
    }
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
            shell=False,
        )
    except FileNotFoundError:
        result["classification"] = "unavailable"
        result["reason"] = "executable_not_found"
        return result
    except subprocess.TimeoutExpired:
        result["classification"] = "unavailable"
        result["reason"] = "timed_out"
        return result
    stdout = completed.stdout or ""
    if len(stdout.encode("utf-8", errors="replace")) > MAX_OUTPUT_BYTES:
        result["classification"] = "malformed"
        result["reason"] = "output_exceeds_cap"
        result["exit_code"] = completed.returncode
        return result
    result["exit_code"] = completed.returncode
    stripped = stdout.strip()
    if not stripped:
        result["classification"] = "failed" if completed.returncode else "unavailable"
        result["reason"] = "empty_stdout"
        return result
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            result["classification"] = "malformed"
            result["reason"] = "stdout_not_json"
            return result
        try:
            parsed = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            result["classification"] = "malformed"
            result["reason"] = "stdout_not_json"
            return result
    if _secret_like(parsed):
        result["classification"] = "blocked"
        result["reason"] = "secret_shaped_output"
        return result
    result["parsed"] = _redact(parsed)
    if completed.returncode == 0:
        if classification_name in ACTUAL_LOCAL_CHECKS:
            result["classification"] = "actual"
        elif "--execute" in argv:
            result["classification"] = "actual"
        else:
            result["classification"] = "simulated"
    elif completed.returncode == 2:
        result["classification"] = "unavailable"
    else:
        result["classification"] = "failed"
    return result


def _git(root: Path, *args: str, timeout_s: float = 15.0) -> dict[str, Any]:
    key = tuple(args)
    allowed = key in ALLOWED_GIT or (len(args) >= 1 and args[0] == "rev-parse")
    if not allowed:
        return {"classification": "blocked", "reason": "git_argv_not_allowlisted", "stdout": "", "exit_code": 4}
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
        return {
            "classification": "malformed",
            "reason": "output_exceeds_cap",
            "stdout": "",
            "exit_code": completed.returncode,
        }
    classification = "actual" if completed.returncode == 0 else "unavailable"
    return {"classification": classification, "exit_code": completed.returncode, "stdout": stdout.strip()}


def _gh(root: Path, *args: str, timeout_s: float = 20.0) -> dict[str, Any]:
    if tuple(args) not in ALLOWED_GH:
        return {"classification": "blocked", "reason": "gh_argv_not_allowlisted", "parsed": None, "exit_code": 4}
    try:
        completed = subprocess.run(
            ["gh", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
            shell=False,
        )
    except FileNotFoundError:
        return {"classification": "unavailable", "reason": "gh_missing", "parsed": None, "exit_code": None}
    except subprocess.TimeoutExpired:
        return {"classification": "unavailable", "reason": "github_network_or_cli", "parsed": None, "exit_code": None}
    if completed.returncode != 0:
        return {
            "classification": "unavailable",
            "reason": "no_pr_or_network_unavailable",
            "parsed": None,
            "exit_code": completed.returncode,
        }
    try:
        parsed = json.loads(completed.stdout or "null")
    except json.JSONDecodeError:
        return {"classification": "malformed", "reason": "gh_json", "parsed": None, "exit_code": completed.returncode}
    if _secret_like(parsed):
        return {"classification": "blocked", "reason": "secret_shaped_output", "parsed": None, "exit_code": completed.returncode}
    return {"classification": "actual", "reason": None, "parsed": _redact(parsed), "exit_code": 0}


def _python() -> str:
    return sys.executable


def _safe_changed_paths(raw: list[str]) -> list[str]:
    cleaned = []
    for path in raw:
        value = str(path).replace("\\", "/")
        if value.startswith("./"):
            value = value[2:]
        if not value or _excluded_path(value):
            continue
        cleaned.append(value)
        if len(cleaned) >= MAX_CHANGED_FILES:
            break
    return cleaned


def _parse_worktrees(raw: str) -> list[dict[str, str | None]]:
    listed: list[dict[str, str | None]] = []
    current: dict[str, str | None] = {}
    for line in (raw or "").splitlines():
        if not line.strip():
            if current.get("path"):
                listed.append(current)
                if len(listed) >= MAX_WORKTREES:
                    return listed
            current = {}
            continue
        if line.startswith("worktree "):
            if current.get("path"):
                listed.append(current)
                if len(listed) >= MAX_WORKTREES:
                    return listed
            current = {"path": line[len("worktree ") :].strip(), "head": None, "branch": None}
        elif line.startswith("HEAD "):
            current["head"] = line[5:].strip()
        elif line.startswith("branch "):
            current["branch"] = line[len("branch ") :].replace("refs/heads/", "").strip()
        elif line.strip() == "detached":
            current["branch"] = "detached"
    if current.get("path") and len(listed) < MAX_WORKTREES:
        listed.append(current)
    return listed


def _classify_drift(head: str | None, origin_main: str | None, merge_base: str | None) -> str:
    if not head or not origin_main or not merge_base:
        return "unavailable"
    if head == origin_main:
        return "aligned"
    if merge_base == origin_main:
        return "ahead"
    if merge_base == head:
        return "behind"
    return "diverged"


def _coderos_status() -> dict[str, Any]:
    try:
        from backend.adapters.coderos_readonly import CoderOSAdapterConfig, health, probe
    except Exception:
        return {
            "classification": "unavailable",
            "reason": "adapter_import_failed",
            "mode": "plan_only",
            "would_execute": False,
        }
    summary = health()
    report = probe(CoderOSAdapterConfig(mode="plan_only"))
    state = getattr(getattr(report, "result", None), "state", "not_run")
    return {
        "classification": "not_run" if state == "not_run" else "unavailable",
        "reason": "plan_only_default",
        "mode": "plan_only",
        "would_execute": False,
        "adapter": summary.get("name"),
        "reachable": False,
        "detail": summary.get("detail"),
        "state": state,
    }


def _blocked_document(reason: str) -> dict[str, Any]:
    empty_worktree = {
        "path": None,
        "branch": None,
        "head": None,
        "clean": False,
        "canonical_checkout": False,
        "listed": [],
        "drift": {"merge_base": None, "vs_origin_main": "unavailable"},
        "ownership_note": "edits must stay in an exclusive worktree; this snapshot is read-only",
    }
    return {
        "schema": SCHEMA,
        "read_only": True,
        "mutated": False,
        "network_calls": False,
        "repository": {"name": None, "path": None, "remote": None},
        "branch": None,
        "HEAD": None,
        "origin_main": None,
        "worktree": empty_worktree,
        "changed_paths": [],
        "open_prs": {"classification": "not_run", "items": []},
        "selected_tests": [],
        "phase1_readiness": {},
        "local_quality_gate": {},
        "development_stack": {"classification": "not_run", "tools": {}},
        "deployment_readiness": {
            "classification": "unavailable",
            "local_checks_are_not_production_proof": True,
            "status": None,
        },
        "blockers": [reason, "deployment_not_proven_from_local_checks"],
        "next_best_action": "repair_repository_path_and_rerun_snapshot",
        "evidence_classifications": {"repository_path": "blocked"},
        "repository_name": None,
        "current_branch": None,
        "head_sha": None,
        "origin_main_sha": None,
        "worktree_clean": False,
        "changed_file_paths": [],
        "active_pr": None,
        "selected_test_paths": [],
        "phase1_readiness_summary": {},
        "current_blockers": [reason, "deployment_not_proven_from_local_checks"],
        "recommended_next_action": "repair_repository_path_and_rerun_snapshot",
        "evidence_classification": {"repository_path": "blocked"},
        "frontend_status": {"classification": "not_run"},
        "tools": {},
        "notes": ["Repository path was rejected; no subprocesses ran."],
    }


def build_snapshot(
    root: Path,
    *,
    include_frontend: bool = False,
    include_github: bool = True,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> tuple[dict[str, Any], int]:
    validated, path_reason = _validate_root(root)
    if validated is None:
        return _blocked_document(path_reason or "invalid_repository_path"), 2

    python = _python()
    head = _git(validated, "rev-parse", "HEAD")
    branch = _git(validated, "branch", "--show-current")
    origin_main = _git(validated, "rev-parse", "origin/main")
    status = _git(validated, "status", "--porcelain")
    remote = _git(validated, "remote", "get-url", "origin")
    toplevel = _git(validated, "rev-parse", "--show-toplevel")
    worktree_list = _git(validated, "worktree", "list", "--porcelain")
    merge_base = _git(validated, "merge-base", "origin/main", "HEAD")
    dirty = bool(status.get("stdout"))
    changed: list[str] = []
    for line in (status.get("stdout") or "").splitlines():
        if len(line) < 4:
            continue
        path = line[3:].split(" -> ")[-1]
        changed.append(path)
    changed = _safe_changed_paths(changed)
    listed = [
        item
        for item in _parse_worktrees(worktree_list.get("stdout") or "")
        if _worktree_safe_metadata(item.get("path"))
    ]
    worktree_path = toplevel.get("stdout") or str(validated)
    drift = _classify_drift(head.get("stdout"), origin_main.get("stdout"), merge_base.get("stdout"))

    tools = {
        name: {"available": bool(shutil.which(name)), "classification": "actual" if shutil.which(name) else "unavailable"}
        for name in ("python", "git", "gh", "node", "npm", "uv", "ollama", "semgrep", "coderos")
    }

    session = _run_allowlisted(
        [python, str(validated / "scripts" / "ai" / "session_start.py"), "--json"],
        cwd=validated,
        timeout_s=timeout_s,
        classification_name="session_start",
    )
    selected = _run_allowlisted(
        [python, str(validated / "scripts" / "ai" / "select_tests.py"), "--from-git", "--json"],
        cwd=validated,
        timeout_s=timeout_s,
        classification_name="select_tests",
    )
    phase1 = _run_allowlisted(
        [python, str(validated / "scripts" / "phase1_readiness_report.py"), "--json"],
        cwd=validated,
        timeout_s=timeout_s,
        classification_name="phase1_readiness",
    )
    quality = _run_allowlisted(
        [python, str(validated / "scripts" / "ai" / "run_local_quality_gate.py"), "--from-git", "--json"],
        cwd=validated,
        timeout_s=min(timeout_s, 60.0),
        classification_name="local_quality_gate",
    )
    pr_ready = _run_allowlisted(
        [python, str(validated / "scripts" / "ai" / "pr_readiness_report.py"), "--from-git", "--json"],
        cwd=validated,
        timeout_s=timeout_s,
        classification_name="pr_readiness",
    )
    dev_stack = _run_allowlisted(
        [python, str(validated / "scripts" / "ai" / "check_dev_stack.py"), "--json"],
        cwd=validated,
        timeout_s=min(timeout_s, 30.0),
        classification_name="development_stack",
    )
    coderos = _coderos_status()

    github_view: dict[str, Any] = {
        "classification": "not_run",
        "reason": "not_requested" if not include_github else None,
        "summary": None,
        "exit_code": None,
    }
    github_list: dict[str, Any] = {
        "classification": "not_run",
        "reason": "not_requested" if not include_github else None,
        "items": [],
        "exit_code": None,
    }
    if include_github:
        if not tools["gh"]["available"]:
            github_view = {"classification": "unavailable", "reason": "gh_missing", "summary": None, "exit_code": None}
            github_list = {"classification": "unavailable", "reason": "gh_missing", "items": [], "exit_code": None}
        else:
            viewed = _gh(validated, "pr", "view", "--json", "number,title,state,isDraft,url,headRefOid,baseRefName")
            github_view = {
                "classification": viewed["classification"],
                "reason": viewed.get("reason"),
                "summary": viewed.get("parsed") if isinstance(viewed.get("parsed"), dict) else None,
                "exit_code": viewed.get("exit_code"),
            }
            listed_prs = _gh(
                validated,
                "pr",
                "list",
                "--state",
                "open",
                "--limit",
                "10",
                "--json",
                "number,title,state,isDraft,headRefName,url",
            )
            items = listed_prs.get("parsed") if isinstance(listed_prs.get("parsed"), list) else []
            github_list = {
                "classification": listed_prs["classification"],
                "reason": listed_prs.get("reason"),
                "items": items[:MAX_OPEN_PRS],
                "exit_code": listed_prs.get("exit_code"),
            }

    frontend: dict[str, Any] = {
        "classification": "not_run",
        "reason": "not_requested" if not include_frontend else None,
        "test": "not_run",
        "typecheck": "not_run",
        "build": "not_run",
    }
    if include_frontend:
        npm = shutil.which("npm")
        if not npm:
            frontend = {
                "classification": "unavailable",
                "reason": "npm_missing",
                "test": "unavailable",
                "typecheck": "unavailable",
                "build": "unavailable",
            }
        else:
            frontend = {
                "classification": "not_run",
                "reason": "frontend_status_not_executed_by_default_snapshot",
                "test": "not_run",
                "typecheck": "not_run",
                "build": "not_run",
            }

    phase1_summary = {}
    if isinstance(phase1.get("parsed"), dict):
        phase1_summary = {
            "overall_status": phase1["parsed"].get("overall_status"),
            "overall_score": phase1["parsed"].get("overall_score"),
            "next_best_action": phase1["parsed"].get("next_best_action"),
            "blocking_gates": phase1["parsed"].get("blocking_gates", []),
            "deployment_readiness": (phase1["parsed"].get("deployment_readiness") or {}).get("status"),
        }

    quality_summary = {}
    if isinstance(quality.get("parsed"), dict):
        quality_summary = {
            "status": quality["parsed"].get("status"),
            "classification": quality["parsed"].get("classification"),
            "mode": quality["parsed"].get("mode"),
            "ready_for_supervised_use": quality["parsed"].get("ready_for_supervised_use"),
        }

    stack_tools: dict[str, Any] = {}
    if isinstance(dev_stack.get("parsed"), dict):
        raw_tools = dev_stack["parsed"].get("tools") or {}
        if isinstance(raw_tools, dict):
            stack_tools = {str(name): bool(value) for name, value in raw_tools.items()}

    development_stack = {
        "classification": dev_stack["classification"],
        "python": (dev_stack.get("parsed") or {}).get("python") if isinstance(dev_stack.get("parsed"), dict) else None,
        "platform": (dev_stack.get("parsed") or {}).get("platform") if isinstance(dev_stack.get("parsed"), dict) else None,
        "tools": stack_tools,
        "exit_code": dev_stack.get("exit_code"),
        "reason": dev_stack.get("reason"),
    }

    deployment_classification = "unavailable"
    phase1_deploy = phase1_summary.get("deployment_readiness")
    if phase1_deploy:
        deployment_classification = "simulated"
    deployment_readiness = {
        "classification": deployment_classification,
        "status": phase1_deploy,
        "local_checks_are_not_production_proof": True,
        "authority": "scripts/phase1_readiness_report.py plus PR #249 dry-run deploy path; this snapshot never executes deployment",
    }

    blockers: list[str] = []
    if dirty:
        blockers.append("worktree_dirty")
    if _is_canonical_checkout(Path(worktree_path)):
        blockers.append("canonical_checkout_do_not_edit")
    if isinstance(phase1_summary.get("blocking_gates"), list):
        blockers.extend(str(item) for item in phase1_summary["blocking_gates"])
    if quality_summary.get("ready_for_supervised_use") is False:
        blockers.append("quality_gate_not_ready_for_supervised_use")
    blockers.append("deployment_not_proven_from_local_checks")

    next_action = phase1_summary.get("next_best_action") or "refresh_origin_and_inspect_open_prs"
    repo_name = (remote.get("stdout") or "").rstrip("/").split("/")[-1].removesuffix(".git") or validated.name
    selected_commands = (
        (selected.get("parsed") or {}).get("recommended_commands") if isinstance(selected.get("parsed"), dict) else []
    )

    checks = {
        "session_start": session["classification"],
        "select_tests": selected["classification"],
        "phase1_readiness": phase1["classification"],
        "local_quality_gate": quality["classification"],
        "pr_readiness": pr_ready["classification"],
        "development_stack": development_stack["classification"],
        "github": github_view["classification"] if github_view["classification"] != "not_run" else github_list["classification"],
        "frontend": frontend["classification"],
        "git_head": head["classification"],
        "git_origin_main": origin_main["classification"],
        "worktree_list": worktree_list["classification"],
        "coderos": coderos["classification"],
    }

    incomplete = any(
        value in {"unavailable", "failed", "malformed", "blocked"}
        for key, value in checks.items()
        if key not in {"frontend", "coderos"}
    )
    unsafe = dirty and any(_excluded_path(path) is False and path.endswith(".env") for path in changed)
    exit_code = 2 if incomplete or unsafe else 0

    worktree = {
        "path": worktree_path,
        "branch": branch.get("stdout") or "detached",
        "head": head.get("stdout") or None,
        "clean": not dirty,
        "canonical_checkout": _is_canonical_checkout(Path(worktree_path)),
        "listed": listed,
        "drift": {
            "merge_base": merge_base.get("stdout") or None,
            "vs_origin_main": drift,
            "classification": merge_base.get("classification"),
        },
        "ownership_note": "edits must stay in this exclusive worktree; never modify the canonical dirty checkout",
    }

    document = {
        "schema": SCHEMA,
        "read_only": True,
        "mutated": False,
        "network_calls": include_github and "actual" in {github_view["classification"], github_list["classification"]},
        "repository": {
            "name": repo_name,
            "path": worktree_path,
            "remote": remote.get("stdout") or None,
        },
        "branch": branch.get("stdout") or "detached",
        "HEAD": head.get("stdout") or None,
        "origin_main": origin_main.get("stdout") or None,
        "worktree": worktree,
        "changed_paths": changed,
        "open_prs": github_list,
        "selected_tests": selected_commands if isinstance(selected_commands, list) else [],
        "phase1_readiness": phase1_summary,
        "local_quality_gate": quality_summary,
        "development_stack": development_stack,
        "deployment_readiness": deployment_readiness,
        "blockers": blockers,
        "next_best_action": next_action,
        "evidence_classifications": checks,
        "coderos": coderos,
        "exit_codes": {
            "session_start": session.get("exit_code"),
            "select_tests": selected.get("exit_code"),
            "phase1_readiness": phase1.get("exit_code"),
            "local_quality_gate": quality.get("exit_code"),
            "pr_readiness": pr_ready.get("exit_code"),
            "development_stack": dev_stack.get("exit_code"),
            "github_view": github_view.get("exit_code"),
            "github_list": github_list.get("exit_code"),
        },
        "repository_name": repo_name,
        "current_branch": branch.get("stdout") or "detached",
        "head_sha": head.get("stdout") or None,
        "origin_main_sha": origin_main.get("stdout") or None,
        "worktree_clean": not dirty,
        "changed_file_paths": changed,
        "active_pr": github_view.get("summary"),
        "selected_test_paths": selected_commands if isinstance(selected_commands, list) else [],
        "phase1_readiness_summary": phase1_summary,
        "frontend_status": frontend,
        "tools": tools,
        "current_blockers": blockers,
        "recommended_next_action": next_action,
        "evidence_classification": checks,
        "deployment_readiness_classification": deployment_classification,
        "notes": [
            "Local quality-gate, phase1, and deployment fields are not live production proof.",
            "GitHub access is classified unavailable when gh or network is absent.",
            "CoderOS stays plan_only / not_run unless a future operator opts into probe mode.",
            "This snapshot never includes artifacts/, .env files, caches, browser traces, or raw provider payloads.",
            "PR #246 Invoke-MarketOSOperator.ps1 remains the Product Validation sprint authority; this snapshot does not replace it.",
            "PR #230 cockpit and PR #213 frontend/API remain the UI/API authorities; this snapshot does not call those endpoints.",
        ],
    }
    return document, exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true", default=True)
    parser.add_argument("--include-frontend", action="store_true")
    parser.add_argument("--no-github", action="store_true")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    document, exit_code = build_snapshot(
        args.repository,
        include_frontend=args.include_frontend,
        include_github=not args.no_github,
        timeout_s=args.timeout,
    )
    print(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

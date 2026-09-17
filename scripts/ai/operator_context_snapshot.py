"""Read-only bounded AI-chat repository context snapshot.

Reuses existing MarketOS AI scripts. Does not recreate quality-gate,
phase-1, or PR-readiness logic. Default is dry-run / read-only.
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
    ("branch", "--show-current"),
    ("status", "--porcelain"),
    ("remote", "get-url", "origin"),
}
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
        result["classification"] = "simulated" if "--execute" not in argv else "actual"
    elif completed.returncode == 2:
        result["classification"] = "unavailable"
    else:
        result["classification"] = "failed"
    return result


def _git(root: Path, *args: str, timeout_s: float = 15.0) -> dict[str, Any]:
    key = tuple(args)
    allowed = key in ALLOWED_GIT or (len(args) >= 2 and args[0] == "rev-parse")
    if not allowed:
        return {"classification": "blocked", "reason": "git_argv_not_allowlisted", "stdout": ""}
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
        return {"classification": "unavailable", "reason": "git_missing", "stdout": ""}
    except subprocess.TimeoutExpired:
        return {"classification": "unavailable", "reason": "git_timed_out", "stdout": ""}
    stdout = (completed.stdout or "").strip()
    classification = "actual" if completed.returncode == 0 else "unavailable"
    return {"classification": classification, "exit_code": completed.returncode, "stdout": stdout}


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


def build_snapshot(
    root: Path,
    *,
    include_frontend: bool = False,
    include_github: bool = True,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> tuple[dict[str, Any], int]:
    python = _python()
    head = _git(root, "rev-parse", "HEAD")
    branch = _git(root, "branch", "--show-current")
    origin_main = _git(root, "rev-parse", "origin/main")
    status = _git(root, "status", "--porcelain")
    remote = _git(root, "remote", "get-url", "origin")
    dirty = bool(status.get("stdout"))
    changed: list[str] = []
    for line in (status.get("stdout") or "").splitlines():
        if len(line) < 4:
            continue
        path = line[3:].split(" -> ")[-1]
        changed.append(path)
    changed = _safe_changed_paths(changed)

    tools = {
        name: {"available": bool(shutil.which(name)), "classification": "actual" if shutil.which(name) else "unavailable"}
        for name in ("python", "git", "gh", "node", "npm", "uv", "ollama", "semgrep")
    }

    session = _run_allowlisted(
        [python, str(root / "scripts" / "ai" / "session_start.py"), "--json"],
        cwd=root,
        timeout_s=timeout_s,
        classification_name="session_start",
    )
    selected = _run_allowlisted(
        [python, str(root / "scripts" / "ai" / "select_tests.py"), "--from-git", "--json"],
        cwd=root,
        timeout_s=timeout_s,
        classification_name="select_tests",
    )
    phase1 = _run_allowlisted(
        [python, str(root / "scripts" / "phase1_readiness_report.py"), "--json"],
        cwd=root,
        timeout_s=timeout_s,
        classification_name="phase1_readiness",
    )
    quality = _run_allowlisted(
        [python, str(root / "scripts" / "ai" / "run_local_quality_gate.py"), "--from-git", "--json"],
        cwd=root,
        timeout_s=min(timeout_s, 60.0),
        classification_name="local_quality_gate",
    )
    pr_ready = _run_allowlisted(
        [python, str(root / "scripts" / "ai" / "pr_readiness_report.py"), "--from-git", "--json"],
        cwd=root,
        timeout_s=timeout_s,
        classification_name="pr_readiness",
    )

    github: dict[str, Any] = {
        "classification": "not_run",
        "reason": "not_requested" if not include_github else None,
        "summary": None,
    }
    if include_github:
        if not tools["gh"]["available"]:
            github = {"classification": "unavailable", "reason": "gh_missing", "summary": None}
        else:
            try:
                completed = subprocess.run(
                    ["gh", "pr", "view", "--json", "number,title,state,isDraft,url,headRefOid,baseRefName"],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=20,
                    check=False,
                    shell=False,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                github = {"classification": "unavailable", "reason": "github_network_or_cli", "summary": None}
            else:
                if completed.returncode != 0:
                    github = {
                        "classification": "unavailable",
                        "reason": "no_pr_or_network_unavailable",
                        "summary": None,
                    }
                else:
                    try:
                        parsed = json.loads(completed.stdout or "{}")
                    except json.JSONDecodeError:
                        github = {"classification": "malformed", "reason": "gh_json", "summary": None}
                    else:
                        if _secret_like(parsed):
                            github = {"classification": "blocked", "reason": "secret_shaped_output", "summary": None}
                        else:
                            github = {"classification": "actual", "reason": None, "summary": _redact(parsed)}

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
            frontend = {"classification": "unavailable", "reason": "npm_missing", "test": "unavailable", "typecheck": "unavailable", "build": "unavailable"}
        else:
            frontend = {
                "classification": "unavailable",
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

    deployment_classification = "unavailable"
    if phase1_summary.get("deployment_readiness"):
        deployment_classification = "simulated" if phase1_summary["deployment_readiness"] != "ready" else "unavailable"

    blockers: list[str] = []
    if dirty:
        blockers.append("worktree_dirty")
    if isinstance(phase1_summary.get("blocking_gates"), list):
        blockers.extend(str(item) for item in phase1_summary["blocking_gates"])
    if quality_summary.get("ready_for_supervised_use") is False:
        blockers.append("quality_gate_not_ready_for_supervised_use")
    blockers.append("deployment_not_proven_from_local_checks")

    next_action = phase1_summary.get("next_best_action") or "refresh_origin_and_inspect_open_prs"
    repo_name = (remote.get("stdout") or "").rstrip("/").split("/")[-1].removesuffix(".git") or root.name

    checks = {
        "session_start": session["classification"],
        "select_tests": selected["classification"],
        "phase1_readiness": phase1["classification"],
        "local_quality_gate": quality["classification"],
        "pr_readiness": pr_ready["classification"],
        "github": github["classification"],
        "frontend": frontend["classification"],
        "git_head": head["classification"],
        "git_origin_main": origin_main["classification"],
    }

    incomplete = any(
        value in {"unavailable", "failed", "malformed", "blocked"}
        for key, value in checks.items()
        if key not in {"frontend"}
    )
    unsafe = dirty and any(_excluded_path(path) is False and path.endswith(".env") for path in changed)
    exit_code = 2 if incomplete or unsafe else 0

    document = {
        "schema": SCHEMA,
        "read_only": True,
        "mutated": False,
        "network_calls": include_github and github["classification"] == "actual",
        "repository_name": repo_name,
        "current_branch": branch.get("stdout") or "detached",
        "head_sha": head.get("stdout") or None,
        "origin_main_sha": origin_main.get("stdout") or None,
        "worktree_clean": not dirty,
        "changed_file_paths": changed,
        "active_pr": github.get("summary"),
        "selected_test_paths": (selected.get("parsed") or {}).get("recommended_commands") if isinstance(selected.get("parsed"), dict) else [],
        "phase1_readiness_summary": phase1_summary,
        "local_quality_gate": quality_summary,
        "deployment_readiness_classification": deployment_classification,
        "frontend_status": frontend,
        "tools": tools,
        "current_blockers": blockers,
        "recommended_next_action": next_action,
        "evidence_classification": checks,
        "notes": [
            "Local quality-gate and phase1 reports are not live deployment proof.",
            "GitHub access is classified unavailable when gh or network is absent.",
            "This snapshot never includes artifacts/, .env files, or raw provider payloads.",
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
    root = args.repository.resolve()
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    document, exit_code = build_snapshot(
        root,
        include_frontend=args.include_frontend,
        include_github=not args.no_github,
        timeout_s=args.timeout,
    )
    print(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

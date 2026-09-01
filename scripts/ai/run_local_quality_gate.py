"""Run deterministic, local-only MarketOS agentic quality gates in one command."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

try:
    from . import ci_matrix_plan, impact_planner, phase_gate, pr_readiness_report, select_tests
    from .operating_layer import changed_from_git, git_lines, normal_paths, render_json_or_markdown, write_optional_output
except ImportError:  # pragma: no cover - direct script execution
    import ci_matrix_plan, impact_planner, phase_gate, pr_readiness_report, select_tests
    from operating_layer import changed_from_git, git_lines, normal_paths, render_json_or_markdown, write_optional_output


QUALITY_GATE_SCHEMA = "MarketOS.LocalQualityGate.v2"
EXIT_PASSED = 0
EXIT_FAILED = 1
EXIT_UNAVAILABLE = 2
EXIT_CONFIGURATION = 3

CLASS_PASS = "pass"
CLASS_CHANGED_SCOPE_FAILURE = "changed_scope_failure"
CLASS_PRE_EXISTING_FAILURE = "pre_existing_failure"
CLASS_FAILURE_ORIGIN_UNVERIFIED = "failure_origin_unverified"
CLASS_MISSING_TOOL = "missing_tool"
CLASS_UNAVAILABLE_DEPENDENCY = "unavailable_dependency"
CLASS_CI_UNAVAILABLE = "ci_unavailable"
CLASS_SECURITY_FINDING = "security_finding"
CLASS_SECURITY_SCANNER_FAILURE = "security_scanner_failure"
CLASS_DIFF_FAILURE = "diff_failure"
CLASS_COLLECTION_FAILED = "collection_failed"
CLASS_TIMEOUT = "timeout"
CLASS_MALFORMED_CONFIGURATION = "malformed"

CHECK_ORDER = ("compile", "pytest", "ruff", "typed", "frontend", "security", "diff_check")
FRONTEND_CHECK_ORDER = ("lint", "typecheck", "test", "build")
KNOWN_LOCKFILES = (
    "uv.lock", "poetry.lock", "Pipfile.lock", "package-lock.json", "pnpm-lock.yaml",
    "yarn.lock", "bun.lock", "bun.lockb",
)
SAFE_FRONTEND_TOKENS = ("eslint", "jest", "tsc", "vite", "vitest", "webpack")
SAFE_FRONTEND_COMMANDS = {"eslint", "jest", "tsc", "vite", "vitest", "webpack"}
UNSAFE_FRONTEND_MARKERS = (
    "curl", "docker", "git ", "invoke-webrequest", "npm install", "pnpm add",
    "pnpm install", "publish", "scp ", "secret", "ssh ", "token", "wget",
)
VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?$")
PYTHON_VERSION_RE = re.compile(r"python(?:\s|-)?version\s*:\s*[\"']?([0-9]+\.[0-9]+(?:\.[0-9]+)?)[\"']?", re.I)
DOCKER_PYTHON_RE = re.compile(r"^\s*FROM\s+python:([0-9]+\.[0-9]+(?:\.[0-9]+)?)", re.I | re.M)
RUFF_TARGET_RE = re.compile(r"^py(\d+)$", re.I)
PYTEST_COUNTS = {
    "passed": re.compile(r"(\d+)\s+passed"),
    "failed": re.compile(r"(\d+)\s+failed"),
    "skipped": re.compile(r"(\d+)\s+skipped"),
    "xfailed": re.compile(r"(\d+)\s+xfailed"),
    "warnings": re.compile(r"(\d+)\s+warnings?"),
}
PYTEST_COLLECTION_RE = re.compile(
    r"(?:ERROR collecting|ImportError while importing test module|collected\s+0\s+items)",
    re.I,
)
DEPENDENCY_ERROR_RE = re.compile(
    r"(?:ModuleNotFoundError|No module named|ImportError while importing|ImportError:\s+No module named)",
    re.I,
)
RUFF_FINDING_RE = re.compile(r"(?:^|\s)[A-Z]\d{3}(?:\s|$)")
CHECK_STATUS_TAXONOMY = (
    "passed", "failed", "unavailable", "timed_out", "not_run", "not_configured",
    "collection_failed", "blocked", "malformed", "ci_unavailable",
)
CI_EVIDENCE_SCHEMA = "MarketOS.CIEvidence.v1"
CI_EVIDENCE_RUN_STATUSES = {"queued", "in_progress", "completed", "waiting", "requested", "pending"}
CI_EVIDENCE_CONCLUSIONS = {
    "success", "failure", "neutral", "cancelled", "skipped", "timed_out",
    "action_required", "stale", "startup_failure", "pending",
}
CI_EVIDENCE_CHECK_STATUSES = {"success", "failure", "neutral", "cancelled", "skipped", "pending"}
CI_EVIDENCE_MAX_BYTES = 64 * 1024
CI_EVIDENCE_MAX_JOBS = 100
QUALITY_GATE_PHASES = {"final", "preflight"}


def _optional_phase1_summary() -> tuple[dict[str, Any], dict[str, Any]]:
    """Return Phase 1 context without making the local gate depend on optional ML deps.

    ``evaluation`` also exposes experimental statistical helpers whose optional SciPy
    dependency is intentionally absent from the lightweight PR workflow.  The
    quality gate remains useful without that context and must not make a PR fail
    solely because an optional evaluation dependency is unavailable.
    """
    try:
        from evaluation.commerce.benchmark_matrix import build_benchmark_matrix
        from evaluation.commerce.readiness import build_phase1_readiness

        readiness = build_phase1_readiness().to_dict()
        benchmark = build_benchmark_matrix().to_dict()
        return readiness, benchmark
    except (ImportError, ModuleNotFoundError) as exc:
        unavailable = {
            "overall_status": "unavailable",
            "overall_score": None,
            "next_best_action": "install the optional evaluation profile to include Phase 1 context",
            "blocking_gates": [],
            "warning": f"Phase 1 context unavailable: {exc.__class__.__name__}",
        }
        return unavailable, {"status": "unavailable", "warning": unavailable["warning"]}


def _diff_text(path: str | None, root: Path = REPOSITORY_ROOT) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    completed = subprocess.run(
        ["git", "-C", str(root), "diff", "HEAD"],
        text=True, encoding="utf-8", errors="replace", capture_output=True, check=False,
    )
    return completed.stdout or ""


def _implementation_diff(paths: list[str], diff_text: str) -> str:
    """Keep mutation phrase checks out of prose/test diffs, not secret scans."""
    allowed = {path for path in paths if not path.startswith(("docs/", "tests/")) and path not in {"AGENTS.md", "CLAUDE.md", "README.md"}}
    if not allowed:
        return ""
    if "diff --git " not in diff_text:
        return diff_text
    chunks = diff_text.split("diff --git ")
    kept = [chunks[0]]
    for chunk in chunks[1:]:
        header = chunk.splitlines()[0] if chunk.splitlines() else ""
        path = header.split(" b/")[-1] if " b/" in header else ""
        if path in allowed:
            kept.append("diff --git " + chunk)
    return "".join(kept)


def run(paths: list[str], *, diff_text: str = "", branch: str = "local") -> dict[str, Any]:
    """Compose existing planning functions; no network, writes, or subprocess tests."""
    paths = normal_paths(paths)
    implementation_diff = _implementation_diff(paths, diff_text)
    readiness = pr_readiness_report.report(paths, diff_text, branch=branch, mutation_diff=implementation_diff)
    phase = phase_gate.check(paths, implementation_diff)
    selected = select_tests.select(paths)
    ci_plan = ci_matrix_plan.plan(paths)
    phase1_readiness, benchmark = _optional_phase1_summary()
    impact = impact_planner.plan(impact_planner.DEFAULT_BACKLOG, phase1_readiness)
    blocked = phase["status"] == "blocked" or readiness["risk_category"] == "blocked"
    status = "blocked" if blocked else "clear" if not paths else "advisory"
    flags = readiness["detections"]
    next_action = (
        "remove credentials, generated artifacts, or blocked mutation work before continuing"
        if blocked else "no changed files; choose one unblocked task from the impact backlog"
        if not paths else "run the recommended focused tests, then session_finish and PR readiness before opening a PR"
    )
    return {
        "status": status, "changed_files": paths, "risk_level": readiness["risk_category"],
        "phase_gate_status": phase["status"], "phase_gate_blockers": phase["blockers"],
        "secret_or_artifact_flags": {key: flags[key] for key in ("artifacts_detected", "credential_file_detected", "secret_value_like_detected")},
        "mutation_flags": {"provider_mutation_like_detected": flags["provider_mutation_like_detected"]},
        "recommended_tests": selected["recommended_commands"], "recommended_ci_lanes": ci_plan["recommended_lanes"],
        "pr_merge_readiness": readiness["merge_readiness"],
        "impact_top_task": impact["ranked_backlog"][0]["task"], "recommended_next_action": next_action,
        "phase1_readiness": {"overall_status": phase1_readiness["overall_status"], "overall_score": phase1_readiness["overall_score"], "next_best_action": phase1_readiness["next_best_action"], "blocking_gates": phase1_readiness["blocking_gates"]},
        "benchmark_matrix": {"status": benchmark.get("status", "unavailable"), "evidence_mode": benchmark.get("evidence_mode", "unavailable"), "top_candidate_id": benchmark.get("top_candidate_id"), "next_best_action": benchmark.get("next_best_action", "install the optional evaluation profile to include benchmark context")},
        "network_calls": False, "mutated": False,
    }


CommandRunner = Callable[[list[str], Path], Any]


def _version_pair(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    match = VERSION_RE.fullmatch(value.strip())
    return (int(match.group(1)), int(match.group(2))) if match else None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _read_python_version(root: Path) -> tuple[str | None, str]:
    text = _read_text(root / ".python-version")
    if text is None:
        return None, "missing"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1 or _version_pair(lines[0]) is None:
        return None, "malformed"
    return lines[0], "valid"


def _read_pyproject(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    text = _read_text(root / "pyproject.toml")
    if text is None:
        return None, "missing"
    try:
        payload = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None, "malformed"
    tool_table = payload.get("tool", {})
    if not isinstance(tool_table, Mapping):
        return None, "malformed"
    for tool_name in ("ruff", "mypy", "pyright"):
        if tool_name in tool_table and not isinstance(tool_table[tool_name], Mapping):
            return None, "malformed"
    return payload, None


def _toolchain_snapshot(root: Path) -> dict[str, Any]:
    python_version, python_file_status = _read_python_version(root)
    pyproject, pyproject_error = _read_pyproject(root)
    docker_versions: set[str] = set()
    for dockerfile in sorted(root.glob("Dockerfile*")):
        if dockerfile.is_file():
            docker_versions.update(DOCKER_PYTHON_RE.findall(_read_text(dockerfile) or ""))
    ci_versions: set[str] = set()
    workflow_root = root / ".github" / "workflows"
    if workflow_root.is_dir():
        for workflow in sorted(workflow_root.glob("*.y*ml")):
            ci_versions.update(PYTHON_VERSION_RE.findall(_read_text(workflow) or ""))

    ruff_target = None
    if pyproject:
        ruff_target = pyproject.get("tool", {}).get("ruff", {}).get("target-version")
    issues: list[str] = []
    if python_file_status == "missing":
        issues.append("missing:.python-version")
    elif python_file_status == "malformed":
        issues.append("malformed:.python-version")
    if pyproject_error and pyproject_error != "missing":
        issues.append(f"{pyproject_error}:pyproject.toml")

    declared_pair = _version_pair(python_version)
    selected_pair = (sys.version_info.major, sys.version_info.minor)
    if declared_pair and selected_pair != declared_pair:
        issues.append("python_interpreter_mismatch:.python-version")
    docker_pairs = {_version_pair(version) for version in docker_versions}
    docker_pairs.discard(None)
    if declared_pair and docker_pairs and declared_pair not in docker_pairs:
        issues.append("python_version_mismatch:docker")
    ci_pairs = {_version_pair(version) for version in ci_versions}
    ci_pairs.discard(None)
    if declared_pair and ci_pairs and declared_pair not in ci_pairs:
        issues.append("python_version_mismatch:ci")
    ruff_match = RUFF_TARGET_RE.fullmatch(str(ruff_target or ""))
    ruff_pair = None
    if ruff_match and len(ruff_match.group(1)) >= 2:
        digits = ruff_match.group(1)
        ruff_pair = (int(digits[0]), int(digits[1:]))
    if declared_pair and ruff_pair and declared_pair != ruff_pair:
        issues.append("python_version_mismatch:ruff")
    return {
        "selected_python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "selected_interpreter": f"<{Path(sys.executable).name or 'python'}>",
        "python_version_file": python_version,
        "python_version_file_status": python_file_status,
        "docker_python_versions": sorted(docker_versions),
        "ci_python_versions": sorted(ci_versions),
        "ruff_target": ruff_target,
        "alignment": "mismatch" if issues else "aligned",
        "findings": sorted(set(issues)),
        "pyproject_status": pyproject_error or "valid",
    }


def _is_pinned_requirement(line: str) -> bool:
    value = line.strip()
    return bool(re.match(r"^[A-Za-z0-9_.-]+(?:\[[^]]+\])?==[^=\s]+", value)) or " @ " in value


def _dependency_snapshot(root: Path) -> dict[str, Any]:
    manifests = sorted(path.name for path in root.glob("requirements*.txt") if path.is_file())
    if (root / "pyproject.toml").is_file():
        manifests.append("pyproject.toml")
    lockfiles: list[str] = []
    for base in (root, root / "frontend"):
        for name in KNOWN_LOCKFILES:
            if (base / name).is_file():
                lockfiles.append(str(Path("frontend") / name if base.name == "frontend" else Path(name)))
    unpinned = 0
    for manifest in root.glob("requirements*.txt"):
        for line in (_read_text(manifest) or "").splitlines():
            value = line.strip()
            if value and not value.startswith(("#", "-", "--")) and not _is_pinned_requirement(value):
                unpinned += 1
    return {
        "manifest_files": manifests,
        "lockfiles": sorted(lockfiles),
        "lockfile_status": "present" if lockfiles else "missing",
        "unpinned_requirement_count": unpinned,
        "status": "ready" if lockfiles and unpinned == 0 else "incomplete",
    }


def _typed_configuration(root: Path, pyproject: dict[str, Any] | None) -> dict[str, Any]:
    mypy_configured = any((root / name).is_file() for name in ("mypy.ini", ".mypy.ini"))
    pyright_configured = (root / "pyrightconfig.json").is_file()
    if pyproject:
        tools = pyproject.get("tool", {})
        mypy_configured = mypy_configured or bool(tools.get("mypy"))
        pyright_configured = pyright_configured or bool(tools.get("pyright"))
    configured_tools = [tool for tool, configured in (("mypy", mypy_configured), ("pyright", pyright_configured)) if configured]
    return {"configured_tools": configured_tools, "status": "configured" if configured_tools else "not_configured"}


def _git_state(root: Path) -> dict[str, Any]:
    if not (root / ".git").exists():
        return {"status": "not_a_git_repository", "tracked_change_count": 0, "untracked_count": 0}
    lines = git_lines("status", "--porcelain", root=root)
    untracked = [line for line in lines if line.startswith("??")]
    tracked = [line for line in lines if not line.startswith("??")]
    return {
        "status": "dirty" if lines else "clean",
        "tracked_change_count": len(tracked),
        "untracked_count": len(untracked),
    }


def _display_command(command: list[str]) -> list[str]:
    return [f"<{Path(value).name}>" if index == 0 and Path(value).is_absolute() else value for index, value in enumerate(command)]


def _tool_prefix(tool: str) -> list[str] | None:
    path = shutil.which(tool)
    if path:
        return [path]
    if tool == "semgrep":
        try:
            from .run_semgrep_policy import semgrep_command
        except ImportError:  # pragma: no cover - direct script execution
            from run_semgrep_policy import semgrep_command
        fallback = semgrep_command()
        if fallback:
            return [fallback]
    if tool == "ruff" and importlib.util.find_spec("ruff") is not None:
        return [sys.executable, "-m", "ruff"]
    return None


def _command_summary(name: str, stdout: str, stderr: str, returncode: int) -> dict[str, Any]:
    combined = f"{stdout}\n{stderr}"
    if name == "pytest":
        summary = {key: 0 for key in PYTEST_COUNTS}
        for key, pattern in PYTEST_COUNTS.items():
            matches = pattern.findall(combined)
            if matches:
                summary[key] = int(matches[-1])
        summary["collection_failed"] = bool(PYTEST_COLLECTION_RE.search(combined))
        summary["dependency_error"] = bool(DEPENDENCY_ERROR_RE.search(combined))
        return summary
    if name == "ruff":
        finding_count = sum(1 for line in combined.splitlines() if RUFF_FINDING_RE.search(line))
        return {"finding_count": finding_count, "dependency_error": bool(DEPENDENCY_ERROR_RE.search(combined))}
    if name == "security":
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return {"finding_count": None, "error_count": 1, "output_parse": "invalid_json"}
        if not isinstance(payload, dict):
            return {"finding_count": None, "error_count": 1, "output_parse": "invalid_json"}
        results = payload.get("results", [])
        errors = payload.get("errors", [])
        if not isinstance(results, list) or not isinstance(errors, list):
            return {"finding_count": None, "error_count": 1, "output_parse": "invalid_json_shape"}
        return {
            "finding_count": len(results),
            "error_count": len(errors),
            "output_parse": "valid_json",
        }
    return {"return_code": returncode, "dependency_error": bool(DEPENDENCY_ERROR_RE.search(combined))}


def _invoke_local(command: list[str], root: Path, runner: CommandRunner | None) -> Any:
    if runner is not None:
        return runner(command, root)
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    process = subprocess.Popen(
        command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", shell=False, creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    try:
        stdout, stderr = process.communicate(timeout=900)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, text=True, check=False, timeout=30,
            )
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        process.kill()
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _check_command(
    name: str,
    command: list[str],
    *,
    root: Path,
    execute: bool,
    tool: str | None = None,
    runner: CommandRunner | None = None,
    semantic_failure: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    prefix = _tool_prefix(tool) if tool else [command[0]]
    available = prefix is not None
    actual_command = prefix + command[1:] if tool and prefix and command and command[0] == tool else command
    result: dict[str, Any] = {
        "name": name,
        "command": _display_command(actual_command),
        "tool": tool,
        "availability": "available" if available else "missing",
        "status": "not_run" if not execute else "unavailable" if not available else "pending",
        "execution_status": "not_executed" if not execute or not available else "pending",
        "timeout": False,
    }
    if not execute or not available:
        if execute and not available:
            result["reason"] = "required_tool_missing"
        return result
    try:
        completed = _invoke_local(actual_command, root, runner)
    except (FileNotFoundError, OSError):
        result.update({"status": "unavailable", "availability": "missing", "execution_status": "not_executed", "reason": "tool_invocation_failed"})
        return result
    except subprocess.TimeoutExpired:
        result.update({"status": "timed_out", "execution_status": "timed_out", "timeout": True, "reason": "timeout"})
        return result
    stdout = str(getattr(completed, "stdout", "") or "")
    stderr = str(getattr(completed, "stderr", "") or "")
    returncode = int(getattr(completed, "returncode", 1))
    summary = _command_summary(name, stdout, stderr, returncode)
    if name == "security" and summary.get("output_parse") != "valid_json":
        status = "malformed"
    elif returncode == 0:
        status = "passed"
    elif name == "pytest" and summary.get("collection_failed"):
        status = "collection_failed"
    elif summary.get("dependency_error"):
        status = "unavailable"
    else:
        status = "failed"
    if status != "malformed" and semantic_failure and semantic_failure(summary):
        status = "failed"
    result.update({
        "status": status,
        "execution_status": "executed",
        "exit_code": returncode,
        "summary": summary,
        "stdout_present": bool(stdout),
        "stderr_present": bool(stderr),
    })
    return result


def _typed_check(root: Path, typed: dict[str, Any], *, execute: bool, runner: CommandRunner | None) -> dict[str, Any]:
    tools = typed["configured_tools"]
    if not tools:
        return {"name": "typed", "status": "not_configured", "availability": "not_applicable", "execution_status": "not_executed", "subchecks": []}
    subchecks = [_check_command(f"typed:{tool}", [tool, "."], root=root, execute=execute, tool=tool, runner=runner) for tool in tools]
    statuses = {item["status"] for item in subchecks}
    if "failed" in statuses:
        status = "failed"
    elif "timed_out" in statuses:
        status = "timed_out"
    elif "unavailable" in statuses:
        status = "unavailable"
    elif not execute:
        status = "not_run"
    else:
        status = "passed"
    execution_status = "timed_out" if any(item.get("execution_status") == "timed_out" for item in subchecks) else "executed" if any(item.get("execution_status") == "executed" for item in subchecks) else "not_executed"
    availability = "unavailable" if "unavailable" in statuses else "available"
    return {"name": "typed", "status": status, "availability": availability, "execution_status": execution_status, "subchecks": subchecks}


def _safe_frontend_script(script: Any) -> bool:
    if not isinstance(script, str):
        return False
    lowered = script.casefold()
    if not any(token in lowered for token in SAFE_FRONTEND_TOKENS) or any(marker in lowered for marker in UNSAFE_FRONTEND_MARKERS):
        return False
    segments = re.split(r"&&|\|\||[;|]", lowered)
    for segment in segments:
        tokens = re.findall(r"[a-z0-9_./\\-]+", segment)
        tokens = [token for token in tokens if "=" not in token]
        while tokens and tokens[0] in {"cross-env", "env"}:
            tokens.pop(0)
        command = tokens[0].replace("\\", "/").rsplit("/", 1)[-1] if tokens else ""
        if command not in SAFE_FRONTEND_COMMANDS:
            return False
    return True


def _frontend_check(root: Path, *, execute: bool, runner: CommandRunner | None) -> dict[str, Any]:
    frontend = root / "frontend"
    package_path = frontend / "package.json"
    if not package_path.is_file():
        return {"name": "frontend", "status": "not_configured", "manifest_status": "missing", "execution_status": "not_executed", "checks": []}
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"name": "frontend", "status": "malformed", "manifest_status": "malformed", "execution_status": "not_executed", "checks": []}
    if not isinstance(package, Mapping):
        return {"name": "frontend", "status": "malformed", "manifest_status": "malformed", "execution_status": "not_executed", "checks": []}
    scripts = package.get("scripts", {})
    if not isinstance(scripts, dict):
        return {"name": "frontend", "status": "malformed", "manifest_status": "malformed", "execution_status": "not_executed", "checks": []}
    lockfile = next((name for name in KNOWN_LOCKFILES[3:] if (frontend / name).is_file()), None)
    manager = "pnpm" if lockfile == "pnpm-lock.yaml" else "yarn" if lockfile == "yarn.lock" else "bun" if lockfile in {"bun.lock", "bun.lockb"} else "npm"
    manager_available = _tool_prefix(manager) is not None
    dependencies_available = (frontend / "node_modules").is_dir()
    checks: list[dict[str, Any]] = []
    for script_name in FRONTEND_CHECK_ORDER:
        script = scripts.get(script_name)
        if script is None:
            checks.append({"name": f"frontend:{script_name}", "status": "not_configured", "availability": "not_applicable", "execution_status": "not_executed"})
            continue
        command = [manager, "run", script_name]
        if not execute:
            checks.append({"name": f"frontend:{script_name}", "command": _display_command(command), "status": "not_run", "availability": "available" if manager_available else "missing", "execution_status": "not_executed"})
        elif not manager_available:
            checks.append({"name": f"frontend:{script_name}", "command": _display_command(command), "status": "unavailable", "availability": "missing", "execution_status": "not_executed", "reason": "package_manager_missing"})
        elif not dependencies_available:
            checks.append({"name": f"frontend:{script_name}", "command": _display_command(command), "status": "unavailable", "availability": "available", "execution_status": "not_executed", "reason": "dependencies_not_installed_network_not_attempted"})
        elif not _safe_frontend_script(script):
            checks.append({"name": f"frontend:{script_name}", "command": _display_command(command), "status": "blocked", "availability": "available", "execution_status": "not_executed", "reason": "script_not_in_local_allowlist"})
        else:
            checks.append(_check_command(f"frontend:{script_name}", command, root=frontend, execute=True, tool=manager, runner=runner))
    configured = [item for item in checks if item["status"] != "not_configured"]
    statuses = {item["status"] for item in configured}
    if "blocked" in statuses:
        status = "blocked"
    elif "failed" in statuses:
        status = "failed"
    elif "timed_out" in statuses:
        status = "timed_out"
    elif "unavailable" in statuses:
        status = "unavailable"
    elif not configured:
        status = "not_configured"
    elif not execute:
        status = "not_run"
    else:
        status = "passed"
    return {
        "name": "frontend", "status": status, "manifest_status": "valid", "package_manager": manager,
        "package_manager_available": manager_available, "lockfile": lockfile,
        "lockfile_status": "present" if lockfile else "missing", "dependencies_status": "installed" if dependencies_available else "missing",
        "execution_status": "timed_out" if any(item.get("execution_status") == "timed_out" for item in checks) else "executed" if any(item.get("execution_status") == "executed" for item in checks) else "not_executed", "checks": checks,
    }


def _security_check(root: Path, *, execute: bool, runner: CommandRunner | None) -> dict[str, Any]:
    if not (root / "semgrep" / "ai-safety.yml").is_file():
        return {
            "name": "security",
            "status": "unavailable" if execute else "not_run",
            "availability": "missing",
            "execution_status": "not_executed",
            "reason": "security_policy_missing",
        }
    return _check_command(
        "security", [sys.executable, "scripts/ai/run_semgrep_policy.py", "--json"], root=root, execute=execute,
        tool="semgrep", runner=runner, semantic_failure=lambda summary: bool(summary.get("finding_count") or summary.get("error_count")),
    )


def _ci_evidence_error(reason: str) -> tuple[dict[str, Any], str]:
    return {
        "status": "malformed",
        "reason": reason,
        "executed_steps": 0,
        "classification": CLASS_MALFORMED_CONFIGURATION,
    }, "malformed_ci_evidence"


def _validate_ci_mapping(value: Any, allowed: set[str]) -> bool:
    return isinstance(value, Mapping) and not (set(value) - allowed)


def load_ci_evidence(path: Path) -> tuple[dict[str, Any], str | None]:
    """Load strict, sanitized CI metadata without importing logs or API behavior."""
    try:
        if path.stat().st_size > CI_EVIDENCE_MAX_BYTES:
            return _ci_evidence_error("ci_evidence_too_large")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _ci_evidence_error("unreadable_ci_evidence")
    if not _validate_ci_mapping(payload, {"schema", "run", "required_jobs", "jobs"}) or payload.get("schema") != CI_EVIDENCE_SCHEMA:
        return _ci_evidence_error("invalid_ci_evidence_schema")

    run = payload.get("run")
    if not _validate_ci_mapping(run, {"status", "conclusion"}):
        return _ci_evidence_error("invalid_ci_run_metadata")
    run_status = run.get("status")
    run_conclusion = run.get("conclusion")
    if run_status not in CI_EVIDENCE_RUN_STATUSES or run_conclusion not in CI_EVIDENCE_CONCLUSIONS:
        return _ci_evidence_error("invalid_ci_run_status")

    required_jobs = payload.get("required_jobs")
    if (
        not isinstance(required_jobs, list) or not required_jobs
        or len(required_jobs) > CI_EVIDENCE_MAX_JOBS
        or any(not isinstance(name, str) or not name.strip() for name in required_jobs)
        or len({name.strip() for name in required_jobs}) != len(required_jobs)
    ):
        return _ci_evidence_error("required_ci_jobs_expected")
    required_jobs = [name.strip() for name in required_jobs]
    raw_jobs = payload.get("jobs")
    if not isinstance(raw_jobs, list) or len(raw_jobs) > CI_EVIDENCE_MAX_JOBS:
        return _ci_evidence_error("ci_jobs_required")
    normalized_jobs: list[dict[str, Any]] = []
    allowed_job_fields = {
        "name", "required", "status", "conclusion", "runner_id", "runner_name",
        "steps_executed", "logs_available", "required_check_status",
    }
    seen_job_names: set[str] = set()
    for raw_job in raw_jobs:
        if not _validate_ci_mapping(raw_job, allowed_job_fields):
            return _ci_evidence_error("invalid_ci_job_metadata")
        name = raw_job.get("name")
        required = raw_job.get("required")
        status = raw_job.get("status")
        conclusion = raw_job.get("conclusion")
        steps = raw_job.get("steps_executed")
        logs_available = raw_job.get("logs_available")
        required_check_status = raw_job.get("required_check_status")
        runner_id = raw_job.get("runner_id")
        runner_name = raw_job.get("runner_name")
        if (
            not isinstance(name, str) or not name.strip() or not isinstance(required, bool)
            or status not in CI_EVIDENCE_RUN_STATUSES or conclusion not in CI_EVIDENCE_CONCLUSIONS
            or not isinstance(steps, int) or isinstance(steps, bool) or steps < 0
            or not isinstance(logs_available, bool)
            or required_check_status not in CI_EVIDENCE_CHECK_STATUSES
        ):
            return _ci_evidence_error("invalid_ci_job_fields")
        if name.strip() in seen_job_names:
            return _ci_evidence_error("duplicate_ci_job_name")
        seen_job_names.add(name.strip())
        if runner_id is not None and (not isinstance(runner_id, int) or isinstance(runner_id, bool) or runner_id < 0):
            return _ci_evidence_error("invalid_ci_runner_id")
        if runner_name is not None and not isinstance(runner_name, str):
            return _ci_evidence_error("invalid_ci_runner_name")
        normalized_jobs.append({
            "name": name.strip(),
            "required": required,
            "status": status,
            "conclusion": conclusion,
            "runner_id": runner_id,
            "runner_name_present": bool(runner_name and runner_name.strip()),
            "steps_executed": steps,
            "logs_available": logs_available,
            "required_check_status": required_check_status,
        })
    if any(job["required"] != (job["name"] in required_jobs) for job in normalized_jobs):
        return _ci_evidence_error("ci_job_required_flag_mismatch")
    return {
        "evidence_format": CI_EVIDENCE_SCHEMA,
        "run_status": run_status,
        "run_conclusion": run_conclusion,
        "required_jobs": required_jobs,
        "jobs": normalized_jobs,
    }, None


def _ci_evidence_snapshot(ci_result: Mapping[str, Any]) -> dict[str, Any]:
    jobs: list[dict[str, Any]] = []
    expected_jobs = set(ci_result["required_jobs"])
    observed_jobs = {job["name"] for job in ci_result["jobs"]}
    for job in ci_result["jobs"]:
        runner_assigned = job["runner_id"] is not None and job["runner_id"] > 0
        if not runner_assigned:
            job_status, reason = "unavailable", "runner_unassigned"
        elif job["steps_executed"] == 0:
            job_status, reason = "unavailable", "ci_report_has_no_executed_steps"
        elif not job["logs_available"]:
            job_status, reason = "unavailable", "ci_logs_unavailable"
        elif job["status"] != "completed":
            job_status, reason = "unavailable", "ci_job_not_completed"
        elif job["conclusion"] != "success" or job["required_check_status"] != "success":
            job_status, reason = "failed", "ci_required_check_failed"
        else:
            job_status, reason = "passed", "observed_ci_success"
        jobs.append({
            "name": job["name"],
            "required": job["required"],
            "status": job_status,
            "conclusion": job["conclusion"],
            "required_check_status": job["required_check_status"],
            "runner_assigned": runner_assigned,
            "steps_executed": job["steps_executed"],
            "logs_available": job["logs_available"],
            "reason": reason,
        })
    for missing_name in sorted(expected_jobs - observed_jobs):
        jobs.append({
            "name": missing_name,
            "required": True,
            "status": "unavailable",
            "conclusion": "pending",
            "required_check_status": "pending",
            "runner_assigned": False,
            "steps_executed": 0,
            "logs_available": False,
            "reason": "required_ci_job_missing",
        })
    required_jobs = [job for job in jobs if job["required"]]
    executed_steps = sum(job["steps_executed"] for job in required_jobs)
    failure_classes = {
        CLASS_FAILURE_ORIGIN_UNVERIFIED
        for job in required_jobs
        if job["status"] == "failed"
    }
    if any(job["status"] == "unavailable" for job in required_jobs):
        failure_classes.add(CLASS_CI_UNAVAILABLE)
    if ci_result["run_status"] != "completed":
        status, reason, classification = "unavailable", "ci_run_not_completed", CLASS_CI_UNAVAILABLE
    elif any(job["status"] == "unavailable" for job in required_jobs):
        status, reason, classification = "unavailable", "required_ci_evidence_unavailable", CLASS_CI_UNAVAILABLE
    elif ci_result["run_conclusion"] != "success" or any(job["status"] == "failed" for job in required_jobs):
        status, reason, classification = "failed", "required_ci_check_failed", CLASS_FAILURE_ORIGIN_UNVERIFIED
    else:
        status, reason, classification = "passed", "observed_ci_success", CLASS_PASS
    return {
        "status": status,
        "reason": reason,
        "executed_steps": executed_steps,
        "classification": classification,
        "run_status": ci_result["run_status"],
        "run_conclusion": ci_result["run_conclusion"],
        "jobs": jobs,
        "required_jobs": sorted(expected_jobs),
        "failure_classes": sorted(failure_classes),
    }


def _ci_snapshot(ci_result: Mapping[str, Any] | None) -> dict[str, Any]:
    if not ci_result:
        return {"status": "unavailable", "reason": "external_ci_not_queried", "executed_steps": 0, "classification": "ci_unavailable"}
    if ci_result.get("evidence_format") == CI_EVIDENCE_SCHEMA:
        return _ci_evidence_snapshot(ci_result)
    try:
        status = str(ci_result.get("status", "")).casefold()
        steps = int(ci_result.get("executed_steps", 0) or 0)
    except (AttributeError, TypeError, ValueError):
        return {"status": "unavailable", "reason": "malformed_ci_evidence", "executed_steps": 0, "classification": CLASS_MALFORMED_CONFIGURATION}
    if status == "malformed":
        return {"status": "malformed", "reason": ci_result.get("reason", "malformed_ci_evidence"), "executed_steps": 0, "classification": CLASS_MALFORMED_CONFIGURATION}
    if status == "success" and steps > 0:
        return {"status": "passed", "reason": "injected_ci_evidence", "executed_steps": steps, "classification": CLASS_PASS}
    if status == "failure" and steps > 0:
        return {"status": "failed", "reason": "injected_ci_evidence", "executed_steps": steps, "classification": CLASS_FAILURE_ORIGIN_UNVERIFIED}
    return {"status": "unavailable", "reason": "ci_report_has_no_executed_steps", "executed_steps": steps, "classification": "ci_unavailable"}


def _timestamp_status(generated_at: str | None) -> tuple[bool, str | None]:
    if generated_at is None:
        return False, None
    try:
        parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return False, "invalid_generated_at"
    return parsed.tzinfo is not None, None if parsed.tzinfo is not None else "generated_at_requires_timezone"


def _baseline_statuses(baseline_report: Mapping[str, Any] | None) -> dict[str, str]:
    """Extract only check statuses from an operator-supplied baseline report."""
    if not isinstance(baseline_report, Mapping):
        return {}
    raw_checks = baseline_report.get("checks", baseline_report)
    if isinstance(raw_checks, list):
        entries = ((item.get("name"), item) for item in raw_checks if isinstance(item, Mapping))
    elif isinstance(raw_checks, Mapping):
        entries = raw_checks.items()
    else:
        return {}
    statuses: dict[str, str] = {}
    for name, value in entries:
        if not isinstance(name, str):
            continue
        status = value if isinstance(value, str) else value.get("status") if isinstance(value, Mapping) else None
        if isinstance(status, str) and status:
            statuses[name] = status
    return statuses


def _classify_check(item: dict[str, Any], *, baseline_statuses: Mapping[str, str], changed_paths: list[str]) -> str:
    status = item.get("status")
    if status == "passed":
        return CLASS_PASS
    if status == "malformed":
        return CLASS_MALFORMED_CONFIGURATION
    if status == "timed_out":
        return CLASS_TIMEOUT
    if status == "collection_failed":
        if (item.get("summary") or {}).get("dependency_error"):
            return CLASS_UNAVAILABLE_DEPENDENCY
        return CLASS_COLLECTION_FAILED
    if status == "unavailable":
        reason = str(item.get("reason") or "")
        if "depend" in reason or (item.get("summary") or {}).get("dependency_error") or (item.get("name") == "typed" and any(isinstance(child, Mapping) and child.get("status") == "unavailable" for child in item.get("subchecks", []))) or (item.get("name") == "frontend" and any(isinstance(child, Mapping) and child.get("status") == "unavailable" for child in item.get("checks", []))):
            return CLASS_UNAVAILABLE_DEPENDENCY
        return CLASS_MISSING_TOOL
    if status == "blocked":
        return "blocked"
    if status == "failed":
        if item.get("name") == "frontend" and any(
            isinstance(child, Mapping) and child.get("status") == "blocked"
            for child in item.get("checks", [])
        ):
            return "blocked"
        if item.get("name") == "security":
            if (item.get("summary") or {}).get("finding_count"):
                return CLASS_SECURITY_FINDING
            return CLASS_SECURITY_SCANNER_FAILURE
        if item.get("name") == "diff_check":
            return CLASS_DIFF_FAILURE
        if (item.get("summary") or {}).get("dependency_error"):
            return CLASS_UNAVAILABLE_DEPENDENCY
        baseline_status = baseline_statuses.get(str(item.get("name")))
        if baseline_status == "failed":
            return CLASS_PRE_EXISTING_FAILURE
        if baseline_status in {"passed", "not_configured"} and _changed_scope_supports_check(str(item.get("name")), changed_paths):
            return CLASS_CHANGED_SCOPE_FAILURE
        return CLASS_FAILURE_ORIGIN_UNVERIFIED
    return str(status or "not_run")


def _changed_scope_supports_check(name: str, changed_paths: list[str]) -> bool:
    """Only attribute failures to changed scope when the path types support it."""
    base_name = name.split(":", 1)[0]
    paths = [path.casefold() for path in changed_paths]
    if base_name in {"compile", "pytest", "ruff", "typed"}:
        return any(path.endswith((".py", ".pyi")) or path in {"pyproject.toml", "pytest.ini"} for path in paths)
    if base_name == "frontend":
        return any(path.startswith("frontend/") for path in paths)
    if base_name == "security":
        return any(not path.startswith(("docs/", "tests/")) for path in paths)
    if base_name == "diff_check":
        return bool(paths)
    return False


def _annotate_check_classes(checks: list[dict[str, Any]], *, baseline_statuses: Mapping[str, str], changed_paths: list[str]) -> list[str]:
    classes: list[str] = []
    for item in checks:
        classification = _classify_check(item, baseline_statuses=baseline_statuses, changed_paths=changed_paths)
        item["classification"] = classification
        item["evidence_classification"] = "observed" if item.get("execution_status") in {"executed", "timed_out"} else "not_observed"
        item["failure_origin"] = classification if classification in {CLASS_CHANGED_SCOPE_FAILURE, CLASS_PRE_EXISTING_FAILURE, CLASS_FAILURE_ORIGIN_UNVERIFIED} else None
        classes.append(classification)
        for child in item.get("checks", []):
            if isinstance(child, dict):
                child_classification = _classify_check(child, baseline_statuses=baseline_statuses, changed_paths=changed_paths)
                child["classification"] = child_classification
                child["evidence_classification"] = "observed" if child.get("execution_status") in {"executed", "timed_out"} else "not_observed"
                child["failure_origin"] = child_classification if child_classification in {CLASS_CHANGED_SCOPE_FAILURE, CLASS_PRE_EXISTING_FAILURE, CLASS_FAILURE_ORIGIN_UNVERIFIED} else None
                classes.append(child_classification)
    return classes


def run_quality_gate(
    root: Path = REPOSITORY_ROOT,
    *,
    generated_at: str | None = None,
    execute: bool = False,
    changed_paths: list[str] | None = None,
    ci_result: Mapping[str, Any] | None = None,
    baseline_report: Mapping[str, Any] | None = None,
    baseline_error: str | None = None,
    ci_evidence_error: str | None = None,
    phase: str = "final",
    runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Run fixed local checks while preserving evidence boundaries.

    Command output is parsed transiently into counts and presence flags. No raw
    stdout, stderr, environment, credentials, network, or repair state is
    included in the returned report.
    """
    root = Path(root).resolve()
    paths = normal_paths(changed_paths if changed_paths is not None else changed_from_git(root))
    toolchain = _toolchain_snapshot(root)
    pyproject, pyproject_error = _read_pyproject(root)
    dependencies = _dependency_snapshot(root)
    typed = _typed_configuration(root, pyproject)
    timestamp_injected, timestamp_error = _timestamp_status(generated_at)
    configuration_errors: list[str] = []
    if pyproject_error and pyproject_error != "missing":
        configuration_errors.append(f"{pyproject_error}:pyproject.toml")
    if timestamp_error:
        configuration_errors.append(timestamp_error)
    if execute and not timestamp_injected:
        configuration_errors.append("timestamp_not_injected")
    if baseline_error:
        configuration_errors.append(baseline_error)
    if ci_evidence_error:
        configuration_errors.append(ci_evidence_error)
    if phase not in QUALITY_GATE_PHASES:
        configuration_errors.append("invalid_quality_gate_phase")
    if phase == "preflight" and ci_result is not None:
        configuration_errors.append("preflight_ci_evidence_forbidden")

    checks = [
        _check_command("compile", [sys.executable, "-m", "compileall", "-q", "."], root=root, execute=execute, runner=runner),
        _check_command("pytest", [sys.executable, "-m", "pytest", "-q"], root=root, execute=execute, runner=runner),
        _check_command("ruff", ["ruff", "check", "."], root=root, execute=execute, tool="ruff", runner=runner),
        _typed_check(root, typed, execute=execute, runner=runner),
        _frontend_check(root, execute=execute, runner=runner),
        _security_check(root, execute=execute, runner=runner),
        _check_command("diff_check", ["git", "diff", "--check"], root=root, execute=execute, runner=runner),
    ]
    for item in checks:
        if item.get("status") == "malformed":
            configuration_errors.append(f"malformed:{item.get('name')}")
    baseline_statuses = _baseline_statuses(baseline_report)
    check_classes = _annotate_check_classes(checks, baseline_statuses=baseline_statuses, changed_paths=paths)
    local_failure_classes = {
        value for value in check_classes if value not in {CLASS_PASS, "not_configured", "not_run"}
    }
    ci = _ci_snapshot(ci_result)
    failure_classes = set(local_failure_classes)
    failure_classes.update(ci.get("failure_classes", []))
    if ci["classification"] != CLASS_PASS:
        failure_classes.add(ci["classification"])
    failure_classes = sorted(failure_classes)
    git = _git_state(root)
    warnings = list(toolchain["findings"])
    if dependencies["lockfile_status"] == "missing":
        warnings.append("lockfile_missing")
    if dependencies["unpinned_requirement_count"]:
        warnings.append("unpinned_requirements_present")
    if dependencies["status"] == "incomplete" and "lockfile_missing" not in warnings:
        warnings.append("dependency_state_incomplete")
    if git["status"] in {"dirty", "not_a_git_repository"}:
        warnings.append(f"git_state:{git['status']}")
    warnings = sorted(set(warnings))

    statuses = {check["status"] for check in checks}
    if configuration_errors:
        local_status, local_exit_code = "configuration_error", EXIT_CONFIGURATION
    elif not execute:
        local_status, local_exit_code = "not_run", EXIT_UNAVAILABLE
    elif {"failed", "timed_out", "collection_failed"} & statuses or "blocked" in statuses:
        local_status, local_exit_code = "failed", EXIT_FAILED
    elif "unavailable" in statuses:
        local_status, local_exit_code = "unavailable", EXIT_UNAVAILABLE
    elif warnings:
        local_status, local_exit_code = "passed_with_warnings", EXIT_PASSED
    else:
        local_status, local_exit_code = "passed", EXIT_PASSED

    if configuration_errors:
        status, final_exit_code = "configuration_error", EXIT_CONFIGURATION
    elif not execute:
        status, final_exit_code = "not_run", EXIT_UNAVAILABLE
    elif local_status == "failed" or ci["status"] == "failed":
        status, final_exit_code = "failed", EXIT_FAILED
    elif local_status == "unavailable" or ci["status"] == "unavailable":
        status, final_exit_code = "unavailable", EXIT_UNAVAILABLE
    else:
        status, final_exit_code = local_status, local_exit_code

    if configuration_errors:
        classification = CLASS_MALFORMED_CONFIGURATION
    elif not execute:
        classification = CLASS_CI_UNAVAILABLE if ci["status"] == "unavailable" else "not_run"
    elif failure_classes:
        priority = (
            CLASS_MALFORMED_CONFIGURATION, CLASS_SECURITY_FINDING, CLASS_SECURITY_SCANNER_FAILURE,
            CLASS_DIFF_FAILURE, CLASS_TIMEOUT, CLASS_COLLECTION_FAILED,
            CLASS_CHANGED_SCOPE_FAILURE, CLASS_PRE_EXISTING_FAILURE,
            CLASS_FAILURE_ORIGIN_UNVERIFIED, CLASS_MISSING_TOOL,
            CLASS_UNAVAILABLE_DEPENDENCY, CLASS_CI_UNAVAILABLE, "blocked",
        )
        if local_failure_classes:
            classification = next((value for value in priority if value in local_failure_classes), sorted(local_failure_classes)[0])
        elif ci["classification"] == CLASS_CI_UNAVAILABLE:
            classification = CLASS_CI_UNAVAILABLE
        else:
            classification = next((value for value in priority if value in failure_classes), sorted(failure_classes)[0])
    else:
        classification = CLASS_PASS
    ready = (
        phase == "final" and execute and status == "passed" and git["status"] == "clean"
        and ci["status"] == "passed"
    )
    preflight = {
        "status": local_status,
        "exit_code": local_exit_code,
        "ready_for_supervised_use": False,
    }
    exit_code = local_exit_code if phase == "preflight" else final_exit_code
    return {
        "schema": QUALITY_GATE_SCHEMA,
        "generated_at": generated_at,
        "timestamp_injected": timestamp_injected,
        "mode": "preflight_execution" if execute and phase == "preflight" else "real_execution" if execute else "dry_run",
        "phase": phase,
        "status": status,
        "classification": classification,
        "failure_classes": failure_classes,
        "exit_code": exit_code,
        "ready_for_supervised_use": ready,
        "preflight": preflight,
        "changed_files": paths,
        "toolchain": toolchain,
        "dependencies": dependencies,
        "typed_analysis": typed,
        "checks": checks,
        "check_order": list(CHECK_ORDER),
        "status_taxonomy": list(CHECK_STATUS_TAXONOMY),
        "frontend_check_order": list(FRONTEND_CHECK_ORDER),
        "ci": ci,
        "baseline": {"provided": baseline_report is not None, "check_statuses": dict(sorted(baseline_statuses.items()))},
        "git_state": git,
        "warnings": warnings,
        "configuration_errors": sorted(set(configuration_errors)),
        "safety": {
            "network_used": False, "provider_calls": False, "credentials_read": False,
            "raw_stdout_persisted": False, "raw_stderr_persisted": False,
            "environment_values_persisted": False, "automatic_repair": False,
            "merge_or_publish": False,
        },
        "operator_action": (
            "supply complete sanitized CIEvidence.v1 to run final attestation; preflight success is not merge evidence"
            if phase == "preflight" and local_exit_code == EXIT_PASSED
            else "run with --execute and an injected timezone-aware --generated-at after resolving unavailable or failed checks"
            if not ready
            else "human review may proceed; inspect the report and CI evidence before merging"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-git", action="store_true", help="include changed/untracked paths from local git state")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--diff-file", help="synthetic or saved diff content for deterministic review")
    parser.add_argument("--branch", default="local")
    parser.add_argument("--repository", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--execute", action="store_true", help="run fixed local checks instead of only reporting their plan")
    parser.add_argument("--phase", choices=("final", "preflight"), default="final", help="final attestation or local preflight")
    parser.add_argument("--generated-at", help="timezone-aware ISO timestamp injected by the caller")
    parser.add_argument("--ci-status", choices=("success", "failure", "unavailable"), help="optional external CI result; never queried by this tool")
    parser.add_argument("--ci-steps", type=int, default=0, help="executed-step count accompanying --ci-status")
    parser.add_argument("--ci-evidence-file", type=Path, help="local sanitized CI metadata JSON; never queries GitHub or reads logs")
    parser.add_argument("--baseline-file", help="optional JSON baseline report used to classify pre-existing failures")
    parser.add_argument("--json", action="store_true"); parser.add_argument("--markdown", action="store_true"); parser.add_argument("--output")
    args = parser.parse_args(argv)
    if args.json and args.markdown: parser.error("choose --json or --markdown")
    paths = list(args.changed_file) + (changed_from_git(args.repository) if args.from_git else [])
    if args.ci_status is not None and args.ci_evidence_file is not None:
        parser.error("choose --ci-status or --ci-evidence-file")
    if args.phase == "preflight" and not args.execute:
        parser.error("--phase preflight requires --execute")
    if args.phase == "preflight" and (args.ci_status is not None or args.ci_evidence_file is not None):
        parser.error("--phase preflight does not accept final CI evidence")
    ci_evidence_error = None
    if args.ci_evidence_file is not None:
        ci_result, ci_evidence_error = load_ci_evidence(args.ci_evidence_file)
    else:
        ci_result = None if args.ci_status is None else {"status": args.ci_status, "executed_steps": args.ci_steps}
    baseline_report = None
    baseline_error = None
    if args.baseline_file:
        try:
            baseline_report = json.loads(Path(args.baseline_file).read_text(encoding="utf-8"))
            if not isinstance(baseline_report, Mapping):
                baseline_report = None
                baseline_error = "malformed_baseline"
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            baseline_error = "malformed_baseline"
    report = run_quality_gate(
        args.repository,
        generated_at=args.generated_at,
        execute=args.execute,
        changed_paths=paths,
        ci_result=ci_result,
        baseline_report=baseline_report,
        baseline_error=baseline_error,
        ci_evidence_error=ci_evidence_error,
        phase=args.phase,
    )
    report["planning_summary"] = run(paths, diff_text=_diff_text(args.diff_file, args.repository), branch=args.branch)
    content = render_json_or_markdown(report, markdown=args.markdown, title="MarketOS local quality gate")
    write_optional_output(content, args.output); print(content, end="")
    return int(report["exit_code"])


if __name__ == "__main__": raise SystemExit(main())

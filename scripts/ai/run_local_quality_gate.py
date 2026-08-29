"""Run deterministic, local-only MarketOS agentic quality gates in one command."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
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
    from .operating_layer import ROOT, changed_from_git, git_lines, normal_paths, render_json_or_markdown, write_optional_output
except ImportError:  # pragma: no cover - direct script execution
    import ci_matrix_plan, impact_planner, phase_gate, pr_readiness_report, select_tests
    from operating_layer import ROOT, changed_from_git, git_lines, normal_paths, render_json_or_markdown, write_optional_output


QUALITY_GATE_SCHEMA = "MarketOS.LocalQualityGate.v2"
NOT_INJECTED = "not_injected"
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
CLASS_TIMEOUT = "timeout"
CLASS_MALFORMED_CONFIGURATION = "malformed_configuration"

CHECK_ORDER = ("compile", "pytest", "ruff", "typed", "frontend", "security", "diff_check")
FRONTEND_CHECK_ORDER = ("lint", "typecheck", "test", "build")
KNOWN_LOCKFILES = (
    "uv.lock",
    "poetry.lock",
    "Pipfile.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
)
SAFE_FRONTEND_TOKENS = (
    "eslint",
    "jest",
    "tsc",
    "vite",
    "vitest",
    "webpack",
)
UNSAFE_FRONTEND_MARKERS = (
    "curl",
    "docker",
    "git ",
    "invoke-webrequest",
    "npm install",
    "pnpm add",
    "pnpm install",
    "publish",
    "scp ",
    "secret",
    "ssh ",
    "token",
    "wget",
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
RUFF_FINDING_RE = re.compile(r"(?:^|\s)[A-Z]\d{3}(?:\s|$)")


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


def _diff_text(path: str | None) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "HEAD"],
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
    path = root / ".python-version"
    text = _read_text(path)
    if text is None:
        return None, "missing"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1 or _version_pair(lines[0]) is None:
        return None, "malformed"
    return lines[0], "valid"


def _read_pyproject(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    path = root / "pyproject.toml"
    text = _read_text(path)
    if text is None:
        return None, "missing"
    try:
        return tomllib.loads(text), None
    except tomllib.TOMLDecodeError:
        return None, "malformed"


def _toolchain_snapshot(root: Path) -> dict[str, Any]:
    python_version, python_file_status = _read_python_version(root)
    pyproject, pyproject_error = _read_pyproject(root)

    docker_versions: set[str] = set()
    for dockerfile in sorted(root.glob("Dockerfile*")):
        if dockerfile.is_file():
            text = _read_text(dockerfile) or ""
            docker_versions.update(DOCKER_PYTHON_RE.findall(text))

    ci_versions: set[str] = set()
    workflow_root = root / ".github" / "workflows"
    if workflow_root.is_dir():
        for workflow in sorted(workflow_root.glob("*.y*ml")):
            text = _read_text(workflow) or ""
            ci_versions.update(PYTHON_VERSION_RE.findall(text))

    ruff_target = None
    if pyproject:
        ruff_target = pyproject.get("tool", {}).get("ruff", {}).get("target-version")
    issues: list[str] = []
    if python_file_status == "missing":
        issues.append("missing:.python-version")
    elif python_file_status == "malformed":
        issues.append("malformed:.python-version")
    if pyproject_error:
        issues.append(f"{pyproject_error}:pyproject.toml")

    selected_pair = (sys.version_info.major, sys.version_info.minor)
    declared_pair = _version_pair(python_version)
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
    ruff_pair = (int(ruff_match.group(1)[0]), int(ruff_match.group(1)[1:])) if ruff_match and len(ruff_match.group(1)) >= 2 else None
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
                lockfiles.append(str((Path("frontend") / name) if base.name == "frontend" else Path(name)))

    unpinned = 0
    for manifest in root.glob("requirements*.txt"):
        text = _read_text(manifest) or ""
        for line in text.splitlines():
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
        mypy_configured = mypy_configured or bool(pyproject.get("tool", {}).get("mypy"))
        pyright_configured = pyright_configured or bool(pyproject.get("tool", {}).get("pyright"))
    tools = []
    if mypy_configured:
        tools.append("mypy")
    if pyright_configured:
        tools.append("pyright")
    return {"configured_tools": tools, "status": "configured" if tools else "not_configured"}


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
    display: list[str] = []
    for index, value in enumerate(command):
        if index == 0 and Path(value).is_absolute():
            display.append(f"<{Path(value).name}>")
        else:
            display.append(value)
    return display


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
        return summary
    if name == "ruff":
        # Ruff's default formatter puts the diagnostic code at the beginning
        # of a line, while concise output includes file coordinates first.
        # Count both formats so a failed run cannot look like zero findings.
        finding_count = sum(1 for line in combined.splitlines() if RUFF_FINDING_RE.search(line))
        return {"finding_count": finding_count}
    if name == "security":
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return {"finding_count": None, "error_count": 1, "output_parse": "invalid_json"}
        return {
            "finding_count": len(payload.get("results", [])),
            "error_count": len(payload.get("errors", [])),
            "output_parse": "valid_json",
        }
    return {"return_code": returncode}


def _invoke_local(command: list[str], root: Path, runner: CommandRunner | None) -> Any:
    if runner is not None:
        return runner(command, root)
    return subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        shell=False,
        timeout=900,
    )


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
    actual_command = command if tool is None else prefix + command[1:] if command and command[0] == tool and prefix else command
    result: dict[str, Any] = {
        "name": name,
        "command": _display_command(actual_command),
        "tool": tool,
        "availability": "available" if available else "missing",
        "status": "not_run" if not execute else "missing" if not available else "pending",
    }
    if not execute or not available:
        if execute and not available:
            result["reason"] = "required_tool_missing"
        return result
    try:
        completed = _invoke_local(actual_command, root, runner)
    except (FileNotFoundError, OSError):
        result.update({"status": "missing", "availability": "missing", "reason": "tool_invocation_failed"})
        return result
    except subprocess.TimeoutExpired:
        result.update({"status": "failed", "reason": "timeout"})
        return result

    stdout = str(getattr(completed, "stdout", "") or "")
    stderr = str(getattr(completed, "stderr", "") or "")
    returncode = int(getattr(completed, "returncode", 1))
    summary = _command_summary(name, stdout, stderr, returncode)
    status = "passed" if returncode == 0 else "failed"
    if semantic_failure and semantic_failure(summary):
        status = "failed"
    result.update(
        {
            "status": status,
            "exit_code": returncode,
            "summary": summary,
            "stdout_present": bool(stdout),
            "stderr_present": bool(stderr),
        }
    )
    return result


def _typed_check(root: Path, typed: dict[str, Any], *, execute: bool, runner: CommandRunner | None) -> dict[str, Any]:
    tools = typed["configured_tools"]
    if not tools:
        return {"name": "typed", "status": "not_configured", "availability": "not_applicable", "subchecks": []}
    subchecks = [
        _check_command(
            f"typed:{tool}",
            [tool, "."],
            root=root,
            execute=execute,
            tool=tool,
            runner=runner,
        )
        for tool in tools
    ]
    statuses = {item["status"] for item in subchecks}
    if "failed" in statuses:
        status = "failed"
    elif "missing" in statuses:
        status = "missing"
    elif not execute:
        status = "not_run"
    else:
        status = "passed"
    availability = "missing" if "missing" in statuses else "available"
    return {"name": "typed", "status": status, "availability": availability, "subchecks": subchecks}


def _safe_frontend_script(script: Any) -> bool:
    if not isinstance(script, str):
        return False
    lowered = script.casefold()
    return any(token in lowered for token in SAFE_FRONTEND_TOKENS) and not any(marker in lowered for marker in UNSAFE_FRONTEND_MARKERS)


def _frontend_check(root: Path, *, execute: bool, runner: CommandRunner | None) -> dict[str, Any]:
    frontend = root / "frontend"
    package_path = frontend / "package.json"
    if not package_path.is_file():
        return {"name": "frontend", "status": "not_configured", "manifest_status": "missing", "checks": []}
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"name": "frontend", "status": "malformed", "manifest_status": "malformed", "checks": []}
    scripts = package.get("scripts", {})
    if not isinstance(scripts, dict):
        return {"name": "frontend", "status": "malformed", "manifest_status": "malformed", "checks": []}

    lockfile = next((name for name in KNOWN_LOCKFILES[3:] if (frontend / name).is_file()), None)
    manager = "pnpm" if lockfile == "pnpm-lock.yaml" else "yarn" if lockfile == "yarn.lock" else "bun" if lockfile in {"bun.lock", "bun.lockb"} else "npm"
    manager_available = _tool_prefix(manager) is not None
    dependencies_available = (frontend / "node_modules").is_dir()
    checks: list[dict[str, Any]] = []
    for script_name in FRONTEND_CHECK_ORDER:
        script = scripts.get(script_name)
        if script is None:
            checks.append({"name": f"frontend:{script_name}", "status": "not_configured", "availability": "not_applicable"})
            continue
        command = [manager, "run", script_name]
        if not execute:
            checks.append({"name": f"frontend:{script_name}", "command": _display_command(command), "status": "not_run", "availability": "available" if manager_available else "missing"})
        elif not manager_available:
            checks.append({"name": f"frontend:{script_name}", "command": _display_command(command), "status": "missing", "availability": "missing", "reason": "package_manager_missing"})
        elif not dependencies_available:
            checks.append({"name": f"frontend:{script_name}", "command": _display_command(command), "status": "unavailable", "availability": "available", "reason": "dependencies_not_installed_network_not_attempted"})
        elif not _safe_frontend_script(script):
            checks.append({"name": f"frontend:{script_name}", "command": _display_command(command), "status": "blocked", "availability": "available", "reason": "script_not_in_local_allowlist"})
        else:
            checks.append(_check_command(f"frontend:{script_name}", command, root=frontend, execute=True, tool=manager, runner=runner))

    configured = [item for item in checks if item["status"] != "not_configured"]
    statuses = {item["status"] for item in configured}
    if "blocked" in statuses or "failed" in statuses:
        status = "failed"
    elif "missing" in statuses or "unavailable" in statuses:
        status = "unavailable"
    elif not configured:
        status = "not_configured"
    elif not execute:
        status = "not_run"
    else:
        status = "passed"
    return {
        "name": "frontend",
        "status": status,
        "manifest_status": "valid",
        "package_manager": manager,
        "package_manager_available": manager_available,
        "lockfile": lockfile,
        "lockfile_status": "present" if lockfile else "missing",
        "dependencies_status": "installed" if dependencies_available else "missing",
        "checks": checks,
    }


def _security_check(root: Path, *, execute: bool, runner: CommandRunner | None) -> dict[str, Any]:
    config = root / "semgrep" / "ai-safety.yml"
    if not config.is_file():
        return {"name": "security", "status": "not_configured", "availability": "not_applicable"}
    command = [sys.executable, "scripts/ai/run_semgrep_policy.py", "--json"]
    return _check_command(
        "security",
        command,
        root=root,
        execute=execute,
        tool="semgrep",
        runner=runner,
        semantic_failure=lambda summary: bool(summary.get("finding_count") or summary.get("error_count")),
    )


def _ci_snapshot(ci_result: Mapping[str, Any] | None) -> dict[str, Any]:
    if not ci_result:
        return {"status": "unavailable", "reason": "external_ci_not_queried", "executed_steps": 0, "classification": CLASS_CI_UNAVAILABLE}
    status = str(ci_result.get("status", "")).casefold()
    steps = int(ci_result.get("executed_steps", 0) or 0)
    if status == "success" and steps > 0:
        return {"status": "passed", "reason": "injected_ci_evidence", "executed_steps": steps, "classification": CLASS_PASS}
    if status == "failure" and steps > 0:
        return {"status": "failed", "reason": "injected_ci_evidence", "executed_steps": steps, "classification": CLASS_FAILURE_ORIGIN_UNVERIFIED}
    return {"status": "unavailable", "reason": "ci_report_has_no_executed_steps", "executed_steps": steps, "classification": CLASS_CI_UNAVAILABLE}


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
    if status == "missing":
        return CLASS_MISSING_TOOL
    if status == "unavailable":
        if item.get("name") == "frontend" and any(child.get("status") == "unavailable" for child in item.get("checks", [])):
            return CLASS_UNAVAILABLE_DEPENDENCY
        return CLASS_MISSING_TOOL
    if status == "blocked":
        return "blocked"
    if status == "failed":
        if item.get("reason") == "timeout":
            return CLASS_TIMEOUT
        if item.get("name") == "security" and (item.get("summary") or {}).get("finding_count"):
            return CLASS_SECURITY_FINDING
        baseline_status = baseline_statuses.get(str(item.get("name")))
        if baseline_status == "failed":
            return CLASS_PRE_EXISTING_FAILURE
        if baseline_status in {"passed", "not_configured"} and changed_paths:
            return CLASS_CHANGED_SCOPE_FAILURE
        return CLASS_FAILURE_ORIGIN_UNVERIFIED
    return str(status or "not_run")


def _annotate_check_classes(checks: list[dict[str, Any]], *, baseline_statuses: Mapping[str, str], changed_paths: list[str]) -> list[str]:
    classes: list[str] = []
    for item in checks:
        classification = _classify_check(item, baseline_statuses=baseline_statuses, changed_paths=changed_paths)
        item["classification"] = classification
        classes.append(classification)
        for child in item.get("checks", []):
            if isinstance(child, dict):
                child_classification = _classify_check(child, baseline_statuses=baseline_statuses, changed_paths=changed_paths)
                child["classification"] = child_classification
                classes.append(child_classification)
    return sorted(set(classes))


def _timestamp_status(generated_at: str | None) -> tuple[bool, str | None]:
    if generated_at is None:
        return False, None
    try:
        parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return True, "invalid_generated_at"
    return parsed.tzinfo is not None, None if parsed.tzinfo is not None else "generated_at_requires_timezone"


def run_quality_gate(
    root: Path = REPOSITORY_ROOT,
    *,
    generated_at: str | None = None,
    execute: bool = False,
    changed_paths: list[str] | None = None,
    ci_result: Mapping[str, Any] | None = None,
    baseline_report: Mapping[str, Any] | None = None,
    baseline_error: str | None = None,
    runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Discover and optionally execute the existing local quality checks.

    Commands are a fixed local allowlist. The runner and timestamp are injectable
    so tests and operators can replay the same report without network or live CI.
    Command output is parsed into counts and presence flags; raw stdout/stderr and
    environment values are never included in the returned report.
    """
    root = Path(root).resolve()
    paths = normal_paths(changed_paths if changed_paths is not None else changed_from_git(root))
    toolchain = _toolchain_snapshot(root)
    pyproject, pyproject_error = _read_pyproject(root)
    dependencies = _dependency_snapshot(root)
    typed = _typed_configuration(root, pyproject)
    timestamp_injected, timestamp_error = _timestamp_status(generated_at)
    configuration_errors = list(toolchain["findings"] if any(item.startswith("malformed:") for item in toolchain["findings"]) else [])
    if pyproject_error and pyproject_error != "missing":
        configuration_errors.append(f"{pyproject_error}:pyproject.toml")
    if timestamp_error:
        configuration_errors.append(timestamp_error)
    if execute and not timestamp_injected:
        configuration_errors.append("timestamp_not_injected")
    if baseline_error:
        configuration_errors.append(baseline_error)

    checks: list[dict[str, Any]] = [
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
    check_classifications = _annotate_check_classes(checks, baseline_statuses=baseline_statuses, changed_paths=paths)
    ci = _ci_snapshot(ci_result)
    failure_classes = {
        classification
        for classification in check_classifications
        if classification not in {CLASS_PASS, "not_configured", "not_run"}
    }
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
        status, exit_code = "configuration_error", EXIT_CONFIGURATION
    elif not execute:
        status, exit_code = "dry_run", EXIT_PASSED
    elif "failed" in statuses or "blocked" in statuses:
        status, exit_code = "failed", EXIT_FAILED
    elif "missing" in statuses or "unavailable" in statuses or ci["status"] == "unavailable":
        status, exit_code = "unavailable", EXIT_UNAVAILABLE
    elif ci["status"] == "failed":
        status, exit_code = "failed", EXIT_FAILED
    elif warnings:
        status, exit_code = "passed_with_warnings", EXIT_PASSED
    else:
        status, exit_code = "passed", EXIT_PASSED

    ready = execute and status == "passed" and git["status"] == "clean" and ci["status"] == "passed"
    if configuration_errors:
        classification = CLASS_MALFORMED_CONFIGURATION
    elif not execute:
        classification = CLASS_PASS
    elif failure_classes:
        priority = (
            CLASS_MALFORMED_CONFIGURATION,
            CLASS_TIMEOUT,
            CLASS_SECURITY_FINDING,
            CLASS_CHANGED_SCOPE_FAILURE,
            CLASS_PRE_EXISTING_FAILURE,
            CLASS_FAILURE_ORIGIN_UNVERIFIED,
            CLASS_MISSING_TOOL,
            CLASS_UNAVAILABLE_DEPENDENCY,
            CLASS_CI_UNAVAILABLE,
            "blocked",
            CLASS_PASS,
        )
        classification = next((value for value in priority if value in failure_classes), failure_classes[0])
    else:
        classification = CLASS_PASS
    return {
        "schema": QUALITY_GATE_SCHEMA,
        "generated_at": generated_at,
        "timestamp_injected": timestamp_injected,
        "mode": "real_execution" if execute else "dry_run",
        "status": status,
        "classification": classification,
        "failure_classes": failure_classes,
        "exit_code": exit_code,
        "ready_for_supervised_use": ready,
        "changed_files": paths,
        "toolchain": toolchain,
        "dependencies": dependencies,
        "typed_analysis": typed,
        "checks": checks,
        "check_order": list(CHECK_ORDER),
        "frontend_check_order": list(FRONTEND_CHECK_ORDER),
        "ci": ci,
        "baseline": {"provided": baseline_report is not None, "check_statuses": dict(sorted(baseline_statuses.items()))},
        "git_state": git,
        "warnings": warnings,
        "configuration_errors": sorted(set(configuration_errors)),
        "safety": {
            "network_used": False,
            "provider_calls": False,
            "credentials_read": False,
            "raw_stdout_persisted": False,
            "raw_stderr_persisted": False,
            "environment_values_persisted": False,
            "automatic_repair": False,
            "merge_or_publish": False,
        },
        "operator_action": "run with --execute and an injected timezone-aware --generated-at after resolving unavailable or failed checks" if not ready else "human review may proceed; inspect the report and CI evidence before merging",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-git", action="store_true", help="include changed/untracked paths from local git state")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--diff-file", help="synthetic or saved diff content for deterministic review")
    parser.add_argument("--branch", default="local")
    parser.add_argument("--repository", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--execute", action="store_true", help="run the fixed local checks instead of only reporting their plan")
    parser.add_argument("--generated-at", help="timezone-aware ISO timestamp injected by the caller")
    parser.add_argument("--ci-status", choices=("success", "failure", "unavailable"), help="optional external CI result; never queried by this tool")
    parser.add_argument("--ci-steps", type=int, default=0, help="executed-step count accompanying --ci-status")
    parser.add_argument("--baseline-file", help="optional JSON baseline report used to classify pre-existing failures")
    parser.add_argument("--json", action="store_true"); parser.add_argument("--markdown", action="store_true"); parser.add_argument("--output")
    args = parser.parse_args(argv)
    if args.json and args.markdown: parser.error("choose --json or --markdown")
    paths = list(args.changed_file) + (changed_from_git(args.repository) if args.from_git else [])
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
    )
    report["planning_summary"] = run(paths, diff_text=_diff_text(args.diff_file), branch=args.branch)
    content = render_json_or_markdown(report, markdown=args.markdown, title="MarketOS local quality gate")
    write_optional_output(content, args.output); print(content, end="")
    return int(report["exit_code"])


if __name__ == "__main__": raise SystemExit(main())

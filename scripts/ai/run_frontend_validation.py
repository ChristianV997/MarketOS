"""Deterministic frontend validation loop for cockpit/workbench contracts.

Classifies failures as dependency, configuration, or source. Does not start
browsers, call providers, or mutate package-lock.json.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MAX_STEP_TIMEOUT_S = 120.0
MAX_STEP_OUTPUT_BYTES = 16384
SAFE_ENVIRONMENT_KEYS = frozenset(
    {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "COMSPEC",
        "PATHEXT",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "HOME",
        "APPDATA",
        "LOCALAPPDATA",
    }
)
EXPECTED_FRONTEND_SCRIPTS = {
    "typecheck": "tsc --noEmit",
    "test": "node --experimental-strip-types --test",
    "build": "tsc && vite build",
}
FRONTEND_SCRIPT_HOOKS = frozenset(
    f"{prefix}{name}"
    for name in EXPECTED_FRONTEND_SCRIPTS
    for prefix in ("pre", "post")
)


def _npm() -> str:
    if shutil.which("npm.cmd"):
        return "npm.cmd"
    if shutil.which("npm"):
        return "npm"
    return ""


def _child_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    """Pass only OS runtime variables; do not forward operator credentials to npm."""
    source = os.environ if base is None else base
    return {key: value for key, value in source.items() if key.upper() in SAFE_ENVIRONMENT_KEYS}


def _frontend_script_error(frontend: Path) -> str | None:
    """Reject package commands and npm hooks outside this runner's fixed contract."""
    try:
        manifest = json.loads((frontend / "package.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "frontend_manifest_invalid"
    scripts = manifest.get("scripts") if isinstance(manifest, dict) else None
    if not isinstance(scripts, dict):
        return "frontend_scripts_missing"
    for name, expected in EXPECTED_FRONTEND_SCRIPTS.items():
        if scripts.get(name) != expected:
            return f"frontend_script_not_allowlisted:{name}"
    for hook in sorted(FRONTEND_SCRIPT_HOOKS):
        if hook in scripts:
            return f"frontend_lifecycle_script_not_allowlisted:{hook}"
    return None


def _stop_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
        except (AttributeError, OSError, ValueError):
            try:
                process.terminate()
            except OSError:
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                process.terminate()
            except OSError:
                pass
    try:
        process.wait(timeout=1.0)
        return
    except subprocess.TimeoutExpired:
        pass

    if os.name == "nt":
        taskkill = shutil.which("taskkill")
        if taskkill:
            try:
                subprocess.run(
                    [taskkill, "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=2.0,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        pass


def _run(command: list[str], cwd: Path, *, timeout_s: float = MAX_STEP_TIMEOUT_S) -> dict[str, Any]:
    process_options: dict[str, Any] = {}
    if os.name == "nt":
        process_options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        process_options["start_new_session"] = True
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=_child_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            **process_options,
        )
    except OSError as exc:
        return {
            "command": command,
            "exit_code": 127,
            "stdout_tail": str(exc)[-MAX_STEP_OUTPUT_BYTES:],
            "stderr_tail": "",
            "output_bytes": 0,
            "output_truncated": False,
            "timed_out": False,
        }

    tail = bytearray()
    output_size = 0

    def collect_output() -> None:
        nonlocal output_size
        if process.stdout is None:
            return
        while True:
            chunk = process.stdout.read(1024)
            if not chunk:
                return
            output_size += len(chunk)
            tail.extend(chunk)
            if len(tail) > MAX_STEP_OUTPUT_BYTES:
                del tail[:-MAX_STEP_OUTPUT_BYTES]

    reader = threading.Thread(target=collect_output, daemon=True)
    reader.start()
    timed_out = False
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _stop_process_tree(process)
    reader.join(timeout=2.0)
    if process.stdout is not None:
        process.stdout.close()
    output = bytes(tail).decode("utf-8", errors="replace")
    return {
        "command": command,
        "exit_code": 124 if timed_out else process.returncode if process.returncode is not None else 127,
        "stdout_tail": output,
        "stderr_tail": "",
        "output_bytes": output_size,
        "output_truncated": output_size > MAX_STEP_OUTPUT_BYTES,
        "timed_out": timed_out,
    }


def classify_step(name: str, result: dict[str, Any]) -> str:
    if result.get("timed_out"):
        return "timed_out"
    if result["exit_code"] == 0:
        return "passed"
    combined = f"{result.get('stdout_tail', '')}\n{result.get('stderr_tail', '')}".lower()
    if name == "npm_ci" or "npm error code" in combined:
        return "dependency"
    if name != "test" and ("enoent" in combined or "cannot find module" in combined):
        return "dependency"
    if (
        "not recognized" in combined
        or "experimental-strip-types" in combined
        or "lockfile" in combined
        or "cannot find module" in combined
    ):
        return "configuration"
    return "source"


def run_frontend_validation(root: Path) -> dict[str, Any]:
    frontend = root / "frontend"
    lockfile = frontend / "package-lock.json"
    npm = _npm()
    report: dict[str, Any] = {
        "schema": "MarketOS.FrontendValidation.v1",
        "frontend": str(frontend),
        "lockfile_present": lockfile.is_file(),
        "node_modules_present": (frontend / "node_modules").is_dir(),
        "npm": npm or None,
        "steps": [],
        "status": "passed",
        "failure_class": None,
        "mutated": False,
        "network_providers": False,
        "dependency_installation": "not_attempted",
    }
    if not frontend.is_dir() or not (frontend / "package.json").is_file():
        report["status"] = "failed"
        report["failure_class"] = "configuration"
        report["reason"] = "frontend_manifest_missing"
        return report
    if not lockfile.is_file():
        report["status"] = "failed"
        report["failure_class"] = "configuration"
        report["reason"] = "package_lock_missing"
        return report
    script_error = _frontend_script_error(frontend)
    if script_error:
        report["status"] = "failed"
        report["failure_class"] = "configuration"
        report["reason"] = script_error
        return report
    if not npm:
        report["status"] = "unavailable"
        report["failure_class"] = "dependency"
        report["reason"] = "npm_missing"
        return report

    if not (frontend / "node_modules").is_dir():
        report["status"] = "unavailable"
        report["failure_class"] = "dependency"
        report["reason"] = "node_modules_missing_install_not_attempted"
        return report

    for script in ("typecheck", "test", "build"):
        result = _run([npm, "run", script], frontend)
        result["name"] = script
        result["failure_class"] = classify_step(script, result) if result["exit_code"] else None
        # Keep command conclusions and bounded metadata; do not expose raw tool output in reports.
        result.pop("stdout_tail", None)
        result.pop("stderr_tail", None)
        report["steps"].append(result)
        if result["exit_code"] != 0:
            report["status"] = (
                "timed_out"
                if result["failure_class"] == "timed_out"
                else "unavailable"
                if result["failure_class"] == "dependency"
                else "failed"
            )
            report["failure_class"] = result["failure_class"]
            return report
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=str(REPOSITORY_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_frontend_validation(Path(args.repository))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"status={report['status']} failure_class={report['failure_class']}")
        for step in report["steps"]:
            print(f"{step['name']}: exit {step['exit_code']}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

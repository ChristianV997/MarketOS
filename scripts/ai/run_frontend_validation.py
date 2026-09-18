"""Deterministic frontend validation loop for cockpit/workbench contracts.

Classifies failures as dependency, configuration, or source. Does not start
browsers, call providers, or mutate package-lock.json.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _npm() -> str:
    if shutil.which("npm.cmd"):
        return "npm.cmd"
    if shutil.which("npm"):
        return "npm"
    return ""


def _run(command: list[str], cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, check=False, shell=False)
    return {
        "command": command,
        "exit_code": completed.returncode,
        "stdout_tail": (completed.stdout or "")[-2000:],
        "stderr_tail": (completed.stderr or "")[-2000:],
    }


def classify_step(name: str, result: dict[str, Any]) -> str:
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


def run_frontend_validation(root: Path, *, skip_ci: bool = False) -> dict[str, Any]:
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
    if not npm:
        report["status"] = "failed"
        report["failure_class"] = "dependency"
        report["reason"] = "npm_missing"
        return report

    need_ci = not skip_ci and not (frontend / "node_modules").is_dir()
    if need_ci:
        ci = _run([npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund"], frontend)
        ci["name"] = "npm_ci"
        ci["failure_class"] = classify_step("npm_ci", ci) if ci["exit_code"] else None
        report["steps"].append(ci)
        if ci["exit_code"] != 0:
            report["status"] = "failed"
            report["failure_class"] = "dependency"
            return report
    elif not (frontend / "node_modules").is_dir():
        report["status"] = "failed"
        report["failure_class"] = "dependency"
        report["reason"] = "node_modules_missing_skip_ci"
        return report

    for script in ("typecheck", "test", "build"):
        result = _run([npm, "run", script], frontend)
        result["name"] = script
        result["failure_class"] = classify_step(script, result) if result["exit_code"] else None
        report["steps"].append(result)
        if result["exit_code"] != 0:
            report["status"] = "failed"
            report["failure_class"] = result["failure_class"]
            return report
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=str(REPOSITORY_ROOT))
    parser.add_argument("--skip-ci", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_frontend_validation(Path(args.repository), skip_ci=args.skip_ci)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"status={report['status']} failure_class={report['failure_class']}")
        for step in report["steps"]:
            print(f"{step['name']}: exit {step['exit_code']}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

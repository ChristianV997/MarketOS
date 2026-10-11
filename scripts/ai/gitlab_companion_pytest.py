"""Run GitLab companion pytest selections without shell evaluation.

Takes changed-path input, asks ``select_tests`` for recommended commands,
keeps only allowlisted pytest argv, appends bounded JUnit flags, and executes
via ``subprocess.run(..., shell=False)``.

This is intentionally narrow: not a generic CI framework. It reuses
``execution_bundle.validate_argv`` / ``assert_valid_test_command`` and never
``eval``s command strings.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

try:
    from . import execution_bundle, select_tests
except ImportError:  # pragma: no cover - direct script execution
    import execution_bundle  # type: ignore
    import select_tests  # type: ignore

FALLBACK_COMMAND = "pytest tests/contracts/test_architecture_boundaries.py"
DEFAULT_MAX_PATHS = 40
DEFAULT_MAX_COMMANDS = 8
DEFAULT_MAXFAIL = 20


def _read_changed_paths(path: Path, *, max_paths: int) -> list[str]:
    if not path.is_file():
        return []
    paths: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        # Reject shell metacharacters in path tokens before they reach selectors.
        if re.search(r"[|;&`$<>\n\r]", item):
            raise execution_bundle.ExecutionBundleError(f"unsafe changed-path token: {item!r}")
        paths.append(item)
        if len(paths) >= max_paths:
            break
    return paths


def _is_pytest_command(command: str) -> bool:
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    if not argv:
        return False
    if argv[0] == "pytest":
        return True
    return len(argv) >= 3 and argv[0] in {"python", "python3"} and argv[1] == "-m" and argv[2] == "pytest"


def _strip_local_quiet(argv: Sequence[str]) -> list[str]:
    return [part for part in argv if part != "-q"]


def _is_github_full_suite(argv: Sequence[str]) -> bool:
    """Reject the GitHub required full-suite shape if it ever appears."""
    normalized = list(argv)
    if "pytest" not in normalized and not (
        len(normalized) >= 3 and normalized[0] in {"python", "python3"} and normalized[1] == "-m" and normalized[2] == "pytest"
    ):
        return False
    has_tests_root = any(part == "tests/" or part == "tests" for part in normalized)
    has_xdist_auto = False
    for index, part in enumerate(normalized[:-1]):
        if part == "-n" and normalized[index + 1] == "auto":
            has_xdist_auto = True
            break
    return has_tests_root and has_xdist_auto


def pytest_commands_from_select_report(report: dict[str, Any]) -> list[str]:
    commands = report.get("recommended_commands") or []
    selected: list[str] = []
    for command in commands:
        if not isinstance(command, str):
            continue
        if not _is_pytest_command(command):
            continue
        selected.append(command)
    if not selected:
        selected = [FALLBACK_COMMAND]
    return selected


def build_pytest_argv(command: str, *, junitxml: Path, maxfail: int) -> list[str]:
    argv = _strip_local_quiet(execution_bundle.assert_valid_test_command(command))
    if _is_github_full_suite(argv):
        raise execution_bundle.ExecutionBundleError(
            f"companion refuses GitHub full-suite command: {command!r}"
        )
    # Re-validate after quiet stripping and before appending CI-only flags.
    verdict = execution_bundle.validate_argv(argv)
    if verdict["classification"] != "ok":
        raise execution_bundle.ExecutionBundleError(
            f"command not allowlisted after normalization ({verdict['reason']}): {command!r}"
        )
    argv = list(argv) + [f"--junitxml={junitxml}", f"--maxfail={maxfail}"]
    # Flags are pytest options; validate_argv still accepts bare pytest executable.
    verdict = execution_bundle.validate_argv(argv)
    if verdict["classification"] != "ok":
        raise execution_bundle.ExecutionBundleError(
            f"augmented pytest argv rejected ({verdict['reason']}): {argv!r}"
        )
    return argv


def run_pytest_argv(argv: Sequence[str], *, cwd: Path | None = None) -> int:
    """Execute validated argv with shell=False; stream stdio; return exit code."""
    if not argv or argv[0] != Path(argv[0]).name:
        raise execution_bundle.ExecutionBundleError("refusing path-qualified executable")
    completed = subprocess.run(
        list(argv),
        cwd=str(cwd) if cwd else None,
        shell=False,
        check=False,
    )
    return int(completed.returncode)


def run_companion(
    *,
    changed_files: Path,
    artifacts_dir: Path,
    maxfail: int = DEFAULT_MAXFAIL,
    max_paths: int = DEFAULT_MAX_PATHS,
    max_commands: int = DEFAULT_MAX_COMMANDS,
    cwd: Path | None = None,
) -> int:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    paths = _read_changed_paths(changed_files, max_paths=max_paths)
    report = select_tests.select(paths)
    (artifacts_dir / "select-tests.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    commands = pytest_commands_from_select_report(report)[:max_commands]
    if not commands:
        commands = [FALLBACK_COMMAND]

    argvs: list[list[str]] = []
    primary_junit = artifacts_dir / "junit.xml"
    for index, command in enumerate(commands):
        junit = primary_junit if index == 0 else artifacts_dir / "junit-extra.xml"
        argvs.append(build_pytest_argv(command, junitxml=junit, maxfail=maxfail))

    (artifacts_dir / "pytest-commands.txt").write_text(
        "\n".join(shlex.join(argv) for argv in argvs) + ("\n" if argvs else ""),
        encoding="utf-8",
    )
    (artifacts_dir / "pytest-argvs.json").write_text(
        json.dumps(argvs, indent=2) + "\n",
        encoding="utf-8",
    )

    exit_code = 0
    for argv in argvs:
        print("+", shlex.join(argv), flush=True)
        code = run_pytest_argv(argv, cwd=cwd)
        if code != 0 and exit_code == 0:
            exit_code = code
            # Preserve blocking semantics: stop on first failing suite.
            break
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-files", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--maxfail", type=int, default=DEFAULT_MAXFAIL)
    parser.add_argument("--max-paths", type=int, default=DEFAULT_MAX_PATHS)
    parser.add_argument("--max-commands", type=int, default=DEFAULT_MAX_COMMANDS)
    args = parser.parse_args(argv)
    try:
        return run_companion(
            changed_files=args.changed_files,
            artifacts_dir=args.artifacts_dir,
            maxfail=args.maxfail,
            max_paths=args.max_paths,
            max_commands=args.max_commands,
        )
    except execution_bundle.ExecutionBundleError as exc:
        print(f"gitlab_companion_pytest: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Focused tests for the GitLab companion pytest argv runner."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ai import execution_bundle, gitlab_companion_pytest as companion


def test_pytest_commands_from_select_report_keeps_pytest_and_falls_back():
    report = {
        "recommended_commands": [
            "python -m compileall -q backend api scripts tests",
            "pytest tests/contracts/test_architecture_boundaries.py -q",
            "git diff --check",
        ]
    }
    assert companion.pytest_commands_from_select_report(report) == [
        "pytest tests/contracts/test_architecture_boundaries.py -q"
    ]
    assert companion.pytest_commands_from_select_report({"recommended_commands": []}) == [
        companion.FALLBACK_COMMAND
    ]


def test_build_pytest_argv_strips_quiet_adds_junit_and_rejects_full_suite():
    argv = companion.build_pytest_argv(
        "pytest tests/contracts/test_architecture_boundaries.py -q",
        junitxml=Path("artifacts/junit.xml"),
        maxfail=20,
    )
    assert argv[0] == "pytest"
    assert "-q" not in argv
    assert "--junitxml=artifacts/junit.xml" in argv
    assert "--maxfail=20" in argv
    assert execution_bundle.validate_argv(argv)["classification"] == "ok"

    with pytest.raises(execution_bundle.ExecutionBundleError, match="full-suite"):
        companion.build_pytest_argv(
            "pytest tests/ -v -n auto",
            junitxml=Path("artifacts/junit.xml"),
            maxfail=20,
        )


def test_build_pytest_argv_rejects_shell_metacharacters():
    with pytest.raises(execution_bundle.ExecutionBundleError):
        companion.build_pytest_argv(
            "pytest tests; rm -rf /",
            junitxml=Path("artifacts/junit.xml"),
            maxfail=20,
        )


def test_run_pytest_argv_uses_shell_false(monkeypatch, tmp_path: Path):
    seen: dict[str, object] = {}

    class Completed:
        returncode = 0

    def fake_run(argv, **kwargs):
        seen["argv"] = list(argv)
        seen["kwargs"] = kwargs
        return Completed()

    monkeypatch.setattr(companion.subprocess, "run", fake_run)
    code = companion.run_pytest_argv(
        ["pytest", "tests/contracts/test_architecture_boundaries.py"],
        cwd=tmp_path,
    )
    assert code == 0
    assert seen["kwargs"]["shell"] is False
    assert seen["argv"][0] == "pytest"


def test_run_companion_writes_artifacts_and_propagates_failure(tmp_path: Path, monkeypatch):
    changed = tmp_path / "changed-files.txt"
    changed.write_text(".gitlab-ci.yml\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"

    monkeypatch.setattr(
        companion.select_tests,
        "select",
        lambda paths: {
            "changed_files": paths,
            "recommended_commands": [
                "pytest tests/contracts/test_architecture_boundaries.py -q",
                "pytest tests/ai/test_native_agent_capability.py -q",
            ],
            "lanes": ["unknown_fallback"],
            "docs_only": False,
        },
    )

    def fake_run(argv, **kwargs):
        class Completed:
            returncode = 7

        assert kwargs["shell"] is False
        assert argv[0] == "pytest"
        return Completed()

    monkeypatch.setattr(companion.subprocess, "run", fake_run)

    # Stop on first failure: inject failure on first suite.
    exit_code = companion.run_companion(
        changed_files=changed,
        artifacts_dir=artifacts,
        maxfail=20,
        max_commands=2,
    )
    assert exit_code == 7
    assert (artifacts / "select-tests.json").is_file()
    assert (artifacts / "pytest-commands.txt").is_file()
    argvs = json.loads((artifacts / "pytest-argvs.json").read_text(encoding="utf-8"))
    assert isinstance(argvs, list) and argvs
    assert argvs[0][0] == "pytest"
    assert any(part.startswith("--junitxml=") for part in argvs[0])


def test_run_companion_empty_changed_files_uses_fallback(tmp_path: Path, monkeypatch):
    changed = tmp_path / "changed-files.txt"
    changed.write_text("", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    seen: list[list[str]] = []

    class Completed:
        returncode = 0

    def fake_run(argv, **kwargs):
        seen.append(list(argv))
        assert kwargs["shell"] is False
        return Completed()

    monkeypatch.setattr(companion.subprocess, "run", fake_run)
    code = companion.run_companion(changed_files=changed, artifacts_dir=artifacts)
    assert code == 0
    assert seen
    assert "tests/contracts/test_architecture_boundaries.py" in seen[0]


def test_changed_path_rejects_metacharacters(tmp_path: Path):
    changed = tmp_path / "changed-files.txt"
    changed.write_text("backend/foo.py; rm -rf /\n", encoding="utf-8")
    with pytest.raises(execution_bundle.ExecutionBundleError, match="unsafe changed-path"):
        companion._read_changed_paths(changed, max_paths=10)

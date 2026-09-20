from __future__ import annotations

import sys
import json
from pathlib import Path

import pytest

from scripts.ai import run_frontend_validation, select_tests
from scripts.ai import run_local_quality_gate as gate

SAFE_NPM_SCRIPTS = {
    "typecheck": "tsc --noEmit",
    "test": "node --experimental-strip-types --test",
    "build": "tsc && vite build",
}


def test_frontend_selector_runs_validation_harness():
    report = select_tests.select(["frontend/src/pages/OperatorEventDashboard.tsx"])
    assert report["recommended_commands"][0] == "python scripts/ai/run_frontend_validation.py --json"
    assert "frontend" in report["lanes"]


def test_node_test_script_is_allowlisted():
    assert gate._safe_frontend_script("node --experimental-strip-types --test") is True
    assert gate._safe_frontend_script("python -c \"print('vitest')\"") is False


def test_test_runner_module_not_found_is_configuration():
    result = {
        "exit_code": 1,
        "stdout_tail": "Error: Cannot find module '...\\frontend\\tests'",
        "stderr_tail": "",
    }
    assert run_frontend_validation.classify_step("test", result) == "configuration"
    assert run_frontend_validation.classify_step("typecheck", result) == "dependency"


def test_validation_harness_fails_closed_without_lockfile(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text("{}", encoding="utf-8")
    report = run_frontend_validation.run_frontend_validation(tmp_path)
    assert report["status"] == "failed"
    assert report["failure_class"] == "configuration"
    assert report["mutated"] is False
    assert report["network_providers"] is False


def test_validation_harness_missing_node_modules_is_unavailable_without_install(tmp_path, monkeypatch):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text(json.dumps({"scripts": SAFE_NPM_SCRIPTS}), encoding="utf-8")
    (frontend / "package-lock.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(run_frontend_validation, "_npm", lambda: "npm")
    monkeypatch.setattr(run_frontend_validation, "_run", lambda *args, **kwargs: pytest.fail("must not install"))
    report = run_frontend_validation.run_frontend_validation(tmp_path)
    assert report["status"] == "unavailable"
    assert report["failure_class"] == "dependency"
    assert report["reason"] == "node_modules_missing_install_not_attempted"
    assert report["dependency_installation"] == "not_attempted"
    assert report["steps"] == []
    assert Path(report["frontend"]).name == "frontend"


@pytest.mark.parametrize(
    ("scripts", "reason"),
    [
        (
            {**SAFE_NPM_SCRIPTS, "test": "node --test && curl https://example.invalid"},
            "frontend_script_not_allowlisted:test",
        ),
        (
            {**SAFE_NPM_SCRIPTS, "pretest": "curl https://example.invalid"},
            "frontend_lifecycle_script_not_allowlisted:pretest",
        ),
    ],
)
def test_validation_harness_rejects_unreviewed_npm_commands(tmp_path, monkeypatch, scripts, reason):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text(json.dumps({"scripts": scripts}), encoding="utf-8")
    (frontend / "package-lock.json").write_text("{}", encoding="utf-8")
    (frontend / "node_modules").mkdir()
    monkeypatch.setattr(run_frontend_validation, "_npm", lambda: "npm")
    monkeypatch.setattr(run_frontend_validation, "_run", lambda *args, **kwargs: pytest.fail("must fail closed"))

    report = run_frontend_validation.run_frontend_validation(tmp_path)

    assert report["status"] == "failed"
    assert report["failure_class"] == "configuration"
    assert report["reason"] == reason
    assert report["steps"] == []


def test_validation_child_environment_is_allowlisted():
    env = run_frontend_validation._child_environment(
        {
            "PATH": "/safe/bin",
            "AWS_SECRET_ACCESS_KEY": "sentinel-secret",
            "OPENAI_API_KEY": "sentinel-secret",
            "FOO": "unrelated",
        }
    )
    assert env == {"PATH": "/safe/bin"}


def test_validation_command_output_is_bounded(tmp_path):
    result = run_frontend_validation._run(
        [sys.executable, "-c", "print('x' * 20000)"],
        tmp_path,
    )
    assert result["exit_code"] == 0
    assert result["output_truncated"] is True
    assert result["output_bytes"] > run_frontend_validation.MAX_STEP_OUTPUT_BYTES
    assert len(result["stdout_tail"].encode("utf-8")) <= run_frontend_validation.MAX_STEP_OUTPUT_BYTES


def test_validation_command_timeout_is_classified(tmp_path):
    result = run_frontend_validation._run(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        tmp_path,
        timeout_s=0.1,
    )
    assert result["timed_out"] is True
    assert run_frontend_validation.classify_step("build", result) == "timed_out"


def test_validation_report_does_not_include_raw_output(tmp_path, monkeypatch):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text(json.dumps({"scripts": SAFE_NPM_SCRIPTS}), encoding="utf-8")
    (frontend / "package-lock.json").write_text("{}", encoding="utf-8")
    (frontend / "node_modules").mkdir()
    monkeypatch.setattr(run_frontend_validation, "_npm", lambda: "npm")
    monkeypatch.setattr(
        run_frontend_validation,
        "_run",
        lambda command, cwd: {
            "command": command,
            "exit_code": 1,
            "stdout_tail": "sentinel-output",
            "stderr_tail": "",
            "output_bytes": 16,
            "output_truncated": False,
            "timed_out": False,
        },
    )
    report = run_frontend_validation.run_frontend_validation(tmp_path)
    assert report["status"] == "failed"
    assert "sentinel-output" not in str(report)
    assert "stdout_tail" not in report["steps"][0]

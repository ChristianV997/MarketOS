from __future__ import annotations

from pathlib import Path

from scripts.ai import run_frontend_validation, select_tests
from scripts.ai import run_local_quality_gate as gate


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
    report = run_frontend_validation.run_frontend_validation(tmp_path, skip_ci=True)
    assert report["status"] == "failed"
    assert report["failure_class"] == "configuration"
    assert report["mutated"] is False
    assert report["network_providers"] is False


def test_validation_harness_missing_node_modules_is_dependency(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text("{}", encoding="utf-8")
    (frontend / "package-lock.json").write_text("{}", encoding="utf-8")
    report = run_frontend_validation.run_frontend_validation(tmp_path, skip_ci=True)
    assert report["failure_class"] == "dependency"
    assert Path(report["frontend"]).name == "frontend"

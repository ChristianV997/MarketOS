from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.ai import run_local_quality_gate as gate


def test_no_changes_is_clear_and_offline():
    report = gate.run([])
    assert report["status"] == "clear"
    assert report["network_calls"] is False
    assert report["mutated"] is False
    assert report["phase1_readiness"]["next_best_action"]
    assert report["benchmark_matrix"]["evidence_mode"] in {"fixture_demo", "unavailable"}
    assert report["impact_top_task"] in {"run_cj_credentialed_readonly_validation", "finish_cj_live_validation_pack"}


def test_docs_only_is_advisory_with_docs_lane():
    report = gate.run(["docs/ai/QUALITY_GATES.md"])
    assert report["status"] == "advisory"
    assert report["recommended_ci_lanes"] == ["docs_only", "diff_check"]
    assert report["recommended_tests"] == ["git diff --check", "python scripts/ai/session_finish.py --dry-run"]


def test_supplier_adapter_selects_supplier_regressions():
    report = gate.run(["backend/adapters/research/cj_readonly_api.py"])
    assert any("test_cj_readonly_supplier" in command for command in report["recommended_tests"])
    assert "supplier_evidence" in report["recommended_ci_lanes"]


def test_evaluation_and_frontend_files_choose_their_specific_lanes():
    evaluation = gate.run(["evaluation/commerce/metrics.py"])
    frontend = gate.run(["frontend/src/pages/OperatorEventDashboard.tsx"])
    assert "evaluation" in evaluation["recommended_ci_lanes"]
    assert "frontend" in frontend["recommended_ci_lanes"]


def test_env_file_blocks_without_exposing_content():
    report = gate.run([".env"], diff_text="CJ_API_KEY=long-secret-value")
    assert report["status"] == "blocked"
    assert report["secret_or_artifact_flags"]["credential_file_detected"] is True
    assert report["secret_or_artifact_flags"]["secret_value_like_detected"] is True


def test_artifact_file_blocks():
    report = gate.run(["artifacts/live/report.json"])
    assert report["status"] == "blocked"
    assert report["secret_or_artifact_flags"]["artifacts_detected"] is True


def test_mutation_like_diff_blocks_phase_gate():
    report = gate.run(["backend/adapter.py"], diff_text="client.create_order()")
    assert report["status"] == "blocked"
    assert report["mutation_flags"]["provider_mutation_like_detected"] is True
    assert "supplier_mutation" in report["phase_gate_blockers"]


def test_unknown_file_has_safe_fallback():
    report = gate.run(["core/new_module.py"])
    assert "unknown_fallback" in report["recommended_ci_lanes"]
    assert report["status"] == "advisory"


def test_result_is_deterministic_for_explicit_inputs():
    first = gate.run(["scripts/ai/select_tests.py"], diff_text="", branch="codex/example")
    assert first == gate.run(["scripts/ai/select_tests.py"], diff_text="", branch="codex/example")


def test_doc_mutation_language_does_not_block_a_mixed_implementation_diff():
    diff = """diff --git a/docs/guide.md b/docs/guide.md
+create_order is forbidden
diff --git a/scripts/ai/tool.py b/scripts/ai/tool.py
+print('safe')
"""
    report = gate.run(["docs/guide.md", "scripts/ai/tool.py"], diff_text=diff)
    assert report["status"] == "advisory"
    assert report["mutation_flags"]["provider_mutation_like_detected"] is False


def test_diff_reader_recovers_when_subprocess_returns_no_stdout(monkeypatch):
    class Result:
        stdout = None
    monkeypatch.setattr(gate.subprocess, "run", lambda *args, **kwargs: Result())
    assert gate._diff_text(None) == ""


def _result(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _all_tools_available(monkeypatch):
    monkeypatch.setattr(gate.shutil, "which", lambda name: f"/tools/{name}")


def _configured_root(tmp_path: Path) -> Path:
    (tmp_path / ".python-version").write_text("3.12\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[tool.ruff]\ntarget-version = "py311"\n[tool.mypy]\n', encoding="utf-8")
    workflow = tmp_path / ".github" / "workflows"
    workflow.mkdir(parents=True)
    (workflow / "ci.yml").write_text("python-version: '3.12'\n", encoding="utf-8")
    semgrep = tmp_path / "semgrep"
    semgrep.mkdir()
    (semgrep / "ai-safety.yml").write_text("rules: []\n", encoding="utf-8")
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "node_modules").mkdir()
    (frontend / "package.json").write_text(
        json.dumps({"scripts": {"lint": "eslint .", "typecheck": "tsc --noEmit", "test": "vitest run", "build": "tsc && vite build"}}),
        encoding="utf-8",
    )
    return tmp_path


def _passing_runner(command, root):
    joined = " ".join(command)
    if "pytest" in joined:
        return _result(stdout="4 passed, 1 skipped")
    if "semgrep" in joined:
        return _result(stdout=json.dumps({"results": [], "errors": []}))
    return _result()


def _write_ci_evidence(tmp_path: Path, *, run=None, required_jobs=None, jobs=None, extra_job_fields=None) -> Path:
    job = {
        "name": "agentic-quality-gate",
        "required": True,
        "status": "completed",
        "conclusion": "success",
        "runner_id": 123,
        "runner_name": "ubuntu-latest",
        "steps_executed": 4,
        "logs_available": True,
        "required_check_status": "success",
    }
    if extra_job_fields:
        job.update(extra_job_fields)
    payload = {
        "schema": gate.CI_EVIDENCE_SCHEMA,
        "run": run or {"status": "completed", "conclusion": "success"},
        "required_jobs": required_jobs or [job["name"]],
        "jobs": jobs or [job],
    }
    path = tmp_path / "ci-evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_ci_evidence_file_reports_observed_required_success(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    root = _configured_root(tmp_path)
    evidence_path = _write_ci_evidence(root)
    evidence, error = gate.load_ci_evidence(evidence_path)

    assert error is None
    report = gate.run_quality_gate(
        root,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        ci_result=evidence,
        runner=_passing_runner,
    )
    assert report["ci"]["status"] == "passed"
    assert report["ci"]["classification"] == gate.CLASS_PASS
    assert report["ci"]["executed_steps"] == 4
    assert report["ci"]["jobs"][0]["runner_assigned"] is True


def test_ci_evidence_file_preserves_executed_failure(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    root = _configured_root(tmp_path)
    evidence_path = _write_ci_evidence(
        root,
        run={"status": "completed", "conclusion": "failure"},
        extra_job_fields={"conclusion": "failure", "required_check_status": "failure"},
    )
    evidence, error = gate.load_ci_evidence(evidence_path)

    assert error is None
    report = gate.run_quality_gate(
        root,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        ci_result=evidence,
        runner=_passing_runner,
    )
    assert report["ci"]["status"] == "failed"
    assert report["ci"]["classification"] == gate.CLASS_FAILURE_ORIGIN_UNVERIFIED
    assert report["exit_code"] == gate.EXIT_FAILED


def test_ci_evidence_file_zero_steps_and_runnerless_are_unavailable(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    root = _configured_root(tmp_path)
    evidence_path = _write_ci_evidence(
        root,
        extra_job_fields={"runner_id": 0, "runner_name": "", "steps_executed": 0, "logs_available": False},
    )
    evidence, error = gate.load_ci_evidence(evidence_path)

    assert error is None
    report = gate.run_quality_gate(
        root,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        ci_result=evidence,
        runner=_passing_runner,
    )
    assert report["ci"]["status"] == "unavailable"
    assert report["ci"]["classification"] == gate.CLASS_CI_UNAVAILABLE
    assert report["ci"]["jobs"][0]["reason"] == "runner_unassigned"
    assert report["ready_for_supervised_use"] is False
    assert report["exit_code"] == gate.EXIT_UNAVAILABLE


def test_ci_evidence_file_missing_logs_are_unavailable(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    root = _configured_root(tmp_path)
    evidence_path = _write_ci_evidence(root, extra_job_fields={"logs_available": False})
    evidence, error = gate.load_ci_evidence(evidence_path)

    assert error is None
    report = gate.run_quality_gate(
        root,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        ci_result=evidence,
        runner=_passing_runner,
    )
    assert report["ci"]["status"] == "unavailable"
    assert report["ci"]["jobs"][0]["reason"] == "ci_logs_unavailable"
    assert report["ci"]["classification"] == gate.CLASS_CI_UNAVAILABLE


def test_ci_evidence_file_rejects_raw_log_fields_as_malformed(tmp_path, capsys):
    evidence_path = _write_ci_evidence(tmp_path, extra_job_fields={"stdout": "secret-like raw log"})
    evidence, error = gate.load_ci_evidence(evidence_path)

    assert evidence["status"] == "malformed"
    assert evidence["classification"] == gate.CLASS_MALFORMED_CONFIGURATION
    assert error == "malformed_ci_evidence"

    exit_code = gate.main(["--ci-evidence-file", str(evidence_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == gate.EXIT_CONFIGURATION
    assert payload["classification"] == gate.CLASS_MALFORMED_CONFIGURATION


def test_ci_evidence_file_is_bounded(tmp_path):
    evidence_path = tmp_path / "ci-evidence.json"
    evidence_path.write_bytes(b"{" + b" " * gate.CI_EVIDENCE_MAX_BYTES + b"}")

    evidence, error = gate.load_ci_evidence(evidence_path)

    assert evidence["status"] == "malformed"
    assert evidence["reason"] == "ci_evidence_too_large"
    assert error == "malformed_ci_evidence"


def test_ci_evidence_file_cli_path_is_deterministic_and_fail_closed(monkeypatch, tmp_path, capsys):
    _all_tools_available(monkeypatch)
    root = _configured_root(tmp_path)
    evidence_path = _write_ci_evidence(root, extra_job_fields={"runner_id": None})
    exit_code = gate.main([
        "--repository", str(root),
        "--ci-evidence-file", str(evidence_path),
        "--generated-at", "2026-08-27T12:00:00+00:00",
        "--json",
    ])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == gate.EXIT_UNAVAILABLE
    assert payload["ci"]["classification"] == gate.CLASS_CI_UNAVAILABLE
    assert payload["ci"]["jobs"][0]["runner_assigned"] is False
    assert payload["ready_for_supervised_use"] is False


def test_preflight_succeeds_locally_without_claiming_final_readiness(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    root = _configured_root(tmp_path)

    report = gate.run_quality_gate(
        root,
        generated_at="2026-09-01T12:00:00+00:00",
        execute=True,
        phase="preflight",
        changed_paths=[],
        runner=_passing_runner,
    )

    assert report["phase"] == "preflight"
    assert report["mode"] == "preflight_execution"
    assert report["check_order"] == list(gate.PREFLIGHT_CHECK_ORDER)
    assert [check["name"] for check in report["checks"]] == list(gate.PREFLIGHT_CHECK_ORDER)
    assert report["status"] == "unavailable"
    assert report["classification"] == gate.CLASS_CI_UNAVAILABLE
    assert report["preflight"]["status"] in {"passed", "passed_with_warnings"}
    assert report["preflight"]["exit_code"] == gate.EXIT_PASSED
    assert report["exit_code"] == gate.EXIT_PASSED
    assert report["ready_for_supervised_use"] is False


def test_preflight_preserves_local_failure_and_final_phase_stays_strict(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    root = _configured_root(tmp_path)

    def failing_runner(command, root):
        if "pytest" in " ".join(command):
            return _result(returncode=1, stdout="1 failed")
        return _passing_runner(command, root)

    preflight = gate.run_quality_gate(
        root,
        generated_at="2026-09-01T12:00:00+00:00",
        execute=True,
        phase="preflight",
        changed_paths=[],
        runner=failing_runner,
    )
    final = gate.run_quality_gate(
        root,
        generated_at="2026-09-01T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        runner=failing_runner,
    )

    assert preflight["preflight"]["status"] == "failed"
    assert preflight["classification"] == gate.CLASS_FAILURE_ORIGIN_UNVERIFIED
    assert preflight["exit_code"] == gate.EXIT_FAILED
    assert preflight["ready_for_supervised_use"] is False
    assert final["phase"] == "final"
    assert final["ci"]["reason"] == "external_ci_not_queried"
    assert final["classification"] == gate.CLASS_FAILURE_ORIGIN_UNVERIFIED
    assert final["exit_code"] == gate.EXIT_FAILED
    assert final["ready_for_supervised_use"] is False


def test_preflight_cli_rejects_final_ci_evidence(tmp_path):
    evidence_path = _write_ci_evidence(tmp_path)

    with pytest.raises(SystemExit):
        gate.main(["--execute", "--phase", "preflight", "--ci-evidence-file", str(evidence_path)])


def test_ci_evidence_file_rejects_duplicate_job_names(tmp_path):
    job_path = _write_ci_evidence(tmp_path)
    payload = json.loads(job_path.read_text(encoding="utf-8"))
    payload["jobs"].append(dict(payload["jobs"][0]))
    job_path.write_text(json.dumps(payload), encoding="utf-8")

    evidence, error = gate.load_ci_evidence(job_path)

    assert evidence["status"] == "malformed"
    assert evidence["reason"] == "duplicate_ci_job_name"
    assert error == "malformed_ci_evidence"


def test_ci_evidence_file_rejects_required_flag_mismatch(tmp_path):
    job_path = _write_ci_evidence(tmp_path)
    payload = json.loads(job_path.read_text(encoding="utf-8"))
    payload["jobs"][0]["required"] = False
    job_path.write_text(json.dumps(payload), encoding="utf-8")

    evidence, error = gate.load_ci_evidence(job_path)

    assert evidence["status"] == "malformed"
    assert evidence["reason"] == "ci_job_required_flag_mismatch"
    assert error == "malformed_ci_evidence"


def test_ci_evidence_partial_required_jobs_preserve_failure_and_unavailability(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    root = _configured_root(tmp_path)
    jobs = [
        {
            "name": "agentic-quality-gate",
            "required": True,
            "status": "completed",
            "conclusion": "success",
            "runner_id": 123,
            "runner_name": "ubuntu-latest",
            "steps_executed": 4,
            "logs_available": True,
            "required_check_status": "success",
        },
        {
            "name": "test",
            "required": True,
            "status": "completed",
            "conclusion": "failure",
            "runner_id": 124,
            "runner_name": "ubuntu-latest",
            "steps_executed": 3,
            "logs_available": True,
            "required_check_status": "failure",
        },
        {
            "name": "quality-advisory",
            "required": True,
            "status": "in_progress",
            "conclusion": "pending",
            "runner_id": 125,
            "runner_name": "ubuntu-latest",
            "steps_executed": 0,
            "logs_available": True,
            "required_check_status": "pending",
        },
        {
            "name": "semgrep-policy",
            "required": True,
            "status": "completed",
            "conclusion": "failure",
            "runner_id": 0,
            "runner_name": "",
            "steps_executed": 0,
            "logs_available": False,
            "required_check_status": "failure",
        },
    ]
    evidence_path = _write_ci_evidence(
        root,
        run={"status": "completed", "conclusion": "failure"},
        required_jobs=[job["name"] for job in jobs],
        jobs=jobs,
    )
    evidence, error = gate.load_ci_evidence(evidence_path)

    assert error is None
    report = gate.run_quality_gate(
        root,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        ci_result=evidence,
        runner=_passing_runner,
    )
    ci_jobs = {job["name"]: job for job in report["ci"]["jobs"]}
    assert ci_jobs["agentic-quality-gate"]["status"] == "passed"
    assert ci_jobs["test"]["status"] == "failed"
    assert ci_jobs["quality-advisory"]["status"] == "unavailable"
    assert ci_jobs["semgrep-policy"]["reason"] == "runner_unassigned"
    assert report["ci"]["status"] == "unavailable"
    assert report["ci"]["classification"] == gate.CLASS_CI_UNAVAILABLE
    assert gate.CLASS_FAILURE_ORIGIN_UNVERIFIED in report["failure_classes"]
    assert report["ready_for_supervised_use"] is False


def test_ci_evidence_missing_required_job_is_unavailable(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    root = _configured_root(tmp_path)
    evidence_path = _write_ci_evidence(
        root,
        required_jobs=["agentic-quality-gate", "test"],
    )
    evidence, error = gate.load_ci_evidence(evidence_path)

    assert error is None
    report = gate.run_quality_gate(
        root,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        ci_result=evidence,
        runner=_passing_runner,
    )
    missing = next(job for job in report["ci"]["jobs"] if job["name"] == "test")
    assert missing["status"] == "unavailable"
    assert missing["reason"] == "required_ci_job_missing"
    assert report["ci"]["classification"] == gate.CLASS_CI_UNAVAILABLE
    assert report["ready_for_supervised_use"] is False


def test_real_gate_reports_stable_order_and_observed_evidence(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    report = gate.run_quality_gate(
        _configured_root(tmp_path),
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        ci_result={"status": "success", "executed_steps": 4},
        runner=_passing_runner,
    )
    assert report["schema"] == gate.QUALITY_GATE_SCHEMA
    assert report["check_order"] == list(gate.CHECK_ORDER)
    assert [item["name"] for item in report["checks"]] == list(gate.CHECK_ORDER)
    assert report["classification"] == gate.CLASS_PASS
    assert report["status"] == "passed_with_warnings"
    assert report["ready_for_supervised_use"] is False
    assert report["checks"][1]["summary"]["passed"] == 4
    assert report["checks"][1]["summary"]["skipped"] == 1
    assert report["checks"][1]["summary"]["collection_failed"] is False
    assert report["checks"][1]["summary"]["dependency_error"] is False
    assert report["status_taxonomy"] == list(gate.CHECK_STATUS_TAXONOMY)
    assert all(item["evidence_classification"] == "observed" for item in report["checks"] if item["status"] == "passed")
    assert report["safety"]["raw_stdout_persisted"] is False


def test_missing_tool_is_unavailable_not_a_pass(monkeypatch, tmp_path):
    original_prefix = gate._tool_prefix
    monkeypatch.setattr(gate, "_tool_prefix", lambda name: None if name == "ruff" else original_prefix(name))
    report = gate.run_quality_gate(tmp_path, generated_at="2026-08-27T12:00:00+00:00", execute=True, changed_paths=[], runner=_passing_runner, ci_result={"status": "success", "executed_steps": 1})
    ruff = next(item for item in report["checks"] if item["name"] == "ruff")
    assert ruff["status"] == "unavailable"
    assert ruff["classification"] == gate.CLASS_MISSING_TOOL
    assert report["status"] == "unavailable"
    assert report["exit_code"] == gate.EXIT_UNAVAILABLE
    assert report["ready_for_supervised_use"] is False


def test_changed_and_pre_existing_failures_require_baseline_evidence(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)

    def runner(command, root):
        joined = " ".join(command)
        if "pytest" in joined:
            return _result(1, "1 failed")
        if "ruff" in joined:
            return _result(1, "scripts/ai/example.py:1: F401 unused")
        return _passing_runner(command, root)

    report = gate.run_quality_gate(
        _configured_root(tmp_path),
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=["scripts/ai/example.py"],
        ci_result={"status": "success", "executed_steps": 1},
        baseline_report={"checks": {"pytest": {"status": "passed"}, "ruff": {"status": "failed", "finding_count": 356}}},
        runner=runner,
    )
    checks = {item["name"]: item for item in report["checks"]}
    assert checks["pytest"]["classification"] == gate.CLASS_CHANGED_SCOPE_FAILURE
    assert checks["pytest"]["failure_origin"] == gate.CLASS_CHANGED_SCOPE_FAILURE
    assert checks["ruff"]["classification"] == gate.CLASS_PRE_EXISTING_FAILURE
    assert set(report["failure_classes"]) >= {gate.CLASS_CHANGED_SCOPE_FAILURE, gate.CLASS_PRE_EXISTING_FAILURE}
    assert report["baseline"]["check_statuses"] == {"pytest": "passed", "ruff": "failed"}


def test_unrelated_changed_paths_do_not_prove_changed_scope(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)

    def runner(command, root):
        if "pytest" in " ".join(command):
            return _result(1, "1 failed")
        return _passing_runner(command, root)

    report = gate.run_quality_gate(
        _configured_root(tmp_path),
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=["docs/README.md"],
        ci_result={"status": "success", "executed_steps": 1},
        baseline_report={"checks": {"pytest": {"status": "passed"}}},
        runner=runner,
    )
    pytest_result = next(item for item in report["checks"] if item["name"] == "pytest")
    assert pytest_result["classification"] == gate.CLASS_FAILURE_ORIGIN_UNVERIFIED


def test_failure_without_baseline_has_unverified_origin(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)

    def runner(command, root):
        if "pytest" in " ".join(command):
            return _result(1, "1 failed")
        return _passing_runner(command, root)

    report = gate.run_quality_gate(tmp_path, generated_at="2026-08-27T12:00:00+00:00", execute=True, changed_paths=[], ci_result={"status": "success", "executed_steps": 1}, runner=runner)
    pytest_result = next(item for item in report["checks"] if item["name"] == "pytest")
    assert pytest_result["classification"] == gate.CLASS_FAILURE_ORIGIN_UNVERIFIED
    assert pytest_result["failure_origin"] == gate.CLASS_FAILURE_ORIGIN_UNVERIFIED


def test_security_findings_are_failures_even_when_scanner_exits_zero(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    root = tmp_path / "repo"
    root.mkdir()
    (root / "semgrep").mkdir()
    (root / "semgrep" / "ai-safety.yml").write_text("rules: []\n", encoding="utf-8")

    def runner(command, cwd):
        if "run_semgrep_policy.py" in " ".join(command):
            return _result(stdout=json.dumps({"results": [{"check_id": "unsafe"}], "errors": []}))
        return _passing_runner(command, cwd)

    report = gate.run_quality_gate(root, generated_at="2026-08-27T12:00:00+00:00", execute=True, changed_paths=[], ci_result={"status": "success", "executed_steps": 1}, runner=runner)
    security = next(item for item in report["checks"] if item["name"] == "security")
    assert security["status"] == "failed"
    assert security["classification"] == gate.CLASS_SECURITY_FINDING
    assert report["exit_code"] == gate.EXIT_FAILED


def test_collection_dependency_scanner_and_diff_outcomes_remain_distinct(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    root = _configured_root(tmp_path)

    def runner(command, cwd):
        joined = " ".join(command)
        if "pytest" in joined:
            return _result(1, "ERROR collecting tests/test_optional.py\nModuleNotFoundError: No module named 'optional_dep'")
        if "run_semgrep_policy.py" in joined:
            return _result(2, "not-json", "scanner crashed")
        if "git diff" in joined:
            return _result(1, "", "trailing whitespace")
        return _passing_runner(command, cwd)

    report = gate.run_quality_gate(
        root,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        ci_result={"status": "success", "executed_steps": 1},
        runner=runner,
    )
    checks = {item["name"]: item for item in report["checks"]}
    assert checks["pytest"]["status"] == "collection_failed"
    assert checks["pytest"]["summary"]["collection_failed"] is True
    assert checks["pytest"]["summary"]["dependency_error"] is True
    assert checks["pytest"]["classification"] == gate.CLASS_UNAVAILABLE_DEPENDENCY
    assert checks["security"]["status"] == "malformed"
    assert checks["security"]["classification"] == gate.CLASS_MALFORMED_CONFIGURATION
    assert checks["diff_check"]["classification"] == gate.CLASS_DIFF_FAILURE
    assert set(report["failure_classes"]) >= {
        gate.CLASS_UNAVAILABLE_DEPENDENCY,
        gate.CLASS_MALFORMED_CONFIGURATION,
        gate.CLASS_DIFF_FAILURE,
    }
    assert report["status"] == "configuration_error"
    assert report["exit_code"] == gate.EXIT_CONFIGURATION


def test_collection_failure_without_dependency_is_explicit(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)

    def runner(command, root):
        if "pytest" in " ".join(command):
            return _result(1, "ERROR collecting tests/test_syntax.py\nSyntaxError: invalid syntax")
        return _passing_runner(command, root)

    report = gate.run_quality_gate(
        tmp_path,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        ci_result={"status": "success", "executed_steps": 1},
        runner=runner,
    )
    pytest_result = next(item for item in report["checks"] if item["name"] == "pytest")
    assert pytest_result["status"] == "collection_failed"
    assert pytest_result["classification"] == gate.CLASS_COLLECTION_FAILED


def test_missing_security_policy_is_unavailable_and_blocks(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    root = _configured_root(tmp_path)
    (root / "semgrep" / "ai-safety.yml").unlink()

    report = gate.run_quality_gate(
        root,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        ci_result={"status": "success", "executed_steps": 1},
        runner=_passing_runner,
    )
    security = next(item for item in report["checks"] if item["name"] == "security")
    assert security["status"] == "unavailable"
    assert security["classification"] == gate.CLASS_MISSING_TOOL
    assert report["exit_code"] == gate.EXIT_UNAVAILABLE
    assert report["ready_for_supervised_use"] is False


def test_lint_text_with_import_error_word_is_not_dependency_failure():
    summary = gate._command_summary("ruff", "example.py:1: F401 ImportError is documented", "", 1)
    assert summary["finding_count"] == 1
    assert summary["dependency_error"] is False


def test_missing_dependency_without_collection_is_unavailable(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)

    def runner(command, root):
        if "pytest" in " ".join(command):
            return _result(1, "ModuleNotFoundError: No module named 'optional_dep'")
        return _passing_runner(command, root)

    report = gate.run_quality_gate(
        tmp_path,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        ci_result={"status": "success", "executed_steps": 1},
        runner=runner,
    )
    pytest_result = next(item for item in report["checks"] if item["name"] == "pytest")
    assert pytest_result["status"] == "unavailable"
    assert pytest_result["classification"] == gate.CLASS_UNAVAILABLE_DEPENDENCY
    assert report["status"] == "unavailable"
    assert report["exit_code"] == gate.EXIT_UNAVAILABLE


def test_typed_dependency_and_timeout_aggregates_do_not_pass(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text('[tool.mypy]\ncheck_untyped_defs = true\n', encoding="utf-8")

    def runner(command, cwd):
        joined = " ".join(command)
        if "mypy" in joined:
            return _result(1, "ModuleNotFoundError: No module named 'mypy_plugin'")
        return _passing_runner(command, cwd)

    report = gate.run_quality_gate(
        root,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        ci_result={"status": "success", "executed_steps": 1},
        runner=runner,
    )
    typed = next(item for item in report["checks"] if item["name"] == "typed")
    assert typed["status"] == "unavailable"
    assert typed["classification"] == gate.CLASS_UNAVAILABLE_DEPENDENCY
    assert report["status"] == "unavailable"


def test_timeout_is_not_a_pass(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)

    def runner(command, root):
        if "pytest" in " ".join(command):
            raise subprocess.TimeoutExpired(command, timeout=1)
        return _passing_runner(command, root)

    report = gate.run_quality_gate(tmp_path, generated_at="2026-08-27T12:00:00+00:00", execute=True, changed_paths=[], ci_result={"status": "success", "executed_steps": 1}, runner=runner)
    pytest_result = next(item for item in report["checks"] if item["name"] == "pytest")
    assert pytest_result["status"] == "timed_out"
    assert pytest_result["classification"] == gate.CLASS_TIMEOUT
    assert pytest_result["execution_status"] == "timed_out"
    assert report["status"] == "failed"


def test_windows_timeout_terminates_descendants_without_waiting(monkeypatch, tmp_path):
    monkeypatch.setattr(gate.os, "name", "nt")

    class FakeStream:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeProcess:
        pid = 1234

        def __init__(self):
            self.stdout = FakeStream()
            self.stderr = FakeStream()
            self.killed = False

        def communicate(self, timeout):
            raise subprocess.TimeoutExpired(["python", "-m", "pytest"], timeout)

        def kill(self):
            self.killed = True

    process = FakeProcess()
    taskkill_calls = []
    monkeypatch.setattr(gate.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda command, **kwargs: taskkill_calls.append((command, kwargs)) or _result(),
    )
    with pytest.raises(subprocess.TimeoutExpired):
        gate._invoke_local(["python", "-m", "pytest"], tmp_path, None)
    assert taskkill_calls[0][0] == ["taskkill", "/PID", "1234", "/T", "/F"]
    assert process.killed is True
    assert process.stdout.closed is True
    assert process.stderr.closed is True


def test_frontend_dependency_unavailability_is_explicit(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    root = _configured_root(tmp_path)
    (root / "frontend" / "node_modules").rmdir()
    report = gate.run_quality_gate(root, generated_at="2026-08-27T12:00:00+00:00", execute=True, changed_paths=[], ci_result={"status": "success", "executed_steps": 1}, runner=_passing_runner)
    frontend = next(item for item in report["checks"] if item["name"] == "frontend")
    assert frontend["status"] == "unavailable"
    assert frontend["execution_status"] == "not_executed"
    assert frontend["classification"] == gate.CLASS_UNAVAILABLE_DEPENDENCY
    assert report["status"] == "unavailable"


def test_zero_step_ci_failure_is_unavailable(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    report = gate.run_quality_gate(tmp_path, generated_at="2026-08-27T12:00:00+00:00", execute=True, changed_paths=[], ci_result={"status": "failure", "executed_steps": 0}, runner=_passing_runner)
    assert report["ci"]["status"] == "unavailable"
    assert report["ci"]["classification"] == gate.CLASS_CI_UNAVAILABLE
    assert report["status"] == "unavailable"
    assert report["exit_code"] == gate.EXIT_UNAVAILABLE


def test_malformed_configuration_and_baseline_have_configuration_exit(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.ruff\n", encoding="utf-8")
    report = gate.run_quality_gate(tmp_path, generated_at="2026-08-27T12:00:00+00:00")
    assert report["classification"] == gate.CLASS_MALFORMED_CONFIGURATION
    assert report["exit_code"] == gate.EXIT_CONFIGURATION
    assert "malformed:pyproject.toml" in report["configuration_errors"]


def test_malformed_frontend_and_timestamp_fail_closed(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text("[]", encoding="utf-8")
    report = gate.run_quality_gate(frontend.parent, generated_at="not-a-timestamp")
    assert report["classification"] == gate.CLASS_MALFORMED_CONFIGURATION
    assert report["timestamp_injected"] is False
    assert "invalid_generated_at" in report["configuration_errors"]
    assert "malformed:frontend" in report["configuration_errors"]


def test_unsafe_frontend_script_is_blocked_before_execution(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "node_modules").mkdir()
    (frontend / "package.json").write_text(
        json.dumps({"scripts": {"test": "python -c \\\"print('vitest')\\\""}}),
        encoding="utf-8",
    )
    called = []

    def runner(command, root):
        called.append(command)
        return _passing_runner(command, root)

    report = gate.run_quality_gate(
        tmp_path,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        ci_result={"status": "success", "executed_steps": 1},
        runner=runner,
    )
    frontend_result = next(item for item in report["checks"] if item["name"] == "frontend")
    test_result = next(item for item in frontend_result["checks"] if item["name"] == "frontend:test")
    assert frontend_result["classification"] == "blocked"
    assert frontend_result["status"] == "blocked"
    assert test_result["status"] == "blocked"
    assert test_result["reason"] == "script_not_in_local_allowlist"
    assert not any("frontend:test" in " ".join(command) for command in called)


def test_dry_run_and_cli_baseline_are_not_false_successes(tmp_path, capsys):
    timestamp = "2026-08-27T12:00:00+00:00"
    assert gate.main(["--repository", str(tmp_path), "--generated-at", timestamp, "--json"]) == gate.EXIT_UNAVAILABLE
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "not_run"
    assert payload["classification"] == gate.CLASS_CI_UNAVAILABLE
    assert payload["ready_for_supervised_use"] is False

    bad_baseline = tmp_path / "bad-baseline.json"
    bad_baseline.write_text("not-json", encoding="utf-8")
    assert gate.main(["--repository", str(tmp_path), "--generated-at", timestamp, "--baseline-file", str(bad_baseline), "--json"]) == gate.EXIT_CONFIGURATION
    assert json.loads(capsys.readouterr().out)["classification"] == gate.CLASS_MALFORMED_CONFIGURATION


def test_deterministic_replay_never_persists_command_output(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)

    def runner(command, cwd):
        return _result(stdout="TOKEN=do-not-persist")

    kwargs = {"generated_at": "2026-08-27T12:00:00+00:00", "execute": True, "changed_paths": ["scripts/ai/example.py"], "ci_result": {"status": "success", "executed_steps": 1}, "runner": runner}
    first = gate.run_quality_gate(tmp_path, **kwargs)
    second = gate.run_quality_gate(tmp_path, **kwargs)
    assert first == second
    assert "do-not-persist" not in json.dumps(first)
    assert first["safety"]["raw_stdout_persisted"] is False

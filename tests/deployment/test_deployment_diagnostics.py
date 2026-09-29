"""Unit tests for backend.deployment.diagnostics."""
from pathlib import Path
from backend.deployment.diagnostics import (
    diagnose_missing_python_module,
    diagnose_missing_node_dependency,
    diagnose_missing_optional_provider,
    diagnose_missing_docker,
    diagnose_unavailable_ollama,
    diagnose_zero_step_ci,
    diagnose_missing_runner,
    diagnose_malformed_report,
    diagnose_failed_healthcheck,
    diagnose_port_collision,
    diagnose_invalid_environment_contract,
    run_all_diagnostics,
)


def test_diagnose_missing_python_module():
    # Present module
    res_ok = diagnose_missing_python_module("sys")
    assert res_ok.status == "ok"
    assert res_ok.code == "missing_python_module"

    # Missing module
    res_err = diagnose_missing_python_module("nonexistent_module_for_test_12345")
    assert res_err.status == "detected"
    assert "pip install" in res_err.remediation


def test_diagnose_missing_node_dependency(tmp_path: Path):
    # Missing package.json
    res_no_pkg = diagnose_missing_node_dependency(frontend_dir=tmp_path)
    assert res_no_pkg.status == "unavailable"

    # With package.json but no node_modules
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    res_no_nm = diagnose_missing_node_dependency(frontend_dir=tmp_path)
    assert res_no_nm.status == "detected"
    assert "npm ci" in res_no_nm.remediation

    # With node_modules
    (tmp_path / "node_modules").mkdir()
    res_nm = diagnose_missing_node_dependency(frontend_dir=tmp_path)
    assert res_nm.status == "ok"


def test_diagnose_missing_optional_provider():
    # Missing provider credentials
    res_missing = diagnose_missing_optional_provider("apify", environ={})
    assert res_missing.status == "detected"
    assert "APIFY_API_TOKEN" in res_missing.failure_details["missing_keys"]

    # Configured provider
    res_present = diagnose_missing_optional_provider("apify", environ={"APIFY_API_TOKEN": "token-xyz"})
    assert res_present.status == "ok"


def test_diagnose_missing_docker():
    res = diagnose_missing_docker()
    assert res.code == "missing_docker"
    assert res.status in {"ok", "detected"}


def test_diagnose_unavailable_ollama():
    # On an unused port
    res = diagnose_unavailable_ollama(port=59999)
    assert res.code == "unavailable_ollama"
    assert res.status == "detected"
    assert "mock inference" in res.remediation


def test_diagnose_zero_step_ci():
    res_zero = diagnose_zero_step_ci("ci_unavailable", 0)
    assert res_zero.status == "detected"
    assert "run_local_quality_gate.py" in res_zero.remediation

    res_active = diagnose_zero_step_ci("success", 12)
    assert res_active.status == "ok"


def test_diagnose_missing_runner():
    res = diagnose_missing_runner()
    assert res.code == "missing_runner"
    assert res.status in {"ok", "detected"}


def test_run_all_diagnostics_defaults_to_unassigned_runner_when_no_ci_evidence_supplied():
    """Backward compatibility: omitting ci_evidence (the prior call shape)
    must reproduce the exact prior no-args diagnose_zero_step_ci() behavior."""
    report = run_all_diagnostics(environ={}, mode="local_dry_run")
    zero_step = next(item for item in report["diagnostics"] if item["code"] == "zero_step_ci")
    assert zero_step["failure_details"]["runner_id"] is None
    assert zero_step["failure_details"]["steps_executed"] == 0


def test_run_all_diagnostics_threads_real_ci_evidence_into_zero_step_diagnosis():
    """A caller with real GitHub Actions evidence (runner_id=0, zero steps)
    must have that exact evidence reach diagnose_zero_step_ci -- before this,
    run_all_diagnostics always called diagnose_zero_step_ci() with no
    arguments, so the caller's actual CI evidence (e.g. from
    classify_github_actions_job) never reached the administrator-facing
    diagnostic message at all, regardless of what was really observed."""
    report = run_all_diagnostics(
        environ={},
        mode="local_dry_run",
        ci_evidence={"ci_status": "ci_unavailable", "steps_executed": 0, "runner_id": 0},
    )
    zero_step = next(item for item in report["diagnostics"] if item["code"] == "zero_step_ci")
    assert zero_step["status"] == "detected"
    assert zero_step["failure_details"]["runner_id"] == 0
    assert zero_step["failure_details"]["runner_assigned"] is False


def test_run_all_diagnostics_reflects_a_real_assigned_runner_with_executed_steps():
    """The same wiring must also report a healthy, non-zero-step CI run
    accurately -- this is not a one-way "always detect" shortcut."""
    report = run_all_diagnostics(
        environ={},
        mode="local_dry_run",
        ci_evidence={"ci_status": "passed", "steps_executed": 6, "runner_id": 4821},
    )
    zero_step = next(item for item in report["diagnostics"] if item["code"] == "zero_step_ci")
    assert zero_step["status"] == "ok"
    assert zero_step["failure_details"]["runner_id"] == 4821


def test_run_all_diagnostics_fails_closed_on_malformed_ci_evidence():
    """A non-mapping ci_evidence must not crash run_all_diagnostics or be
    silently ignored as if it were never supplied -- it is surfaced as its
    own detected diagnostic instead."""
    report = run_all_diagnostics(environ={}, mode="local_dry_run", ci_evidence="not-a-mapping")
    zero_step = next(item for item in report["diagnostics"] if item["code"] == "zero_step_ci")
    assert zero_step["status"] == "detected"
    assert zero_step["failure_details"]["ci_status"] == "malformed"


def test_diagnose_malformed_report():
    # Non-dict
    res_bad_root = diagnose_malformed_report(["item"], ("schema", "status"))
    assert res_bad_root.status == "detected"

    # Missing fields
    res_missing = diagnose_malformed_report({"schema": "v1"}, ("schema", "status", "version"))
    assert res_missing.status == "detected"
    assert "status" in res_missing.failure_details["missing_fields"]

    # Valid report
    res_ok = diagnose_malformed_report({"schema": "v1", "status": "ok"}, ("schema", "status"))
    assert res_ok.status == "ok"


def test_diagnose_failed_healthcheck():
    # Unbound port
    res = diagnose_failed_healthcheck(port=59998)
    assert res.code == "failed_healthcheck"
    assert res.status == "detected"


def test_diagnose_port_collision():
    # Port 59997 should be available
    res = diagnose_port_collision(port=59997)
    assert res.code == "port_collision"
    assert res.status == "ok"


def test_diagnose_invalid_environment_contract():
    # Local dry-run with no mutation flags is valid
    res_ok = diagnose_invalid_environment_contract(environ={}, mode="local_dry_run")
    assert res_ok.status == "ok"

    # Staging missing required variables is detected
    res_err = diagnose_invalid_environment_contract(environ={}, mode="staging")
    assert res_err.status == "detected"
    assert len(res_err.failure_details["blockers"]) > 0


def test_run_all_diagnostics():
    report = run_all_diagnostics(environ={}, mode="local_dry_run")
    assert report["schema"] == "MarketOS.DeploymentDiagnostics.v1"
    assert "diagnostics" in report
    assert report["summary"]["total_checks"] == 10

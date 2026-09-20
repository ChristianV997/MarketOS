"""tests.test_service_delivery_dry_run -- Unit and integration tests for MarketOS

Service Delivery deployment dry-run and release smoke validation.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.deployment.service_delivery_smoke import (
    classify_service_delivery_ci,
    is_path_under_artifacts,
    probe_service_delivery_workbench,
    run_service_delivery_smoke,
    validate_service_delivery_projection,
)
from backend.deployment.diagnostics import (
    diagnose_service_delivery_readiness,
    diagnose_zero_step_ci,
)
from scripts.run_service_delivery_dry_run import main as cli_main


@pytest.fixture
def artifacts_tmp(tmp_path: Path):
    art = tmp_path / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    return art


def test_ci_zero_step_runner_allocation_failure_is_ci_unavailable():
    """Zero-step CI or runner allocation failures are classified as ci_unavailable, never failed."""
    # Billing limit / spending limit blocked runner
    res = classify_service_delivery_ci(
        runner_id=0,
        total_steps=0,
        ci_status="failure",
        logs_available=False,
        annotations=["The job was not started because recent account payments have failed or your spending limit needs to be increased."],
    )
    assert res["state"] == "ci_unavailable"
    assert res["root_cause"] == "github_actions_runner_allocation_failure"
    assert res["is_zero_step"] is True
    assert "spending limit" in res["classification_reason"]

    # Standard zero-step
    res2 = classify_service_delivery_ci(runner_id=0, total_steps=0, ci_status="ci_unavailable", logs_available=False)
    assert res2["state"] == "ci_unavailable"
    assert res2["root_cause"] == "ci_unavailable_zero_steps"
    assert res2["is_zero_step"] is True


def test_ci_executed_steps_failure_is_failed():
    """CI pipeline with executed steps that failed is classified as failed."""
    res = classify_service_delivery_ci(
        runner_id=12345,
        total_steps=8,
        ci_status="failed",
        logs_available=True,
    )
    assert res["state"] == "failed"
    assert res["root_cause"] == "ci_test_failure"
    assert res["is_zero_step"] is False


def test_ci_executed_steps_success_with_logs_is_passed():
    """CI pipeline with executed steps and accessible logs is classified as passed."""
    res = classify_service_delivery_ci(
        runner_id=12345,
        total_steps=15,
        ci_status="success",
        logs_available=True,
    )
    assert res["state"] == "passed"
    assert res["root_cause"] == "ci_passed"


def test_ci_success_without_logs_is_ci_unavailable():
    """CI claiming pass without audit logs fails closed to ci_unavailable."""
    res = classify_service_delivery_ci(
        runner_id=12345,
        total_steps=15,
        ci_status="success",
        logs_available=False,
    )
    assert res["state"] == "ci_unavailable"
    assert "inaccessible" in res["classification_reason"]


def test_diagnose_zero_step_ci_with_billing_annotations():
    """Diagnostic check identifies runner allocation issues honestly."""
    res = diagnose_zero_step_ci(
        ci_status="failure",
        steps_executed=0,
        runner_id=0,
        annotations=["spending limit needs to be increased"],
    )
    assert res.status == "detected"
    assert res.failure_details["runner_allocation_blocked"] is True
    assert "spending limit" in res.message


def test_service_delivery_projection_validation_passed(artifacts_tmp: Path):
    """Valid projection artifact under artifacts/ passes validation."""
    valid_data = {
        "schema_version": "service-engagement-projection-v1",
        "report_version": "service-engagement-projection-v1",
        "read_only": True,
        "network_calls": False,
        "mutated": False,
        "generated_at": "2026-09-19T00:00:00Z",
        "engagements": [
            {
                "package_id": "pkg_launch_accelerator",
                "lifecycle_state": "intake",
                "service_fee": {"amount": 2500, "currency": "USD"},
            }
        ],
    }
    proj_file = artifacts_tmp / "service_delivery_projection.json"
    proj_file.write_text(json.dumps(valid_data), encoding="utf-8")

    res = validate_service_delivery_projection(path=proj_file, artifacts_root=artifacts_tmp)
    assert res["status"] == "passed"
    assert res["reason"] == "valid_projection"
    assert res["row_count"] == 1
    assert res["is_artifact_safe"] is True
    assert res["leakage_detected"] is False


def test_service_delivery_projection_path_traversal_blocked(tmp_path: Path):
    """Path traversing outside artifacts directory is blocked fail-closed."""
    art_dir = tmp_path / "artifacts"
    art_dir.mkdir()
    outside_file = tmp_path / "outside.json"
    outside_file.write_text("{}", encoding="utf-8")

    res = validate_service_delivery_projection(path=outside_file, artifacts_root=art_dir)
    assert res["status"] == "blocked"
    assert res["reason"] == "projection_path_outside_artifacts"
    assert res["is_artifact_safe"] is False


def test_service_delivery_projection_workspace_leak_rejected(artifacts_tmp: Path):
    """Projection containing internal formulas/prompts is rejected with failed status."""
    leaky_data = {
        "schema_version": "service-engagement-projection-v1",
        "read_only": True,
        "network_calls": False,
        "mutated": False,
        "internal_formula": "cpa_target * 0.4",
        "engagements": [
            {
                "package_id": "pkg_audit",
                "internal_prompt": "Confidential internal system instructions",
            }
        ],
    }
    proj_file = artifacts_tmp / "leaky_projection.json"
    proj_file.write_text(json.dumps(leaky_data), encoding="utf-8")

    res = validate_service_delivery_projection(path=proj_file, artifacts_root=artifacts_tmp)
    assert res["status"] == "failed"
    assert res["reason"] == "service_delivery_projection_failed_workspace_isolation"
    assert res["leakage_detected"] is True
    assert any("internal_formula" in item for item in res["leakage_details"])


def test_service_delivery_projection_unsafe_flags_blocked(artifacts_tmp: Path):
    """Projection with mutated=True or read_only=False is blocked."""
    unsafe_data = {
        "schema_version": "service-engagement-projection-v1",
        "read_only": True,
        "network_calls": True,  # Unsafe!
        "mutated": False,
        "engagements": [],
    }
    proj_file = artifacts_tmp / "unsafe_projection.json"
    proj_file.write_text(json.dumps(unsafe_data), encoding="utf-8")

    res = validate_service_delivery_projection(path=proj_file, artifacts_root=artifacts_tmp)
    assert res["status"] == "blocked"
    assert res["reason"] == "unsafe_service_delivery_projection"


def test_service_delivery_projection_malformed_formats(artifacts_tmp: Path):
    """Invalid JSON, non-object root, and unsupported version are malformed."""
    # 1. Invalid JSON
    bad_json = artifacts_tmp / "bad.json"
    bad_json.write_text("{not valid json", encoding="utf-8")
    res1 = validate_service_delivery_projection(path=bad_json, artifacts_root=artifacts_tmp)
    assert res1["status"] == "malformed"
    assert res1["reason"] == "service_delivery_projection_invalid_json"

    # 2. Array root
    array_root = artifacts_tmp / "array.json"
    array_root.write_text("[]", encoding="utf-8")
    res2 = validate_service_delivery_projection(path=array_root, artifacts_root=artifacts_tmp)
    assert res2["status"] == "malformed"
    assert res2["reason"] == "service_delivery_projection_root_must_be_object"

    # 3. Unsupported version
    bad_ver = artifacts_tmp / "bad_ver.json"
    bad_ver.write_text(json.dumps({"schema_version": "unsupported-v99", "read_only": True}), encoding="utf-8")
    res3 = validate_service_delivery_projection(path=bad_ver, artifacts_root=artifacts_tmp)
    assert res3["status"] == "malformed"
    assert res3["reason"] == "unsupported_service_delivery_projection"


def test_service_delivery_workbench_probe_offline():
    """Probing workbench offline returns clean unavailable status on main (unmerged PR #271)."""
    res = probe_service_delivery_workbench(base_url=None)
    assert res["mode"] == "in_process"
    assert res["status"] == "unavailable"
    assert res["reason"] == "service_delivery_route_not_installed"


def test_service_delivery_workbench_probe_http_unreachable():
    """Probing unreachable HTTP host returns unavailable without unhandled exception."""
    res = probe_service_delivery_workbench(base_url="http://127.0.0.1:59996", timeout_seconds=0.5)
    assert res["mode"] == "http"
    assert res["status"] == "unavailable"
    assert res["reason"] == "service_unreachable"


def test_service_delivery_smoke_full_report_deterministic(artifacts_tmp: Path):
    """Full smoke report satisfies schema, read-only safety, and deterministic hash."""
    valid_data = {
        "schema_version": "service-engagement-projection-v1",
        "read_only": True,
        "network_calls": False,
        "mutated": False,
        "engagements": [],
    }
    proj_file = artifacts_tmp / "test_proj.json"
    proj_file.write_text(json.dumps(valid_data), encoding="utf-8")

    report = run_service_delivery_smoke(
        environ={},
        projection_path=proj_file,
        environment_mode="local_dry_run",
        artifacts_root=artifacts_tmp,
    )
    assert report.schema == "MarketOS.ServiceDeliverySmoke.v1"
    assert report.read_only is True
    assert report.network_calls is False
    assert report.mutated is False
    assert report.projection_check["status"] == "passed"
    assert len(report.deterministic_hash) == 64

    # Bit-identical replay verification
    report2 = run_service_delivery_smoke(
        environ={},
        projection_path=proj_file,
        environment_mode="local_dry_run",
        artifacts_root=artifacts_tmp,
    )
    assert report.deterministic_hash == report2.deterministic_hash


def test_service_delivery_smoke_mutation_flags_blocked(artifacts_tmp: Path):
    """Active live mutation flags cause overall_status to be blocked."""
    report = run_service_delivery_smoke(
        environ={"MARKETOS_ENABLE_LIVE_ACTIONS": "1", "SHOPIFY_WRITE_ENABLED": "1"},
        environment_mode="local_dry_run",
    )
    assert report.overall_status == "blocked"
    assert report.mutation_guard["status"] == "blocked"
    assert any("live_mutations_forbidden" in b for b in report.blockers)


def test_diagnose_service_delivery_readiness():
    """Diagnostic check identifies service delivery readiness state."""
    # When unconfigured
    res_unconf = diagnose_service_delivery_readiness(environ={})
    assert res_unconf.status == "detected"
    assert res_unconf.code == "service_delivery_readiness"


def test_cli_runner_script(capsys):
    """CLI script runs and outputs valid JSON with exit code 0 on clean offline mode."""
    exit_code = cli_main(["--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["schema"] == "MarketOS.ServiceDeliverySmoke.v1"
    assert data["read_only"] is True
    assert data["mutated"] is False

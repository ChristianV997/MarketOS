"""tests.test_service_delivery_dry_run -- Unit and integration tests for MarketOS

Service Delivery deployment dry-run and release smoke validation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

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


def test_ci_zero_step_annotation_does_not_infer_billing_cause():
    """Zero-step CI stays unavailable; free-form annotations do not prove a billing cause."""
    res = classify_service_delivery_ci(
        runner_id=0,
        total_steps=0,
        ci_status="failure",
        logs_available=False,
        annotations=["The job was not started because recent account payments have failed or your spending limit needs to be increased."],
    )
    assert res["state"] == "ci_unavailable"
    assert res["root_cause"] == "ci_unavailable_zero_steps"
    assert res["is_zero_step"] is True
    assert "unverified" in res["classification_reason"]
    assert "spending limit" not in res["classification_reason"]

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


@pytest.mark.parametrize("ci_status", ["failed", "failure"])
def test_ci_executed_failure_without_logs_remains_failed(ci_status):
    """Unavailable logs must not erase an executed runner's reported failure."""
    res = classify_service_delivery_ci(
        runner_id=12345,
        total_steps=15,
        ci_status=ci_status,
        logs_available=False,
    )
    assert res["state"] == "failed"
    assert res["root_cause"] == "ci_test_failure"


def test_diagnose_zero_step_ci_does_not_infer_billing_from_annotation_text():
    """A free-form billing annotation does not establish the true CI failure cause."""
    res = diagnose_zero_step_ci(
        ci_status="failure",
        steps_executed=0,
        runner_id=0,
        annotations=["spending limit needs to be increased"],
    )
    assert res.status == "detected"
    assert res.failure_details["runner_assigned"] is False
    assert res.failure_details["cause_verified"] is False
    assert "unverified" in res.message
    assert "spending limit" not in res.message


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
    """Probing workbench offline returns clean passed status on main (merged PR #271)."""
    res = probe_service_delivery_workbench(base_url=None)
    assert res["mode"] == "in_process"
    assert res["status"] == "passed"
    assert res["reason"] == "in_process_router_verified"


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


def test_projection_payload_invariants_reject_truthy_strings(artifacts_tmp: Path):
    """Projection with truthy string or int for network_calls/mutated must be blocked."""
    # 1. Truthy string
    payload1 = {
        "schema_version": "service-engagement-projection-v1",
        "read_only": True,
        "network_calls": "true",
        "mutated": False,
        "engagements": [],
    }
    f1 = artifacts_tmp / "truthy_str.json"
    f1.write_text(json.dumps(payload1), encoding="utf-8")
    res1 = validate_service_delivery_projection(path=f1, artifacts_root=artifacts_tmp)
    assert res1["status"] == "blocked"
    assert res1["reason"] == "unsafe_service_delivery_projection"

    # 2. Integer 1
    payload2 = {
        "schema_version": "service-engagement-projection-v1",
        "read_only": True,
        "network_calls": False,
        "mutated": 1,
        "engagements": [],
    }
    f2 = artifacts_tmp / "int_mutation.json"
    f2.write_text(json.dumps(payload2), encoding="utf-8")
    res2 = validate_service_delivery_projection(path=f2, artifacts_root=artifacts_tmp)
    assert res2["status"] == "blocked"
    assert res2["reason"] == "unsafe_service_delivery_projection"

    # 3. String read_only
    payload3 = {
        "schema_version": "service-engagement-projection-v1",
        "read_only": "true",
        "network_calls": False,
        "mutated": False,
        "engagements": [],
    }
    f3 = artifacts_tmp / "str_readonly.json"
    f3.write_text(json.dumps(payload3), encoding="utf-8")
    res3 = validate_service_delivery_projection(path=f3, artifacts_root=artifacts_tmp)
    assert res3["status"] == "blocked"
    assert res3["reason"] == "unsafe_service_delivery_projection"


def test_projection_payload_invariants_reject_omitted_flags(artifacts_tmp: Path):
    """Projection missing network_calls or mutated fields must fail-closed."""
    payload = {
        "schema_version": "service-engagement-projection-v1",
        "read_only": True,
        "engagements": [],
    }
    f = artifacts_tmp / "missing_flags.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    res = validate_service_delivery_projection(path=f, artifacts_root=artifacts_tmp)
    assert res["status"] == "blocked"
    assert res["reason"] == "unsafe_service_delivery_projection"


def test_projection_file_size_bounded(artifacts_tmp: Path, monkeypatch):
    """Files exceeding maximum allowed size must be rejected prior to parsing."""
    import backend.deployment.service_delivery_smoke as smoke_mod
    monkeypatch.setattr(smoke_mod, "MAX_PROJECTION_BYTES", 100)

    f = artifacts_tmp / "oversized.json"
    f.write_text(json.dumps({"schema_version": "service-engagement-projection-v1", "padding": "x" * 200}), encoding="utf-8")
    res = validate_service_delivery_projection(path=f, artifacts_root=artifacts_tmp)
    assert res["status"] == "malformed"
    assert res["reason"] == "service_delivery_projection_file_too_large"


def test_projection_directory_as_path_rejected(artifacts_tmp: Path):
    """Passing a directory instead of an artifact file fails closed."""
    subdir = artifacts_tmp / "subdir"
    subdir.mkdir()
    res = validate_service_delivery_projection(path=subdir, artifacts_root=artifacts_tmp)
    assert res["status"] == "unavailable"
    assert res["reason"] == "service_delivery_projection_is_directory"
    assert res["is_artifact_safe"] is False

    # Passing the root artifacts directory directly is rejected by allow_root=False
    res_root = validate_service_delivery_projection(path=artifacts_tmp, artifacts_root=artifacts_tmp)
    assert res_root["status"] == "blocked"
    assert res_root["reason"] == "projection_path_outside_artifacts"


def test_is_path_under_artifacts_null_byte_handled():
    """Null byte in path must not cause unhandled ValueError crash."""
    assert is_path_under_artifacts("artifacts/test.json\0.txt") is False


def test_is_path_under_artifacts_windows_backslash_normalized(artifacts_tmp: Path):
    """Windows backslashes resolve safely under artifacts."""
    f = artifacts_tmp / "nested" / "proj.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{}", encoding="utf-8")
    rel_win = f"artifacts\\nested\\proj.json"
    assert is_path_under_artifacts(rel_win, artifacts_root=artifacts_tmp) is True


def test_projection_workspace_isolation_detects_secret_values(artifacts_tmp: Path):
    """Projection containing secret values (Bearer token, API key) must be rejected."""
    payload = {
        "schema_version": "service-engagement-projection-v1",
        "read_only": True,
        "network_calls": False,
        "mutated": False,
        "engagements": [
            {
                "package_id": "product-validation-sprint",
                "notes": "Authorization: Bearer sk-live-secret-99998888",
            }
        ],
    }
    f = artifacts_tmp / "bearer_leak.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    res = validate_service_delivery_projection(path=f, artifacts_root=artifacts_tmp)
    assert res["status"] == "failed"
    assert res["reason"] == "service_delivery_projection_failed_workspace_isolation"
    assert res["leakage_detected"] is True
    assert any("forbidden_value_marker" in str(d) for d in res["leakage_details"])


def test_probe_service_delivery_workbench_ssrf_blocked():
    """Arbitrary URL schemes (such as file://) are blocked before making requests."""
    res = probe_service_delivery_workbench(base_url="file:///etc/passwd")
    assert res["status"] == "blocked"
    assert res["reason"] == "unsupported_url_scheme"


@pytest.mark.parametrize("base_url", ["https://example.invalid", "http://192.0.2.10:8080"])
def test_probe_service_delivery_workbench_non_loopback_blocked(base_url):
    """Remote endpoint probes are blocked without making a network request."""
    res = probe_service_delivery_workbench(base_url=base_url)
    assert res["status"] == "blocked"
    assert res["reason"] == "non_loopback_endpoint_blocked"


def test_probe_service_delivery_workbench_redacts_url_credentials():
    """Userinfo and query strings cannot be included in probe reports."""
    res = probe_service_delivery_workbench(
        base_url="http://probe-user:sentinel-42@127.0.0.1:3000?marker=sentinel-42"
    )
    assert res["status"] == "blocked"
    assert res["reason"] == "unsafe_base_url"
    assert "sentinel-42" not in json.dumps(res)


def test_probe_service_delivery_workbench_does_not_follow_redirects():
    """A loopback probe cannot redirect the request to a non-loopback host."""
    captured_handlers = []

    class RedirectingOpener:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 302, "redirect", {}, None)

    def fake_build_opener(*handlers):
        captured_handlers.extend(handlers)
        return RedirectingOpener()

    with patch(
        "backend.deployment.service_delivery_smoke.urllib_request.build_opener",
        side_effect=fake_build_opener,
    ):
        res = probe_service_delivery_workbench(base_url="http://127.0.0.1:3000")

    assert res["status"] == "failed"
    assert res["status_code"] == 302
    redirect_handler = next(handler for handler in captured_handlers if handler.__class__.__name__ == "_NoRedirectHandler")
    redirect_request = Request("http://127.0.0.1:3000/api/service-delivery/workbench")
    assert redirect_handler.redirect_request(
        redirect_request,
        None,
        302,
        "Found",
        {"Location": "https://example.invalid/collect"},
        "https://example.invalid/collect",
    ) is None


def test_probe_service_delivery_workbench_invalid_json_fails():
    """HTTP endpoint returning HTML or non-JSON payload returns failed status."""
    class FakeResponse:
        status = 200
        def read(self, n):
            return b"<html><body>Not JSON</body></html>"
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    class FakeOpener:
        def open(self, request, timeout):
            return FakeResponse()

    with patch(
        "backend.deployment.service_delivery_smoke.urllib_request.build_opener",
        return_value=FakeOpener(),
    ):
        res = probe_service_delivery_workbench(base_url="http://127.0.0.1:3000")
        assert res["status"] == "failed"
        assert res["reason"] == "invalid_json_endpoint_response"


def test_probe_service_delivery_workbench_does_not_retain_response_payload():
    """Valid endpoint bodies are parsed for shape but never copied into the report."""
    class FakeResponse:
        status = 200

        def read(self, n):
            return b'{"field":"marker-value-42"}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class FakeOpener:
        def open(self, request, timeout):
            return FakeResponse()

    with patch(
        "backend.deployment.service_delivery_smoke.urllib_request.build_opener",
        return_value=FakeOpener(),
    ):
        res = probe_service_delivery_workbench(base_url="http://127.0.0.1:3000")

    assert res["status"] == "passed"
    assert res["response_shape"] == "object"
    assert "response" not in res
    assert "marker-value-42" not in json.dumps(res)


def test_ci_failure_override_propagates_to_overall_status_and_exit_code(artifacts_tmp: Path):
    """Executed CI failure propagates to overall_status='failed' and exit code 1."""
    report = run_service_delivery_smoke(
        environ={},
        artifacts_root=artifacts_tmp,
        ci_override={
            "runner_id": 100,
            "total_steps": 10,
            "ci_status": "failed",
            "logs_available": True,
        },
    )
    assert report.overall_status == "failed"
    assert any("ci_failed" in b for b in report.blockers)

    # CLI exit code 1
    exit_code = cli_main(["--ci-status", "failed", "--ci-steps", "10", "--ci-runner-id", "100", "--ci-logs"])
    assert exit_code == 1


def test_cli_summary_mode(capsys):
    """CLI --summary mode outputs human-readable component headers and returns 0."""
    exit_code = cli_main(["--summary"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "MarketOS Service Delivery Deployment Dry-Run" in captured.out
    assert "Component Checks" in captured.out
    assert "Container Runtime" in captured.out


def test_cli_output_outside_artifacts_rejected(capsys):
    """CLI --output path outside artifacts directory returns exit code 1."""
    exit_code = cli_main(["--output", "../outside.json"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "must resolve under artifacts/" in captured.err


def test_cli_mutation_flags_return_exit_code_1(monkeypatch):
    """Active live mutation flag in environment causes CLI to exit with code 1."""
    monkeypatch.setenv("MARKETOS_ENABLE_LIVE_ACTIONS", "1")
    exit_code = cli_main(["--json"])
    assert exit_code == 1

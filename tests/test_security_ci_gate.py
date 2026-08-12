from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import evaluation.trustos.security_ci_gate as gate
from evaluation.trustos.control_plane import ACTION_CATEGORIES
from evaluation.trustos.security_ci_gate import (
    COMMAND_IDS,
    COMMAND_MODES,
    COMMAND_STATUSES,
    DECISIONS,
    SecurityCIGateConfig,
    SecurityCIGateReport,
    SecurityCISafetySummary,
    SecurityScannerArtifactPolicy,
    SecurityScannerCommand,
    SecurityScannerOutputPolicy,
    SecurityScannerTimeoutPolicy,
    build_scanner_allowlist,
    build_security_ci_gate_report,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "security_ci_gate"
CLI = ROOT / "scripts" / "run_security_ci_gate.py"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], cwd=ROOT, text=True, capture_output=True, check=False, timeout=60)


def test_default_report_is_deterministic_and_offline():
    first = build_security_ci_gate_report().to_dict()
    second = build_security_ci_gate_report().to_dict()
    assert first == second
    assert first["overall_decision"] == "soft_block"
    assert first["safety_summary"]["network_calls"] is False
    assert first["safety_summary"]["scanner_execution"] is False
    assert first["safety_summary"]["raw_outputs_stored"] is False


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_every_command_is_allowlisted(command_id: str):
    commands = build_scanner_allowlist(root_path=str(ROOT)).commands
    command = next(item for item in commands if item.command_id == command_id)
    assert command.command_id == command_id
    assert command.network_allowed is False
    assert command.credentials_required is False
    assert command.writes_artifacts is False
    assert command.redaction_required is True
    assert command.timeout_seconds > 0
    assert command.max_output_bytes > 0
    assert command.forbidden_paths


@pytest.mark.parametrize("mode", COMMAND_MODES)
def test_command_mode_vocabulary(mode: str):
    config = SecurityCIGateConfig(mode=mode)
    assert config.mode == mode


@pytest.mark.parametrize("status", COMMAND_STATUSES)
def test_execution_status_vocabulary(status: str):
    result = gate.SecurityScannerExecutionResult("gitleaks_detect", "gitleaks", status, None, 0, 0, False, False, False, False, False, True, "", ())
    assert result.status == status


@pytest.mark.parametrize("decision", DECISIONS)
def test_gate_decision_vocabulary(decision: str):
    item = gate.SecurityCIGateDecision("public_beta_launch", decision, "Synthetic decision.", (), (), "Review the next action.")
    assert item.decision == decision


def test_config_rejects_network():
    with pytest.raises(ValueError):
        SecurityCIGateConfig(network_allowed=True)


def test_config_rejects_credentials():
    with pytest.raises(ValueError):
        SecurityCIGateConfig(credentials_required=True)


def test_config_rejects_shell():
    with pytest.raises(ValueError):
        SecurityCIGateConfig(shell_allowed=True)


def test_config_rejects_zero_limits():
    with pytest.raises(ValueError):
        SecurityCIGateConfig(max_output_bytes=0)
    with pytest.raises(ValueError):
        SecurityCIGateConfig(default_timeout_seconds=0)


def test_allowlist_rejects_network():
    with pytest.raises(ValueError):
        gate.SecurityScannerAllowlist("bad", (), network_allowed=True)


def test_output_policy_rejects_raw_retention():
    with pytest.raises(ValueError):
        SecurityScannerOutputPolicy(100, True, False, False, "reject", "Synthetic")


def test_artifact_policy_rejects_writes():
    with pytest.raises(ValueError):
        SecurityScannerArtifactPolicy(True, (), True, True, False)


def test_safety_summary_rejects_network():
    with pytest.raises(ValueError):
        SecurityCISafetySummary(network_calls=True)


def test_timeout_policy_requires_positive_value():
    with pytest.raises(ValueError):
        SecurityScannerTimeoutPolicy(0, "blocked", "Synthetic")


@pytest.mark.parametrize("command_id", ["gitleaks_detect", "trufflehog_filesystem", "osv_scanner_lockfiles", "trivy_filesystem"])
def test_runnable_commands_default_to_planned_not_run(command_id: str):
    report = build_security_ci_gate_report(command_id=command_id)
    plan = report.execution_plans[0]
    assert plan.mode == "run_local_if_available"
    assert plan.status == "planned_not_run"
    assert report.execution_results == ()
    assert report.safety_summary.scanner_execution is False


@pytest.mark.parametrize("command_id", ["codeql_sarif_ingest", "semgrep_json_ingest", "semgrep_sarif_ingest", "manual_security_review_ingest"])
def test_ingest_commands_are_plan_only_by_default(command_id: str):
    plan = build_security_ci_gate_report(command_id=command_id).execution_plans[0]
    assert plan.mode == "ingest_existing_output"
    assert plan.status == "planned_not_run"
    assert plan.args == ()


def test_scorecard_is_plan_only():
    plan = build_security_ci_gate_report(command_id="openssf_scorecard_reference").execution_plans[0]
    assert plan.mode == "plan_only"
    assert plan.status == "planned_not_run"


@pytest.mark.parametrize("fixture_name,command_id", [
    ("gitleaks_sanitized_output.json", "gitleaks_detect"),
    ("osv_sanitized_output.json", "osv_scanner_lockfiles"),
    ("trivy_sanitized_output.json", "trivy_filesystem"),
    ("codeql_sarif_sanitized_output.json", "codeql_sarif_ingest"),
    ("semgrep_sanitized_output.json", "semgrep_json_ingest"),
    ("manual_review_sanitized_output.json", "manual_security_review_ingest"),
])
def test_sanitized_fixture_ingestion_uses_adapter(fixture_name: str, command_id: str):
    report = build_security_ci_gate_report(command_id=command_id, fixture_payload=load(fixture_name), fixture_source=f"fixture://{fixture_name}")
    assert report.execution_results[0].status == "ingested_fixture"
    assert report.normalization_results[0].adapter_report_version == "security-scanner-evidence-adapter-v1"
    assert report.normalization_results[0].finding_count >= 1
    assert report.safety_summary.scanner_execution is False


@pytest.mark.parametrize("fixture_name", ["secret_like_output_rejected.json", "raw_html_output_rejected.json"])
def test_unsafe_fixture_ingestion_is_rejected(fixture_name: str):
    with pytest.raises(ValueError):
        build_security_ci_gate_report(command_id="gitleaks_detect", fixture_payload=load(fixture_name), fixture_source=f"fixture://{fixture_name}")


def test_malformed_fixture_ingestion_is_rejected():
    with pytest.raises(ValueError):
        build_security_ci_gate_report(command_id="gitleaks_detect", fixture_payload=load("malformed_scanner_output.json"))


def test_fixture_evidence_and_impacts_are_retained():
    report = build_security_ci_gate_report(command_id="trivy_filesystem", fixture_payload=load("trivy_sanitized_output.json"))
    assert report.evidence_records
    assert report.gate_impacts
    assert report.evidence_records[0].redaction_status == "safe_summary_only"
    assert all(item.raw_output_stored is False for item in report.execution_results)


def test_critical_fixture_hard_blocks_public_launch():
    report = build_security_ci_gate_report(command_id="trivy_filesystem", fixture_payload=load("trivy_sanitized_output.json"), action="public_beta_launch")
    decision = report.decisions[0]
    assert decision.action == "public_beta_launch"
    assert decision.decision == "hard_block"


def test_high_dependency_fixture_soft_blocks_public_launch():
    report = build_security_ci_gate_report(command_id="osv_scanner_lockfiles", fixture_payload=load("osv_sanitized_output.json"), action="public_beta_launch")
    assert report.decisions[0].decision == "soft_block"


def test_low_secret_fixture_warns():
    report = build_security_ci_gate_report(command_id="gitleaks_detect", fixture_payload=load("gitleaks_sanitized_output.json"), action="public_beta_launch")
    assert report.decisions[0].decision == "warn"


def test_missing_security_evidence_soft_blocks_public_launch():
    report = build_security_ci_gate_report(action="public_beta_launch")
    assert report.decisions[0].decision == "soft_block"
    assert "security_scan_evidence" in report.decisions[0].missing_evidence


@pytest.mark.parametrize("action", ["activate_provider", "enable_live_model_calls", "client_workspace_export", "enable_public_signup", "run_provider_readonly_call"])
def test_missing_security_evidence_is_not_pass(action: str):
    report = build_security_ci_gate_report(action=action)
    assert report.decisions[0].decision in {"soft_block", "planned_not_run"}


def test_fixture_action_is_scoped_to_requested_action():
    report = build_security_ci_gate_report(command_id="gitleaks_detect", fixture_payload=load("gitleaks_sanitized_output.json"), action="activate_provider")
    assert len(report.decisions) == 1
    assert report.decisions[0].action == "activate_provider"


def test_local_run_requires_explicit_flag():
    report = build_security_ci_gate_report(command_id="gitleaks_detect", plan_only=True)
    assert report.execution_results == ()
    assert report.safety_summary.scanner_execution is False


def test_local_run_with_missing_executable_skips(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(gate.shutil, "which", lambda _: None)
    report = build_security_ci_gate_report(command_id="gitleaks_detect", run_local_scanners=True)
    assert report.execution_results[0].status == "skipped_unavailable"
    assert report.execution_results[0].error_code == "executable_unavailable"
    assert report.safety_summary.scanner_execution is True


def test_require_scanners_fails_when_unavailable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(gate.shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match="unavailable"):
        build_security_ci_gate_report(command_id="gitleaks_detect", run_local_scanners=True, require_scanners=True)


def _fake_completed(payload: dict, *, returncode: int = 0, stderr: bytes = b"") -> SimpleNamespace:
    return SimpleNamespace(stdout=json.dumps(payload).encode("utf-8"), stderr=stderr, returncode=returncode)


def test_allowlisted_local_run_normalizes_bounded_output(monkeypatch: pytest.MonkeyPatch):
    payload = {"findings": [{"id": "local-1", "category": "dependency_vulnerability", "severity": "low", "title": "Synthetic local result", "summary": "Synthetic local summary."}]}
    monkeypatch.setattr(gate.shutil, "which", lambda _: "C:/synthetic/gitleaks.exe")
    monkeypatch.setattr(gate.subprocess, "run", lambda *args, **kwargs: _fake_completed(payload))
    report = build_security_ci_gate_report(command_id="gitleaks_detect", run_local_scanners=True)
    assert report.execution_results[0].status == "executed_sanitized"
    assert report.normalization_results[0].finding_count == 1
    assert report.evidence_records
    assert report.safety_summary.raw_outputs_stored is False


def test_nonzero_scanner_exit_can_still_normalize_findings(monkeypatch: pytest.MonkeyPatch):
    payload = {"findings": [{"id": "local-1", "category": "secret_exposure", "severity": "high", "title": "Synthetic result", "summary": "Synthetic summary."}]}
    monkeypatch.setattr(gate.shutil, "which", lambda _: "C:/synthetic/gitleaks.exe")
    monkeypatch.setattr(gate.subprocess, "run", lambda *args, **kwargs: _fake_completed(payload, returncode=1))
    report = build_security_ci_gate_report(command_id="gitleaks_detect", run_local_scanners=True)
    assert report.execution_results[0].status == "executed_sanitized"
    assert report.decisions[0].decision == "hard_block"


def test_local_timeout_discards_output(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(gate.shutil, "which", lambda _: "C:/synthetic/gitleaks.exe")
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="gitleaks", timeout=1)
    monkeypatch.setattr(gate.subprocess, "run", timeout)
    report = build_security_ci_gate_report(command_id="gitleaks_detect", run_local_scanners=True)
    assert report.execution_results[0].status == "failed"
    assert report.execution_results[0].error_code == "timeout"
    assert report.execution_results[0].raw_output_stored is False


def test_local_output_cap_blocks(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(gate.shutil, "which", lambda _: "C:/synthetic/gitleaks.exe")
    monkeypatch.setattr(gate.subprocess, "run", lambda *args, **kwargs: _fake_completed({"findings": []}, stderr=b"x" * 100))
    config = SecurityCIGateConfig(mode="run_local_if_available", root_path=str(ROOT), max_output_bytes=10)
    report = build_security_ci_gate_report(command_id="gitleaks_detect", run_local_scanners=True, config=config)
    assert report.execution_results[0].status == "blocked_output_too_large"
    assert report.redaction_results[0].status == "rejected"


def test_local_secret_output_is_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(gate.shutil, "which", lambda _: "C:/synthetic/gitleaks.exe")
    monkeypatch.setattr(gate.subprocess, "run", lambda *args, **kwargs: _fake_completed({"api_key": "synthetic-key"}))
    report = build_security_ci_gate_report(command_id="gitleaks_detect", run_local_scanners=True)
    assert report.execution_results[0].status == "redacted_or_rejected"
    assert report.safety_summary.raw_outputs_stored is False


def test_local_invalid_json_is_discarded(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(gate.shutil, "which", lambda _: "C:/synthetic/gitleaks.exe")
    monkeypatch.setattr(gate.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=b"not-json", stderr=b"", returncode=0))
    report = build_security_ci_gate_report(command_id="gitleaks_detect", run_local_scanners=True)
    assert report.execution_results[0].status == "failed"
    assert report.execution_results[0].error_code == "unexpected_schema"


def test_subprocess_is_called_without_shell(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(gate.shutil, "which", lambda _: "C:/synthetic/gitleaks.exe")
    observed: dict = {}
    def fake_run(*args, **kwargs):
        observed.update(kwargs)
        return _fake_completed({"findings": []})
    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    build_security_ci_gate_report(command_id="gitleaks_detect", run_local_scanners=True)
    assert observed["shell"] is False
    assert observed["timeout"] > 0
    assert observed["capture_output"] is True


def test_forbidden_paths_are_in_command_args_policy():
    for command in build_scanner_allowlist(root_path=str(ROOT)).commands:
        assert ".git" in command.forbidden_paths
        assert "artifacts" in command.forbidden_paths
        assert "node_modules" in command.forbidden_paths


def test_root_path_is_allowlisted():
    command = build_scanner_allowlist(root_path=str(ROOT)).commands[0]
    assert str(ROOT) in command.allowed_paths
    assert all(".." not in item for item in command.safe_args)


def test_root_path_traversal_is_rejected():
    with pytest.raises(ValueError, match="traversal"):
        build_security_ci_gate_report(root_path="../outside")


def test_reports_do_not_include_raw_output_fields():
    report = build_security_ci_gate_report(command_id="gitleaks_detect", fixture_payload=load("gitleaks_sanitized_output.json"))
    rendered = json.dumps(report.to_dict()).lower()
    assert "actual_secret_value" not in rendered
    assert "raw stdout" not in rendered
    assert "raw stderr" not in rendered


def test_report_markdown_has_required_sections():
    markdown = build_security_ci_gate_report().to_markdown()
    for heading in ("Scanner Allowlist", "Availability", "Execution Results", "Redaction and Normalization", "TrustOS Gate Impacts", "Safety Boundaries"):
        assert f"## {heading}" in markdown


def test_report_serializes_as_expected_type():
    report = build_security_ci_gate_report()
    assert isinstance(report, SecurityCIGateReport)
    assert report.to_dict()["report_version"] == "security-ci-gate-v1"


def test_cli_json():
    result = run_cli("--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["safety_summary"]["network_calls"] is False
    assert data["overall_decision"] in DECISIONS


def test_cli_markdown():
    result = run_cli("--markdown")
    assert result.returncode == 0
    assert "# Security CI Gate" in result.stdout


def test_cli_plan_only():
    result = run_cli("--plan-only", "--markdown")
    assert result.returncode == 0
    assert "planned_not_run" in result.stdout


@pytest.mark.parametrize("command_id", ["gitleaks_detect", "osv_scanner_lockfiles", "trivy_filesystem"])
def test_cli_scanner_filter(command_id: str):
    result = run_cli("--scanner", command_id, "--json")
    assert result.returncode == 0
    assert json.loads(result.stdout)["command_count"] == 1


def test_cli_fixture_input():
    result = run_cli("--scanner", "gitleaks_detect", "--fixture", str(FIXTURES / "gitleaks_sanitized_output.json"), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["finding_count"] == 1
    assert data["execution_results"][0]["status"] == "ingested_fixture"


@pytest.mark.parametrize("action", ["public_beta_launch", "activate_provider"])
def test_cli_action(action: str):
    result = run_cli("--action", action, "--markdown")
    assert result.returncode == 0
    assert action in result.stdout


def test_cli_missing_scanner_is_graceful():
    result = run_cli("--run-local-scanners", "--scanner", "gitleaks_detect", "--markdown")
    assert result.returncode == 0
    assert "skipped_unavailable" in result.stdout or "executed_sanitized" in result.stdout


def test_cli_require_scanner_may_fail_closed():
    result = run_cli("--run-local-scanners", "--require-scanners", "--scanner", "gitleaks_detect", "--json")
    assert result.returncode in {0, 2}
    if result.returncode == 2:
        assert "unavailable" in result.stderr.lower()


def test_cli_rejects_traversal():
    result = run_cli("--fixture", str(ROOT.parent / "outside.json"), "--json")
    assert result.returncode != 0
    assert "inside the repository" in result.stderr


def test_cli_output_writes_sanitized_files(tmp_path: Path):
    output = tmp_path / "security-ci"
    result = run_cli("--scanner", "gitleaks_detect", "--output", str(output), "--json")
    assert result.returncode == 0
    expected = {"security_ci_gate_report.json", "security_ci_gate_report.md", "execution_plan.json", "execution_results_sanitized.json", "normalization_results.json", "trustos_evidence_records.json", "trustos_gate_impacts.json", "redaction_report.json", "scanner_availability.json"}
    assert expected == {item.name for item in output.iterdir()}
    assert all("synthetic-secret" not in item.read_text(encoding="utf-8") for item in output.iterdir())


def test_cli_unsafe_fixture_does_not_print_secret():
    result = run_cli("--scanner", "gitleaks_detect", "--fixture", str(FIXTURES / "secret_like_output_rejected.json"), "--json")
    assert result.returncode != 0
    assert "synthetic-secret-like-value" not in result.stderr


def test_cli_raw_html_fixture_rejected():
    result = run_cli("--scanner", "gitleaks_detect", "--fixture", str(FIXTURES / "raw_html_output_rejected.json"), "--json")
    assert result.returncode != 0
    assert "<html>" not in result.stderr


def test_cli_does_not_execute_by_default():
    result = run_cli("--scanner", "gitleaks_detect", "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["safety_summary"]["scanner_execution"] is False
    assert data["execution_results"] == []


def test_cli_has_no_network_dependency():
    source = CLI.read_text(encoding="utf-8").lower()
    assert "requests" not in source
    assert "httpx" not in source
    assert "urllib" not in source


def test_gate_module_has_no_network_client():
    source = (ROOT / "evaluation" / "trustos" / "security_ci_gate.py").read_text(encoding="utf-8").lower()
    assert "requests." not in source
    assert "httpx" not in source
    assert "urllib.request" not in source


def test_adapter_version_is_reused():
    report = build_security_ci_gate_report(command_id="gitleaks_detect", fixture_payload=load("gitleaks_sanitized_output.json"))
    assert report.normalization_results[0].adapter_report_version == "security-scanner-evidence-adapter-v1"


def test_evidence_records_are_trustos_records():
    report = build_security_ci_gate_report(command_id="gitleaks_detect", fixture_payload=load("gitleaks_sanitized_output.json"))
    assert all(isinstance(item, object) for item in report.evidence_records)
    assert all(item.source_type == "security_scanner_fixture" for item in report.evidence_records)


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_command_has_trustos_control_metadata(command_id: str):
    command = next(item for item in build_scanner_allowlist(root_path=str(ROOT)).commands if item.command_id == command_id)
    assert "security_baseline" in command.trustos_controls_covered
    assert "public_launch_readiness" in command.trustos_controls_covered


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_command_has_sanitized_artifact_policy(command_id: str):
    command = next(item for item in build_scanner_allowlist(root_path=str(ROOT)).commands if item.command_id == command_id)
    assert command.artifact_policy == "sanitized_outputs_only"
    assert command.redaction_required is True


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_command_plan_is_read_only(command_id: str):
    report = build_security_ci_gate_report(command_id=command_id)
    plan = report.execution_plans[0]
    assert plan.network_allowed is False
    assert plan.credentials_required is False
    assert plan.writes_artifacts is False
    assert plan.approval_required is True


@pytest.mark.parametrize("action", ACTION_CATEGORIES)
def test_trustos_actions_can_be_simulated_without_live_action(action: str):
    report = build_security_ci_gate_report(action=action)
    assert report.decisions[0].action == action
    assert report.safety_summary.network_calls is False
    assert report.safety_summary.external_services_called is False


@pytest.mark.parametrize("fixture_name,expected", [
    ("gitleaks_sanitized_output.json", "warn"),
    ("osv_sanitized_output.json", "soft_block"),
    ("trivy_sanitized_output.json", "hard_block"),
])
def test_fixture_decision_mapping(fixture_name: str, expected: str):
    command = {"gitleaks_sanitized_output.json": "gitleaks_detect", "osv_sanitized_output.json": "osv_scanner_lockfiles", "trivy_sanitized_output.json": "trivy_filesystem"}[fixture_name]
    report = build_security_ci_gate_report(command_id=command, fixture_payload=load(fixture_name), action="public_beta_launch")
    assert report.decisions[0].decision == expected


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_report_has_next_best_action(command_id: str):
    assert build_security_ci_gate_report(command_id=command_id).next_best_action


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_report_safety_flags(command_id: str):
    safety = build_security_ci_gate_report(command_id=command_id).safety_summary.to_dict()
    assert safety["read_only"] is True
    assert safety["network_calls"] is False
    assert safety["github_api_calls"] is False
    assert safety["credentials_read"] is False
    assert safety["raw_outputs_stored"] is False
    assert safety["uploads_performed"] is False


def test_execution_result_rejects_raw_storage():
    with pytest.raises(ValueError):
        gate.SecurityScannerExecutionResult("gitleaks_detect", "gitleaks", "failed", 1, 1, 0, False, True, False, False, False, True, "x", ())


def test_command_rejects_network():
    with pytest.raises(ValueError):
        SecurityScannerCommand("gitleaks_detect", "gitleaks", "Synthetic", "gitleaks", (), (str(ROOT),), (".git",), 10, 10, True, False, False, "sanitized", True, "gitleaks", (), "fixture_only")


def test_fixture_output_has_no_artifacts_by_default(tmp_path: Path):
    before = set(tmp_path.iterdir())
    build_security_ci_gate_report(command_id="gitleaks_detect", fixture_payload=load("gitleaks_sanitized_output.json"))
    assert set(tmp_path.iterdir()) == before


def test_plan_only_is_explicitly_safe():
    report = build_security_ci_gate_report(plan_only=True)
    assert all(item.status == "planned_not_run" for item in report.execution_plans)
    assert report.safety_summary.scanner_execution is False


def test_report_gate_impacts_are_sanitized():
    report = build_security_ci_gate_report(command_id="trivy_filesystem", fixture_payload=load("trivy_sanitized_output.json"))
    rendered = json.dumps([item.to_dict() for item in report.gate_impacts]).lower()
    assert "raw_payload" not in rendered
    assert "<html" not in rendered


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_plan_has_bounded_timeout(command_id: str):
    plan = build_security_ci_gate_report(command_id=command_id).execution_plans[0]
    assert plan.timeout_seconds <= 300


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_plan_has_bounded_output(command_id: str):
    plan = build_security_ci_gate_report(command_id=command_id).execution_plans[0]
    assert plan.max_output_bytes <= 10_000_000


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_plan_has_no_network(command_id: str):
    assert build_security_ci_gate_report(command_id=command_id).execution_plans[0].network_allowed is False


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_plan_has_no_credentials(command_id: str):
    assert build_security_ci_gate_report(command_id=command_id).execution_plans[0].credentials_required is False


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_plan_requires_approval_metadata(command_id: str):
    assert build_security_ci_gate_report(command_id=command_id).execution_plans[0].approval_required is True


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_plan_forbids_shell_and_uploads_by_policy(command_id: str):
    report = build_security_ci_gate_report(command_id=command_id)
    assert report.allowlist.shell_execution_allowed is False
    assert report.allowlist.artifact_upload_allowed is False


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_availability_is_not_checked_in_default_mode(command_id: str):
    item = build_security_ci_gate_report(command_id=command_id).availability[0]
    assert item.checked is False
    assert item.available is False


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_default_plan_never_has_execution_result(command_id: str):
    assert build_security_ci_gate_report(command_id=command_id).execution_results == ()


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_default_report_has_fail_closed_safety(command_id: str):
    assert build_security_ci_gate_report(command_id=command_id).safety_summary.fail_closed is True


@pytest.mark.parametrize("fixture_name,command_id", [
    ("gitleaks_sanitized_output.json", "gitleaks_detect"),
    ("osv_sanitized_output.json", "osv_scanner_lockfiles"),
    ("trivy_sanitized_output.json", "trivy_filesystem"),
    ("codeql_sarif_sanitized_output.json", "codeql_sarif_ingest"),
    ("semgrep_sanitized_output.json", "semgrep_json_ingest"),
    ("manual_review_sanitized_output.json", "manual_security_review_ingest"),
])
def test_fixture_result_never_stores_raw_output(fixture_name: str, command_id: str):
    report = build_security_ci_gate_report(command_id=command_id, fixture_payload=load(fixture_name))
    result = report.execution_results[0]
    assert result.raw_output_stored is False
    assert result.stderr_stored is False
    assert result.temp_files_deleted is True


@pytest.mark.parametrize("fixture_name,command_id", [
    ("gitleaks_sanitized_output.json", "gitleaks_detect"),
    ("osv_sanitized_output.json", "osv_scanner_lockfiles"),
    ("trivy_sanitized_output.json", "trivy_filesystem"),
    ("codeql_sarif_sanitized_output.json", "codeql_sarif_ingest"),
    ("semgrep_sanitized_output.json", "semgrep_json_ingest"),
    ("manual_review_sanitized_output.json", "manual_security_review_ingest"),
])
def test_fixture_normalization_is_bounded(fixture_name: str, command_id: str):
    result = build_security_ci_gate_report(command_id=command_id, fixture_payload=load(fixture_name)).normalization_results[0]
    assert result.finding_count <= 1000
    assert result.adapter_report_version.endswith("v1")


@pytest.mark.parametrize("action", ["public_beta_launch", "customer_facing_launch", "activate_provider", "use_credentials", "enable_public_signup", "enable_live_model_calls", "run_provider_readonly_call", "process_uploaded_file", "client_workspace_export"])
def test_required_security_actions_have_decisions(action: str):
    report = build_security_ci_gate_report(action=action)
    assert report.decisions[0].action == action
    assert report.decisions[0].decision in DECISIONS


@pytest.mark.parametrize("action", ["public_beta_launch", "activate_provider", "enable_live_model_calls"])
def test_no_run_high_priority_actions_never_pass(action: str):
    assert build_security_ci_gate_report(action=action).decisions[0].decision != "pass"


@pytest.mark.parametrize("command_id", ["gitleaks_detect", "trufflehog_filesystem", "osv_scanner_lockfiles", "trivy_filesystem"])
def test_local_plan_is_not_enabled_by_default(command_id: str):
    report = build_security_ci_gate_report(command_id=command_id)
    assert report.config.mode == "fixture_only"
    assert report.execution_plans[0].mode == "run_local_if_available"


@pytest.mark.parametrize("command_id", ["codeql_sarif_ingest", "semgrep_json_ingest", "semgrep_sarif_ingest", "manual_security_review_ingest"])
def test_ingest_plan_cannot_execute_a_binary(command_id: str):
    plan = build_security_ci_gate_report(command_id=command_id).execution_plans[0]
    assert plan.args == ()
    assert plan.status == "planned_not_run"


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_command_source_scanner_mapping_is_present(command_id: str):
    command = next(item for item in build_scanner_allowlist(root_path=str(ROOT)).commands if item.command_id == command_id)
    assert command.scanner_id == command.normalizer_scanner_id


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_command_execution_scope_is_repository_only(command_id: str):
    command = next(item for item in build_scanner_allowlist(root_path=str(ROOT)).commands if item.command_id == command_id)
    assert command.allowed_paths == (str(ROOT),)


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_command_artifact_policy_is_sanitized(command_id: str):
    command = next(item for item in build_scanner_allowlist(root_path=str(ROOT)).commands if item.command_id == command_id)
    assert command.artifact_policy == "sanitized_outputs_only"


@pytest.mark.parametrize("command_id", COMMAND_IDS)
def test_report_allowlist_has_unique_command_ids(command_id: str):
    report = build_security_ci_gate_report(command_id=command_id)
    ids = [item.command_id for item in report.allowlist.commands]
    assert len(ids) == len(set(ids))


def test_overall_decision_prioritizes_hard_block():
    report = build_security_ci_gate_report(command_id="trivy_filesystem", fixture_payload=load("trivy_sanitized_output.json"))
    assert report.overall_decision == "hard_block"


def test_overall_decision_prioritizes_soft_block_over_warning():
    report = build_security_ci_gate_report(command_id="osv_scanner_lockfiles", fixture_payload=load("osv_sanitized_output.json"))
    assert report.overall_decision == "soft_block"


def test_overall_decision_warns_when_only_low_fixture_finding_exists():
    report = build_security_ci_gate_report(command_id="gitleaks_detect", fixture_payload=load("gitleaks_sanitized_output.json"))
    assert report.overall_decision == "warn"


def test_output_policy_is_reported():
    policy = build_security_ci_gate_report().output_policy
    assert policy.raw_output_retained is False
    assert policy.raw_stdout_printed is False
    assert policy.raw_stderr_printed is False


def test_artifact_policy_is_reported():
    policy = build_security_ci_gate_report().artifact_policy
    assert policy.write_enabled is False
    assert policy.raw_files_forbidden is True
    assert policy.upload_enabled is False


def test_timeout_policy_is_reported():
    policy = build_security_ci_gate_report().timeout_policy
    assert policy.action == "blocked"
    assert policy.timeout_seconds > 0


def test_safety_summary_has_no_external_effects():
    data = build_security_ci_gate_report().safety_summary.to_dict()
    assert data["external_services_called"] is False
    assert data["artifacts_written"] is False
    assert data["uploads_performed"] is False


def test_fixture_source_is_metadata_only():
    report = build_security_ci_gate_report(command_id="gitleaks_detect", fixture_payload=load("gitleaks_sanitized_output.json"), fixture_source="fixture://gitleaks-ci")
    assert report.execution_results[0].notes
    assert "fixture://" not in report.execution_results[0].notes[0]

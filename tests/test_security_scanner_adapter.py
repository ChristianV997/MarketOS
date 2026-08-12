from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.trustos.control_plane import ACTION_CATEGORIES, EVIDENCE_STATUSES
from evaluation.trustos.security_scanner_adapter import (
    CATEGORIES,
    GATE_ACTIONS,
    INTEGRATION_MODES,
    SCANNER_IDS,
    SEVERITIES,
    SecurityFindingCategory,
    SecurityFindingSeverity,
    SecurityScanRedactionPolicy,
    SecurityScanSafetySummary,
    SecurityScannerAdapterReport,
    SecurityScannerOutputContract,
    SecurityScannerReference,
    build_scanner_references,
    build_security_scanner_report,
    parse_security_fixture,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "security_scanner_adapter"
CLI = ROOT / "scripts" / "run_security_scanner_adapter.py"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], cwd=ROOT, text=True, capture_output=True, check=False, timeout=60)


def test_default_report_is_deterministic_and_offline():
    first = build_security_scanner_report().to_dict()
    second = build_security_scanner_report().to_dict()
    assert first == second
    assert first["safety_summary"]["network_calls"] is False
    assert first["safety_summary"]["scanner_execution"] is False
    assert first["safety_summary"]["fail_closed"] is True


@pytest.mark.parametrize("scanner_id", SCANNER_IDS)
def test_every_scanner_reference_is_seeded(scanner_id: str):
    reference = next(item for item in build_scanner_references() if item.scanner_id == scanner_id)
    assert reference.integration_mode in INTEGRATION_MODES
    assert reference.run_mode == "normalize_fixture_only"
    assert reference.network_required is False
    assert reference.credentials_required is False
    assert reference.safe_to_run_in_ci_later is True


@pytest.mark.parametrize("severity", SEVERITIES)
def test_severity_vocabulary_serializes(severity: str):
    assert SecurityFindingSeverity(severity).to_dict()["value"] == severity


@pytest.mark.parametrize("category", CATEGORIES)
def test_category_vocabulary_serializes(category: str):
    assert SecurityFindingCategory(category).to_dict()["value"] == category


@pytest.mark.parametrize("fixture_name,scanner_id", [
    ("gitleaks_report_fixture.json", "gitleaks"),
    ("trufflehog_report_fixture.json", "trufflehog"),
    ("github_secret_scanning_fixture.json", "github_secret_scanning"),
    ("codeql_sarif_fixture.json", "codeql_sarif"),
    ("semgrep_json_fixture.json", "semgrep_json"),
    ("semgrep_sarif_fixture.json", "semgrep_sarif"),
    ("osv_scanner_fixture.json", "osv_scanner"),
    ("trivy_report_fixture.json", "trivy"),
    ("syft_sbom_fixture.json", "syft_sbom"),
    ("grype_report_fixture.json", "grype"),
    ("openssf_scorecard_fixture.json", "openssf_scorecard"),
    ("dependency_check_fixture.json", "owasp_dependency_check"),
    ("zap_baseline_fixture.json", "zap_baseline"),
    ("nuclei_fixture.json", "nuclei"),
    ("pyr_it_fixture.json", "pyr_it"),
    ("garak_fixture.json", "garak"),
    ("manual_security_review_fixture.json", "manual_security_review"),
])
def test_fixture_parser_supports_every_scanner(fixture_name: str, scanner_id: str):
    result = parse_security_fixture(load(fixture_name), scanner_id=scanner_id, source_file=f"fixture://{fixture_name}")
    assert result.status == "parsed"
    assert result.summary.scanner_id == scanner_id
    assert all(item.raw_payload_stored is False for item in result.findings)
    assert all(item.exploit_payload_stored is False for item in result.findings)
    assert all(item.status in EVIDENCE_STATUSES for item in result.evidence_records)


@pytest.mark.parametrize("fixture_name", [
    "secret_like_scanner_output_rejected.json",
    "raw_html_scanner_output_rejected.json",
    "exploit_payload_scanner_output_rejected.json",
])
def test_unsafe_fixture_is_rejected(fixture_name: str):
    with pytest.raises(ValueError):
        parse_security_fixture(load(fixture_name), scanner_id="gitleaks")


def test_malformed_fixture_is_rejected_safely():
    with pytest.raises(ValueError, match="must be a list"):
        parse_security_fixture(load("malformed_scanner_output.json"), scanner_id="gitleaks")


def test_fixture_mode_is_required():
    with pytest.raises(ValueError, match="fixture_mode"):
        parse_security_fixture({"findings": []}, scanner_id="gitleaks")


def test_finding_normalization_contains_safe_fields():
    finding = parse_security_fixture(load("osv_scanner_fixture.json"), scanner_id="osv_scanner").findings[0]
    data = finding.to_dict()
    assert data["category"] == "dependency_vulnerability"
    assert data["severity"] == "high"
    assert data["package_placeholder"] == "synthetic-package"
    assert data["source_ref"].startswith("fixture://")
    assert "raw_payload" not in data


@pytest.mark.parametrize("scanner_id,expected", [
    ("gitleaks", "secret_exposure"),
    ("osv_scanner", "dependency_vulnerability"),
    ("codeql_sarif", "code_vulnerability"),
    ("syft_sbom", "sbom_inventory"),
    ("openssf_scorecard", "repo_posture"),
    ("zap_baseline", "web_app_security"),
    ("pyr_it", "ai_prompt_injection"),
    ("manual_security_review", "manual_review"),
])
def test_scanner_category_mapping(scanner_id: str, expected: str):
    report = build_security_scanner_report(scanner=scanner_id)
    assert report.findings[0].category == expected


def test_critical_secret_has_public_provider_and_credential_blocks():
    payload = {"fixture_id": "critical-secret", "fixture_mode": True, "findings": [{"id": "secret-1", "category": "secret_exposure", "severity": "critical", "title": "Synthetic critical secret", "summary": "Synthetic summary only."}]}
    report = build_security_scanner_report(scanner="gitleaks", payload=payload)
    decisions = {(item.action, item.decision) for item in report.gate_impacts}
    assert ("public_beta_launch", "hard_block") in decisions
    assert ("activate_provider", "hard_block") in decisions
    assert ("use_credentials", "hard_block") in decisions


def test_critical_dependency_blocks_public_launch():
    payload = {"fixture_id": "critical-dep", "fixture_mode": True, "findings": [{"id": "dep-1", "category": "dependency_vulnerability", "severity": "critical", "title": "Synthetic dependency issue", "summary": "Synthetic summary only."}]}
    report = build_security_scanner_report(scanner="osv_scanner", payload=payload)
    impact = next(item for item in report.gate_impacts if item.action == "public_beta_launch")
    assert impact.decision == "hard_block"


def test_high_dependency_is_soft_block():
    payload = {"fixture_id": "high-dep", "fixture_mode": True, "findings": [{"id": "dep-1", "category": "dependency_vulnerability", "severity": "high", "title": "Synthetic dependency issue", "summary": "Synthetic summary only."}]}
    report = build_security_scanner_report(scanner="osv_scanner", payload=payload)
    impact = next(item for item in report.gate_impacts if item.action == "public_beta_launch")
    assert impact.decision == "soft_block"


def test_ai_prompt_injection_blocks_live_model_calls():
    payload = {"fixture_id": "prompt", "fixture_mode": True, "findings": [{"id": "ai-1", "category": "ai_prompt_injection", "severity": "high", "title": "Synthetic prompt injection", "summary": "Synthetic safety result only."}]}
    report = build_security_scanner_report(scanner="pyr_it", payload=payload)
    impact = next(item for item in report.gate_impacts if item.action == "enable_live_model_calls")
    assert impact.decision == "hard_block"
    assert report.ai_agent_activation_security_decision == "hard_block"


def test_ai_approval_bypass_blocks_external_action():
    payload = {"fixture_id": "bypass", "fixture_mode": True, "findings": [{"id": "ai-1", "category": "ai_approval_bypass", "severity": "critical", "title": "Synthetic approval bypass", "summary": "Synthetic safety result only."}]}
    report = build_security_scanner_report(scanner="garak", payload=payload)
    assert any(item.action == "activate_provider" and item.decision == "hard_block" for item in report.gate_impacts)
    assert any(item.action == "send_outbound_email" and item.decision == "hard_block" for item in report.gate_impacts)


def test_low_scorecard_score_warns():
    report = build_security_scanner_report(scanner="openssf_scorecard", payload=load("openssf_scorecard_fixture.json"))
    impact = next(item for item in report.gate_impacts if item.action == "public_beta_launch")
    assert impact.decision == "warn"


def test_sbom_inventory_is_planned_warning():
    report = build_security_scanner_report(scanner="syft_sbom", payload=load("syft_sbom_fixture.json"))
    assert any(item.decision == "warn" for item in report.gate_impacts)


def test_manual_review_requests_security_owner():
    report = build_security_scanner_report(scanner="manual_security_review", payload=load("manual_security_review_fixture.json"))
    impact = next(item for item in report.gate_impacts if item.action == "public_beta_launch")
    assert impact.decision == "needs_security_owner"


def test_report_contains_evidence_risks_and_coverage():
    report = build_security_scanner_report(scanner="gitleaks")
    assert report.evidence_records
    assert report.risk_items
    assert report.control_coverage
    assert report.redaction_policy.client_export_safe is True


def test_action_simulation_is_fail_closed():
    report = build_security_scanner_report(scanner="gitleaks", action="public_beta_launch")
    assert any(item.action == "public_beta_launch" for item in report.gate_impacts)
    assert report.safety_summary.fail_closed is True


@pytest.mark.parametrize("action", GATE_ACTIONS)
def test_supported_action_names_are_safe_to_plan(action: str):
    report = build_security_scanner_report(scanner="gitleaks", action=action)
    assert report.safety_summary.network_calls is False
    assert report.safety_summary.scanner_execution is False


def test_run_local_scanner_fails_closed():
    with pytest.raises(ValueError, match="blocked"):
        build_security_scanner_report(run_local_scanner=True)


def test_safety_dataclass_rejects_live_flags():
    with pytest.raises(ValueError):
        SecurityScanSafetySummary(network_calls=True)


def test_output_contract_rejects_raw_payload_permissions():
    with pytest.raises(ValueError):
        SecurityScannerOutputContract("bad", "gitleaks", ("json",), (), (), True, False, False, False)


def test_reference_rejects_credentials_required():
    with pytest.raises(ValueError):
        SecurityScannerReference("gitleaks", "Gitleaks", "secret_exposure", "normalize_fixture_now", "review", "use", ("json",), (), "warn", "normalize_fixture_only", False, True, True)


def test_redaction_policy_is_metadata_only():
    policy = build_security_scanner_report(scanner="gitleaks").redaction_policy.to_dict()
    assert "api_key" in policy["redacted_patterns"]
    assert "raw_html" in policy["rejected_patterns"]
    assert policy["client_export_safe"] is True


def test_markdown_contains_required_sections():
    markdown = build_security_scanner_report(scanner="gitleaks").to_markdown()
    for heading in ("Scanner Coverage", "Findings Summary", "TrustOS Evidence Mapping", "Gate Impacts", "Safety Boundaries"):
        assert f"## {heading}" in markdown


def test_cli_json():
    result = run_cli("--json")
    assert result.returncode == 0
    assert json.loads(result.stdout)["safety_summary"]["network_calls"] is False


def test_cli_markdown():
    result = run_cli("--markdown")
    assert result.returncode == 0
    assert "# Security Scanner Evidence Adapter" in result.stdout


@pytest.mark.parametrize("scanner_id", ["gitleaks", "codeql_sarif", "osv_scanner", "trivy", "garak"])
def test_cli_scanner_filter(scanner_id: str):
    result = run_cli("--scanner", scanner_id, "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["scanner_count"] == 1
    assert data["scanner_references"][0]["scanner_id"] == scanner_id


def test_cli_fixture_input():
    result = run_cli("--fixture", str(FIXTURES / "gitleaks_report_fixture.json"), "--json")
    assert result.returncode == 0
    assert json.loads(result.stdout)["finding_count"] == 1


def test_cli_action_public_beta_launch():
    result = run_cli("--scanner", "gitleaks", "--action", "public_beta_launch", "--markdown")
    assert result.returncode == 0
    assert "Public Launch Security Decision" in result.stdout


def test_cli_run_local_scanner_fails_closed():
    result = run_cli("--run-local-scanner", "--json")
    assert result.returncode != 0
    assert "blocked" in result.stderr.lower()


def test_cli_rejects_secret_fixture():
    result = run_cli("--fixture", str(FIXTURES / "secret_like_scanner_output_rejected.json"), "--scanner", "gitleaks", "--json")
    assert result.returncode != 0
    assert "secret" in result.stderr.lower()
    assert "not-a-real-secret" not in result.stderr


def test_cli_rejects_path_traversal():
    result = run_cli("--fixture", str(ROOT.parent / "outside.json"), "--json")
    assert result.returncode != 0
    assert "inside the repository" in result.stderr


def test_cli_writes_explicit_outputs(tmp_path: Path):
    output = tmp_path / "scanner-output"
    result = run_cli("--scanner", "gitleaks", "--output", str(output), "--json")
    assert result.returncode == 0
    expected = {"security_scanner_adapter_report.json", "security_scanner_adapter_report.md", "scanner_references.json", "normalized_findings.json", "trustos_evidence_records.json", "trustos_risk_items.json", "gate_impacts.json", "redaction_report.json", "scanner_integration_roadmap.json"}
    assert expected == {item.name for item in output.iterdir()}


@pytest.mark.parametrize("scanner_id", SCANNER_IDS)
def test_default_scanner_has_no_network_or_payload(scanner_id: str):
    report = build_security_scanner_report(scanner=scanner_id)
    assert report.safety_summary.network_calls is False
    assert report.safety_summary.raw_payloads_stored is False
    assert report.safety_summary.credentials_read is False


@pytest.mark.parametrize("scanner_id", ["gitleaks", "osv_scanner", "pyr_it", "manual_security_review"])
def test_each_priority_scanner_has_next_action(scanner_id: str):
    report = build_security_scanner_report(scanner=scanner_id)
    assert report.next_best_action


def test_no_scanner_source_invocation_in_adapter():
    source = (ROOT / "evaluation" / "trustos" / "security_scanner_adapter.py").read_text(encoding="utf-8").lower()
    assert "subprocess" not in source
    assert "requests." not in source
    assert "httpx" not in source


def test_no_scanner_source_invocation_in_cli():
    source = CLI.read_text(encoding="utf-8").lower()
    assert "subprocess" not in source
    assert "requests." not in source


def test_evidence_is_internal_and_summary_only():
    report = build_security_scanner_report(scanner="gitleaks")
    record = report.evidence_records[0].to_dict()
    assert record["internal_only"] is False
    assert record["redaction_status"] == "safe_summary_only"
    assert "raw" not in record["summary"].lower()


def test_all_report_safety_flags_are_false_or_readonly():
    safety = build_security_scanner_report().safety_summary.to_dict()
    assert safety["read_only"] is True
    assert all(value is False or key in {"read_only", "fail_closed"} for key, value in safety.items())


@pytest.mark.parametrize("fixture_name", ["gitleaks_report_fixture.json", "codeql_sarif_fixture.json", "osv_scanner_fixture.json", "trivy_report_fixture.json", "pyr_it_fixture.json"])
def test_fixture_parsing_is_repeatable(fixture_name: str):
    scanner = {"gitleaks_report_fixture.json": "gitleaks", "codeql_sarif_fixture.json": "codeql_sarif", "osv_scanner_fixture.json": "osv_scanner", "trivy_report_fixture.json": "trivy", "pyr_it_fixture.json": "pyr_it"}[fixture_name]
    payload = load(fixture_name)
    assert parse_security_fixture(payload, scanner_id=scanner).to_dict() == parse_security_fixture(payload, scanner_id=scanner).to_dict()


@pytest.mark.parametrize("scanner_id", SCANNER_IDS)
def test_reference_has_output_contract_metadata(scanner_id: str):
    reference = next(item for item in build_scanner_references() if item.scanner_id == scanner_id)
    assert reference.output_formats
    assert reference.trustos_controls_covered
    assert reference.license_note
    assert reference.recommended_use


@pytest.mark.parametrize("scanner_id", SCANNER_IDS)
def test_default_fixture_has_one_bounded_summary(scanner_id: str):
    report = build_security_scanner_report(scanner=scanner_id)
    assert len(report.summaries) == 1
    summary = report.summaries[0]
    assert summary.scanner_id == scanner_id
    assert summary.finding_count >= 1
    assert "Synthetic fixture" in summary.notes[0]


@pytest.mark.parametrize("scanner_id", SCANNER_IDS)
def test_normalized_evidence_has_trustos_metadata(scanner_id: str):
    report = build_security_scanner_report(scanner=scanner_id)
    evidence = report.evidence_records[0]
    assert evidence.evidence_id.startswith("evidence-")
    assert evidence.control_id.startswith("control-")
    assert evidence.source_type == "security_scanner_fixture"
    assert evidence.source_ref.startswith("fixture://")
    assert evidence.redaction_status == "safe_summary_only"


@pytest.mark.parametrize("scanner_id", SCANNER_IDS)
def test_normalized_findings_never_retain_raw_content(scanner_id: str):
    report = build_security_scanner_report(scanner=scanner_id)
    for finding in report.findings:
        data = finding.to_dict()
        assert data["raw_payload_stored"] is False
        assert data["exploit_payload_stored"] is False
        assert data["client_data_present"] is False
        assert len(finding.title) <= 280
        assert len(finding.summary) <= 280


@pytest.mark.parametrize("scanner_id", SCANNER_IDS)
def test_scanner_reports_have_safe_roadmap_entry(scanner_id: str):
    report = build_security_scanner_report(scanner=scanner_id)
    roadmap = next(item for item in report.scanner_integration_roadmap if item["scanner_id"] == scanner_id)
    assert roadmap["next_mode"] in {"run_ci_later", "study_later"}
    assert "TrustOS" in roadmap["activation_gate"]

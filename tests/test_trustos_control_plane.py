from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.trustos.control_plane import (
    ACTION_CATEGORIES,
    DOMAINS,
    EVIDENCE_STATUSES,
    EXCEPTION_STATUSES,
    GATE_BEHAVIORS,
    TrustActionManifest,
    TrustControl,
    TrustEvidenceRecord,
    TrustEvidenceRequirement,
    TrustGate,
    TrustSafetySummary,
    build_action_manifests,
    build_default_evidence,
    build_policy_packs_from_controls,
    build_trust_controls,
    build_trustos_report,
)
from evaluation.trustos.evidence_locker import build_evidence_locker
from evaluation.trustos.gate_runner import TrustGateContext, TrustGateInput, TrustGateRunner, evaluate_action
from evaluation.trustos.policy_packs import POLICY_PACK_IDS, build_policy_packs
from evaluation.trustos.public_launch_readiness import DECISIONS, build_public_launch_readiness
from evaluation.trustos.client_trustops_report import build_client_trustos_report
from evaluation.trustos.trustos_report import build_trustos_combined_report

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_trustos_control_plane.py"
FIXTURES = ROOT / "tests" / "fixtures" / "trustos"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=ROOT, text=True, capture_output=True, timeout=60)


def report():
    return build_trustos_report()


def test_report_is_deterministic():
    assert report().to_dict() == report().to_dict()
    assert report().to_markdown() == report().to_markdown()


def test_report_version_and_offline_posture():
    item = report()
    assert item.report_version == "trustos-control-plane-v1"
    assert item.safety_summary.read_only is True
    assert item.safety_summary.network_calls is False
    assert item.safety_summary.external_mutations is False


@pytest.mark.parametrize("domain", DOMAINS)
def test_domain_vocabulary(domain):
    assert domain in DOMAINS
    assert any(control.domain == domain for control in build_trust_controls())


@pytest.mark.parametrize("behavior", GATE_BEHAVIORS)
def test_gate_behavior_vocabulary(behavior):
    assert behavior in GATE_BEHAVIORS


@pytest.mark.parametrize("status", EXCEPTION_STATUSES)
def test_exception_status_vocabulary(status):
    assert status in EXCEPTION_STATUSES


@pytest.mark.parametrize("status", EVIDENCE_STATUSES)
def test_evidence_status_vocabulary(status):
    assert status in EVIDENCE_STATUSES


@pytest.mark.parametrize("action", ACTION_CATEGORIES)
def test_action_manifest_serializes(action):
    item = next(entry for entry in build_action_manifests() if entry.action == action)
    assert item.to_dict()["action"] == action
    assert item.default_gate in GATE_BEHAVIORS


def test_action_manifest_rejects_unknown_action():
    with pytest.raises(ValueError):
        TrustActionManifest("unknown", "Unknown", True, "hard_block", "none")


def test_control_registry_is_substantial():
    controls = build_trust_controls()
    assert len(controls) >= 60
    assert len({item.control_id for item in controls}) == len(controls)


@pytest.mark.parametrize("control", build_trust_controls(), ids=lambda item: item.control_id)
def test_control_has_required_policy_metadata(control):
    assert control.name and control.description
    assert control.applies_to_actions
    assert control.owner_department
    assert control.evidence_required
    assert control.source_refs
    assert control.review_frequency_days > 0
    assert control.status == "planned"


@pytest.mark.parametrize("control", build_trust_controls(), ids=lambda item: item.control_id)
def test_control_evidence_requirements_are_structured(control):
    for requirement in control.evidence_required:
        assert requirement.evidence_type
        assert requirement.description
        assert requirement.required is True


def test_control_invalid_domain_rejected():
    with pytest.raises(ValueError):
        TrustControl("bad", "Bad", "not-a-domain", "x", "x", ("publish_site",), ("risk_approval",), ("global",), "high", (), "hard_block", "none", (), 30, "risk_approval", False)


def test_control_invalid_action_rejected():
    with pytest.raises(ValueError):
        TrustControl("bad", "Bad", "security", "x", "x", ("send_secret",), ("risk_approval",), ("global",), "high", (), "hard_block", "none", (), 30, "risk_approval", False)


@pytest.mark.parametrize("pack_id", POLICY_PACK_IDS)
def test_policy_pack_exists(pack_id):
    packs = build_policy_packs()
    assert pack_id in {pack.pack_id for pack in packs}


def test_policy_pack_counts_and_sources():
    packs = build_policy_packs()
    assert len(packs) == 7
    assert all(pack.controls and pack.source_refs for pack in packs)


@pytest.mark.parametrize("pack", build_policy_packs(), ids=lambda item: item.pack_id)
def test_policy_pack_controls_match_category(pack):
    assert all(control.category == pack.pack_id for control in pack.controls)
    assert all(control.domain in DOMAINS for control in pack.controls)


def test_security_baseline_controls_present():
    names = {item.name.lower() for item in next(pack for pack in build_policy_packs() if pack.pack_id == "security_baseline").controls}
    for term in ("secret scan", "dependency scan", "code scan", "audit logging"):
        assert term in names


def test_ai_security_controls_present():
    names = {item.name.lower() for item in next(pack for pack in build_policy_packs() if pack.pack_id == "ai_agent_security").controls}
    for term in ("prompt injection", "tool hijack", "approval bypass", "least privilege"):
        assert term in names


def test_provider_activation_controls_present():
    names = {item.name.lower() for item in next(pack for pack in build_policy_packs() if pack.pack_id == "provider_activation").controls}
    for term in ("provider registered", "credential reference", "terms review", "privacy review", "live disabled"):
        assert term in names


def test_privacy_legal_controls_require_review():
    pack = next(pack for pack in build_policy_packs() if pack.pack_id == "privacy_legal_baseline")
    assert any(item.professional_review_required for item in pack.controls)
    assert any(item.gate_behavior == "needs_professional_review" for item in pack.controls)


def test_tax_pack_disclaims_advice():
    pack = next(pack for pack in build_policy_packs() if pack.pack_id == "tax_accounting_readiness")
    assert pack.source_refs
    assert all(item.domain in {"tax", "financial_controls"} for item in pack.controls)


def test_public_launch_pack_has_isolation_control():
    pack = next(pack for pack in build_policy_packs() if pack.pack_id == "public_launch_readiness")
    assert any("workspace" in item.name.lower() for item in pack.controls)


def test_client_service_pack_has_minimal_export_control():
    pack = next(pack for pack in build_policy_packs() if pack.pack_id == "client_trustos_service")
    assert any("minimal export" in item.name.lower() for item in pack.controls)


def test_evidence_record_serializes():
    item = build_default_evidence()[0]
    data = item.to_dict()
    assert data["evidence_id"]
    assert data["status"] in EVIDENCE_STATUSES
    assert "secret" not in json.dumps(data).lower()


def test_evidence_client_internal_exclusivity():
    with pytest.raises(ValueError):
        TrustEvidenceRecord("id", "control", "source", "ref", "summary", "risk_approval", "now", "later", "draft", "none", True, True, False)


def test_evidence_locker_is_metadata_only():
    locker = build_evidence_locker(build_default_evidence())
    assert locker.artifacts_stored is False
    assert locker.records
    assert locker.missing()
    assert locker.export_policy.cross_client_isolation is True


def test_evidence_locker_has_redactions_and_sources():
    locker = build_evidence_locker(build_default_evidence())
    assert len(locker.redactions) == len(locker.records)
    assert locker.sources
    assert all(item.metadata_only for item in locker.sources)


def test_evidence_locker_rejects_artifact_storage():
    with pytest.raises(ValueError):
        from evaluation.trustos.evidence_locker import TrustEvidenceLocker
        TrustEvidenceLocker((), (), (), (), build_evidence_locker().export_policy, True)


@pytest.mark.parametrize("action", ("activate_provider", "run_provider_readonly_call", "run_provider_write_call"))
def test_provider_actions_block_without_prerequisites(action):
    result = evaluate_action(action)
    assert result.decision == "hard_block"
    assert result.blockers
    assert "approval_recorded required" in result.blockers


def test_provider_action_can_reach_review_only_with_all_metadata():
    result = evaluate_action("activate_provider", context={"provider_registered": True, "credential_reference_exists": True, "secret_value_absent": True, "approval_recorded": True, "budget_cap_set": True, "terms_review_complete": True, "privacy_review_complete": True, "output_contract_tested": True})
    assert result.decision == "needs_professional_review"
    assert result.simulated is True
    assert "Live transport" in result.warnings[0]


@pytest.mark.parametrize("action", ("send_outbound_email", "send_customer_message"))
def test_outreach_requires_consent_and_unsubscribe(action):
    result = evaluate_action(action)
    assert result.decision == "hard_block"
    assert "consent_verified required" in result.blockers
    assert "unsubscribe_present required" in result.blockers


def test_outreach_do_not_contact_blocks():
    result = evaluate_action("send_outbound_email", context={"consent_verified": True, "unsubscribe_present": True, "ai_disclosure_present": True, "do_not_contact": True})
    assert result.decision == "hard_block"
    assert "do_not_contact is true" in result.blockers


def test_outreach_with_conditions_never_sends():
    result = evaluate_action("send_outbound_email", context={"consent_verified": True, "unsubscribe_present": True, "ai_disclosure_present": True})
    assert result.decision == "needs_professional_review"
    assert result.simulated is True


def test_live_model_calls_require_spend_controls():
    result = evaluate_action("enable_live_model_calls")
    assert result.decision == "hard_block"
    assert "model-spend controls" in result.blockers[0]


def test_live_model_calls_remain_review_only():
    result = evaluate_action("enable_live_model_calls", context={"model_spend_controls": True, "approval_recorded": True, "budget_cap_set": True})
    assert result.decision == "needs_professional_review"
    assert "model calls" in result.warnings[0]


@pytest.mark.parametrize("action", ("create_payment", "create_order", "launch_ad", "sync_accounting", "use_credentials"))
def test_high_risk_actions_blocked(action):
    result = evaluate_action(action)
    assert result.decision == "hard_block"
    assert result.blockers


def test_payment_requires_accountant_review():
    result = evaluate_action("create_payment")
    assert "accountant review required" in result.blockers
    assert "payment_creation" in result.required_approvals


def test_site_publish_requires_security_policy_and_approval():
    result = evaluate_action("publish_site")
    assert result.decision == "hard_block"
    assert "security_evidence_present required" in result.blockers
    assert "lawyer_review required" in result.blockers


def test_site_publish_with_metadata_reaches_professional_review():
    result = evaluate_action("publish_site", context={"security_evidence_present": True, "policies_present": True, "incident_response_present": True, "approval_recorded": True, "lawyer_review": True})
    assert result.decision == "needs_professional_review"


def test_public_beta_is_blocked_by_default():
    result = evaluate_action("public_beta_launch")
    assert result.decision == "hard_block"
    assert len(result.blockers) >= 5


def test_client_export_blocks_internal_leakage():
    result = evaluate_action("client_workspace_export")
    assert result.decision == "hard_block"
    assert "internal_notes_excluded required" in result.blockers


def test_client_export_allows_safe_projection_only():
    result = evaluate_action("client_workspace_export", context={"client_isolated": True, "internal_notes_excluded": True})
    assert result.decision == "allow"


def test_personal_data_requires_privacy_controls():
    result = evaluate_action("collect_personal_data")
    assert result.decision == "hard_block"
    assert result.blockers


def test_sanitized_upload_reaches_allowed_path():
    result = evaluate_action("process_uploaded_file", context={"uploaded_file_sanitized": True})
    assert result.decision == "allow"


def test_unsanitized_upload_needs_review():
    result = evaluate_action("process_uploaded_file")
    assert result.decision == "needs_professional_review"


def test_gate_runner_class_matches_function():
    runner = TrustGateRunner()
    item = TrustGateInput("activate_provider", context={})
    assert runner.evaluate(item).to_dict() == evaluate_action("activate_provider").to_dict()
    assert runner.simulate("public_beta_launch").decision == "hard_block"


def test_gate_input_rejects_unknown_action():
    with pytest.raises(ValueError):
        TrustGateInput("unknown")


@pytest.mark.parametrize("action", ACTION_CATEGORIES)
def test_every_supported_action_has_result(action):
    result = evaluate_action(action)
    assert result.action == action
    assert result.gate_id == f"gate-{action}"
    assert result.simulated is True


def test_gate_serializes():
    gate = next(item for item in report().gates if item.action == "activate_provider")
    assert gate.to_dict()["default_decision"] == "hard_block"
    assert gate.required_approvals


def test_launch_readiness_default_decision():
    item = build_public_launch_readiness()
    assert item.decision.decision == "blocked_for_public_beta"
    assert item.blockers
    assert item.required_evidence


def test_launch_readiness_has_all_areas():
    item = build_public_launch_readiness()
    assert {area.area_id for area in item.areas} == {"security", "privacy", "legal", "tax", "ai_governance", "provider_activation", "credential_safety", "approval_controls", "client_workspace_isolation", "incident_response", "financial_controls"}


@pytest.mark.parametrize("decision", DECISIONS)
def test_launch_decision_vocabulary(decision):
    from evaluation.trustos.public_launch_readiness import LaunchGoNoGoDecision
    assert LaunchGoNoGoDecision(decision, "placeholder", (), "next").decision == decision


@pytest.mark.parametrize("area", build_public_launch_readiness().areas, ids=lambda item: item.area_id)
def test_launch_area_has_evidence_and_owner(area):
    assert area.required_evidence
    assert area.owner_department
    assert 0 <= area.score <= 100


def test_launch_readiness_score_is_bounded():
    assert 0 <= build_public_launch_readiness().score.score <= 100
    assert build_public_launch_readiness().score.hard_blockers > 0


def test_launch_readiness_professional_exceptions_are_placeholders():
    item = build_public_launch_readiness()
    assert item.exceptions
    assert all("conclusion" in exception.reason.lower() for exception in item.exceptions)


def test_launch_markdown_has_required_sections():
    markdown = build_public_launch_readiness().to_markdown()
    for heading in ("## Decision", "## Areas", "## Blockers", "## Required Evidence", "## Safety Boundaries"):
        assert heading in markdown


def test_client_report_excludes_internal_notes_in_safe_projection():
    item = build_client_trustos_report(evidence=build_default_evidence(), risks=report().risks)
    safe = item.to_dict(client_safe=True)
    assert "internal_notes" not in safe
    assert "prompt" not in json.dumps(safe).lower()


def test_client_report_separates_internal_notes():
    item = build_client_trustos_report(evidence=build_default_evidence(), risks=report().risks)
    assert item.internal_notes.excluded_from_client_export is True
    assert item.external_summary.status == "blocked_pending_review"


def test_client_safe_checklist_has_minimal_fields():
    item = build_client_trustos_report(evidence=build_default_evidence(), risks=report().risks)
    serialized = json.dumps(item.evidence_checklist.to_dict())
    for forbidden in ("raw_payload", "formula", "prompt", "source_code"):
        assert forbidden not in serialized


def test_lawyer_packet_disclaims_conclusion():
    packet = build_client_trustos_report().lawyer_packet
    assert any("No legal conclusion" in note for note in packet.disclaimers)


def test_accountant_packet_disclaims_advice():
    packet = build_client_trustos_report().accountant_packet
    assert any("No tax advice" in note for note in packet.disclaimers)


def test_security_packet_does_not_claim_scans():
    packet = build_client_trustos_report().security_packet
    assert any("No scan" in note for note in packet.disclaimers)


def test_client_report_markdown_is_external_by_default():
    markdown = build_client_trustos_report().to_markdown(client_safe=True)
    assert "Internal TrustOps Notes" not in markdown
    assert "Safety Boundaries" in markdown


def test_combined_report_counts_and_decisions():
    item = build_trustos_combined_report()
    data = item.to_dict()
    assert data["control_count"] >= 60
    assert data["policy_pack_count"] == 7
    assert data["public_launch_decision"] == "blocked_for_public_beta"
    assert data["provider_activation_decision"] == "blocked_for_live_provider_activation"
    assert data["client_workspace_export_decision"] == "hard_block"


def test_combined_report_contains_service_opportunities():
    item = build_trustos_combined_report()
    assert "Public Launch Readiness Audit" in item.service_package_opportunities
    assert "AI Agent Safety Audit" in item.service_package_opportunities


def test_combined_client_safe_projection_excludes_internal_structures():
    data = build_trustos_combined_report().to_dict(client_safe=True)
    assert "gate_results" not in data
    assert "integration_decisions" not in data
    assert "internal_notes" not in json.dumps(data)


def test_combined_markdown_has_sections():
    markdown = build_trustos_combined_report().to_markdown()
    for heading in ("# TrustOS Control Plane", "## Public Launch Readiness", "## Client-safe TrustOps Summary", "## Service Opportunities"):
        assert heading in markdown


def test_safety_summary_rejects_network():
    with pytest.raises(ValueError):
        TrustSafetySummary(network_calls=True)


def test_safety_summary_rejects_scanner_execution():
    with pytest.raises(ValueError):
        TrustSafetySummary(scanner_runs=True)


def test_safety_summary_rejects_credentials():
    with pytest.raises(ValueError):
        TrustSafetySummary(credentials_read=True)


def test_safety_summary_rejects_legal_conclusions():
    with pytest.raises(ValueError):
        TrustSafetySummary(legal_conclusions=True)


def test_safety_summary_rejects_tax_conclusions():
    with pytest.raises(ValueError):
        TrustSafetySummary(tax_conclusions=True)


def test_safety_summary_rejects_client_data():
    with pytest.raises(ValueError):
        TrustSafetySummary(client_data_present=True)


def test_fixture_inputs_are_sanitized():
    for path in FIXTURES.glob("*.json"):
        text = path.read_text(encoding="utf-8").lower()
        assert "-----begin" not in text
        assert "bearer " not in text


def test_default_cli_json():
    result = run_cli("--json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["report_version"] == "trustos-control-plane-v1"
    assert data["safety_summary"]["network_calls"] is False


def test_default_cli_markdown():
    result = run_cli("--markdown")
    assert result.returncode == 0
    assert result.stdout.startswith("# TrustOS Control Plane")
    assert "blocked_for_public_beta" in result.stdout


@pytest.mark.parametrize("action", ("activate_provider", "public_beta_launch", "client_workspace_export"))
def test_cli_action_result(action):
    result = run_cli("--action", action, "--json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["requested_action_result"]["action"] == action
    assert data["requested_action_result"]["simulated"] is True


@pytest.mark.parametrize("pack", POLICY_PACK_IDS)
def test_cli_policy_pack_filter(pack):
    result = run_cli("--policy-pack", pack, "--json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert {item["pack_id"] for item in data["policy_packs"]} == {pack}


def test_cli_client_safe():
    result = run_cli("--client-safe", "--json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert "gate_results" not in data
    assert "internal_notes" not in json.dumps(data)


def test_cli_context_input():
    result = run_cli("--context", str(FIXTURES / "gate_context_activate_provider.json"), "--action", "activate_provider", "--json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["requested_action_result"]["decision"] == "hard_block"


def test_cli_output_writes_only_declared_files(tmp_path):
    output = tmp_path / "trustos"
    result = run_cli("--output", str(output), "--markdown")
    assert result.returncode == 0, result.stderr
    expected = {"trustos_report.json", "trustos_report.md", "control_registry.json", "policy_packs.json", "evidence_locker.json", "gate_results.json", "public_launch_readiness.json", "client_trustops_report.md", "lawyer_ready_packet.md", "accountant_ready_packet.md", "security_reviewer_packet.md", "service_opportunities.json"}
    assert {item.name for item in output.iterdir()} == expected


def test_cli_rejects_path_traversal():
    result = run_cli("--context", "..\\tests\\fixtures\\trustos\\trustos_context.json", "--json")
    assert result.returncode == 2
    assert "path traversal" in result.stderr


def test_cli_rejects_external_input(tmp_path):
    path = tmp_path / "outside.json"
    path.write_text("{}", encoding="utf-8")
    result = run_cli("--context", str(path), "--json")
    assert result.returncode == 2
    assert "inside the repository" in result.stderr


def test_cli_rejects_secret_like_input():
    result = run_cli("--context", str(FIXTURES / "secret_like_trustos_input_rejected.json"), "--json")
    assert result.returncode == 2
    assert "secret-like" in result.stderr


def test_cli_rejects_client_leakage_fixture():
    result = run_cli("--context", str(FIXTURES / "client_data_leakage_fixture_rejected.json"), "--json")
    assert result.returncode == 2
    assert "secret-like" in result.stderr


def test_cli_rejects_two_formats():
    result = run_cli("--json", "--markdown")
    assert result.returncode != 0


def test_no_external_action_code_in_cli():
    source = SCRIPT.read_text(encoding="utf-8").lower()
    for forbidden in ("requests.get", "httpx", "smtplib", "send_email", "stripe", "subprocess.run"):
        if forbidden == "subprocess.run":
            continue
        assert forbidden not in source


def test_no_scanner_execution_in_control_plane():
    source = (ROOT / "evaluation" / "trustos" / "control_plane.py").read_text(encoding="utf-8").lower()
    assert "subprocess" not in source
    assert "requests" not in source
    assert "scanner_runs" in source


def test_existing_approval_request_vocabulary_reused():
    from evaluation.companyos.approval_ledger import REQUEST_TYPES
    assert "provider_call" in REQUEST_TYPES
    assert "site_publish" in REQUEST_TYPES
    assert "payment_creation" in REQUEST_TYPES


def test_trustos_does_not_define_second_provider_registry():
    source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "evaluation" / "trustos").glob("*.py"))
    assert "ProviderRegistryReport" not in source
    assert "build_provider_registry" not in source


def test_trustos_does_not_define_second_approval_ledger():
    source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "evaluation" / "trustos").glob("*.py"))
    assert "ApprovalLedgerReport" not in source
    assert "build_approval_ledger" not in source


def test_dataforseo_readiness_can_be_context_for_trustos():
    context = json.loads((FIXTURES / "dataforseo_readiness_sample.json").read_text(encoding="utf-8"))
    result = evaluate_action("activate_provider", context={"provider_registered": True, "credential_reference_exists": True, "secret_value_absent": context["secret_value_absent"], "output_contract_tested": True})
    assert result.decision == "hard_block"


def test_report_has_all_top_level_safety_posture():
    data = build_trustos_combined_report().to_dict()
    safety = data["safety_summary"]
    assert safety["read_only"] is True
    assert safety["network_calls"] is False
    assert safety["scanner_runs"] is False
    assert safety["credentials_read"] is False
    assert safety["legal_conclusions"] is False
    assert safety["tax_conclusions"] is False
    assert safety["external_mutations"] is False

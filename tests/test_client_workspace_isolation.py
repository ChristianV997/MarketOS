from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from evaluation.trustos.control_plane import ACTION_CATEGORIES
from evaluation.trustos.client_workspace_isolation import (
    ACCESS_MODES, CLIENT_EXPORT_FIELDS, CLONE_TYPES, DATA_CLASSES, LEAKAGE_STATUSES, MAX_CLIENT_EVIDENCE_EXPORT_BYTES,
    SERVICE_PACKAGES, WORKSPACE_STATUSES, WORKSPACE_TYPES, ClientWorkspaceCloneManifest, ClientWorkspaceDataClass,
    ClientWorkspaceEvidenceExport, ClientWorkspaceExportError, ClientWorkspaceIsolationReport, ClientWorkspaceLeakageCheck,
    ClientWorkspaceManifest, ClientWorkspacePermission,
    ClientWorkspaceSafetySummary, ClientWorkspaceVisibilityRule, build_client_workspace_isolation_report, check_workspace_leakage,
    export_client_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "client_workspace_isolation"
CLI = ROOT / "scripts" / "run_client_workspace_isolation.py"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def export_context(tmp_path):
    registry = WorkspaceRegistry(str(tmp_path / "workspaces.json"))
    workspace = registry.register(ClientWorkspace(workspace_id="client-alpha", name="client-alpha"))
    return workspace, registry


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], cwd=ROOT, text=True, capture_output=True, check=False, timeout=60)


def test_report_deterministic():
    assert build_client_workspace_isolation_report().to_dict() == build_client_workspace_isolation_report().to_dict()


def test_report_is_schema_only_and_safe():
    report = build_client_workspace_isolation_report()
    assert isinstance(report, ClientWorkspaceIsolationReport)
    assert report.safety_summary.read_only is True
    assert report.safety_summary.network_calls is False
    assert report.safety_summary.database_writes is False
    assert report.safety_summary.auth_calls is False
    assert report.safety_summary.tenant_created is False


@pytest.mark.parametrize("workspace_type", WORKSPACE_TYPES)
def test_workspace_types_generate_safe_manifests(workspace_type: str):
    item = build_client_workspace_isolation_report(workspace_type=workspace_type).manifests[0]
    assert item.workspace_type == workspace_type
    assert item.status == "client_safe"
    assert item.cross_client_access is False
    assert item.source_code_access is False
    assert item.prompt_access is False
    assert item.scoring_formula_access is False
    assert item.global_provider_intelligence_access is False


@pytest.mark.parametrize("status", WORKSPACE_STATUSES)
def test_workspace_status_vocabulary(status: str):
    assert status in WORKSPACE_STATUSES


@pytest.mark.parametrize("access", ACCESS_MODES)
def test_access_mode_vocabulary(access: str):
    assert access in ACCESS_MODES


@pytest.mark.parametrize("data_class", DATA_CLASSES)
def test_data_class_has_visibility_rule(data_class: str):
    report = build_client_workspace_isolation_report()
    item = next(item for item in report.data_classes if item.data_class == data_class)
    rule = next(item for item in report.visibility_rules if item.data_class == data_class)
    assert item.default_visibility == rule.access_mode
    assert item.default_visibility in ACCESS_MODES


@pytest.mark.parametrize("data_class", ["internal_prompt", "internal_scoring_formula", "internal_heuristic", "internal_strategy_note", "internal_pricing_note", "internal_upsell_note", "internal_agent_instruction", "source_code"])
def test_internal_content_is_internal_only(data_class: str):
    item = next(item for item in build_client_workspace_isolation_report().data_classes if item.data_class == data_class)
    assert item.default_visibility == "internal_only"
    assert item.export_allowed is False


@pytest.mark.parametrize("data_class", ["global_provider_intelligence", "cross_client_learning"])
def test_global_and_cross_client_content_is_not_client_visible(data_class: str):
    item = next(item for item in build_client_workspace_isolation_report().data_classes if item.data_class == data_class)
    assert item.default_visibility != "client_visible"
    assert item.export_allowed is (data_class == "global_provider_intelligence")


def test_client_private_data_is_workspace_only():
    item = next(item for item in build_client_workspace_isolation_report().data_classes if item.data_class == "client_private_data")
    assert item.default_visibility == "workspace_only"


@pytest.mark.parametrize("data_class", ["client_safe_summary", "client_safe_blocker", "client_safe_evidence_requirement", "client_safe_approval_request", "client_safe_next_action", "client_safe_export_packet"])
def test_client_safe_classes_are_visible(data_class: str):
    item = next(item for item in build_client_workspace_isolation_report().data_classes if item.data_class == data_class)
    assert item.default_visibility == "client_visible"
    assert item.export_allowed is True


@pytest.mark.parametrize("data_class", ["lawyer_ready_packet", "accountant_ready_packet", "security_reviewer_packet"])
def test_professional_packets_require_redaction(data_class: str):
    item = next(item for item in build_client_workspace_isolation_report().data_classes if item.data_class == data_class)
    assert item.default_visibility == "redacted_summary_only"
    assert item.redaction_required is True


@pytest.mark.parametrize("clone_type", CLONE_TYPES)
def test_clone_manifests_are_curated_projections(clone_type: str):
    clone = build_client_workspace_isolation_report(clone_type=clone_type).clone_manifests[0]
    assert clone.clone_type == clone_type
    assert clone.generated_artifacts_allowed is False
    assert clone.excluded_internal_fields
    assert clone.client_visible_report_refs
    assert clone.status == "client_safe"


def test_clone_excludes_source_code_and_prompts():
    clone = build_client_workspace_isolation_report(clone_type="trustops_readiness_clone").clone_manifests[0]
    assert "source_code" in clone.excluded_internal_fields
    assert "internal_prompt" in clone.excluded_internal_fields
    assert "cross_client_learning" in clone.excluded_internal_fields


def test_export_policies_have_required_checks():
    for policy in build_client_workspace_isolation_report().export_policies:
        assert "leakage_check" in policy.required_checks
        assert "redaction_policy" in policy.required_checks
        assert policy.excluded_fields


def test_redaction_policy_is_strict():
    policy = build_client_workspace_isolation_report().redaction_policy
    assert policy.client_export_safe is True
    assert "internal_prompt" in policy.redacted_data_classes
    assert "api_key" in policy.rejected_patterns


@pytest.mark.parametrize("fixture_name", ["internal_notes_leakage_fixture_rejected.json", "internal_prompt_leakage_fixture_rejected.json", "scoring_formula_leakage_fixture_rejected.json", "source_code_leakage_fixture_rejected.json", "cross_client_leakage_fixture_rejected.json", "global_provider_intelligence_leakage_fixture_rejected.json", "credential_metadata_leakage_fixture_rejected.json", "secret_like_workspace_input_rejected.json"])
def test_unsafe_payload_creates_hard_block(fixture_name: str):
    checks = check_workspace_leakage(load(fixture_name))
    assert checks
    assert any(item.status == "hard_block" for item in checks)


@pytest.mark.parametrize("key,data_class", [("internal_prompt", "internal_prompt"), ("internal_scoring_formula", "internal_scoring_formula"), ("internal_heuristic", "internal_heuristic"), ("internal_pricing_note", "internal_pricing_note"), ("source_code", "source_code"), ("cross_client_learning", "cross_client_learning"), ("global_provider_intelligence", "global_provider_intelligence"), ("api_key", "client_private_data")])
def test_leakage_finding_identifies_field(key: str, data_class: str):
    result = check_workspace_leakage({key: "synthetic placeholder"})[0]
    assert result.field_path == key
    assert result.data_class == data_class
    assert result.client_visible is False
    assert result.internal_only is True


def test_safe_client_report_passes_without_findings():
    assert check_workspace_leakage(load("safe_client_report_seed.json")) == ()


def test_professional_packet_requests_review():
    checks = check_workspace_leakage({"lawyer_ready_packet": {"status": "draft"}})
    assert checks[0].status == "requires_review"


def test_leakage_status_vocabulary():
    for status in LEAKAGE_STATUSES:
        item = ClientWorkspaceLeakageCheck("id", "internal_prompt", "field", "violation", "high", "remove", False, True, status)
        assert item.status == status


def test_leakage_blocks_workspace_export():
    report = build_client_workspace_isolation_report(payload=load("internal_prompt_leakage_fixture_rejected.json"))
    gate = next(item for item in report.gate_results if item.action == "client_workspace_export")
    assert gate.decision == "hard_block"


def test_leakage_blocks_clone_generation():
    report = build_client_workspace_isolation_report(payload=load("cross_client_leakage_fixture_rejected.json"))
    gate = next(item for item in report.gate_results if item.action == "client_clone_generation")
    assert gate.decision == "hard_block"


def test_leakage_blocks_workspace_activation():
    report = build_client_workspace_isolation_report(payload=load("source_code_leakage_fixture_rejected.json"))
    gate = next(item for item in report.gate_results if item.action == "client_workspace_activation")
    assert gate.decision == "hard_block"


def test_multi_client_access_is_blocked_by_default():
    gate = next(item for item in build_client_workspace_isolation_report().gate_results if item.action == "multi_client_workspace_access")
    assert gate.decision == "hard_block"


@pytest.mark.parametrize("action", ["lawyer_packet_export", "accountant_packet_export", "security_reviewer_packet_export"])
def test_professional_exports_require_review(action: str):
    gate = next(item for item in build_client_workspace_isolation_report().gate_results if item.action == action)
    assert gate.decision == "needs_professional_review"


def test_client_report_generation_is_allowed_projection():
    gate = next(item for item in build_client_workspace_isolation_report().gate_results if item.action == "client_report_generation")
    assert gate.decision == "allow"


@pytest.mark.parametrize("action", ACTION_CATEGORIES)
def test_all_trustos_actions_remain_simulation_only(action: str):
    report = build_client_workspace_isolation_report()
    assert all(item.action in ACTION_CATEGORIES for item in report.gate_results)
    assert report.safety_summary.network_calls is False


@pytest.mark.parametrize("package", SERVICE_PACKAGES)
def test_service_package_mapping_exists(package: str):
    mapping = next(item for item in build_client_workspace_isolation_report().service_package_mappings if item["service_package"] == package)
    assert mapping["default_workspace_type"] in WORKSPACE_TYPES
    assert mapping["client_visible_reports"]
    assert mapping["internal_only_reports"]
    assert "internal_upsell_notes" in mapping["internal_only_reports"]
    assert "internal_upsell_notes" not in mapping["client_visible_reports"]


def test_public_launch_pack_mapping():
    report = build_client_workspace_isolation_report(service_package="Public Launch Readiness Pack")
    assert report.manifests[0].created_for_service_package == "Public Launch Readiness Pack"


def test_service_package_filter_does_not_expose_internal_upsell():
    report = build_client_workspace_isolation_report(service_package="MarketOS Growth Retainer")
    rendered = json.dumps(report.to_dict())
    assert "internal_upsell_notes" in rendered
    assert "upsell strategy" not in rendered.lower()


def test_manifest_permissions_use_known_actions():
    for permission in build_client_workspace_isolation_report().manifests[0].permissions:
        assert permission.action in ACTION_CATEGORIES


def test_manifest_forbidden_actions_include_mutations():
    manifest = build_client_workspace_isolation_report().manifests[0]
    assert "use_credentials" in manifest.forbidden_actions
    assert "create_payment" in manifest.forbidden_actions
    assert "publish_site" in manifest.forbidden_actions


def test_manifest_policy_is_fail_closed():
    manifest = build_client_workspace_isolation_report().manifests[0]
    assert manifest.policy.cross_client_isolation is True
    assert manifest.policy.internal_content_excluded is True
    assert manifest.boundary.enforcement_mode == "fail_closed"


def test_manifest_scope_forbids_internal_data():
    scope = build_client_workspace_isolation_report().manifests[0].scope
    assert "internal_prompt" in scope.data_classes_forbidden
    assert "source_code" in scope.data_classes_forbidden
    assert "client_safe_summary" in scope.data_classes_allowed


def test_internal_external_summary_is_present():
    data = build_client_workspace_isolation_report().to_dict()
    assert "internal_external_separation_summary" in data
    assert "curated projections" in data["internal_external_separation_summary"]


def test_report_counts_are_present():
    data = build_client_workspace_isolation_report().to_dict()
    for key in ("workspace_count", "clone_manifest_count", "export_policy_count", "leakage_check_count", "hard_blocker_count", "warning_count", "client_safe_workspace_count", "blocked_workspace_count"):
        assert key in data


def test_report_markdown_sections():
    markdown = build_client_workspace_isolation_report().to_markdown()
    for heading in ("Workspace Manifests", "Internal vs External Data Classes", "Visibility Rules", "Clone Manifests", "Export Policies", "Leakage Checks", "TrustOS Gate Results", "Service Package Mapping", "Safety Boundaries"):
        assert f"## {heading}" in markdown


def test_cli_json():
    result = run_cli("--json")
    assert result.returncode == 0
    assert json.loads(result.stdout)["safety_summary"]["network_calls"] is False


def test_cli_markdown():
    result = run_cli("--markdown")
    assert result.returncode == 0
    assert "# Client Workspace Isolation Plan" in result.stdout


@pytest.mark.parametrize("workspace_type", ["client_trustops_workspace", "client_companyos_workspace", "client_launch_workspace"])
def test_cli_workspace_type(workspace_type: str):
    result = run_cli("--workspace-type", workspace_type, "--markdown")
    assert result.returncode == 0
    assert workspace_type in result.stdout


def test_cli_clone_type():
    result = run_cli("--clone-type", "trustops_readiness_clone", "--markdown")
    assert result.returncode == 0
    assert "trustops_readiness_clone" in result.stdout


def test_cli_service_package():
    result = run_cli("--service-package", "Public Launch Readiness Pack", "--markdown")
    assert result.returncode == 0
    assert "Public Launch Readiness Pack" in result.stdout


def test_cli_check_leakage():
    result = run_cli("--check-leakage", "--markdown")
    assert result.returncode == 0
    assert "Leakage Checks" in result.stdout


def test_cli_context_safe_report():
    result = run_cli("--context", str(FIXTURES / "safe_client_report_seed.json"), "--json")
    assert result.returncode == 0
    assert json.loads(result.stdout)["leakage_check_count"] == 0


def test_cli_context_leakage_is_reported():
    result = run_cli("--context", str(FIXTURES / "internal_prompt_leakage_fixture_rejected.json"), "--json")
    assert result.returncode == 0
    assert json.loads(result.stdout)["hard_blocker_count"] >= 1


def test_cli_rejects_traversal():
    result = run_cli("--context", str(ROOT.parent / "outside.json"), "--json")
    assert result.returncode != 0
    assert "inside the repository" in result.stderr


def test_cli_writes_sanitized_outputs(tmp_path: Path):
    output = tmp_path / "workspace"
    result = run_cli("--output", str(output), "--markdown")
    assert result.returncode == 0
    expected = {"client_workspace_isolation_report.json", "client_workspace_isolation_report.md", "workspace_manifests.json", "clone_manifests.json", "visibility_rules.json", "export_policies.json", "leakage_checks.json", "trustos_gate_results.json", "service_package_mappings.json"}
    assert expected == {item.name for item in output.iterdir()}
    assert all("synthetic internal prompt" not in item.read_text(encoding="utf-8") for item in output.iterdir())


def test_cli_is_deterministic():
    first = run_cli("--json"); second = run_cli("--json")
    assert first.stdout == second.stdout


def test_no_database_or_auth_in_module():
    source = (ROOT / "evaluation" / "trustos" / "client_workspace_isolation.py").read_text(encoding="utf-8").lower()
    assert "sqlalchemy" not in source
    assert "supabase" not in source
    assert "subprocess" not in source
    assert "requests" not in source


def test_no_client_data_in_default_report():
    rendered = json.dumps(build_client_workspace_isolation_report().to_dict()).lower()
    assert "real client" not in rendered
    assert "client@example" not in rendered
    assert "synthetic-secret-value" not in rendered


def test_safety_constructor_rejects_client_data():
    with pytest.raises(ValueError):
        ClientWorkspaceSafetySummary(client_data_present=True)


def test_manifest_constructor_rejects_source_access():
    base = build_client_workspace_isolation_report().manifests[0]
    with pytest.raises(ValueError):
        ClientWorkspaceManifest(**{**base.to_dict(), "source_code_access": True})


def test_clone_constructor_rejects_artifacts():
    base = build_client_workspace_isolation_report().clone_manifests[0]
    with pytest.raises(ValueError):
        ClientWorkspaceCloneManifest(**{**base.to_dict(), "generated_artifacts_allowed": True})


def test_permission_rejects_unknown_action():
    with pytest.raises(ValueError):
        ClientWorkspacePermission("bad", "workspace", "unknown_action", "blocked", False)


def test_visibility_rejects_unknown_class():
    with pytest.raises(ValueError):
        ClientWorkspaceVisibilityRule("bad", "unknown_class", "blocked", "condition", "hard_block")


def test_data_class_rejects_unknown_class():
    with pytest.raises(ValueError):
        ClientWorkspaceDataClass("unknown_class", "blocked", "bad", False, True)


def test_export_policy_serializes():
    policy = build_client_workspace_isolation_report().export_policies[0]
    assert policy.to_dict()["policy_id"].startswith("export-")


def test_redaction_policy_serializes():
    assert build_client_workspace_isolation_report().redaction_policy.to_dict()["client_export_safe"] is True


def test_safe_summary_does_not_expose_internal_notes():
    markdown = build_client_workspace_isolation_report().to_markdown()
    assert "exclude prompts" in markdown.lower()
    assert "no auth" in markdown.lower()


def test_service_mapping_exports_are_limited():
    for item in build_client_workspace_isolation_report().service_package_mappings:
        assert set(item["allowed_exports"]) <= {"client_safe_report", "professional_packet"}


def test_workspace_has_placeholder_client_id():
    assert build_client_workspace_isolation_report().manifests[0].client_id_placeholder == "client-placeholder"


def test_workspace_has_no_cross_client_access():
    assert build_client_workspace_isolation_report().manifests[0].cross_client_access is False


def test_workspace_provider_visibility_is_aggregated():
    assert build_client_workspace_isolation_report().manifests[0].provider_visibility == "aggregated_safe_summary_only"


def test_workspace_credentials_are_reference_only():
    assert build_client_workspace_isolation_report().manifests[0].credential_visibility == "reference_only"


def test_workspace_internal_notes_are_internal_only():
    assert build_client_workspace_isolation_report().manifests[0].internal_notes_visibility == "internal_only"


def test_workspace_actions_are_limited():
    assert set(build_client_workspace_isolation_report().manifests[0].allowed_actions) <= {"client_report_generation", "client_workspace_export"}


def test_report_has_risk_items():
    assert len(build_client_workspace_isolation_report().risks) >= 2


def test_report_has_six_clone_types():
    assert len(build_client_workspace_isolation_report().clone_manifests) == 6


def test_report_has_all_service_packages():
    assert len(build_client_workspace_isolation_report().service_package_mappings) == len(SERVICE_PACKAGES)


def test_report_version():
    assert build_client_workspace_isolation_report().report_version == "client-workspace-isolation-v1"


def test_client_safe_workspace_count():
    assert build_client_workspace_isolation_report().to_dict()["client_safe_workspace_count"] == 1


def test_leakage_check_paths_are_deterministic():
    first = check_workspace_leakage({"internal_prompt": {"text": "x"}})
    second = check_workspace_leakage({"internal_prompt": {"text": "x"}})
    assert first == second


def test_leakage_check_rejects_secret_marker():
    checks = check_workspace_leakage({"note": "-----BEGIN PRIVATE KEY-----"})
    assert checks[0].severity == "critical"


@pytest.mark.parametrize("candidate_id", ("desk-clamp-lamp", "desk-clamp-lamp-amazon-mirror"))
def test_leakage_check_accepts_hyphenated_candidate_identifier(candidate_id: str):
    assert check_workspace_leakage({"top_candidate_id": candidate_id}) == ()


def test_leakage_check_rejects_sk_secret_prefix_without_echoing_value():
    synthetic_secret = "sk-" + "SYNTHETICEXAMPLE0000"
    checks = check_workspace_leakage({"note": synthetic_secret})
    assert checks
    assert all(item.status == "hard_block" for item in checks)
    assert synthetic_secret not in str(checks)


def test_leakage_check_rejects_html_marker():
    checks = check_workspace_leakage({"note": "<html>unsafe</html>"})
    assert checks[0].status == "hard_block"


def test_leakage_check_does_not_store_payload():
    check = check_workspace_leakage({"internal_prompt": "synthetic"})[0]
    assert "synthetic" not in json.dumps(check.to_dict())


@pytest.mark.parametrize("workspace_type", WORKSPACE_TYPES)
def test_every_workspace_type_has_a_safe_manifest(workspace_type: str):
    report = build_client_workspace_isolation_report(workspace_type=workspace_type)
    manifest = report.manifests[0]
    assert manifest.workspace_type == workspace_type
    assert manifest.client_id_placeholder == "client-placeholder"
    assert manifest.cross_client_access is False
    assert manifest.source_code_access is False
    assert manifest.prompt_access is False
    assert manifest.scoring_formula_access is False


@pytest.mark.parametrize("clone_type", CLONE_TYPES)
def test_every_clone_type_is_a_projection(clone_type: str):
    report = build_client_workspace_isolation_report(clone_type=clone_type)
    clone = report.clone_manifests[0]
    assert clone.clone_type == clone_type
    assert clone.generated_artifacts_allowed is False
    assert "internal_prompt" in clone.excluded_internal_fields
    assert "source_code" in clone.excluded_internal_fields
    assert "cross_client_learning" in clone.excluded_internal_fields


@pytest.mark.parametrize("package_name", SERVICE_PACKAGES)
def test_every_service_package_has_client_safe_mapping(package_name: str):
    report = build_client_workspace_isolation_report(service_package=package_name)
    mapping = next(item for item in report.service_package_mappings if item["service_package"] == package_name)
    assert mapping["default_workspace_type"] in WORKSPACE_TYPES
    assert mapping["client_visible_reports"]
    assert mapping["allowed_exports"]
    assert "internal_upsell_notes" not in mapping["client_visible_reports"]
    assert "retainer_path" in mapping


@pytest.mark.parametrize("action", ["client_workspace_export", "client_clone_generation", "client_report_generation", "lawyer_packet_export", "accountant_packet_export", "security_reviewer_packet_export", "client_workspace_activation", "multi_client_workspace_access"])
def test_new_client_boundary_actions_are_registered(action: str):
    assert action in ACTION_CATEGORIES
    report = build_client_workspace_isolation_report()
    result = next(item for item in report.gate_results if item.action == action)
    assert result.decision in {"allow", "warn", "soft_block", "hard_block", "needs_professional_review", "not_applicable"}


@pytest.mark.parametrize("fixture_name", ["internal_notes_leakage_fixture_rejected.json", "internal_prompt_leakage_fixture_rejected.json", "scoring_formula_leakage_fixture_rejected.json", "source_code_leakage_fixture_rejected.json", "cross_client_leakage_fixture_rejected.json", "global_provider_intelligence_leakage_fixture_rejected.json", "credential_metadata_leakage_fixture_rejected.json"])
def test_each_rejected_fixture_produces_actionable_metadata(fixture_name: str):
    findings = check_workspace_leakage(load(fixture_name))
    assert findings
    assert all(item.field_path for item in findings)
    assert all(item.recommended_action for item in findings)
    assert all(item.client_visible is False for item in findings)


@pytest.mark.parametrize("key", ["internal_prompt", "internal_scoring_formula", "internal_heuristic", "internal_pricing_note", "source_code", "cross_client_learning", "api_key", "private_key", "password", "raw_html"])
def test_sensitive_key_never_survives_leakage_finding(key: str):
    findings = check_workspace_leakage({key: "synthetic-secret-value"})
    assert findings
    assert "synthetic-secret-value" not in json.dumps([item.to_dict() for item in findings])


@pytest.mark.parametrize("status", WORKSPACE_STATUSES)
def test_status_vocabulary_is_explicit(status: str):
    assert status in WORKSPACE_STATUSES
    report = build_client_workspace_isolation_report()
    assert report.manifests[0].status in WORKSPACE_STATUSES


@pytest.mark.parametrize("access_mode", ACCESS_MODES)
def test_access_mode_vocabulary_is_explicit(access_mode: str):
    assert access_mode in ACCESS_MODES
    report = build_client_workspace_isolation_report()
    assert all(item.default_visibility in ACCESS_MODES for item in report.data_classes)


def test_report_counts_match_nested_records():
    report = build_client_workspace_isolation_report(check_leakage=True)
    payload = report.to_dict()
    assert payload["workspace_count"] == len(report.manifests)
    assert payload["clone_manifest_count"] == len(report.clone_manifests)
    assert payload["export_policy_count"] == len(report.export_policies)
    assert payload["leakage_check_count"] == len(report.leakage_checks)


def test_safe_report_exposes_only_client_safe_next_action():
    report = build_client_workspace_isolation_report()
    assert "internal" in report.next_best_action.lower()
    assert "auth/database/RLS" in report.next_best_action


def test_policy_exports_do_not_include_secret_values():
    rendered = json.dumps(build_client_workspace_isolation_report().to_dict())
    for marker in ("synthetic-secret-value", "client@example.com", "BEGIN PRIVATE KEY"):
        assert marker not in rendered


def test_client_safe_summary_contains_required_fields():
    mapping = build_client_workspace_isolation_report().service_package_mappings[0]
    for key in ("client_visible_reports", "allowed_exports", "professional_packets", "upsell_paths", "retainer_path"):
        assert key in mapping


def test_professional_packets_are_review_bound():
    report = build_client_workspace_isolation_report()
    policy = report.redaction_policy
    assert policy.client_export_safe is True
    assert report.manifests[0].policy.professional_review_required is True
    professional_export = report.export_policies[1]
    assert professional_export.professional_review_required is True


def test_visibility_rules_cover_every_data_class():
    report = build_client_workspace_isolation_report()
    assert {item.data_class for item in report.visibility_rules} == set(DATA_CLASSES)


def test_clone_exports_are_nonempty_and_safe():
    for clone in build_client_workspace_isolation_report().clone_manifests:
        assert clone.client_visible_report_refs
        assert clone.export_scope == "workspace_only"
        assert clone.status in {"planned", "client_safe"}


def test_workspace_policy_is_fail_closed():
    policy = build_client_workspace_isolation_report().manifests[0].policy
    assert policy.internal_content_excluded is True
    assert policy.cross_client_isolation is True
    assert "internal_to_client_unredacted" in build_client_workspace_isolation_report().manifests[0].boundary.prohibited_flows


def test_boundary_allows_only_safe_projection_classes():
    boundary = build_client_workspace_isolation_report().manifests[0].boundary
    assert "client_safe_summary" in boundary.external_side
    assert "source_code" in boundary.internal_side
    assert boundary.enforcement_mode == "fail_closed"


def test_report_markdown_mentions_projection_not_fork():
    assert "curated projections" in build_client_workspace_isolation_report().to_markdown()


def test_client_evidence_export_preserves_safe_metadata_and_fingerprint(export_context):
    workspace, registry = export_context
    payload = {
        "workspace_id": "client-alpha",
        "status": "present",
        "blockers": [],
        "evidence_required": ["synthetic evidence review"],
        "approvals_required": ["human review"],
        "next_actions": ["review evidence from the approved source"],
    }
    exported = export_client_evidence(
        workspace=workspace,
        registry=registry,
        provenance="fixture://client-safe",
        evidence_state="present",
        payload=payload,
    )
    assert isinstance(exported, ClientWorkspaceEvidenceExport)
    assert exported.workspace_id == "client-alpha"
    assert exported.provenance == "fixture://client-safe"
    assert exported.evidence_state == "present"
    assert exported.payload == payload
    assert set(exported.payload) <= CLIENT_EXPORT_FIELDS
    assert exported.redaction_status == "validated_no_sensitive_fields"
    assert exported.redaction_policy_id == "client-workspace-redaction-v1"
    assert exported.redacted_fields == ()
    assert len(exported.fingerprint) == 64
    assert exported.payload_size_bytes <= MAX_CLIENT_EVIDENCE_EXPORT_BYTES


def test_client_evidence_export_fingerprint_is_canonical(export_context):
    workspace, registry = export_context
    first = export_client_evidence(
        workspace=workspace,
        registry=registry,
        provenance="fixture://client-safe",
        evidence_state="present",
        payload={"status": "present", "next_actions": ["review"], "blockers": []},
    )
    second = export_client_evidence(
        workspace=workspace,
        registry=registry,
        provenance="fixture://client-safe",
        evidence_state="present",
        payload={"blockers": [], "next_actions": ["review"], "status": "present"},
    )
    assert first.fingerprint == second.fingerprint
    assert first.to_dict() == second.to_dict()


@pytest.mark.parametrize("candidate", ["client-alpha", {"workspace_id": "client-alpha"}, None])
def test_client_evidence_export_rejects_raw_workspace_principals(candidate, export_context):
    _, registry = export_context
    with pytest.raises(ValueError, match="invalid client evidence export"):
        export_client_evidence(
            workspace=candidate,
            registry=registry,
            provenance="fixture://safe",
            evidence_state="present",
            payload={},
        )


@pytest.mark.parametrize(
    "candidate",
    [
        ClientWorkspace(workspace_id="client-unknown", name="unknown"),
        ClientWorkspace(workspace_id="client-alpha", name="forged"),
    ],
)
def test_client_evidence_export_rejects_unknown_or_forged_workspace(candidate, export_context):
    _, registry = export_context
    with pytest.raises(ValueError, match="client workspace identity rejected") as error:
        export_client_evidence(
            workspace=candidate,
            registry=registry,
            provenance="fixture://safe",
            evidence_state="present",
            payload={},
        )
    assert "client-" not in str(error.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"internal_prompt": "synthetic internal prompt"},
        {"internal_scoring_formula": "synthetic formula"},
        {"internal_heuristic": "synthetic heuristic"},
        {"source_code": "synthetic source"},
        {"cross_client_data": "synthetic other_client record"},
        {"client_private_data": "synthetic private tenant data"},
        {"credentials": "synthetic credential"},
        {"cookie": "synthetic cookie"},
        {"token": "synthetic token"},
        {"raw_provider_payload": {"value": "synthetic provider response"}},
        {"next_actions": [{"raw_provider_payload": "synthetic nested provider response"}]},
        {"next_actions": ["def internal_helper():"]},
    ],
)
def test_client_evidence_export_rejects_forbidden_content(payload, export_context):
    workspace, registry = export_context
    with pytest.raises(ValueError, match="client evidence export rejected") as error:
        export_client_evidence(
            workspace=workspace,
            registry=registry,
            provenance="fixture://unsafe",
            evidence_state="present",
            payload=payload,
        )
    assert "synthetic" not in str(error.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "actual"},
        {"status": "live_validated"},
        {"status": "fixture evidence is live"},
        {"next_actions": [r"C:\\synthetic\\private\\report.json"]},
        {"next_actions": ["/synthetic/private/report.json"]},
        {"next_actions": ["file:///synthetic/private/report.json"]},
    ],
)
def test_client_evidence_export_rejects_non_authoritative_claims_and_paths(payload, export_context):
    workspace, registry = export_context
    with pytest.raises(ClientWorkspaceExportError) as error:
        export_client_evidence(
            workspace=workspace,
            registry=registry,
            provenance="fixture://unsafe",
            evidence_state="present",
            payload=payload,
        )
    assert error.value.code == "content_rejected"
    assert "synthetic" not in str(error.value)


def test_client_evidence_export_rejects_control_characters(export_context):
    workspace, registry = export_context
    with pytest.raises(ClientWorkspaceExportError) as error:
        export_client_evidence(
            workspace=workspace,
            registry=registry,
            provenance="fixture://unsafe",
            evidence_state="present",
            payload={"next_actions": ["review\nsecret"]},
        )
    assert error.value.code == "invalid_metadata"


@pytest.mark.parametrize(
    "key",
    [
        "internal_prompt",
        "internal_scoring_formula",
        "internal_heuristic",
        "source_code",
        "cross_client_data",
        "client_private_data",
        "credentials",
        "cookie",
        "token",
        "raw_provider_payload",
    ],
)
def test_leakage_check_blocks_forbidden_export_classes(key):
    findings = check_workspace_leakage({key: "synthetic forbidden value"})
    assert findings
    assert any(item.status == "hard_block" for item in findings)


def test_client_evidence_export_rejects_workspace_mismatch(export_context):
    workspace, registry = export_context
    with pytest.raises(ValueError, match="client evidence export rejected"):
        export_client_evidence(
            workspace=workspace,
            registry=registry,
            provenance="fixture://mismatch",
            evidence_state="present",
            payload={"workspace_id": "client-beta", "status": "present"},
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"provenance": "", "evidence_state": "present", "payload": {}},
        {"provenance": "fixture://safe", "evidence_state": "unknown", "payload": {}},
        {"provenance": "fixture://safe", "evidence_state": "present", "payload": []},
    ],
)
def test_client_evidence_export_rejects_invalid_metadata(kwargs, export_context):
    workspace, registry = export_context
    with pytest.raises(ValueError, match="invalid client evidence export"):
        export_client_evidence(workspace=workspace, registry=registry, **kwargs)


def test_client_evidence_export_rejects_unsafe_registered_workspace_id(export_context):
    _, registry = export_context
    unsafe = registry.register(ClientWorkspace(workspace_id="client/alpha", name="unsafe"))
    with pytest.raises(ValueError, match="invalid client evidence export"):
        export_client_evidence(
            workspace=unsafe,
            registry=registry,
            provenance="fixture://safe",
            evidence_state="present",
            payload={},
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"provenance": "file://synthetic/private/path", "evidence_state": "present", "payload": {}},
        {"provenance": "fixture://../private", "evidence_state": "present", "payload": {}},
        {"provenance": "fixture://safe", "evidence_state": "present", "payload": {"status": {"unsafe": object()}}},
    ],
)
def test_client_evidence_export_rejects_unsafe_identity_or_value(kwargs, export_context):
    workspace, registry = export_context
    with pytest.raises(ValueError, match="invalid client evidence export"):
        export_client_evidence(workspace=workspace, registry=registry, **kwargs)


def test_client_evidence_export_rejects_oversized_payload(export_context):
    workspace, registry = export_context
    with pytest.raises(ValueError, match="client evidence export exceeds size limit"):
        export_client_evidence(
            workspace=workspace,
            registry=registry,
            provenance="fixture://safe",
            evidence_state="present",
            payload={"status": "x" * 128},
            max_payload_bytes=32,
        )


def test_client_evidence_export_rejects_unbounded_limit(export_context):
    workspace, registry = export_context
    with pytest.raises(ValueError, match="invalid client evidence export"):
        export_client_evidence(
            workspace=workspace,
            registry=registry,
            provenance="fixture://safe",
            evidence_state="present",
            payload={"status": "present"},
            max_payload_bytes=MAX_CLIENT_EVIDENCE_EXPORT_BYTES + 1,
        )

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from evaluation.companyos.approval_ledger import (
    DECISION_CLASSES,
    REQUEST_TYPES,
    RISK_LEVELS,
    SIMULATION_STATUSES,
    ApprovalAuditEvent,
    ApprovalBudgetCap,
    ApprovalCondition,
    ApprovalEvidence,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalScope,
    build_approval_ledger,
    default_approval_policies,
    make_request,
    revoke_request,
    simulate_action,
    transition_status,
)

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "run_companyos_approval_ledger.py"
FIXTURES = ROOT / "tests" / "fixtures" / "companyos_approval"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], cwd=ROOT, text=True, capture_output=True, check=False)


def test_default_report_is_deterministic_and_read_only():
    first = build_approval_ledger().to_dict()
    second = build_approval_ledger().to_dict()
    assert first == second
    assert first["safety_summary"]["read_only"] is True
    assert first["safety_summary"]["network_calls"] is False
    assert first["safety_summary"]["mutated"] is False
    assert first["safety_summary"]["external_action_performed"] is False


def test_report_contains_required_sections_and_counts():
    report = build_approval_ledger()
    data = report.to_dict()
    for key in ("requests", "decisions", "audit_events", "policies", "simulations", "queue_summary", "safety_summary", "registry_integration", "next_best_action"):
        assert key in data
    assert report.approval_count == len(report.requests)
    assert len(report.audit_events) == report.approval_count


@pytest.mark.parametrize("request_type", REQUEST_TYPES)
def test_all_request_types_have_a_policy(request_type: str):
    policy = next(item for item in default_approval_policies() if item.request_type == request_type)
    assert policy.policy_id.endswith(request_type)
    assert policy.required_approver_role
    assert policy.rationale


@pytest.mark.parametrize("status", ("draft", "pending_review", "approved", "denied", "expired", "revoked", "simulated", "blocked_by_policy"))
def test_status_vocabulary_is_enforced(status: str):
    if status == "approved":
        # The model accepts the vocabulary; transition logic prevents granting it offline.
        request = make_request(approval_id="status-approved", request_type="model_spend", status=status)
        assert request.status == status
    else:
        request = make_request(approval_id=f"status-{status}", request_type="model_spend", status=status)
        assert request.status == status


@pytest.mark.parametrize("risk", RISK_LEVELS)
def test_risk_vocabulary_is_serializable(risk: str):
    request_type = "payment_creation" if risk in {"critical", "blocked"} else "model_spend"
    request = make_request(approval_id=f"risk-{risk}", request_type=request_type, status="simulated")
    request = replace(request, risk_level=risk)
    assert request.to_dict()["risk_level"] == risk


@pytest.mark.parametrize("decision", DECISION_CLASSES)
def test_policy_decision_classes_are_explicit(decision: str):
    policy = ApprovalPolicy("policy-test", "model_spend", decision, "medium", "human_operator", (), ApprovalBudgetCap("test", 1, 10), "test policy", decision == "blocked_in_current_mode")
    assert policy.decision_class == decision


@pytest.mark.parametrize("field", ("read_only", "network_calls", "mutated", "external_action_performed"))
def test_request_rejects_unsafe_flag(field: str):
    request = make_request(approval_id="unsafe", request_type="model_spend")
    with pytest.raises(ValueError):
        replace(request, **{field: False if field == "read_only" else True})


def test_scope_contains_offline_constraint():
    request = make_request(approval_id="scope", request_type="site_publish")
    assert request.requested_scope.environments == ("offline",)
    assert "no external execution" in request.requested_scope.constraints
    assert request.requested_scope.expiry_required is True


def test_budget_cap_rejects_negative_values():
    with pytest.raises(ValueError):
        ApprovalBudgetCap("bad", -1, 1)


def test_budget_cap_derives_remaining():
    cap = ApprovalBudgetCap("model", 2, 10, consumed=3)
    assert cap.remaining == 7


def test_evidence_is_sanitized_by_default():
    evidence = ApprovalEvidence("e-1", "tool_registry_entry", "registry", "Blocked tool definition")
    assert evidence.sanitized is True
    request = make_request(approval_id="evidence", request_type="model_spend", evidence=(evidence,))
    assert request.to_dict()["evidence"][0]["summary"] == "Blocked tool definition"


def test_conditions_expose_missing_operator_input():
    request = make_request(approval_id="conditions", request_type="email_send")
    assert any(not condition.satisfied for condition in request.conditions)
    assert "recipient consent verified" in {condition.description for condition in request.conditions}


@pytest.mark.parametrize("action,expected_type", (("send_email", "email_send"), ("send_whatsapp", "whatsapp_send"), ("send_sms", "sms_send"), ("place_call", "voice_call"), ("publish_site", "site_publish"), ("launch_ad", "ad_launch"), ("create_payment", "payment_creation"), ("supplier_order", "supplier_order"), ("provider_call", "provider_call"), ("manual_import", "web_data_acquisition")))
def test_action_aliases_map_to_canonical_request_types(action: str, expected_type: str):
    simulation = simulate_action(action)
    assert simulation.request_type == expected_type
    assert simulation.request.request_type == expected_type


@pytest.mark.parametrize("action", ("send_email", "send_whatsapp", "send_sms", "place_call", "publish_site", "launch_ad", "create_payment", "supplier_order", "provider_call", "index_vectors"))
def test_external_world_simulations_fail_closed(action: str):
    simulation = simulate_action(action)
    assert simulation.result in {"would_be_blocked_by_policy", "would_be_denied_missing_conditions"}
    assert simulation.can_be_approved_now is False
    assert simulation.request.external_action_performed is False


def test_email_simulation_requires_consent_and_message_approval():
    simulation = simulate_action("send_email")
    assert simulation.result == "would_be_denied_missing_conditions"
    assert "recipient consent verified" in simulation.missing_conditions
    assert "message approved" in simulation.missing_conditions


def test_email_with_conditions_remains_blocked_in_current_mode():
    simulation = simulate_action("send_email", consent=True, unsubscribe=True, message_approved=True)
    assert simulation.result == "would_be_blocked_by_policy"
    assert simulation.missing_conditions == ()


def test_do_not_contact_blocks_outreach_even_with_other_conditions():
    simulation = simulate_action("send_email", consent=True, do_not_contact=True, unsubscribe=True, message_approved=True)
    assert simulation.result == "would_be_denied_missing_conditions"
    assert "do-not-contact is false" in simulation.missing_conditions


def test_model_spend_under_cap_is_draft_simulation_only():
    simulation = simulate_action("model_spend", requested_budget=0.20)
    assert simulation.result == "would_auto_allow_draft"
    assert simulation.can_be_approved_now is True
    assert simulation.request.status == "simulated"


def test_model_spend_over_cap_is_denied():
    simulation = simulate_action("model_spend", requested_budget=25)
    assert simulation.result == "would_be_denied_missing_conditions"
    assert "requested budget exceeds the applicable cap" in simulation.blocking_reasons


def test_unknown_model_route_is_missing_condition():
    simulation = simulate_action("model_spend", route_registered=False, requested_budget=0.2)
    assert "model route is registered" in simulation.missing_conditions


def test_manual_import_is_auto_allowed_as_draft():
    simulation = simulate_action("manual_import")
    assert simulation.result == "would_auto_allow_draft"
    assert simulation.request.network_calls is False


def test_site_publish_is_blocked_even_if_conditions_are_not_missing():
    simulation = simulate_action("publish_site")
    assert simulation.result == "would_be_blocked_by_policy"
    assert simulation.budget_cap.monthly == 0


def test_payment_creation_is_blocked():
    simulation = simulate_action("create_payment")
    assert simulation.result == "would_be_blocked_by_policy"
    assert simulation.request.risk_level == "critical"


def test_unknown_action_fails_to_safe_workflow_type():
    simulation = simulate_action("unregistered-action")
    assert simulation.action == "unknown_action"
    assert simulation.request_type == "workflow_resume"
    assert simulation.result == "would_be_blocked_by_policy"


def test_simulation_status_vocabulary_is_complete():
    observed = {simulate_action(action).result for action in ("manual_import", "send_email", "publish_site", "model_spend")}
    assert observed <= set(SIMULATION_STATUSES)
    assert "would_auto_allow_draft" in observed


@pytest.mark.parametrize("fixture_name", ("approval_requests_seed.json", "model_spend_request.json", "email_send_request.json", "whatsapp_send_request.json", "voice_call_request.json", "crm_mutation_request.json", "accounting_sync_request.json", "payment_creation_request.json", "supplier_order_request.json", "ad_launch_request.json", "site_publish_request.json", "domain_change_request.json", "provider_data_call_request.json", "manual_import_request.json", "missing_consent_request.json", "expired_request.json", "revoked_request.json"))
def test_fixture_files_are_sanitized_json(fixture_name: str):
    value = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
    assert value is not None
    assert "api_key" not in json.dumps(value).lower()


def test_registry_integration_counts_are_present():
    report = build_approval_ledger()
    integration = report.registry_integration
    counts = integration["registry_counts"]
    assert counts["tool_count"] >= 20
    assert counts["workflow_count"] >= 10
    assert "send_email" in integration["linked_controls"]["blocked_tools"]
    assert "pause_before_external_action" in integration["linked_controls"]["workflow_interrupts"]


def test_registry_report_input_is_consumed():
    seed = json.loads((FIXTURES / "companyos_registry_report.json").read_text(encoding="utf-8"))
    report = build_approval_ledger(registry_report=seed)
    counts = report.registry_integration["registry_counts"]
    assert counts == {"tool_count": 2, "workflow_count": 1, "agent_count": 1, "skill_count": 1, "model_route_count": 1, "quality_gate_count": 1, "knowledge_source_count": 1}


def test_failed_registry_quality_gate_blocks_nonterminal_requests():
    seed = {"eval_registry": {"quality_gates": [{"gate_id": "approval_required_gate"}], "gate_results": [{"gate_id": "approval_required_gate", "status": "failed"}]}}
    report = build_approval_ledger(registry_report=seed)
    assert report.registry_integration["linked_controls"]["failed_quality_gates"] == ["approval_required_gate"]
    assert all(request.status in {"blocked_by_policy", "expired", "revoked"} for request in report.requests)


def test_request_seed_input_is_normalized():
    values = json.loads((FIXTURES / "approval_requests_seed.json").read_text(encoding="utf-8"))
    report = build_approval_ledger(approval_requests=values)
    assert [item.approval_id for item in report.requests] == ["seed-manual-import", "seed-publish"]
    assert report.requests[1].status == "blocked_by_policy"


def test_malformed_request_type_is_rejected():
    with pytest.raises(ValueError, match="unsupported approval request type"):
        build_approval_ledger(approval_requests=[{"request_type": "not-supported"}])


@pytest.mark.parametrize("request_type", ("payment_creation", "supplier_order", "ad_launch", "site_publish", "domain_change", "hosting_change", "customer_message"))
def test_high_impact_policies_are_blocked(request_type: str):
    policy = next(item for item in default_approval_policies() if item.request_type == request_type)
    assert policy.blocked_in_current_mode is True
    assert policy.default_risk in {"high", "critical"}


@pytest.mark.parametrize("request_type", ("email_send", "whatsapp_send", "sms_send", "voice_call", "customer_message"))
def test_outreach_policies_require_consent(request_type: str):
    policy = next(item for item in default_approval_policies() if item.request_type == request_type)
    assert any("consent" in condition for condition in policy.required_conditions)
    assert any("do-not-contact" in condition for condition in policy.required_conditions)


def test_audit_events_are_created_for_each_request():
    report = build_approval_ledger()
    assert {event.approval_id for event in report.audit_events} == {request.approval_id for request in report.requests}
    assert all(event.immutable_note for event in report.audit_events)
    assert all(not any(secret in event.reason.lower() for secret in ("token", "password", "api_key")) for event in report.audit_events)


def test_transition_to_pending_review_creates_audit_event():
    request = make_request(approval_id="transition", request_type="model_spend", status="draft")
    updated, event = transition_status(request, "pending_review")
    assert updated.status == "pending_review"
    assert event.before_status == "draft"
    assert event.after_status == "pending_review"


def test_offline_transition_cannot_grant_approval():
    request = make_request(approval_id="approve", request_type="model_spend", status="pending_review")
    with pytest.raises(ValueError, match="cannot grant live approval"):
        transition_status(request, "approved")


def test_terminal_status_cannot_be_reopened():
    request = make_request(approval_id="terminal", request_type="site_publish", status="revoked")
    with pytest.raises(ValueError, match="terminal approval status"):
        transition_status(request, "pending_review")


def test_revocation_produces_record_and_event():
    request = make_request(approval_id="revoke", request_type="model_spend", status="pending_review")
    updated, revocation, event = revoke_request(request, reason="scope changed")
    assert updated.status == "revoked"
    assert revocation.approval_id == "revoke"
    assert event.after_status == "revoked"


def test_revocation_is_idempotence_protected():
    request = make_request(approval_id="revoke-again", request_type="model_spend", status="revoked")
    with pytest.raises(ValueError, match="already revoked"):
        revoke_request(request)


def test_markdown_contains_required_sections():
    markdown = build_approval_ledger().to_markdown()
    for section in ("Executive Summary", "Pending Approvals", "Blocked Actions", "Approval Policies", "High-Risk Requests", "Simulations", "Budget Caps", "Missing Conditions", "Audit Trail", "Safety Boundaries", "Next Best Action"):
        assert f"## {section}" in markdown


@pytest.mark.parametrize("action", ("send_email", "publish_site", "model_spend", "create_payment", "supplier_order", "launch_ad", "provider_call", "manual_import"))
def test_cli_simulation_is_json_safe(action: str):
    result = run_cli("--simulate-action", action, "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["safety_summary"]["network_calls"] is False
    assert payload["simulations"][0]["action"] == action


def test_cli_markdown_is_client_readable():
    result = run_cli("--markdown")
    assert result.returncode == 0
    assert result.stdout.startswith("# CompanyOS Approval Ledger")
    assert "No credentials" in result.stdout


def test_cli_registry_input_is_supported():
    result = run_cli("--registry-report", str(FIXTURES / "companyos_registry_report.json"), "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["registry_integration"]["registry_counts"]["tool_count"] == 2


def test_cli_request_input_is_supported():
    result = run_cli("--approval-requests", str(FIXTURES / "approval_requests_seed.json"), "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["approval_count"] == 2


def test_cli_rejects_traversal_path():
    result = run_cli("--registry-report", "tests/fixtures/companyos_approval/../companyos_registry/companyos_registry_context.json", "--json")
    assert result.returncode == 2
    assert "traversal" in result.stderr


def test_cli_rejects_secret_like_input():
    result = run_cli("--approval-requests", str(FIXTURES / "secret_like_approval_input_rejected.json"), "--json")
    assert result.returncode == 2
    assert "secret-like" in result.stderr


def test_cli_rejects_non_array_requests():
    result = run_cli("--approval-requests", str(FIXTURES / "companyos_registry_report.json"), "--json")
    assert result.returncode == 2
    assert "JSON array" in result.stderr


def test_cli_writes_sanitized_exports(tmp_path: Path):
    output = tmp_path / "approval"
    result = run_cli("--output", str(output), "--simulate-action", "send_email", "--markdown")
    assert result.returncode == 0, result.stderr
    expected = {"approval_ledger_report.json", "approval_ledger_report.md", "approval_queue.json", "approval_policies.json", "approval_audit_trail.json", "approval_simulations.json", "blocked_actions.json", "budget_caps.json"}
    assert {path.name for path in output.iterdir()} == expected
    assert "api_key" not in (output / "approval_ledger_report.json").read_text(encoding="utf-8")


def test_cli_is_offline_by_default():
    result = run_cli("--json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["safety_summary"]["network_calls"] is False


def test_safety_summary_has_no_live_capability():
    summary = build_approval_ledger().safety_summary
    assert summary.credentials_present is False
    assert summary.live_capabilities_enabled is False
    assert summary.policy_fail_closed is True
    assert summary.secrets_stored is False


@pytest.mark.parametrize("request_type", REQUEST_TYPES)
def test_policy_budget_caps_are_non_negative(request_type: str):
    policy = next(item for item in default_approval_policies() if item.request_type == request_type)
    assert policy.budget_cap.per_run >= 0
    assert policy.budget_cap.monthly >= 0
    assert policy.budget_cap.currency == "USD"


@pytest.mark.parametrize("request_type", REQUEST_TYPES)
def test_policy_rationale_names_current_mode(request_type: str):
    policy = next(item for item in default_approval_policies() if item.request_type == request_type)
    assert policy.rationale
    if policy.blocked_in_current_mode:
        assert "not" in policy.rationale.lower() or "blocked" in policy.rationale.lower() or "disabled" in policy.rationale.lower()


@pytest.mark.parametrize("request_type", ("email_send", "whatsapp_send", "sms_send", "voice_call", "customer_message"))
def test_outreach_requests_are_offline_and_external_action_free(request_type: str):
    request = make_request(approval_id=f"outreach-{request_type}", request_type=request_type)
    assert request.read_only is True
    assert request.network_calls is False
    assert request.mutated is False
    assert request.external_action_performed is False


@pytest.mark.parametrize("request_type", ("crm_mutation", "accounting_sync", "invoice_creation", "payment_creation", "supplier_order", "ad_launch", "site_publish", "domain_change", "hosting_change"))
def test_mutation_requests_carry_a_human_approver_placeholder(request_type: str):
    request = make_request(approval_id=f"mutation-{request_type}", request_type=request_type)
    assert request.required_approver_role
    assert request.status == "blocked_by_policy"
    assert request.requested_mode == "simulation"


@pytest.mark.parametrize("action", ("manual_import", "model_spend", "provider_call", "send_email", "publish_site", "create_payment", "supplier_order", "launch_ad"))
def test_simulations_have_audit_event_type(action: str):
    simulation = simulate_action(action, requested_budget=0.2 if action == "model_spend" else 0)
    assert simulation.audit_event_type.startswith("companyos_approval_simulation_")
    assert simulation.simulation_id.startswith("simulation-")


@pytest.mark.parametrize("action", ("send_email", "send_whatsapp", "send_sms", "place_call", "publish_site", "launch_ad", "create_payment", "supplier_order"))
def test_blocked_simulations_have_an_explanation(action: str):
    simulation = simulate_action(action)
    assert simulation.blocking_reasons or simulation.missing_conditions
    assert simulation.request.requested_scope.constraints == ("no external execution",)


def test_model_simulation_contains_budget_cap():
    simulation = simulate_action("model_spend", requested_budget=0.2)
    assert simulation.budget_cap.per_run == 5
    assert simulation.budget_cap.monthly == 100
    assert simulation.request.requested_budget_cap.per_run == 0.2


def test_report_counts_critical_and_blocked_requests():
    report = build_approval_ledger()
    assert report.critical_count >= 1
    assert report.blocked_count >= 1
    assert report.queue_summary.high_risk >= report.critical_count


def test_highest_risk_requests_are_sorted_deterministically():
    report = build_approval_ledger()
    ids = tuple(item.approval_id for item in report.highest_risk_requests)
    assert ids == tuple(item.approval_id for item in build_approval_ledger().highest_risk_requests)
    assert report.highest_risk_requests[0].risk_level in {"critical", "blocked"}


def test_report_simulation_is_preserved():
    simulation = simulate_action("manual_import")
    report = build_approval_ledger(simulations=(simulation,))
    assert report.simulations[0].simulation_id == simulation.simulation_id
    assert report.to_dict()["simulations"][0]["result"] == "would_auto_allow_draft"


def test_report_markdown_explicitly_separates_approval_from_execution():
    markdown = build_approval_ledger().to_markdown().lower()
    assert "does not authorize execution" in markdown
    assert "external action" in markdown or "no provider" in markdown


def test_request_dict_contains_all_required_safety_fields():
    data = make_request(approval_id="shape", request_type="model_spend").to_dict()
    for key in ("read_only", "network_calls", "mutated", "external_action_performed", "requested_scope", "requested_budget_cap", "requested_time_window", "conditions", "evidence"):
        assert key in data


def test_audit_event_serialization_is_json_safe():
    event = ApprovalAuditEvent("event", "approval", "decision_recorded", "operator", "offline", "pending_review", "denied", "missing condition", ("evidence-1",))
    encoded = json.dumps(event.__dict__, sort_keys=True)
    assert "evidence-1" in encoded
    assert "token" not in encoded.lower()


def test_condition_evidence_reference_is_retained():
    condition = ApprovalCondition("consent", "recipient consent verified", True, False, "consent-record-placeholder")
    request = make_request(approval_id="condition-ref", request_type="email_send", evidence=(ApprovalEvidence("consent-record-placeholder", "consent_record_placeholder", "operator", "Placeholder only"),))
    assert condition.evidence_ref == request.evidence[0].ref_id


def test_registry_linked_agent_forbidden_action_is_visible():
    report = build_approval_ledger()
    assert "send_email" in report.registry_integration["linked_controls"]["forbidden_agent_actions"]


def test_registry_quality_gate_link_is_visible():
    report = build_approval_ledger()
    assert "approval_required_gate" in report.registry_integration["linked_controls"]["quality_gates"]


def test_registry_private_knowledge_source_is_visible():
    report = build_approval_ledger()
    assert "companyos-docs" in report.registry_integration["linked_controls"]["privacy_sources"]


def test_report_expiry_records_are_present_for_all_requests():
    report = build_approval_ledger()
    assert len(report.expiries) == report.approval_count
    assert all(item.expires_at for item in report.expiries)


def test_queue_summary_missing_condition_count_is_stable():
    report = build_approval_ledger()
    expected = sum(any(not condition.satisfied for condition in request.conditions if condition.required) for request in report.requests)
    assert report.queue_summary.missing_conditions == expected


def test_safe_manual_import_does_not_require_a_provider():
    simulation = simulate_action("manual_import")
    assert simulation.request.external_system == "none"
    assert simulation.request.side_effect_type == "none"


def test_provider_call_mentions_network_gate():
    policy = next(item for item in default_approval_policies() if item.request_type == "provider_call")
    assert "network gate" in " ".join(policy.required_conditions)
    assert policy.blocked_in_current_mode is True


def test_vector_indexing_mentions_privacy_and_retention():
    policy = next(item for item in default_approval_policies() if item.request_type == "vector_indexing")
    assert "privacy classification approved" in policy.required_conditions
    assert "retention policy approved" in policy.required_conditions


def test_domain_and_host_changes_are_critical():
    for request_type in ("domain_change", "hosting_change"):
        request = make_request(approval_id=request_type, request_type=request_type)
        assert request.risk_level == "critical"


def test_revoke_event_is_offline_only():
    request = make_request(approval_id="revocation-safety", request_type="workflow_resume", status="pending_review")
    updated, revocation, event = revoke_request(request)
    assert updated.network_calls is False
    assert revocation.effective_immediately is True
    assert "external" not in event.event_type

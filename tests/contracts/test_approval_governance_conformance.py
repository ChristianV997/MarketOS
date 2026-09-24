"""Cross-authority contract for CompanyOS and backend approval controls.

The CompanyOS Approval Ledger records policy and offline simulations. Backend
governance evaluates a proposal in a workspace context, and the planner,
executor, and reviewer path consumes that result. This contract proves the
relationship without merging either authority or treating an approval record
as an execution token.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from backend.governance.approval_policy import evaluate_proposal_approval
from backend.governance.proposal import Proposal
from backend.organization.agent_role import AgentRole
from backend.organization.planner_executor_reviewer import run_planner_executor_reviewer
from evaluation.companyos.approval_ledger import (
    LIVE_ACTION_TYPES,
    ApprovalEvidence,
    build_approval_ledger,
    make_request,
    simulate_action,
    transition_status,
)
from evaluation.companyos.resource_execution_governor import (
    ExecutionDecisionRequest,
    evaluate_execution_request,
)
from evaluation.trustos.gate_runner import evaluate_action


SAFE_WORKSPACE = {"workspace_id": "workspace-alpha"}
SAFE_ROLE = AgentRole(
    agent_id="agent-manager",
    name="Fixture manager",
    department_id="product",
    role_type="manager",
    max_budget_authority=100.0,
    requires_review_above=100.0,
)


def _json_safe(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, allow_nan=False)
    for forbidden_value in ("fixture-api-key-value", "fixture-password-value", "fixture-token-value"):
        assert forbidden_value not in encoded
    return encoded


@pytest.mark.parametrize("action", sorted(LIVE_ACTION_TYPES))
def test_companyos_external_actions_are_blocked_or_simulation_only(action: str) -> None:
    simulation = simulate_action(action, requested_budget=0.2 if action == "model_spend" else 0.0)

    assert simulation.request.read_only is True
    assert simulation.request.network_calls is False
    assert simulation.request.mutated is False
    assert simulation.request.external_action_performed is False
    assert simulation.can_be_approved_now is False
    assert simulation.result in {
        "would_be_blocked_by_policy",
        "would_be_denied_missing_conditions",
        "would_require_human_approval",
    }


def test_companyos_draft_simulations_are_not_execution_permission() -> None:
    simulation = simulate_action("model_spend", requested_budget=0.20)
    report = build_approval_ledger(generated_at="fixed", simulations=(simulation,))

    assert simulation.result == "would_auto_allow_draft"
    assert simulation.request.status == "simulated"
    assert simulation.can_be_approved_now is True
    assert report.simulations[0].request.external_action_performed is False
    assert report.safety_summary.live_capabilities_enabled is False
    assert all(item.simulation_only for item in report.decisions)


def test_companyos_status_transition_cannot_grant_live_approval() -> None:
    request = make_request(approval_id="approval-conformance", request_type="model_spend", status="pending_review")

    with pytest.raises(ValueError, match="cannot grant live approval"):
        transition_status(request, "approved")


@pytest.mark.parametrize("workspace", (None, "", "   ", {}, {"name": "missing-id"}))
def test_backend_governance_rejects_missing_workspace_identity(workspace: Any) -> None:
    result = evaluate_proposal_approval(Proposal(workspace_id=""), SAFE_ROLE, workspace)

    assert result["allowed"] is False
    assert result["dry_run_safe"] is True
    assert "workspace_required" in result["blocked_reasons"]


def test_backend_governance_rejects_inactive_agent() -> None:
    inactive = AgentRole(**{**SAFE_ROLE.to_dict(), "active": False})

    result = evaluate_proposal_approval(Proposal(workspace_id="workspace-alpha"), inactive, SAFE_WORKSPACE)

    assert result["allowed"] is False
    assert "active_agent_required" in result["blocked_reasons"]


def test_backend_governance_preserves_and_matches_workspace_identity() -> None:
    proposal = Proposal(workspace_id="workspace-alpha", requested_budget=0.0)
    matching = evaluate_proposal_approval(proposal, SAFE_ROLE, SAFE_WORKSPACE)
    mismatched = evaluate_proposal_approval(proposal, SAFE_ROLE, {"workspace_id": "workspace-beta"})

    assert matching["allowed"] is True
    assert mismatched["allowed"] is False
    assert "workspace_mismatch" in mismatched["blocked_reasons"]
    assert "workspace-alpha" not in json.dumps(mismatched)
    assert "workspace-beta" not in json.dumps(mismatched)


def test_backend_governance_requires_human_review_for_live_actions() -> None:
    result = evaluate_proposal_approval(
        Proposal(workspace_id="workspace-alpha"), SAFE_ROLE, SAFE_WORKSPACE, live_action_requested=True
    )

    assert result["allowed"] is False
    assert result["human_review_required"] is True
    assert "human" in result["required_reviews"]
    assert "human_approval_required_for_live_action" in result["blocked_reasons"]


def test_backend_governance_requires_finance_and_risk_above_authority() -> None:
    proposal = Proposal(workspace_id="workspace-alpha", requested_budget=101.0)
    result = evaluate_proposal_approval(proposal, SAFE_ROLE, SAFE_WORKSPACE)

    assert result["allowed"] is False
    assert result["finance_review_required"] is True
    assert result["risk_review_required"] is True
    assert {"finance", "risk"}.issubset(result["required_reviews"])
    assert {"finance_review_required", "risk_review_required", "budget_authority_exceeded"}.issubset(result["blocked_reasons"])


def test_companyos_failed_quality_gate_blocks_nonterminal_requests() -> None:
    registry_report = {
        "eval_registry": {
            "quality_gates": [{"gate_id": "governance-gate"}],
            "gate_results": [{"gate_id": "governance-gate", "status": "failed"}],
        }
    }
    report = build_approval_ledger(
        generated_at="fixed",
        registry_report=registry_report,
        approval_requests=[
            {"approval_id": "draft-request", "request_type": "model_spend", "status": "draft"},
            {"approval_id": "expired-request", "request_type": "model_spend", "status": "expired"},
        ],
    )

    assert report.registry_integration["linked_controls"]["failed_quality_gates"] == ["governance-gate"]
    assert report.requests[0].status == "blocked_by_policy"
    assert report.requests[1].status == "expired"


def test_unknown_companyos_action_fails_closed() -> None:
    simulation = simulate_action("unregistered-action")

    assert simulation.action == "unknown_action"
    assert simulation.request_type == "workflow_resume"
    assert simulation.result == "would_be_blocked_by_policy"
    assert simulation.can_be_approved_now is False


def test_model_spend_is_bounded_and_draft_only() -> None:
    within_cap = simulate_action("model_spend", requested_budget=0.20)
    above_cap = simulate_action("model_spend", requested_budget=6.0)

    assert within_cap.result == "would_auto_allow_draft"
    assert within_cap.request.requested_budget_cap.per_run == 0.2
    assert within_cap.request.external_action_performed is False
    assert above_cap.result == "would_be_denied_missing_conditions"
    assert "requested budget exceeds the applicable cap" in above_cap.blocking_reasons


@dataclass
class _FakeDepartment:
    manager_agent_id: str = "agent-manager"
    active: bool = True

    def allows_service(self, service_name: str) -> bool:
        return service_name == "unit_economics"


class _FakeOrganization:
    def list_departments(self) -> list[_FakeDepartment]:
        return [_FakeDepartment()]

    def bootstrap_defaults(self) -> dict[str, Any]:
        raise AssertionError("live planner test must not bootstrap or write organization state")

    def get_department(self, department_id: str) -> _FakeDepartment | None:
        return _FakeDepartment() if department_id == "product" else None

    def get_agent(self, agent_id: str) -> AgentRole | None:
        return SAFE_ROLE if agent_id == SAFE_ROLE.agent_id else None


class _FakeGovernance:
    def __init__(self) -> None:
        self.proposals: list[Any] = []
        self.decisions: list[Any] = []

    def register_proposal(self, proposal: Any) -> Any:
        self.proposals.append(proposal)
        return proposal

    def list_decisions(self, proposal_id: str) -> list[Any]:
        return []

    def register_decision(self, decision: Any) -> Any:
        self.decisions.append(decision)
        return decision


class _FakeReportRegistry:
    def register(self, report: Any) -> Any:
        return report


@dataclass
class _FakeReport:
    report_id: str = "report-conformance"

    def to_dict(self) -> dict[str, str]:
        return {"report_id": self.report_id}


def test_planner_reviewer_forces_live_input_back_to_blocked_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.organization.planner_executor_reviewer as planner

    governance = _FakeGovernance()
    monkeypatch.setattr(planner, "get_organization_registry", lambda: _FakeOrganization())
    monkeypatch.setattr(planner, "get_governance_registry", lambda: governance)
    monkeypatch.setattr(planner, "get_report_registry", lambda: _FakeReportRegistry())
    monkeypatch.setattr(planner, "build_report_from_execution", lambda *args: _FakeReport())
    monkeypatch.setattr(planner, "sync_proposal_note", lambda *args, **kwargs: {"status": "skipped"})

    result = run_planner_executor_reviewer(
        "Offline economics rehearsal",
        SAFE_WORKSPACE,
        "product",
        "unit_economics",
        {"live": True},
        planner_agent_id=SAFE_ROLE.agent_id,
    )

    assert result["status"] == "blocked"
    assert result["approval"]["allowed"] is False
    assert "live_execution_forbidden_in_governance_loop" in result["approval"]["blocked_reasons"]
    assert result["execution"] == {"service_name": "unit_economics", "status": "not_run", "dry_run": True}
    assert result["decision"]["decision"] == "blocked"
    assert result["proposal"]["workspace_id"] == "workspace-alpha"
    assert result["decision"]["workspace_id"] == "workspace-alpha"
    assert governance.decisions[0].workspace_id == "workspace-alpha"


def test_both_policy_paths_are_deterministic_json_safe_and_non_authorizing() -> None:
    first_ledger = build_approval_ledger(generated_at="fixed")
    second_ledger = build_approval_ledger(generated_at="fixed")
    backend_first = evaluate_proposal_approval(
        Proposal(workspace_id="workspace-alpha"), SAFE_ROLE, SAFE_WORKSPACE
    )
    backend_second = evaluate_proposal_approval(
        Proposal(workspace_id="workspace-alpha"), SAFE_ROLE, SAFE_WORKSPACE
    )

    first_json = _json_safe(first_ledger.to_dict())
    second_json = _json_safe(second_ledger.to_dict())
    backend_first_json = _json_safe(backend_first)
    backend_second_json = _json_safe(backend_second)

    assert first_json == second_json
    assert backend_first_json == backend_second_json
    assert first_ledger.safety_summary.external_action_performed is False
    assert first_ledger.safety_summary.network_calls is False
    assert backend_first["dry_run_safe"] is True


def test_approval_records_cannot_be_reused_as_execution_permission() -> None:
    request = make_request(approval_id="record-only", request_type="site_publish")
    ledger = build_approval_ledger(generated_at="fixed", approval_requests=[request.to_dict()])

    assert ledger.requests[0].status == "blocked_by_policy"
    assert ledger.decisions == ()
    assert ledger.safety_summary.live_capabilities_enabled is False
    assert ledger.safety_summary.policy_fail_closed is True


def test_approval_evidence_does_not_bypass_trustos_client_export_gate() -> None:
    evidence = ApprovalEvidence("approval-evidence", "manual", "fixture", "reviewed offline")
    ledger = build_approval_ledger(
        generated_at="fixed",
        approval_requests=[
            make_request(
                approval_id="export-review",
                request_type="site_publish",
                evidence=(evidence,),
            ).to_dict()
        ],
    )

    result = evaluate_action(
        "client_workspace_export",
        context={
            "approval_recorded": True,
            "approval_ids": [ledger.requests[0].approval_id],
            "client_isolated": True,
            "internal_notes_excluded": False,
        },
    )

    assert result.decision == "hard_block"
    assert "internal_notes_excluded required" in result.blockers


def test_approval_state_does_not_bypass_governor_trustos_or_workspace_gate() -> None:
    request = ExecutionDecisionRequest(
        request_id="approved-export",
        action_type="generate_client_export",
        domain="client_workspace",
        owner_department="management",
        workspace_id="workspace-alpha",
        requested_amount=1.0,
        resource_type="client_export_quota",
        approval_state="approved",
        trustos_decision="hard_block",
        workspace_decision="hard_block",
    )

    result = evaluate_execution_request(request)

    assert result.outcome == "hard_block"
    assert "TrustOS gate is blocked" in result.blockers
    assert "client workspace gate is blocked" in result.blockers
    assert result.simulated_only is True


@pytest.mark.parametrize("payload", ("fixture-api-key-value", "fixture-password-value", "fixture-token-value"))
def test_secret_like_evidence_is_rejected_without_reflection(payload: str) -> None:
    with pytest.raises(ValueError, match="sanitized and secret-free") as error:
        ApprovalEvidence("evidence", "manual", "fixture", payload)

    assert payload not in str(error.value)

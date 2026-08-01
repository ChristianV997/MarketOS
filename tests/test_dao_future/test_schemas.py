"""Tests for backend.dao_future.schemas — placeholder dataclasses only.

Confirms every documented type instantiates with defaults and carries the
fields docs/DAO_FUTURE_ARCHITECTURE.md's mapping table describes. No
behavior to test — these are plain data containers with no validation.
"""
from backend.dao_future import (
    BusinessCell,
    CapitalAllocationRequest,
    GovernanceDecision,
    OperatorRole,
    Proposal,
    RevenueShareRule,
)


def test_all_six_required_types_are_exported():
    for cls in (BusinessCell, Proposal, GovernanceDecision, CapitalAllocationRequest, OperatorRole, RevenueShareRule):
        instance = cls()
        assert instance is not None


def test_business_cell_default_fields():
    cell = BusinessCell(cell_id="c1", workspace_id="ws1", name="Test Cell")
    assert cell.enabled_services == []
    assert cell.operator_ids == []


def test_proposal_default_status_is_proposed():
    proposal = Proposal(proposal_id="p1", cell_id="c1")
    assert proposal.status == "proposed"


def test_governance_decision_default_status_is_pending():
    decision = GovernanceDecision(decision_id="d1", proposal_id="p1")
    assert decision.decision == "pending"


def test_capital_allocation_request_default_approved_amount_is_none():
    request = CapitalAllocationRequest(request_id="r1", cell_id="c1", requested_amount=100.0)
    assert request.approved_amount is None


def test_operator_role_default_role_is_member():
    operator = OperatorRole(operator_id="o1", cell_id="c1")
    assert operator.role == "member"


def test_revenue_share_rule_carries_metadata_dict():
    rule = RevenueShareRule(rule_id="r1", cell_id="c1", operator_id="o1", share_pct=10.0)
    assert rule.metadata == {}

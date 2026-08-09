from backend.governance.approval_policy import evaluate_proposal_approval
from backend.governance.proposal import Proposal
from backend.organization.agent_role import AgentRole


def test_live_action_is_blocked_and_budget_requires_reviews():
    proposal = Proposal(requested_budget=100)
    role = AgentRole(agent_id="a", name="x", department_id="product", max_budget_authority=10)
    result = evaluate_proposal_approval(proposal, role, "workspace", live_action_requested=True)
    assert not result["allowed"]
    assert "human" in result["required_reviews"]
    assert "finance" in result["required_reviews"] and "risk" in result["required_reviews"]


def test_missing_workspace_blocks():
    result = evaluate_proposal_approval(Proposal(), None, None)
    assert not result["allowed"]
    assert "workspace_required" in result["blocked_reasons"]


def test_policy_thresholds_and_specialist_review():
    proposal = Proposal(requested_budget=20)
    role = AgentRole(agent_id="a", name="x", department_id="product", role_type="specialist", max_budget_authority=100, requires_review_above=10)
    result = evaluate_proposal_approval(proposal, role, "workspace")
    assert result["budget_review_required"] is True
    assert result["finance_review_required"] is True
    assert result["risk_review_required"] is True
    assert not result["allowed"]

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

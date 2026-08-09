from backend.governance.proposal import Proposal
from backend.governance.registry import GovernanceRegistry


def test_proposal_lifecycle_and_corrupt_file(tmp_path):
    path = tmp_path / "governance.json"
    registry = GovernanceRegistry(path)
    proposal = Proposal(workspace_id="w1", department_id="product", title="Research")
    proposal.mark_proposed(); proposal.mark_under_review(); proposal.mark_approved(); proposal.mark_executing("exp-1"); proposal.mark_completed()
    registry.register_proposal(proposal)
    loaded = GovernanceRegistry(path)
    assert loaded.get_proposal(proposal.proposal_id).status == "completed"
    path.write_text("not-json", encoding="utf-8")
    assert GovernanceRegistry(path).list_proposals() == []

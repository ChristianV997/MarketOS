from backend.governance.proposal import Proposal


def test_valid_and_invalid_transitions_are_safe():
    proposal = Proposal()
    assert proposal.transition("completed")["allowed"] is False
    assert proposal.status == "draft"
    proposal.mark_proposed(); proposal.mark_under_review(); proposal.mark_approved(); proposal.mark_executing(); proposal.mark_completed()
    assert proposal.status == "completed"
    assert proposal.transition("executing")["allowed"] is False


def test_rejected_and_blocked_are_terminal():
    rejected = Proposal(); rejected.mark_proposed(); rejected.mark_under_review(); rejected.mark_rejected("no")
    assert rejected.mark_executing()["allowed"] is False
    blocked = Proposal(); blocked.mark_proposed(); blocked.mark_blocked("unsafe")
    assert blocked.mark_approved()["allowed"] is False

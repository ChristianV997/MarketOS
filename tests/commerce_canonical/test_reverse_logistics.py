
from backend.economics.kernel import EvidenceRef as EvidenceReference
from evaluation.commerce.reverse_logistics import evaluate_return_eligibility

def test_return_eligible_standard():
    ev = {"receipt": EvidenceReference("id", "source")}
    decision = evaluate_return_eligibility("standard", 15, "new", ev)
    assert decision.eligible is True
    assert decision.reason == "eligible"
    assert decision.missing_evidence == ()

def test_return_missing_receipt():
    ev = {"receipt": None}
    decision = evaluate_return_eligibility("standard", 15, "new", ev)
    assert decision.eligible is False
    assert decision.reason == "missing_required_evidence"
    assert "receipt_missing" in decision.missing_evidence

def test_return_outside_window():
    ev = {"receipt": EvidenceReference("id", "source"), "authorization": None}
    decision = evaluate_return_eligibility("standard", 35, "new", ev)
    assert decision.eligible is False
    assert decision.reason == "missing_required_evidence"
    assert "authorization_missing_for_late_return" in decision.missing_evidence

def test_return_outside_window_with_auth():
    ev = {"receipt": EvidenceReference("id", "source"), "authorization": EvidenceReference("id", "source")}
    decision = evaluate_return_eligibility("standard", 35, "new", ev)
    assert decision.eligible is False
    assert decision.reason == "outside_return_window"

def test_oversized_freight_missing_schedule():
    ev = {"receipt": EvidenceReference("id", "source")}
    decision = evaluate_return_eligibility("oversized_freight", 5, "new", ev)
    assert decision.eligible is False
    assert decision.reason == "freight_schedule_required"
    assert "freight_schedule_missing" in decision.missing_evidence

def test_damaged_condition():
    ev = {"receipt": EvidenceReference("id", "source")}
    decision = evaluate_return_eligibility("standard", 5, "damaged_by_customer", ev)
    assert decision.eligible is False
    assert decision.reason == "customer_damaged"

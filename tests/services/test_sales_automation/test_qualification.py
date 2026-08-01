"""Tests for services.sales_automation.qualification."""
from services.sales_automation.qualification import generate_qualification_flow, qualify_lead
from services.sales_automation.schemas import QualificationSlots


class TestGenerateQualificationFlow:
    def test_known_vertical_uses_real_vertical_playbook_questions(self):
        flow = generate_qualification_flow("real_estate")
        assert "Timeline?" in flow

    def test_unknown_vertical_falls_back_to_generic_slots(self):
        flow = generate_qualification_flow("not_a_real_vertical")
        assert len(flow) == 5

    def test_never_raises_when_playbook_lookup_fails(self, monkeypatch):
        monkeypatch.setattr(
            "services.customer_intelligence.vertical_playbooks.build_vertical_playbook",
            lambda vertical: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        flow = generate_qualification_flow("real_estate")
        assert flow  # falls back to generic


class TestQualifyLead:
    def test_captures_intent(self):
        slots = QualificationSlots()
        qualify_lead(slots, "I'm looking to buy a new car")
        assert slots.intent == "buying"

    def test_captures_support_intent(self):
        slots = QualificationSlots()
        qualify_lead(slots, "I have a problem with my order, it's broken")
        assert slots.intent == "support"

    def test_captures_timeline(self):
        slots = QualificationSlots()
        qualify_lead(slots, "I need this asap")
        assert slots.timeline == "immediate"

    def test_captures_budget_from_currency_pattern(self):
        slots = QualificationSlots()
        qualify_lead(slots, "My budget is around $5,000")
        assert slots.budget is not None and "5" in slots.budget

    def test_captures_location_hint(self):
        slots = QualificationSlots()
        qualify_lead(slots, "I'm looking for something in Austin")
        assert slots.location == "Austin"

    def test_does_not_overwrite_already_filled_slots(self):
        slots = QualificationSlots(intent="buying")
        qualify_lead(slots, "actually I want to sell instead")
        assert slots.intent == "buying"  # first-write-wins, doesn't flip-flop

    def test_never_raises_on_empty_message(self):
        slots = QualificationSlots()
        qualify_lead(slots, "")
        assert slots.intent == "unknown"

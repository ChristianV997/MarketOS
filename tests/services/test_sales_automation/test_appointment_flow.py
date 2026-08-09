"""Tests for services.sales_automation.appointment_flow."""
from services.sales_automation.appointment_flow import (
    answer_faq,
    create_appointment_handoff,
    handle_chat_turn,
    recommend_next_message,
)
from services.sales_automation.schemas import ChatSession


class TestHandleChatTurn:
    def test_appends_lead_and_bot_turns(self):
        session = ChatSession(vertical="ecommerce_brand")
        handle_chat_turn(session, "I'm looking to buy something")
        assert len(session.turns) == 2
        assert session.turns[0].speaker == "lead"
        assert session.turns[1].speaker == "bot"

    def test_support_intent_hands_off_immediately(self):
        session = ChatSession(vertical="clinic_wellness")
        handle_chat_turn(session, "I have a problem, this is broken")
        assert session.handed_off is True
        assert "support" in session.handoff_reason

    def test_fully_qualified_session_hands_off(self):
        session = ChatSession(vertical="real_estate")
        handle_chat_turn(session, "I'm looking to buy a house in Austin")
        handle_chat_turn(session, "asap, budget is $500,000")
        assert session.handed_off is True

    def test_low_confidence_after_many_turns_hands_off(self):
        session = ChatSession(vertical="ecommerce_brand")
        for _ in range(7):
            handle_chat_turn(session, "hmm")  # never fills any slot meaningfully after the first
        assert session.handed_off is True
        assert "low qualification confidence" in session.handoff_reason

    def test_never_raises_on_none_like_input(self):
        session = ChatSession(vertical="ecommerce_brand")
        handle_chat_turn(session, "")
        assert session.turns  # still recorded, no crash


class TestRecommendNextMessage:
    def test_asks_for_first_missing_slot(self):
        session = ChatSession(vertical="ecommerce_brand")
        message = recommend_next_message(session)
        assert "buy, sell" in message  # intent question, since nothing captured yet

    def test_handed_off_session_gets_handoff_message(self):
        session = ChatSession(vertical="ecommerce_brand")
        session.handed_off = True
        message = recommend_next_message(session)
        assert "connecting you" in message


class TestAnswerFaq:
    def test_returns_context_answer_on_good_overlap(self):
        context = {"what are your business hours": "We're open Monday-Friday, 9am-5pm."}
        answer, from_context = answer_faq("what are your business hours", context)
        assert from_context is True
        assert "9am" in answer

    def test_never_invents_an_answer_outside_context(self):
        context = {"what are your business hours": "9am-5pm"}
        answer, from_context = answer_faq("do you offer a lifetime warranty", context)
        assert from_context is False
        assert "don't have that information" in answer

    def test_empty_context_never_raises(self):
        answer, from_context = answer_faq("anything", {})
        assert from_context is False


class TestCreateAppointmentHandoff:
    def test_high_quality_lead_recommends_booking(self):
        session = ChatSession(vertical="real_estate")
        handle_chat_turn(session, "I'm looking to buy a house in Austin")
        handle_chat_turn(session, "asap, budget is $500,000")
        handoff = create_appointment_handoff(session)
        assert handoff.lead_quality_score >= 0.6
        assert handoff.recommended_human_action == "book_appointment"

    def test_low_quality_lead_recommends_further_qualification(self):
        session = ChatSession(vertical="ecommerce_brand")
        handoff = create_appointment_handoff(session)  # no turns at all
        assert handoff.recommended_human_action == "human_qualification_needed"

    def test_transcript_summary_never_raises_and_is_nonempty(self):
        session = ChatSession(vertical="ecommerce_brand")
        handoff = create_appointment_handoff(session)
        assert handoff.transcript_summary

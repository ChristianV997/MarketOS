"""services.sales_automation.appointment_flow — handle_chat_turn,
recommend_next_message, create_appointment_handoff, and FAQ answering.

Every reply is a fixed template or a verbatim FAQ-context answer — the bot
never invents claims, never makes a binding commitment (price/availability/
refunds), and hands off to a human whenever confidence is low or intent is
a support/complaint. No real messaging integration — this operates purely
on ChatSession objects a caller constructs (see simulate.py for a local
conversation harness).
"""
from __future__ import annotations

from .qualification import qualify_lead
from .schemas import SLOT_ORDER, AppointmentHandoff, ChatSession, ChatTurn

_SLOT_QUESTIONS = {
    "intent": "What brings you here today — are you looking to buy, sell, or just exploring?",
    "need": "Tell me a bit more about what you're looking for.",
    "timeline": "What's your timeline — right away, or just exploring for now?",
    "budget": "Do you have a budget range in mind?",
    "location": "Where are you located, so I can check availability in your area?",
}

_HANDOFF_MESSAGE = "I'm connecting you with a member of our team who can help further — they'll be in touch shortly."
_SUPPORT_HANDOFF_MESSAGE = "I'm sorry to hear that — let me connect you with a member of our team who can help resolve this directly."
_FAQ_UNKNOWN_MESSAGE = "I don't have that information on hand — let me get someone who can answer that directly rather than guess."

_MIN_TURNS_BEFORE_LOW_CONFIDENCE_HANDOFF = 6
_LOW_CONFIDENCE_THRESHOLD = 0.4


def _compute_confidence(session: ChatSession) -> float:
    return round(session.slots.filled_count() / len(SLOT_ORDER), 4)


def _should_hand_off(session: ChatSession) -> tuple[bool, str | None]:
    if session.slots.intent == "support":
        return True, "support/complaint intent — route to human immediately"
    lead_turns = sum(1 for t in session.turns if t.speaker == "lead")
    if lead_turns >= _MIN_TURNS_BEFORE_LOW_CONFIDENCE_HANDOFF and session.confidence < _LOW_CONFIDENCE_THRESHOLD:
        return True, "low qualification confidence after multiple turns — escalate to human"
    if session.slots.filled_count() == len(SLOT_ORDER):
        return True, "fully qualified — hand off for appointment booking"
    return False, None


def recommend_next_message(session: ChatSession) -> str:
    """Never raises."""
    if session.handed_off:
        return _HANDOFF_MESSAGE
    if session.slots.intent == "support":
        return _SUPPORT_HANDOFF_MESSAGE
    missing = session.slots.missing_slots()
    if not missing:
        return "Great, I have everything I need. Let's get you booked with a specialist — what's the best way to reach you?"
    return _SLOT_QUESTIONS.get(missing[0], "Could you tell me a bit more about that?")


def answer_faq(question: str, context: dict[str, str]) -> tuple[str, bool]:
    """Never raises. Returns (answer, answered_from_context) — a keyword-
    overlap match against `context` ({faq_question: answer}); no match
    returns a safe non-committal message rather than inventing an answer."""
    try:
        q_words = set(question.lower().split())
        best_match, best_overlap = None, 0
        for faq_q, faq_a in context.items():
            overlap = len(q_words & set(faq_q.lower().split()))
            if overlap > best_overlap:
                best_match, best_overlap = faq_a, overlap
        if best_match and best_overlap >= 2:
            return best_match, True
    except Exception:
        pass
    return _FAQ_UNKNOWN_MESSAGE, False


def handle_chat_turn(session: ChatSession, message: str) -> ChatSession:
    """Never raises. Mutates and returns `session`."""
    try:
        session.turns.append(ChatTurn(speaker="lead", message=message))
        qualify_lead(session.slots, message)
        session.confidence = _compute_confidence(session)

        handed_off, reason = _should_hand_off(session)
        if handed_off and not session.handed_off:
            session.handed_off = True
            session.handoff_reason = reason

        reply = recommend_next_message(session)
        session.turns.append(ChatTurn(speaker="bot", message=reply))
    except Exception:
        pass
    return session


def _lead_quality_score(session: ChatSession) -> float:
    score = session.slots.filled_count() / len(SLOT_ORDER)
    if session.slots.intent in ("buying", "renting"):
        score += 0.1
    if session.slots.timeline == "immediate":
        score += 0.1
    if session.slots.intent == "browsing" or session.slots.timeline == "exploring":
        score -= 0.1
    return round(max(0.0, min(1.0, score)), 4)


def _summarize_transcript(session: ChatSession) -> str:
    lead_messages = [t.message for t in session.turns if t.speaker == "lead"]
    slots = session.slots
    return (
        f"{len(lead_messages)} lead message(s). "
        f"Intent: {slots.intent}. Need: {slots.need or 'not captured'}. "
        f"Timeline: {slots.timeline or 'not captured'}. Budget: {slots.budget or 'not captured'}. "
        f"Location: {slots.location or 'not captured'}."
    )


def create_appointment_handoff(session: ChatSession) -> AppointmentHandoff:
    """Never raises."""
    score = _lead_quality_score(session)
    action = "book_appointment" if score >= 0.6 else "human_qualification_needed"
    return AppointmentHandoff(
        session_id=session.session_id,
        vertical=session.vertical,
        slots=session.slots.to_dict(),
        transcript_summary=_summarize_transcript(session),
        lead_quality_score=score,
        recommended_human_action=action,
    )

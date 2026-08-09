"""Tests for services.sales_automation.follow_up.generate_follow_up_sequence."""
from services.sales_automation.follow_up import generate_follow_up_sequence
from services.sales_automation.schemas import ChatSession


def test_returns_three_messages():
    session = ChatSession(vertical="ecommerce_brand")
    sequence = generate_follow_up_sequence(session)
    assert len(sequence) == 3


def test_references_captured_need_when_available():
    session = ChatSession(vertical="ecommerce_brand")
    session.slots.need = "a new laptop"
    sequence = generate_follow_up_sequence(session)
    assert "a new laptop" in sequence[0]


def test_never_fabricates_need_when_not_captured():
    session = ChatSession(vertical="ecommerce_brand")
    sequence = generate_follow_up_sequence(session)
    assert "what you were looking into" in sequence[0]

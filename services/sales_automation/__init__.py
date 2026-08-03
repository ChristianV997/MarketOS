"""services.sales_automation — chat-based lead qualification and
appointment handoff. Simulation-only: no real outbound messaging adapter
exists yet (WhatsApp/web-chat/CRM/calendar integrations are future work —
see docs/SALES_AUTOMATION_MODULE.md)."""
from .appointment_flow import answer_faq, create_appointment_handoff, handle_chat_turn, recommend_next_message
from .follow_up import generate_follow_up_sequence
from .qualification import generate_qualification_flow, qualify_lead
from .real_handoff import attempt_real_conversation_handoff
from .report import render_sales_bot_setup_plan_markdown
from .schemas import AppointmentHandoff, ChatSession, QualificationSlots
from .simulate import run_sales_bot_simulation, run_simulated_conversation

__all__ = [
    "qualify_lead",
    "generate_qualification_flow",
    "handle_chat_turn",
    "recommend_next_message",
    "answer_faq",
    "create_appointment_handoff",
    "generate_follow_up_sequence",
    "run_simulated_conversation",
    "run_sales_bot_simulation",
    "attempt_real_conversation_handoff",
    "render_sales_bot_setup_plan_markdown",
    "ChatSession",
    "QualificationSlots",
    "AppointmentHandoff",
]

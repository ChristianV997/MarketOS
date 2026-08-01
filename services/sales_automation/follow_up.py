"""services.sales_automation.follow_up — generate_follow_up_sequence.

Templates only — this returns message text for a human/future adapter to
actually send, it does not send anything itself.
"""
from __future__ import annotations

from .schemas import ChatSession


def generate_follow_up_sequence(session: ChatSession) -> list[str]:
    """Never raises. 3-message re-engagement sequence for a lead that went
    quiet, referencing captured slots when available without ever
    fabricating specifics the lead didn't actually provide."""
    need = session.slots.need or "what you were looking into"
    return [
        f"Hey — just checking in about {need}. Still something you'd like help with?",
        "No pressure at all — happy to answer any questions whenever you're ready.",
        "Last check-in from me — reply anytime and I'll pick this back up, or let me know if now isn't the right time.",
    ]

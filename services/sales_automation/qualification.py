"""services.sales_automation.qualification — generate_qualification_flow,
qualify_lead.

generate_qualification_flow reuses services.customer_intelligence's vertical
playbooks (qualification_questions) rather than a second per-vertical
question bank. qualify_lead extracts slot values via deterministic keyword/
pattern matching — no LLM call, no cost, fully testable offline.
"""
from __future__ import annotations

import re

from .schemas import QualificationSlots

_INTENT_KEYWORDS = {
    "buying": ["buy", "purchase", "looking to get", "interested in getting"],
    "selling": ["sell", "sale", "list my", "get rid of"],
    "renting": ["rent", "lease", "renting"],
    "support": ["help", "issue", "problem", "broken", "not working", "complaint"],
    "browsing": ["just looking", "just browsing", "curious", "not sure yet"],
}

_TIMELINE_KEYWORDS = {
    "immediate": ["today", "now", "asap", "urgent", "emergency", "right away"],
    "this_week": ["this week", "few days", "couple of days"],
    "this_month": ["this month", "few weeks", "soon"],
    "exploring": ["not sure", "just exploring", "no rush", "eventually"],
}

# Bound repeated numeric groups because messages are user-controlled.  This
# avoids pathological regex backtracking on adversarial input.
_BUDGET_PATTERN = re.compile(
    r"[\$€£]\s?\d{1,18}(?:[\d,.]{0,30})|\d{1,18}(?:[\d,.]{0,30})\s?(?:usd|mxn|dollars|pesos|k\b)",
    re.IGNORECASE,
)
_LOCATION_HINT_PATTERN = re.compile(r"\b(?:in|near|at)\s+([A-Z][a-zA-Z\s]{2,30})")


def generate_qualification_flow(vertical: str) -> list[str]:
    """Never raises. Returns the vertical's real qualification questions
    (services.customer_intelligence) when known, else the 5 generic slots."""
    try:
        from services.customer_intelligence.vertical_playbooks import build_vertical_playbook
        playbook = build_vertical_playbook(vertical)
        if playbook.qualification_questions:
            return list(playbook.qualification_questions)
    except Exception:
        pass
    return [
        "What brings you here today?",
        "What are you looking to accomplish?",
        "What's your timeline?",
        "What's your budget range?",
        "Where are you located?",
    ]


def qualify_lead(slots: QualificationSlots, message: str) -> QualificationSlots:
    """Never raises. Updates and returns `slots` in place from `message`'s
    content — a message can fill more than one slot at once."""
    try:
        lower = message.lower()

        if slots.intent == "unknown":
            for intent, keywords in _INTENT_KEYWORDS.items():
                if any(kw in lower for kw in keywords):
                    slots.intent = intent
                    break

        if slots.timeline is None:
            for timeline, keywords in _TIMELINE_KEYWORDS.items():
                if any(kw in lower for kw in keywords):
                    slots.timeline = timeline
                    break

        if slots.budget is None:
            match = _BUDGET_PATTERN.search(message[:512])
            if match:
                slots.budget = match.group(0).strip()

        if slots.location is None:
            match = _LOCATION_HINT_PATTERN.search(message)
            if match:
                slots.location = match.group(1).strip()

        if slots.need is None and len(message.strip()) > 3:
            # First substantive message that isn't purely a slot-fill answer
            # doubles as the "need" statement if nothing more specific was
            # captured — a deliberately low bar so the bot always has
            # *something* to hand off, matching "never leave a slot
            # meaningfully empty when the lead has actually said something".
            slots.need = message.strip()[:200]
    except Exception:
        pass

    return slots

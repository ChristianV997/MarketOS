"""services.sales_automation.schemas — chat qualification session models."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

INTENTS = ("buying", "selling", "renting", "browsing", "support", "unknown")

# Fixed slot-filling order — deterministic, matches the qualification
# spec's required capture list (intent, need, timeline, budget, location).
SLOT_ORDER = ("intent", "need", "timeline", "budget", "location")


@dataclass
class QualificationSlots:
    intent: str = "unknown"
    need: str | None = None
    timeline: str | None = None
    budget: str | None = None
    location: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"intent": self.intent, "need": self.need, "timeline": self.timeline,
                "budget": self.budget, "location": self.location}

    def filled_count(self) -> int:
        return sum(1 for slot in SLOT_ORDER if getattr(self, slot) not in (None, "unknown"))

    def missing_slots(self) -> list[str]:
        return [slot for slot in SLOT_ORDER if getattr(self, slot) in (None, "unknown")]


@dataclass
class ChatTurn:
    speaker: str  # "lead" | "bot"
    message: str
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {"speaker": self.speaker, "message": self.message, "ts": self.ts}


@dataclass
class ChatSession:
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    vertical: str = "ecommerce_brand"
    turns: list[ChatTurn] = field(default_factory=list)
    slots: QualificationSlots = field(default_factory=QualificationSlots)
    confidence: float = 0.0
    handed_off: bool = False
    handoff_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id, "vertical": self.vertical,
            "turns": [t.to_dict() for t in self.turns], "slots": self.slots.to_dict(),
            "confidence": self.confidence, "handed_off": self.handed_off,
            "handoff_reason": self.handoff_reason,
        }


@dataclass
class AppointmentHandoff:
    session_id: str
    vertical: str
    slots: dict[str, Any]
    transcript_summary: str
    lead_quality_score: float
    recommended_human_action: str
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id, "vertical": self.vertical, "slots": self.slots,
            "transcript_summary": self.transcript_summary,
            "lead_quality_score": self.lead_quality_score,
            "recommended_human_action": self.recommended_human_action,
            "generated_at": self.generated_at,
        }

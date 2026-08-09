from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CalendarBlock:
    block_id: str
    workspace_id: str
    day_label: str
    start_slot: str
    duration_hours: float
    task_ids: list[str] = field(default_factory=list)
    title: str = ""
    objective: str = ""
    outputs: list[str] = field(default_factory=list)
    safety_notes: list[str] = field(default_factory=lambda: ["Local planning block; no automatic execution."])
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.start_slot not in {"morning", "midday", "afternoon", "evening", "flexible", "backlog"}:
            self.start_slot = "flexible"
        self.duration_hours = max(0.0, min(float(self.duration_hours or 0), 24.0))

    def to_dict(self): return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data): return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass
class OperatingCalendar:
    calendar_id: str
    workspace_id: str
    plan_id: str
    horizon: str
    blocks: list[CalendarBlock] = field(default_factory=list)
    total_hours: float = 0.0
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self): return {key: ([x.to_dict() for x in value] if key == "blocks" else value) for key, value in ((key, getattr(self, key)) for key in self.__dataclass_fields__)}
    @classmethod
    def from_dict(cls, data):
        data = dict(data); data["blocks"] = [CalendarBlock.from_dict(x) for x in data.get("blocks", [])]
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})
    def to_markdown(self):
        rows = "\n".join(f"- **{b.day_label} / {b.start_slot}** ({b.duration_hours:.1f}h): {b.title} — `{', '.join(b.task_ids)}`" for b in self.blocks) or "- No blocks."
        return f"# Operating Calendar\n\nPlan `{self.plan_id}` · `{self.horizon}` · `{self.total_hours:.1f}h`\n\n{rows}\n\n> Local calendar artifact only. No external calendar writes or automatic execution occur.\n"
    def to_ics_text(self):
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//MarketOS//Operating Calendar//EN", "X-MARKETOS-LOCAL_ONLY:TRUE"]
        for block in self.blocks:
            lines += ["BEGIN:VEVENT", f"UID:{block.block_id}@marketos.local", f"SUMMARY:{block.title}", f"DESCRIPTION:{block.objective}\\nPlanning-only; no automatic execution.", f"X-MARKETOS-DAY:{block.day_label}", f"X-MARKETOS-SLOT:{block.start_slot}", "END:VEVENT"]
        return "\n".join(lines + ["END:VCALENDAR", ""])


def build_operating_calendar(plan, preferred_start_day: str = "day_1") -> OperatingCalendar:
    blocks = []
    slot_order = ["morning", "midday", "afternoon", "evening"]
    for task in plan.tasks:
        slot = "backlog" if task.status == "blocked" or task.due_day == "backlog" else slot_order[task.sequence_order % len(slot_order)]
        blocks.append(CalendarBlock(f"block_{plan.plan_id}_{task.task_id}", plan.workspace_id, task.due_day or preferred_start_day, slot, task.estimated_hours, [task.task_id], task.title, task.description, task.expected_outputs, task.safety_notes, {"planning_only": True}))
    return OperatingCalendar(f"calendar_{plan.plan_id}", plan.workspace_id, plan.plan_id, plan.horizon, blocks, sum(x.duration_hours for x in blocks), metadata={"local_only": True, "preferred_start_day": preferred_start_day})

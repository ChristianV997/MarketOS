"""services.sales_automation.report — render_sales_bot_setup_plan_markdown."""
from __future__ import annotations

from services.reporting.render import render_markdown_report

from .schemas import AppointmentHandoff, ChatSession

TITLE = "MarketOS Appointment Setter Bot Setup Plan"


def render_sales_bot_setup_plan_markdown(
    session: ChatSession, handoff: AppointmentHandoff, qualification_flow: list[str], *, dry_run: bool = True,
) -> str:
    sections = [
        {"heading": "Vertical", "body": {"vertical": session.vertical}},
        {"heading": "Qualification Flow", "body": qualification_flow},
        {"heading": "Simulated Transcript", "body": [t.to_dict() for t in session.turns]},
        {"heading": "Captured Slots", "body": session.slots.to_dict()},
        {"heading": "Appointment Handoff", "body": handoff.to_dict()},
    ]
    return render_markdown_report(TITLE, sections, dry_run=dry_run)

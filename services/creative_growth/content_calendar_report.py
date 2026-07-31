"""services.creative_growth.content_calendar_report — build_content_calendar.

Wraps the existing core.ugc.content_calendar singleton rather than a new
scheduling primitive. Dry-run by design: this only reports gaps and, when
asked, schedules calendar entries (bookkeeping only) — it never posts
anything to a real platform.
"""
from __future__ import annotations

from typing import Any


def build_content_calendar(
    product_name: str,
    *,
    briefs: list[dict[str, Any]] | None = None,
    schedule_gap_fill: bool = False,
) -> dict[str, Any]:
    """Never raises. Reports the product's current content gap status via
    core.ugc.content_calendar; if schedule_gap_fill=True and a gap exists,
    schedules one calendar entry per brief (dry-run bookkeeping only, no
    real post)."""
    has_gap = True
    gap_details: dict[str, Any] = {}
    scheduled: list[dict[str, Any]] = []

    try:
        from core.ugc.content_calendar import content_calendar
        has_gap, gap_details = content_calendar.has_content_gap(product_name)

        if schedule_gap_fill and has_gap:
            for i, brief in enumerate(briefs or []):
                post = content_calendar.schedule_post(
                    creator_id=f"unassigned_creator_{i}",
                    product_id=product_name,
                    content_type=brief.get("content_type", "post"),
                )
                scheduled.append(post.to_dict())
    except Exception:
        pass

    return {
        "product_name": product_name,
        "has_content_gap": has_gap,
        "gap_details": gap_details,
        "newly_scheduled": scheduled,
    }

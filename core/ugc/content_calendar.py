"""core.ugc.content_calendar — organic content scheduling and gap detection.

Lightweight calendar for scheduled organic content (UGC posts, unboxings,
reviews from seeded creators). Tracks:
- Scheduled posts per product (from creator calendar integrations)
- Content gap detection (no scheduled posts for N days)
- Triggers auto-seeding of new creators when gaps exceed threshold
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone


class ContentPost:
    """Scheduled or posted organic content (from seeded creator)."""

    def __init__(
        self,
        creator_id: str,
        product_id: str,
        content_type: str = "post",  # post, unboxing, review, etc.
        scheduled_date: float | None = None,
        posted_date: float | None = None,
    ):
        self.creator_id = creator_id
        self.product_id = product_id
        self.content_type = content_type
        self.scheduled_date = scheduled_date or datetime.now(timezone.utc).timestamp()
        self.posted_date = posted_date
        self.engagement_score = 0.0  # Updated after post (likes, shares, comments normalized)

    def mark_posted(self, ts: float | None = None, engagement: float = 0.0) -> None:
        """Mark content as posted and set engagement."""
        self.posted_date = ts or datetime.now(timezone.utc).timestamp()
        self.engagement_score = engagement

    def to_dict(self) -> dict:
        """Serialize for storage."""
        return {
            "creator_id": self.creator_id,
            "product_id": self.product_id,
            "content_type": self.content_type,
            "scheduled_date": self.scheduled_date,
            "posted_date": self.posted_date,
            "engagement_score": round(self.engagement_score, 4),
        }


class ContentCalendar:
    """Track scheduled organic content per product.

    Enables gap detection: if no content scheduled for product within N days,
    flag for auto-seeding of new creators.
    """

    def __init__(self, gap_threshold_days: int = 7):
        self.gap_threshold_days = gap_threshold_days
        self.gap_threshold_seconds = gap_threshold_days * 86400

        # product_id → list of ContentPost
        self._calendar: dict[str, list[ContentPost]] = defaultdict(list)
        # (creator_id, product_id) → ContentPost
        self._by_creator_product: dict[tuple[str, str], list[ContentPost]] = defaultdict(list)

    def schedule_post(
        self,
        creator_id: str,
        product_id: str,
        content_type: str = "post",
        scheduled_date: float | None = None,
    ) -> ContentPost:
        """Add a scheduled post to the calendar."""
        post = ContentPost(creator_id, product_id, content_type, scheduled_date)
        self._calendar[product_id].append(post)
        self._by_creator_product[(creator_id, product_id)].append(post)
        return post

    def mark_posted(
        self,
        creator_id: str,
        product_id: str,
        engagement: float = 0.0,
        posted_date: float | None = None,
    ) -> None:
        """Mark a scheduled post as posted (find by most recent scheduled for creator/product)."""
        posts = self._by_creator_product.get((creator_id, product_id), [])
        if posts:
            # Mark the most recent unposted post
            for post in reversed(posts):
                if post.posted_date is None:
                    post.mark_posted(posted_date, engagement)
                    break

    def has_content_gap(self, product_id: str, ts: float | None = None) -> tuple[bool, dict]:
        """Check if a product has a content gap (no scheduled posts within threshold).

        Returns (has_gap: bool, details: dict) where details contains:
          - days_since_last_scheduled: days since most recent scheduled post
          - days_since_last_posted: days since most recent actually-posted post
          - num_scheduled_upcoming: count of scheduled posts in next N days
          - threshold_days: the gap threshold
        """
        ts = ts or datetime.now(timezone.utc).timestamp()
        posts = self._calendar.get(product_id, [])

        if not posts:
            return True, {
                "days_since_last_scheduled": float("inf"),
                "days_since_last_posted": float("inf"),
                "num_scheduled_upcoming": 0,
                "threshold_days": self.gap_threshold_days,
                "no_posts_ever": True,
            }

        # Most recent scheduled
        scheduled_posts = [p for p in posts if p.scheduled_date]
        most_recent_scheduled = max((p.scheduled_date for p in scheduled_posts), default=None)
        days_since_scheduled = (ts - most_recent_scheduled) / 86400 if most_recent_scheduled else float("inf")

        # Most recent posted
        posted_posts = [p for p in posts if p.posted_date]
        most_recent_posted = max((p.posted_date for p in posted_posts), default=None)
        days_since_posted = (ts - most_recent_posted) / 86400 if most_recent_posted else float("inf")

        # Count scheduled for near future
        upcoming_cutoff = ts + self.gap_threshold_seconds
        num_upcoming = sum(1 for p in posts if p.scheduled_date and ts < p.scheduled_date <= upcoming_cutoff)

        # Gap exists if: no recent posts AND no upcoming posts
        has_gap = (days_since_scheduled > self.gap_threshold_days) and (num_upcoming == 0)

        return has_gap, {
            "days_since_last_scheduled": round(days_since_scheduled, 2),
            "days_since_last_posted": round(days_since_posted, 2),
            "num_scheduled_upcoming": num_upcoming,
            "threshold_days": self.gap_threshold_days,
            "no_posts_ever": False,
        }

    def get_products_with_gaps(self, ts: float | None = None) -> list[str]:
        """Return all products with content gaps (for auto-seeding trigger)."""
        ts = ts or datetime.now(timezone.utc).timestamp()
        products_with_gaps = []

        for product_id in self._calendar.keys():
            has_gap, _ = self.has_content_gap(product_id, ts)
            if has_gap:
                products_with_gaps.append(product_id)

        return products_with_gaps

    def all_posts_as_dicts(self) -> list[dict]:
        """Export all posts for persistence."""
        all_dicts = []
        for posts_list in self._calendar.values():
            for post in posts_list:
                all_dicts.append(post.to_dict())
        return all_dicts

    def restore_from_dicts(self, posts_data: list[dict]) -> None:
        """Restore posts from persisted data."""
        self._calendar.clear()
        self._by_creator_product.clear()

        for data in posts_data:
            post = ContentPost(
                creator_id=data["creator_id"],
                product_id=data["product_id"],
                content_type=data.get("content_type", "post"),
                scheduled_date=data.get("scheduled_date"),
            )
            post.posted_date = data.get("posted_date")
            post.engagement_score = data.get("engagement_score", 0.0)

            self._calendar[post.product_id].append(post)
            self._by_creator_product[(post.creator_id, post.product_id)].append(post)


# Module singleton
content_calendar = ContentCalendar(gap_threshold_days=7)


# ── persistence (Phase E) ─────────────────────────────────────────────────────
# The calendar previously lived only in memory; organic posting made it a
# real bookkeeping surface, so it now snapshots to state/content_calendar.json
# on every write (PlaybookMemory-style) and restores on import.

def _persist_calendar() -> None:
    try:
        from backend.core.persistence import save_json_atomic, state_path
        save_json_atomic(state_path("content_calendar.json"),
                         {"posts": content_calendar.all_posts_as_dicts()})
    except Exception:
        pass  # persistence is best-effort, never disturbs callers


def _wrap_persisting(method_name: str) -> None:
    original = getattr(ContentCalendar, method_name)

    def wrapper(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if self is content_calendar:
            _persist_calendar()
        return result

    setattr(ContentCalendar, method_name, wrapper)


for _m in ("schedule_post", "mark_posted"):
    _wrap_persisting(_m)


def _restore_calendar() -> None:
    try:
        from backend.core.persistence import load_json, state_path
        data = load_json(state_path("content_calendar.json"))
        if data and data.get("posts"):
            content_calendar.restore_from_dicts(data["posts"])
    except Exception:
        pass


_restore_calendar()

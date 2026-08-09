"""Tests for core.ugc.content_calendar — organic content scheduling and gap detection."""
from __future__ import annotations

from datetime import datetime, timezone
import pytest

from core.ugc.content_calendar import ContentCalendar, ContentPost


class TestContentPostBasics:
    """Single content post basics."""

    def test_create_post(self):
        post = ContentPost("creator_1", "product_1", content_type="unboxing")
        assert post.creator_id == "creator_1"
        assert post.product_id == "product_1"
        assert post.content_type == "unboxing"
        assert post.posted_date is None
        assert post.engagement_score == 0.0

    def test_mark_post_as_posted(self):
        post = ContentPost("creator_1", "product_1")
        post.mark_posted(engagement=0.75)
        assert post.posted_date is not None
        assert post.engagement_score == 0.75

    def test_post_serialization(self):
        post = ContentPost("creator_1", "product_1", content_type="review")
        post.mark_posted(engagement=0.8)

        data = post.to_dict()
        assert data["creator_id"] == "creator_1"
        assert data["product_id"] == "product_1"
        assert data["content_type"] == "review"
        assert data["engagement_score"] == pytest.approx(0.8)


class TestContentCalendarBasics:
    """Calendar operations."""

    def test_schedule_post(self):
        cal = ContentCalendar()
        post = cal.schedule_post("creator_1", "product_1", "post")
        assert post is not None
        assert post.product_id == "product_1"

    def test_mark_scheduled_post_as_posted(self):
        cal = ContentCalendar()
        cal.schedule_post("creator_1", "product_1", "post")
        cal.mark_posted("creator_1", "product_1", engagement=0.7)

        # Verify it was marked
        posts = cal._by_creator_product[("creator_1", "product_1")]
        assert posts[0].posted_date is not None
        assert posts[0].engagement_score == 0.7

    def test_multiple_posts_per_product(self):
        cal = ContentCalendar()
        cal.schedule_post("creator_1", "product_1", "post")
        cal.schedule_post("creator_1", "product_1", "unboxing")
        cal.schedule_post("creator_2", "product_1", "review")

        posts = cal._calendar["product_1"]
        assert len(posts) == 3


class TestContentGapDetection:
    """Gap detection logic."""

    def test_no_gap_with_recent_post(self):
        cal = ContentCalendar(gap_threshold_days=7)
        now = datetime.now(timezone.utc).timestamp()
        # Schedule a post for today
        cal.schedule_post("creator_1", "product_1", scheduled_date=now)

        has_gap, details = cal.has_content_gap("product_1", ts=now)
        assert not has_gap
        assert details["days_since_last_scheduled"] == pytest.approx(0.0, abs=0.01)

    def test_gap_when_no_posts(self):
        cal = ContentCalendar()
        has_gap, details = cal.has_content_gap("product_1")
        assert has_gap
        assert details["no_posts_ever"]

    def test_gap_after_threshold(self):
        cal = ContentCalendar(gap_threshold_days=7)
        now = datetime.now(timezone.utc).timestamp()
        # Schedule post 10 days ago
        old_ts = now - (10 * 86400)
        cal.schedule_post("creator_1", "product_1", scheduled_date=old_ts)

        has_gap, details = cal.has_content_gap("product_1", ts=now)
        assert has_gap
        assert details["days_since_last_scheduled"] > 7

    def test_no_gap_with_upcoming_posts(self):
        cal = ContentCalendar(gap_threshold_days=7)
        now = datetime.now(timezone.utc).timestamp()
        # Last post was 5 days ago
        old_ts = now - (5 * 86400)
        cal.schedule_post("creator_1", "product_1", scheduled_date=old_ts)
        # But new post scheduled in 2 days
        future_ts = now + (2 * 86400)
        cal.schedule_post("creator_2", "product_1", scheduled_date=future_ts)

        has_gap, details = cal.has_content_gap("product_1", ts=now)
        # No gap because upcoming post within 7-day threshold
        assert not has_gap
        assert details["num_scheduled_upcoming"] > 0

    def test_multiple_products_different_gaps(self):
        cal = ContentCalendar(gap_threshold_days=7)
        now = datetime.now(timezone.utc).timestamp()

        # Product 1: recent post
        cal.schedule_post("creator_1", "product_1", scheduled_date=now)

        # Product 2: old post
        old_ts = now - (10 * 86400)
        cal.schedule_post("creator_2", "product_2", scheduled_date=old_ts)

        has_gap_1, _ = cal.has_content_gap("product_1", ts=now)
        has_gap_2, _ = cal.has_content_gap("product_2", ts=now)

        assert not has_gap_1
        assert has_gap_2


class TestGapProducts:
    """Get products with gaps."""

    def test_get_products_with_gaps(self):
        cal = ContentCalendar(gap_threshold_days=7)
        now = datetime.now(timezone.utc).timestamp()

        # Product 1: no gap
        cal.schedule_post("creator_1", "product_1", scheduled_date=now)

        # Product 2: has gap
        old_ts = now - (10 * 86400)
        cal.schedule_post("creator_2", "product_2", scheduled_date=old_ts)

        # Product 3: no posts ever (gap)
        # Just check without scheduling anything

        gaps = cal.get_products_with_gaps(ts=now)
        assert "product_2" in gaps

    def test_no_gaps(self):
        cal = ContentCalendar(gap_threshold_days=7)
        now = datetime.now(timezone.utc).timestamp()

        for i in range(3):
            cal.schedule_post(f"creator_{i}", f"product_{i}", scheduled_date=now)

        gaps = cal.get_products_with_gaps(ts=now)
        assert len(gaps) == 0

    def test_all_gaps(self):
        cal = ContentCalendar(gap_threshold_days=7)
        now = datetime.now(timezone.utc).timestamp()
        old_ts = now - (10 * 86400)

        for i in range(3):
            cal.schedule_post(f"creator_{i}", f"product_{i}", scheduled_date=old_ts)

        gaps = cal.get_products_with_gaps(ts=now)
        assert len(gaps) == 3


class TestCalendarSerialization:
    """Persistence round-trip."""

    def test_export_and_restore(self):
        cal1 = ContentCalendar()
        cal1.schedule_post("creator_1", "product_1", "post")
        cal1.schedule_post("creator_2", "product_1", "unboxing")
        cal1.mark_posted("creator_1", "product_1", engagement=0.8)

        posts_data = cal1.all_posts_as_dicts()

        cal2 = ContentCalendar()
        cal2.restore_from_dicts(posts_data)

        posts_list = cal2._calendar["product_1"]
        assert len(posts_list) == 2

        # Check first post is marked as posted
        posted_posts = [p for p in posts_list if p.posted_date is not None]
        assert len(posted_posts) == 1
        assert posted_posts[0].engagement_score == 0.8


class TestCalendarThreshold:
    """Custom gap threshold."""

    def test_custom_threshold(self):
        cal = ContentCalendar(gap_threshold_days=14)
        now = datetime.now(timezone.utc).timestamp()

        # Post 10 days ago (within 14-day threshold)
        old_ts = now - (10 * 86400)
        cal.schedule_post("creator_1", "product_1", scheduled_date=old_ts)

        has_gap, details = cal.has_content_gap("product_1", ts=now)
        assert not has_gap
        assert details["threshold_days"] == 14

        # Post 15 days ago (beyond 14-day threshold)
        very_old_ts = now - (15 * 86400)
        cal2 = ContentCalendar(gap_threshold_days=14)
        cal2.schedule_post("creator_1", "product_1", scheduled_date=very_old_ts)

        has_gap2, _ = cal2.has_content_gap("product_1", ts=now)
        assert has_gap2

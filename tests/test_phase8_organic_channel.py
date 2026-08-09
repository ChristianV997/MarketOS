"""Phase 8: Organic/Earned-Media Channel Tests.

Tests cover:
1. Creator seeding tracking (cost, attributed orders)
2. Organic ROAS computation (cost per order)
3. Creator performance ranking
4. Content calendar scheduling
5. Content gap detection
6. Integration with capital allocation
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.ugc.creator_tracker import CreatorSeed, CreatorTracker, creator_tracker
from core.ugc.content_calendar import ContentCalendar, ContentPost


class TestCreatorSeeding:
    """Test creator seeding event tracking."""

    def test_creator_seed_initialization(self):
        """Test CreatorSeed object creation."""
        seed = CreatorSeed(
            creator_id="creator_123",
            product_id="product_456",
            seeding_cost=50.0,
        )
        assert seed.creator_id == "creator_123"
        assert seed.product_id == "product_456"
        assert seed.seeding_cost == 50.0
        assert seed.organic_orders_attributed == 0
        assert seed.organic_revenue == 0.0

    def test_creator_seed_add_organic_order(self):
        """Test recording organic orders on a seed."""
        seed = CreatorSeed("creator_1", "product_1", seeding_cost=50.0)

        # Record two orders
        seed.add_organic_order(order_value=29.99)
        seed.add_organic_order(order_value=34.99)

        assert seed.organic_orders_attributed == 2
        assert abs(seed.organic_revenue - 64.98) < 0.01

    def test_creator_seed_serialization(self):
        """Test serialization and deserialization of CreatorSeed."""
        seed = CreatorSeed("creator_1", "product_1", seeding_cost=50.0)
        seed.add_organic_order(29.99)

        # Serialize
        data = seed.to_dict()
        assert data["creator_id"] == "creator_1"
        assert data["seeding_cost"] == 50.0
        assert data["organic_orders_attributed"] == 1

        # Deserialize
        restored = CreatorSeed.from_dict(data)
        assert restored.creator_id == "creator_1"
        assert restored.organic_orders_attributed == 1
        assert abs(restored.organic_revenue - 29.99) < 0.01


class TestCreatorTracker:
    """Test CreatorTracker management."""

    def test_tracker_initialization(self):
        """Test CreatorTracker initialization."""
        tracker = CreatorTracker()
        assert len(tracker._seeds) == 0

    def test_record_seed(self):
        """Test recording a creator seed."""
        tracker = CreatorTracker()
        seed = tracker.record_seed(
            creator_id="creator_1",
            product_id="product_1",
            seeding_cost=75.0,
        )
        assert seed.creator_id == "creator_1"
        assert seed.seeding_cost == 75.0
        assert len(tracker._seeds) == 1

    def test_add_organic_order(self):
        """Test adding organic order to tracked seed."""
        tracker = CreatorTracker()
        tracker.record_seed("creator_1", "product_1", seeding_cost=50.0)
        tracker.add_organic_order("creator_1", "product_1", order_value=29.99)

        seed = tracker.get_seed("creator_1", "product_1")
        assert seed is not None
        assert seed.organic_orders_attributed == 1
        assert abs(seed.organic_revenue - 29.99) < 0.01

    def test_creator_stats_single_product(self):
        """Test aggregating stats for a creator with one seeding."""
        tracker = CreatorTracker()
        tracker.record_seed("creator_1", "product_1", seeding_cost=50.0)
        tracker.add_organic_order("creator_1", "product_1", order_value=29.99)
        tracker.add_organic_order("creator_1", "product_1", order_value=29.99)

        stats = tracker.creator_stats("creator_1")
        assert stats["total_seeds"] == 1
        assert stats["total_seeding_cost"] == 50.0
        assert stats["total_organic_orders"] == 2
        assert abs(stats["total_organic_revenue"] - 59.98) < 0.01
        assert abs(stats["avg_cost_per_order"] - 25.0) < 0.01

    def test_creator_stats_multiple_products(self):
        """Test aggregating stats for a creator with multiple seedings."""
        tracker = CreatorTracker()

        # Seed product 1: $50 cost, 2 orders
        tracker.record_seed("creator_1", "product_1", seeding_cost=50.0)
        tracker.add_organic_order("creator_1", "product_1", 30.0)
        tracker.add_organic_order("creator_1", "product_1", 20.0)

        # Seed product 2: $30 cost, 1 order
        tracker.record_seed("creator_1", "product_2", seeding_cost=30.0)
        tracker.add_organic_order("creator_1", "product_2", 25.0)

        stats = tracker.creator_stats("creator_1")
        assert stats["total_seeds"] == 2
        assert stats["total_seeding_cost"] == 80.0
        assert stats["total_organic_orders"] == 3
        assert abs(stats["total_organic_revenue"] - 75.0) < 0.01
        # CAC = 80 / 3 = 26.67
        assert abs(stats["avg_cost_per_order"] - 26.67) < 0.05

    def test_product_stats(self):
        """Test aggregating stats for a product across all seeders."""
        tracker = CreatorTracker()

        # Creator 1: $50, 2 orders
        tracker.record_seed("creator_1", "product_1", seeding_cost=50.0)
        tracker.add_organic_order("creator_1", "product_1", 30.0)
        tracker.add_organic_order("creator_1", "product_1", 20.0)

        # Creator 2: $30, 1 order
        tracker.record_seed("creator_2", "product_1", seeding_cost=30.0)
        tracker.add_organic_order("creator_2", "product_1", 25.0)

        stats = tracker.product_stats("product_1")
        assert stats["total_seeders"] == 2
        assert stats["total_seeding_cost"] == 80.0
        assert stats["total_organic_orders"] == 3

    def test_top_creators_by_cost_per_order(self):
        """Test ranking creators by cost-per-order (lower is better)."""
        tracker = CreatorTracker()

        # Creator A: $50 / 5 orders = $10 CAC (best)
        tracker.record_seed("creator_a", "product_1", seeding_cost=50.0)
        for _ in range(5):
            tracker.add_organic_order("creator_a", "product_1", 20.0)

        # Creator B: $50 / 2 orders = $25 CAC
        tracker.record_seed("creator_b", "product_2", seeding_cost=50.0)
        for _ in range(2):
            tracker.add_organic_order("creator_b", "product_2", 20.0)

        top = tracker.top_creators(n=2, by="avg_cost_per_order")
        assert top[0][0] == "creator_a"  # $10 CAC
        assert top[1][0] == "creator_b"  # $25 CAC

    def test_top_creators_by_revenue(self):
        """Test ranking creators by total revenue (higher is better)."""
        tracker = CreatorTracker()

        # Creator A: $500 revenue
        tracker.record_seed("creator_a", "product_1", seeding_cost=50.0)
        for _ in range(5):
            tracker.add_organic_order("creator_a", "product_1", 100.0)

        # Creator B: $200 revenue
        tracker.record_seed("creator_b", "product_2", seeding_cost=50.0)
        for _ in range(2):
            tracker.add_organic_order("creator_b", "product_2", 100.0)

        top = tracker.top_creators(n=2, by="total_organic_revenue")
        assert top[0][0] == "creator_a"  # $500
        assert top[1][0] == "creator_b"  # $200

    def test_persistence_export_import(self):
        """Test exporting and restoring tracker state."""
        tracker1 = CreatorTracker()
        tracker1.record_seed("creator_1", "product_1", seeding_cost=50.0)
        tracker1.add_organic_order("creator_1", "product_1", 29.99)

        # Export
        seeds_data = tracker1.all_seeds_as_dicts()
        assert len(seeds_data) == 1

        # Import into new tracker
        tracker2 = CreatorTracker()
        tracker2.restore_from_dicts(seeds_data)

        # Verify
        stats = tracker2.creator_stats("creator_1")
        assert stats["total_seeds"] == 1
        assert abs(stats["total_organic_revenue"] - 29.99) < 0.01


class TestContentCalendar:
    """Test content scheduling and gap detection."""

    def test_content_post_initialization(self):
        """Test ContentPost object creation."""
        post = ContentPost(
            creator_id="creator_1",
            product_id="product_1",
            content_type="unboxing",
        )
        assert post.creator_id == "creator_1"
        assert post.product_id == "product_1"
        assert post.content_type == "unboxing"
        assert post.posted_date is None

    def test_content_post_mark_posted(self):
        """Test marking a post as posted."""
        post = ContentPost("creator_1", "product_1", content_type="review")
        post.mark_posted(engagement=0.85)

        assert post.posted_date is not None
        assert abs(post.engagement_score - 0.85) < 0.01

    def test_content_calendar_initialization(self):
        """Test ContentCalendar initialization."""
        cal = ContentCalendar(gap_threshold_days=7)
        assert cal.gap_threshold_days == 7

    def test_schedule_post(self):
        """Test scheduling a post."""
        cal = ContentCalendar()
        post = cal.schedule_post(
            creator_id="creator_1",
            product_id="product_1",
            content_type="post",
        )

        assert post.creator_id == "creator_1"
        assert post.product_id == "product_1"
        assert len(cal._calendar["product_1"]) == 1

    def test_mark_posted(self):
        """Test marking scheduled content as posted."""
        cal = ContentCalendar()
        cal.schedule_post("creator_1", "product_1", content_type="unboxing")
        cal.mark_posted("creator_1", "product_1", engagement=0.75)

        posts = cal._by_creator_product[("creator_1", "product_1")]
        assert posts[0].posted_date is not None
        assert abs(posts[0].engagement_score - 0.75) < 0.01

    def test_has_content_gap_false_when_recently_scheduled(self):
        """Test that no gap is detected when content is recently scheduled."""
        cal = ContentCalendar(gap_threshold_days=7)
        now = datetime.now(timezone.utc).timestamp()
        recently = now - (2 * 86400)  # 2 days ago

        cal.schedule_post("creator_1", "product_1", scheduled_date=recently)

        has_gap, details = cal.has_content_gap("product_1", ts=now)
        assert has_gap is False

    def test_has_content_gap_true_when_gap_exceeds_threshold(self):
        """Test that gap is detected when no recent content scheduled."""
        cal = ContentCalendar(gap_threshold_days=7)
        now = datetime.now(timezone.utc).timestamp()
        old = now - (10 * 86400)  # 10 days ago (exceeds 7-day threshold)

        cal.schedule_post("creator_1", "product_1", scheduled_date=old)

        has_gap, details = cal.has_content_gap("product_1", ts=now)
        assert has_gap is True

    def test_has_content_gap_true_when_no_content(self):
        """Test that gap is detected for products with no scheduled content."""
        cal = ContentCalendar(gap_threshold_days=7)
        has_gap, details = cal.has_content_gap("unknown_product")
        assert has_gap is True


class TestOrganicChannelIntegration:
    """Integration tests for organic channel with capital allocation."""

    def test_organic_cac_vs_paid_cac_comparison(self):
        """Test comparing organic CAC to paid CAC for go/no-go gate."""
        tracker = CreatorTracker()

        # Seed 3 creators for product_1
        for creator_num in range(1, 4):
            creator_id = f"creator_{creator_num}"
            tracker.record_seed(creator_id, "product_1", seeding_cost=40.0)

            # Add orders: total 3 creators * 2 orders = 6 orders, $120 total cost
            for _ in range(2):
                tracker.add_organic_order(creator_id, "product_1", order_value=30.0)

        # Stats: $120 / 6 orders = $20 CAC
        stats = tracker.product_stats("product_1")
        organic_cac = stats["avg_cost_per_order"]

        # Assume paid CAC is ~$50
        paid_cac = 50.0
        organic_cac_ratio = organic_cac / paid_cac  # 20/50 = 0.4 (40% of paid)

        # Gate: if organic CAC < 60% of paid CAC, scale organic; else iterate
        assert organic_cac_ratio < 0.6  # Should scale
        assert organic_cac_ratio == 0.4

    def test_organic_channel_content_gap_triggers_seeding(self):
        """Test end-to-end: gap detection → trigger new creator seeding."""
        cal = ContentCalendar(gap_threshold_days=7)
        tracker = CreatorTracker()

        # Existing creator seeded, but no recent posts
        now = datetime.now(timezone.utc).timestamp()
        old_scheduled = now - (10 * 86400)

        cal.schedule_post("creator_old", "product_1", scheduled_date=old_scheduled)
        has_gap, details = cal.has_content_gap("product_1", ts=now)

        # Gap detected → trigger seeding of new creator
        if has_gap:
            new_creator = "creator_new"
            tracker.record_seed(new_creator, "product_1", seeding_cost=50.0)
            cal.schedule_post(new_creator, "product_1", scheduled_date=now)

        # Verify new creator is scheduled
        new_posts = cal._by_creator_product[("creator_new", "product_1")]
        assert len(new_posts) > 0
        assert abs(new_posts[0].scheduled_date - now) < 1

    def test_creator_performance_tracking_over_time(self):
        """Test tracking and comparing creator performance across multiple campaigns."""
        tracker = CreatorTracker()

        # Campaign 1: creator_1 seeds multiple products
        for product_num in range(1, 4):
            product_id = f"product_{product_num}"
            tracker.record_seed("creator_1", product_id, seeding_cost=50.0)
            # Product 1-2: good performance (3 orders each)
            num_orders = 3 if product_num <= 2 else 1
            for _ in range(num_orders):
                tracker.add_organic_order("creator_1", product_id, order_value=30.0)

        # Creator 1 lifetime CAC: $150 / 7 orders = $21.43
        stats = tracker.creator_stats("creator_1")
        assert stats["total_seeds"] == 3
        assert stats["total_organic_orders"] == 7
        assert abs(stats["avg_cost_per_order"] - 21.43) < 0.1

        # Creator 1 is high-performer (best CAC), eligible for repeat seeding
        top = tracker.top_creators(n=1, by="avg_cost_per_order")
        assert top[0][0] == "creator_1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

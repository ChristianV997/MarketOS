"""Tests for core.ugc.creator_tracker — creator seeding and organic ROI tracking."""
from __future__ import annotations

import pytest

from core.ugc.creator_tracker import CreatorTracker, CreatorSeed


class TestCreatorSeedBasics:
    """Single seeding event basics."""

    def test_create_seed_with_cost(self):
        seed = CreatorSeed("creator_1", "product_1", seeding_cost=25.0)
        assert seed.creator_id == "creator_1"
        assert seed.product_id == "product_1"
        assert seed.seeding_cost == 25.0
        assert seed.organic_orders_attributed == 0
        assert seed.organic_revenue == 0.0

    def test_add_organic_order(self):
        seed = CreatorSeed("creator_1", "product_1", seeding_cost=25.0)
        seed.add_organic_order(order_value=49.99)
        assert seed.organic_orders_attributed == 1
        assert seed.organic_revenue == pytest.approx(49.99)

    def test_add_multiple_orders(self):
        seed = CreatorSeed("creator_1", "product_1", seeding_cost=25.0)
        seed.add_organic_order(order_value=30.0)
        seed.add_organic_order(order_value=45.0)
        seed.add_organic_order(order_value=50.0)
        assert seed.organic_orders_attributed == 3
        assert seed.organic_revenue == pytest.approx(125.0)

    def test_seed_serialization(self):
        seed = CreatorSeed("creator_1", "product_1", seeding_cost=25.0)
        seed.add_organic_order(order_value=49.99)

        data = seed.to_dict()
        assert data["creator_id"] == "creator_1"
        assert data["product_id"] == "product_1"
        assert data["seeding_cost"] == 25.0
        assert data["organic_revenue"] == pytest.approx(49.99)

    def test_seed_deserialization(self):
        data = {
            "creator_id": "creator_1",
            "product_id": "product_1",
            "seeding_cost": 25.0,
            "sent_date": 1000.0,
            "organic_orders_attributed": 2,
            "organic_revenue": 100.0,
            "last_order_ts": 2000.0,
        }
        seed = CreatorSeed.from_dict(data)
        assert seed.creator_id == "creator_1"
        assert seed.organic_orders_attributed == 2
        assert seed.organic_revenue == 100.0


class TestCreatorTrackerBasics:
    """Multi-seed tracking across creators and products."""

    def test_record_single_seed(self):
        tracker = CreatorTracker()
        seed = tracker.record_seed("creator_1", "product_1", seeding_cost=25.0)
        assert seed is not None
        assert tracker.get_seed("creator_1", "product_1") is seed

    def test_add_organic_order_to_seed(self):
        tracker = CreatorTracker()
        tracker.record_seed("creator_1", "product_1", seeding_cost=25.0)
        tracker.add_organic_order("creator_1", "product_1", order_value=49.99)

        seed = tracker.get_seed("creator_1", "product_1")
        assert seed.organic_orders_attributed == 1
        assert seed.organic_revenue == pytest.approx(49.99)

    def test_nonexistent_seed_ignored_on_order(self):
        tracker = CreatorTracker()
        # Should not crash, just be a no-op
        tracker.add_organic_order("unknown_creator", "unknown_product", order_value=50.0)
        assert tracker.get_seed("unknown_creator", "unknown_product") is None

    def test_multiple_creators_same_product(self):
        tracker = CreatorTracker()
        tracker.record_seed("creator_1", "product_1", seeding_cost=25.0)
        tracker.record_seed("creator_2", "product_1", seeding_cost=30.0)
        tracker.add_organic_order("creator_1", "product_1", order_value=40.0)
        tracker.add_organic_order("creator_2", "product_1", order_value=50.0)

        seed1 = tracker.get_seed("creator_1", "product_1")
        seed2 = tracker.get_seed("creator_2", "product_1")

        assert seed1.organic_orders_attributed == 1
        assert seed2.organic_orders_attributed == 1
        assert seed1.organic_revenue + seed2.organic_revenue == pytest.approx(90.0)

    def test_same_creator_multiple_products(self):
        tracker = CreatorTracker()
        tracker.record_seed("creator_1", "product_1", seeding_cost=25.0)
        tracker.record_seed("creator_1", "product_2", seeding_cost=30.0)
        tracker.add_organic_order("creator_1", "product_1", order_value=40.0)
        tracker.add_organic_order("creator_1", "product_2", order_value=50.0)

        seed1 = tracker.get_seed("creator_1", "product_1")
        seed2 = tracker.get_seed("creator_1", "product_2")

        assert seed1.organic_orders_attributed == 1
        assert seed2.organic_orders_attributed == 1


class TestCreatorStats:
    """Creator-level aggregation."""

    def test_single_seed_stats(self):
        tracker = CreatorTracker()
        tracker.record_seed("creator_1", "product_1", seeding_cost=25.0)
        tracker.add_organic_order("creator_1", "product_1", order_value=49.99)

        stats = tracker.creator_stats("creator_1")
        assert stats["total_seeds"] == 1
        assert stats["total_seeding_cost"] == 25.0
        assert stats["total_organic_orders"] == 1
        assert stats["total_organic_revenue"] == pytest.approx(49.99)
        assert stats["avg_cost_per_order"] == pytest.approx(25.0)

    def test_multiple_seeds_aggregation(self):
        tracker = CreatorTracker()
        tracker.record_seed("creator_1", "product_1", seeding_cost=25.0)
        tracker.record_seed("creator_1", "product_2", seeding_cost=30.0)
        tracker.add_organic_order("creator_1", "product_1", order_value=40.0)
        tracker.add_organic_order("creator_1", "product_2", order_value=60.0)
        tracker.add_organic_order("creator_1", "product_2", order_value=50.0)

        stats = tracker.creator_stats("creator_1")
        assert stats["total_seeds"] == 2
        assert stats["total_seeding_cost"] == 55.0
        assert stats["total_organic_orders"] == 3
        assert stats["total_organic_revenue"] == pytest.approx(150.0)
        # (25 + 30) / 3 = 18.33
        assert stats["avg_cost_per_order"] == pytest.approx(18.33, abs=0.01)

    def test_no_orders_stats(self):
        tracker = CreatorTracker()
        tracker.record_seed("creator_1", "product_1", seeding_cost=25.0)

        stats = tracker.creator_stats("creator_1")
        assert stats["total_seeds"] == 1
        assert stats["total_seeding_cost"] == 25.0
        assert stats["total_organic_orders"] == 0
        assert stats["avg_cost_per_order"] == 0.0

    def test_unknown_creator_stats(self):
        tracker = CreatorTracker()
        stats = tracker.creator_stats("unknown_creator")
        assert stats["total_seeds"] == 0
        assert stats["total_seeding_cost"] == 0.0


class TestProductStats:
    """Product-level aggregation."""

    def test_single_seeder_product_stats(self):
        tracker = CreatorTracker()
        tracker.record_seed("creator_1", "product_1", seeding_cost=25.0)
        tracker.add_organic_order("creator_1", "product_1", order_value=49.99)

        stats = tracker.product_stats("product_1")
        assert stats["total_seeders"] == 1
        assert stats["total_organic_orders"] == 1

    def test_multiple_seeders_product_stats(self):
        tracker = CreatorTracker()
        tracker.record_seed("creator_1", "product_1", seeding_cost=20.0)
        tracker.record_seed("creator_2", "product_1", seeding_cost=30.0)
        tracker.add_organic_order("creator_1", "product_1", order_value=40.0)
        tracker.add_organic_order("creator_2", "product_1", order_value=60.0)
        tracker.add_organic_order("creator_2", "product_1", order_value=50.0)

        stats = tracker.product_stats("product_1")
        assert stats["total_seeders"] == 2
        assert stats["total_organic_orders"] == 3
        assert stats["total_seeding_cost"] == 50.0
        assert stats["total_organic_revenue"] == pytest.approx(150.0)

    def test_unknown_product_stats(self):
        tracker = CreatorTracker()
        stats = tracker.product_stats("unknown_product")
        assert stats["total_seeders"] == 0


class TestTopCreators:
    """Creator ranking."""

    def test_top_creators_by_cost_per_order(self):
        tracker = CreatorTracker()
        # Creator 1: $20 seeding, 2 orders = $10/order
        tracker.record_seed("creator_1", "product_1", seeding_cost=20.0)
        tracker.add_organic_order("creator_1", "product_1", order_value=50.0)
        tracker.add_organic_order("creator_1", "product_1", order_value=50.0)

        # Creator 2: $30 seeding, 1 order = $30/order
        tracker.record_seed("creator_2", "product_2", seeding_cost=30.0)
        tracker.add_organic_order("creator_2", "product_2", order_value=50.0)

        top = tracker.top_creators(n=2, by="avg_cost_per_order")
        assert len(top) == 2
        assert top[0][0] == "creator_1"  # Lower cost per order
        assert top[1][0] == "creator_2"

    def test_top_creators_by_revenue(self):
        tracker = CreatorTracker()
        # Creator 1: 2 orders, $100 total revenue
        tracker.record_seed("creator_1", "product_1", seeding_cost=20.0)
        tracker.add_organic_order("creator_1", "product_1", order_value=50.0)
        tracker.add_organic_order("creator_1", "product_1", order_value=50.0)

        # Creator 2: 1 order, $200 total revenue
        tracker.record_seed("creator_2", "product_2", seeding_cost=30.0)
        tracker.add_organic_order("creator_2", "product_2", order_value=200.0)

        top = tracker.top_creators(n=2, by="total_organic_revenue")
        assert len(top) == 2
        assert top[0][0] == "creator_2"  # Higher revenue
        assert top[1][0] == "creator_1"

    def test_top_creators_limit_n(self):
        tracker = CreatorTracker()
        for i in range(5):
            tracker.record_seed(f"creator_{i}", f"product_{i}", seeding_cost=25.0)
            tracker.add_organic_order(f"creator_{i}", f"product_{i}", order_value=50.0)

        top = tracker.top_creators(n=3)
        assert len(top) == 3


class TestTrackerSerialization:
    """Persistence round-trip."""

    def test_export_and_restore(self):
        tracker1 = CreatorTracker()
        tracker1.record_seed("creator_1", "product_1", seeding_cost=25.0)
        tracker1.add_organic_order("creator_1", "product_1", order_value=49.99)
        tracker1.record_seed("creator_2", "product_1", seeding_cost=30.0)

        seeds_data = tracker1.all_seeds_as_dicts()

        tracker2 = CreatorTracker()
        tracker2.restore_from_dicts(seeds_data)

        seed1 = tracker2.get_seed("creator_1", "product_1")
        seed2 = tracker2.get_seed("creator_2", "product_1")

        assert seed1.organic_orders_attributed == 1
        assert seed1.organic_revenue == pytest.approx(49.99)
        assert seed2.seeding_cost == 30.0

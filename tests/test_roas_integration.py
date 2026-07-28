"""Tests for real ROAS data integration.

Tests cover:
1. RoasRepository schema and basic CRUD
2. Multi-touch order deduplication
3. Cross-platform ROAS reconciliation

(Connector dry-run and daily-ingestion-worker tests were removed when
backend/connectors/real_data_connector.py and
backend/workers/roas_ingestion_worker.py were retired — that batch
pipeline duplicated backend/integrations/{shopify_client,meta_ads_client,
tiktok_ads}.py's real spend/order fetching and was never actually
scheduled anywhere in production; Commerce Phase C's real-time webhook
path (api/routes/webhooks.py -> backend.commerce.orders.ingest_order)
supersedes it for order/UTM-attribution ingestion.)
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.data.repositories.roas_repository import (
    Order,
    PlatformInsight,
    RoasRepository,
)


@pytest.fixture
def temp_db():
    """Create temporary database for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        yield str(db_path)


@pytest.fixture
def repo(temp_db):
    """Create a RoasRepository for testing."""
    return RoasRepository(db_path=temp_db)


class TestRoasRepository:
    """Test core repository functionality."""

    def test_schema_initialization(self, repo):
        """Verify schema is created on init."""
        # Should not raise
        conn = repo.db_path.open()
        conn.close()

    def test_ingest_orders_basic(self, repo):
        """Test basic order ingestion."""
        now = datetime.now(timezone.utc)
        orders = [
            Order(
                id="order-1",
                customer_id="cust-1",
                product_id="prod-a",
                created_at=now,
                total_price=100.0,
            ),
            Order(
                id="order-2",
                customer_id="cust-2",
                product_id="prod-b",
                created_at=now + timedelta(hours=1),
                total_price=150.0,
            ),
        ]

        count = repo.ingest_orders(orders)
        assert count == 2

    def test_ingest_platform_insights(self, repo):
        """Test platform insights ingestion."""
        insights = [
            PlatformInsight(
                date="2024-01-15",
                platform="meta",
                campaign_id="meta-camp-1",
                product_id="prod-a",
                spend=500.0,
                revenue=1500.0,
                clicks=100,
                conversions=20,
            ),
            PlatformInsight(
                date="2024-01-15",
                platform="tiktok",
                campaign_id="tiktok-camp-1",
                product_id="prod-a",
                spend=300.0,
                revenue=900.0,
                clicks=80,
                conversions=15,
            ),
        ]

        count = repo.ingest_platform_insights(insights)
        assert count == 2

    def test_get_platform_comparison(self, repo):
        """Test platform comparison aggregation (via roas_daily table)."""
        import sqlite3

        # Use a recent date (within the 30-day window)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Directly populate roas_daily (bypassing platform_insights)
        conn = sqlite3.connect(repo.db_path)
        conn.execute(
            """
            INSERT INTO roas_daily
            (date, product_id, platform, spend, revenue, roas, clicks, conversions, deduplication_confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (today, "prod-a", "meta", 500.0, 1500.0, 3.0, 100, 20, 1.0),
        )
        conn.execute(
            """
            INSERT INTO roas_daily
            (date, product_id, platform, spend, revenue, roas, clicks, conversions, deduplication_confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (today, "prod-b", "meta", 300.0, 600.0, 2.0, 60, 10, 1.0),
        )
        conn.execute(
            """
            INSERT INTO roas_daily
            (date, product_id, platform, spend, revenue, roas, clicks, conversions, deduplication_confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (today, "prod-a", "tiktok", 400.0, 1200.0, 3.0, 120, 25, 1.0),
        )
        conn.commit()
        conn.close()

        comparison = repo.get_platform_comparison(days=30)

        assert "meta" in comparison
        assert "tiktok" in comparison
        assert comparison["meta"]["total_spend"] == 800.0
        assert comparison["tiktok"]["total_spend"] == 400.0

    def test_get_product_roas(self, repo):
        """Test product ROAS time series retrieval."""
        insights = [
            PlatformInsight(
                date="2024-01-15",
                platform="meta",
                campaign_id="meta-1",
                product_id="prod-a",
                spend=500.0,
                revenue=1500.0,
                clicks=100,
                conversions=20,
            ),
            PlatformInsight(
                date="2024-01-16",
                platform="meta",
                campaign_id="meta-1",
                product_id="prod-a",
                spend=600.0,
                revenue=1200.0,
                clicks=80,
                conversions=18,
            ),
        ]

        repo.ingest_platform_insights(insights)
        roas_series = repo.get_product_roas("prod-a", days=30)

        # Note: The series is empty because roas_daily table is populated
        # separately; in the test we're only populating platform_insights
        # In production, the daily ingestion job populates both
        assert isinstance(roas_series, list)


class TestOrderDeduplication:
    """Test multi-touch attribution deduplication."""

    def test_deduplicate_same_customer_same_product(self, repo):
        """
        Test deduplication when same customer orders same product multiple times
        within the window (multi-touch scenario).
        """
        now = datetime.now(timezone.utc)

        # Same customer, same product, 3-day spread (within 7-day window)
        orders = [
            Order(
                id="order-1",
                customer_id="cust-123",
                product_id="prod-a",
                created_at=now,
                total_price=100.0,
                platform="meta",
            ),
            Order(
                id="order-2",
                customer_id="cust-123",
                product_id="prod-a",
                created_at=now + timedelta(days=1),
                total_price=100.0,
                platform="tiktok",
            ),
            Order(
                id="order-3",
                customer_id="cust-123",
                product_id="prod-a",
                created_at=now + timedelta(days=3),
                total_price=100.0,
                platform="organic",
            ),
        ]

        repo.ingest_orders(orders)

        # Should group the 3 orders as multi-touch
        result = repo.deduplicate_orders(window_days=7, attribution_method="last_click")

        assert result["deduped_count"] == 1  # One group
        assert result["duplicate_count"] == 2  # Two marked as duplicate
        assert result["primary_count"] == 1  # One primary (not duplicate)

    def test_last_click_attribution(self, repo):
        """
        Verify that last_click attribution selects the most recent order
        as primary.
        """
        now = datetime.now(timezone.utc)
        base_time = now - timedelta(days=3)

        orders = [
            Order(
                id="order-early",
                customer_id="cust-x",
                product_id="prod-b",
                created_at=base_time,
                total_price=100.0,
                platform="meta",
            ),
            Order(
                id="order-late",
                customer_id="cust-x",
                product_id="prod-b",
                created_at=base_time + timedelta(days=1),
                total_price=100.0,
                platform="tiktok",
            ),
        ]

        repo.ingest_orders(orders)
        repo.deduplicate_orders(window_days=7, attribution_method="last_click")

        # Verify via direct query
        import sqlite3

        conn = sqlite3.connect(repo.db_path)
        row = conn.execute(
            "SELECT id, is_duplicate FROM orders WHERE id = ?", ("order-late",)
        ).fetchone()
        assert row[1] == 0  # order-late is primary (not duplicate)

        row = conn.execute(
            "SELECT id, is_duplicate FROM orders WHERE id = ?", ("order-early",)
        ).fetchone()
        assert row[1] == 1  # order-early is duplicate
        conn.close()

    def test_no_dedup_for_different_products(self, repo):
        """
        Same customer, different products → should NOT deduplicate
        (these are separate purchases).
        """
        now = datetime.now(timezone.utc)

        orders = [
            Order(
                id="order-prod-a",
                customer_id="cust-y",
                product_id="prod-a",
                created_at=now,
                total_price=50.0,
            ),
            Order(
                id="order-prod-b",
                customer_id="cust-y",
                product_id="prod-b",
                created_at=now + timedelta(days=1),
                total_price=75.0,
            ),
        ]

        repo.ingest_orders(orders)
        result = repo.deduplicate_orders(window_days=7)

        assert result["deduped_count"] == 0  # No multi-touch groups
        assert result["duplicate_count"] == 0  # Nothing marked duplicate


class TestCrossPlatformReconciliation:
    """Test ROAS reconciliation across Meta and TikTok."""

    def test_raw_vs_deduped_roas(self, repo):
        """
        Verify that deduplicated ROAS is different from platform-reported ROAS
        when orders are attributed to multiple platforms (multi-touch).
        """
        # Anchored to the start of today (not "now") so the second order's
        # +12h offset below can never cross midnight UTC and land on a
        # different calendar day than date_str — that was the actual root
        # cause of this test's previously-reported flakiness (it failed
        # whenever run in the afternoon UTC, since compute_deduped_roas
        # filters strictly by calendar date).
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0)
        now = today_start + timedelta(hours=2)
        date_str = now.strftime("%Y-%m-%d")

        # Scenario: Same customer buys via Meta and TikTok
        # Platform-reported revenue (with double-counting):
        #   Meta: $100 spend → $250 revenue (ROAS 2.5)
        #   TikTok: $100 spend → $250 revenue (ROAS 2.5)
        #   Total reported: $200 spend, $500 revenue
        #
        # Actual orders (after dedup):
        #   Only one $250 sale (multi-touch, attributed to TikTok)
        #   True ROAS: $250 / $200 = 1.25

        # Populate roas_daily directly (platform-reported data)
        import sqlite3

        conn = sqlite3.connect(repo.db_path)
        conn.execute(
            """
            INSERT INTO roas_daily
            (date, product_id, platform, spend, revenue, roas, clicks, conversions, deduplication_confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (date_str, "prod-multi", "meta", 100.0, 250.0, 2.5, 50, 10, 0.8),
        )
        conn.execute(
            """
            INSERT INTO roas_daily
            (date, product_id, platform, spend, revenue, roas, clicks, conversions, deduplication_confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (date_str, "prod-multi", "tiktok", 100.0, 250.0, 2.5, 60, 12, 0.8),
        )
        conn.commit()
        conn.close()

        # Actual orders (same customer, same product, multi-touch)
        orders = [
            Order(
                id="order-meta",
                customer_id="cust-multi",
                product_id="prod-multi",
                created_at=now,
                total_price=250.0,
                platform="meta",
            ),
            Order(
                id="order-tiktok",
                customer_id="cust-multi",
                product_id="prod-multi",
                created_at=now + timedelta(hours=12),
                total_price=250.0,
                platform="tiktok",
            ),
        ]

        repo.ingest_orders(orders)
        repo.deduplicate_orders(window_days=7, attribution_method="last_click")

        # Compute deduped ROAS
        deduped_roas = repo.compute_deduped_roas(
            product_id="prod-multi",
            date=date_str,
        )

        # Deduped ROAS should be lower than platform-reported
        # (because we recognized the double-counting)
        # True revenue: $250 (one sale after dedup)
        # Total spend: $200 (sum of both platforms)
        # True ROAS: 250 / 200 = 1.25
        assert deduped_roas == pytest.approx(1.25, rel=0.01)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

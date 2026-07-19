"""Tests for product discovery integration.

Tests cover:
1. ProductRepository CRUD and signal storage
2. Trend discovery workers (Reddit, Google Trends, supplier catalogs)
3. Signal merging and confidence scoring
4. Discovery pipeline end-to-end
"""
from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.data.repositories.product_repository import (
    DiscoveredProduct,
    ProductRepository,
    TrendSignal,
)
from backend.discovery.trend_discovery import (
    GoogleTrendsDiscovery,
    RedditDiscovery,
    SupplierCatalogDiscovery,
)
from backend.workers.product_discovery_worker import ProductDiscoveryWorker


@pytest.fixture
def temp_db():
    """Create temporary database for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        yield str(db_path)


@pytest.fixture
def repo(temp_db):
    """Create a ProductRepository for testing."""
    return ProductRepository(db_path=temp_db)


class TestProductRepository:
    """Test core repository functionality."""

    @pytest.mark.asyncio
    async def test_add_discovered_product(self, repo):
        """Test basic product insertion."""
        now = datetime.now(timezone.utc).isoformat()
        product = DiscoveredProduct(
            id="test-001",
            name="Wireless Charger",
            category="electronics",
            supplier_id="aliexpress_123",
            cost_usd=8.50,
            suggested_retail=24.99,
            trends_mentioned=45,
            search_interest=0.82,
            successful_sellers=3,
            avg_rating=4.6,
            reviews_count=1250,
            market_saturation=0.65,
            trend_direction="rising",
            supply_risk="abundant",
            discovered_from="reddit,google_trends,supplier",
            discovered_date=now,
            last_updated=now,
            confidence=0.85,
            signal_count=3,
        )

        result = await repo.add_discovered_product(product)
        assert result is True

    @pytest.mark.asyncio
    async def test_add_signal(self, repo):
        """Test signal addition for a product."""
        now = datetime.now(timezone.utc).isoformat()
        product = DiscoveredProduct(
            id="test-002",
            name="USB Hub",
            category="electronics",
            supplier_id=None,
            cost_usd=None,
            suggested_retail=None,
            trends_mentioned=0,
            search_interest=0.0,
            successful_sellers=0,
            avg_rating=None,
            reviews_count=0,
            market_saturation=0.0,
            trend_direction="stable",
            supply_risk="moderate",
            discovered_from="reddit",
            discovered_date=now,
            last_updated=now,
            confidence=0.5,
            signal_count=0,
        )

        await repo.add_discovered_product(product)

        signal = TrendSignal(
            source="reddit",
            signal_type="mention_count",
            value=32.0,
            confidence=0.78,
            timestamp=now,
        )

        result = await repo.add_signal("test-002", signal)
        assert result is True

    @pytest.mark.asyncio
    async def test_get_trending_products(self, repo):
        """Test retrieval of trending products."""
        now = datetime.now(timezone.utc).isoformat()

        # Add multiple products with varying confidence
        for i in range(3):
            product = DiscoveredProduct(
                id=f"trend-{i}",
                name=f"Product {i}",
                category="electronics",
                supplier_id=None,
                cost_usd=None,
                suggested_retail=None,
                trends_mentioned=50 - (i * 10),
                search_interest=0.9 - (i * 0.1),
                successful_sellers=0,
                avg_rating=None,
                reviews_count=0,
                market_saturation=0.5,
                trend_direction="rising",
                supply_risk="moderate",
                discovered_from="test",
                discovered_date=now,
                last_updated=now,
                confidence=0.8 - (i * 0.05),
                signal_count=1,
            )
            await repo.add_discovered_product(product)

        # Get top 2 trending
        trending = await repo.get_trending_products(limit=2, min_confidence=0.6)

        assert len(trending) == 2
        assert trending[0].confidence >= trending[1].confidence

    @pytest.mark.asyncio
    async def test_get_validated_products(self, repo):
        """Test retrieval of high-confidence validated products."""
        now = datetime.now(timezone.utc).isoformat()

        # Add high-confidence product (>=3 signals)
        product = DiscoveredProduct(
            id="validated-001",
            name="Validated Product",
            category="electronics",
            supplier_id=None,
            cost_usd=None,
            suggested_retail=None,
            trends_mentioned=50,
            search_interest=0.85,
            successful_sellers=2,
            avg_rating=4.5,
            reviews_count=500,
            market_saturation=0.6,
            trend_direction="rising",
            supply_risk="abundant",
            discovered_from="reddit,google,supplier",
            discovered_date=now,
            last_updated=now,
            confidence=0.82,
            signal_count=3,  # Multiple signals
        )

        await repo.add_discovered_product(product)

        # Get validated products (high confidence + ≥3 signals)
        validated = await repo.get_validated_products(min_confidence=0.75, limit=10)

        assert len(validated) >= 1
        assert validated[0].signal_count >= 3

    @pytest.mark.asyncio
    async def test_get_signals_for_product(self, repo):
        """Test signal retrieval for a product."""
        now = datetime.now(timezone.utc).isoformat()
        product_id = "signal-test-001"

        product = DiscoveredProduct(
            id=product_id,
            name="Signal Test Product",
            category="electronics",
            supplier_id=None,
            cost_usd=None,
            suggested_retail=None,
            trends_mentioned=0,
            search_interest=0.0,
            successful_sellers=0,
            avg_rating=None,
            reviews_count=0,
            market_saturation=0.0,
            trend_direction="stable",
            supply_risk="moderate",
            discovered_from="test",
            discovered_date=now,
            last_updated=now,
            confidence=0.5,
            signal_count=0,
        )

        await repo.add_discovered_product(product)

        # Add multiple signals
        for i in range(3):
            signal = TrendSignal(
                source=["reddit", "google", "supplier"][i],
                signal_type="mention_count",
                value=float(10 * i),
                confidence=0.7 + (i * 0.05),
                timestamp=now,
            )
            await repo.add_signal(product_id, signal)

        signals = await repo.get_signals_for_product(product_id)

        assert len(signals) == 3
        assert all(isinstance(s, TrendSignal) for s in signals)

    @pytest.mark.asyncio
    async def test_update_product_status(self, repo):
        """Test product validation status updates."""
        now = datetime.now(timezone.utc).isoformat()
        product_id = "status-test-001"

        product = DiscoveredProduct(
            id=product_id,
            name="Status Test",
            category="electronics",
            supplier_id=None,
            cost_usd=None,
            suggested_retail=None,
            trends_mentioned=0,
            search_interest=0.0,
            successful_sellers=0,
            avg_rating=None,
            reviews_count=0,
            market_saturation=0.0,
            trend_direction="stable",
            supply_risk="moderate",
            discovered_from="test",
            discovered_date=now,
            last_updated=now,
            confidence=0.5,
            signal_count=0,
        )

        await repo.add_discovered_product(product)

        # Update status
        await repo.update_product_status(
            product_id,
            "validating",
            "Checking supplier availability",
        )

        status = await repo.get_product_status(product_id)

        assert status is not None
        assert status["status"] == "validating"
        assert "Checking supplier" in status["notes"]


class TestTrendDiscovery:
    """Test trend discovery workers."""

    @pytest.mark.asyncio
    async def test_reddit_discovery_dry_run(self):
        """Test Reddit discovery in dry-run mode."""
        discovery = RedditDiscovery(dry_run=True)
        result = await discovery.fetch_trending_products()

        assert result["success"]
        assert len(result["products"]) > 0
        assert "name" in result["products"][0]
        assert "mentions" in result["products"][0]
        assert "confidence" in result["products"][0]

    @pytest.mark.asyncio
    async def test_google_trends_dry_run(self):
        """Test Google Trends discovery in dry-run mode."""
        discovery = GoogleTrendsDiscovery(dry_run=True)
        result = await discovery.fetch_trending_keywords()

        assert result["success"]
        assert len(result["keywords"]) > 0
        assert "keyword" in result["keywords"][0]
        assert "interest" in result["keywords"][0]
        assert "trend" in result["keywords"][0]

    @pytest.mark.asyncio
    async def test_supplier_discovery_dry_run(self):
        """Test supplier catalog discovery in dry-run mode."""
        discovery = SupplierCatalogDiscovery(dry_run=True)
        result = await discovery.fetch_trending_products()

        assert result["success"]
        assert len(result["products"]) > 0
        assert "name" in result["products"][0]
        assert "price" in result["products"][0]
        assert "reviews" in result["products"][0]


class TestDiscoveryWorker:
    """Test end-to-end discovery pipeline."""

    @pytest.mark.asyncio
    async def test_run_daily_discovery(self, temp_db):
        """Test full discovery pipeline."""
        worker = ProductDiscoveryWorker(product_repo_path=temp_db, dry_run=True)
        result = await worker.run_daily_discovery()

        assert result["success"]
        assert result["reddit_products"] > 0
        assert result["google_trends"] > 0
        assert result["supplier_products"] > 0
        assert result["merged_products"] > 0
        assert result["persisted_products"] > 0

    @pytest.mark.asyncio
    async def test_merge_signals_cross_source(self, temp_db):
        """Test signal merging across multiple sources."""
        worker = ProductDiscoveryWorker(product_repo_path=temp_db, dry_run=True)

        # Mock data with same product from multiple sources
        reddit_products = [
            {
                "name": "Wireless Charger",
                "mentions": 45,
                "avg_score": 250,
                "confidence": 0.85,
            }
        ]

        google_keywords = [
            {
                "keyword": "Wireless Charger",
                "interest": 82,
                "trend": "rising",
                "confidence": 0.88,
            }
        ]

        supplier_products = [
            {
                "name": "Wireless Charger",
                "supplier": "aliexpress",
                "price": 8.99,
                "reviews": 1250,
                "rating": 4.6,
                "confidence": 0.80,
            }
        ]

        now = datetime.now(timezone.utc).isoformat()

        merged = await worker._merge_signals(
            reddit_products,
            google_keywords,
            supplier_products,
            now,
        )

        # Should merge into single product
        assert len(merged) == 1
        product_data = list(merged.values())[0]

        # Should have signals from all 3 sources
        assert "reddit" in product_data["sources"]
        assert "google_trends" in product_data["sources"]
        assert "supplier_catalog" in product_data["sources"]

        # Should aggregate signals
        assert product_data["signal_count"] == 3
        assert product_data["trends_mentioned"] > 0
        assert product_data["search_interest"] > 0.0

        # Confidence should be max of all sources
        assert product_data["confidence"] >= 0.80


class TestProductSignalIntegration:
    """Test signal aggregation across sources."""

    @pytest.mark.asyncio
    async def test_confidence_scoring_multi_source(self, repo):
        """Test confidence scoring from multiple sources."""
        now = datetime.now(timezone.utc).isoformat()

        # Product with signals from 2 sources
        product = DiscoveredProduct(
            id="multi-source-001",
            name="Multi-Source Product",
            category="electronics",
            supplier_id="aliexpress_123",
            cost_usd=12.50,
            suggested_retail=39.99,
            trends_mentioned=35,
            search_interest=0.78,
            successful_sellers=2,
            avg_rating=4.5,
            reviews_count=800,
            market_saturation=0.55,
            trend_direction="rising",
            supply_risk="abundant",
            discovered_from="reddit,supplier",
            discovered_date=now,
            last_updated=now,
            confidence=0.82,  # High confidence due to multiple sources
            signal_count=2,
        )

        await repo.add_discovered_product(product)

        # Verify high-confidence product is in validated list
        validated = await repo.get_validated_products(
            min_confidence=0.75, limit=10
        )

        # May or may not be in list depending on signal_count requirement
        # But should be retrievable by trending query
        trending = await repo.get_trending_products(limit=10, min_confidence=0.75)

        assert len(trending) >= 1
        assert any(p.id == "multi-source-001" for p in trending)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

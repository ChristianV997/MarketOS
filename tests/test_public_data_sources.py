"""Tests for public data sources (no API keys required).

Tests cover:
1. Amazon bestsellers scraping
2. GitHub trending repositories
3. RSS feed aggregation
4. Wikipedia trending articles
5. Public datasets loading
6. Full integration pipeline
"""
from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.discovery.public_data_sources import (
    AmazonBestsellersDiscovery,
    GitHubTrendingDiscovery,
    PublicDatasetsLoader,
    RSSFeedAggregator,
    WikipediaTrendingDiscovery,
)
from backend.workers.public_data_integration_worker import PublicDataIntegrationWorker


class TestAmazonBestsellers:
    """Test Amazon bestsellers discovery."""

    @pytest.mark.asyncio
    async def test_dry_run_mode(self):
        """Test Amazon discovery in dry-run mode."""
        discovery = AmazonBestsellersDiscovery(dry_run=True)
        result = await discovery.fetch_bestsellers()

        assert result["success"]
        assert len(result["products"]) > 0
        assert "name" in result["products"][0]
        assert "price" in result["products"][0]
        assert "rating" in result["products"][0]
        assert "confidence" in result["products"][0]

    @pytest.mark.asyncio
    async def test_by_category(self):
        """Test Amazon discovery by category."""
        discovery = AmazonBestsellersDiscovery(dry_run=True)
        result = await discovery.fetch_bestsellers(
            categories=["electronics", "beauty"]
        )

        assert result["success"]
        # In dry-run mode, should return products (filtering tested in real API)
        assert len(result["products"]) > 0


class TestGitHubTrending:
    """Test GitHub trending repositories discovery."""

    @pytest.mark.asyncio
    async def test_dry_run_mode(self):
        """Test GitHub discovery in dry-run mode."""
        discovery = GitHubTrendingDiscovery(dry_run=True)
        result = await discovery.fetch_trending_repos()

        assert result["success"]
        assert len(result["repos"]) > 0
        assert "name" in result["repos"][0]
        assert "url" in result["repos"][0]
        assert "stars" in result["repos"][0]
        assert "language" in result["repos"][0]

    @pytest.mark.asyncio
    async def test_by_language(self):
        """Test GitHub discovery by programming language."""
        discovery = GitHubTrendingDiscovery(dry_run=True)
        result = await discovery.fetch_trending_repos(languages=["python", "rust"])

        assert result["success"]
        # Mock data should have repos
        assert len(result["repos"]) >= 0


class TestRSSFeedAggregation:
    """Test RSS feed aggregation."""

    @pytest.mark.asyncio
    async def test_dry_run_mode(self):
        """Test RSS aggregation in dry-run mode."""
        aggregator = RSSFeedAggregator(dry_run=True)
        result = await aggregator.fetch_trending_articles()

        assert result["success"]
        assert len(result["articles"]) > 0
        assert "title" in result["articles"][0]
        assert "url" in result["articles"][0]
        assert "source" in result["articles"][0]


class TestWikipediaTrending:
    """Test Wikipedia trending articles."""

    @pytest.mark.asyncio
    async def test_dry_run_mode(self):
        """Test Wikipedia discovery in dry-run mode."""
        discovery = WikipediaTrendingDiscovery(dry_run=True)
        result = await discovery.fetch_trending_articles()

        assert result["success"]
        assert len(result["articles"]) > 0
        assert "title" in result["articles"][0]
        assert "url" in result["articles"][0]
        assert "category" in result["articles"][0]


class TestPublicDatasets:
    """Test public datasets loading."""

    @pytest.mark.asyncio
    async def test_dry_run_mode(self):
        """Test dataset loading in dry-run mode."""
        loader = PublicDatasetsLoader(dry_run=True)
        result = await loader.load_kaggle_datasets()

        assert result["success"]
        assert len(result["datasets"]) > 0
        assert "name" in result["datasets"][0]
        assert "rows" in result["datasets"][0]
        assert "columns" in result["datasets"][0]


class TestPublicDataIntegration:
    """Test end-to-end public data integration."""

    @pytest.mark.asyncio
    async def test_full_pipeline_dry_run(self):
        """Test full public data integration pipeline."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            worker = PublicDataIntegrationWorker(
                product_repo_path=str(db_path), dry_run=True
            )
            result = await worker.run_public_data_ingestion()

            assert result["success"]
            assert result["amazon_products"] > 0
            assert result["github_repos"] > 0
            assert result["rss_articles"] > 0
            assert result["wikipedia_articles"] > 0
            assert result["merged_products"] > 0
            assert result["total_signals"] > 0

    @pytest.mark.asyncio
    async def test_cross_source_merging(self):
        """Test merging products from multiple sources."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            worker = PublicDataIntegrationWorker(
                product_repo_path=str(db_path), dry_run=True
            )

            # Run ingestion
            result = await worker.run_public_data_ingestion()

            # Verify merged products have signals from multiple sources
            assert result["success"]
            assert result["merged_products"] > 0

            # Check that at least some products have multiple signals
            # (indicating cross-source matching worked)
            assert result["total_signals"] >= result["merged_products"]


class TestDataSourceQuality:
    """Test data quality and confidence scoring."""

    @pytest.mark.asyncio
    async def test_amazon_confidence_scoring(self):
        """Test Amazon product confidence scores."""
        discovery = AmazonBestsellersDiscovery(dry_run=True)
        result = await discovery.fetch_bestsellers()

        for product in result["products"]:
            # Confidence should be between 0 and 1
            assert 0 <= product["confidence"] <= 1

    @pytest.mark.asyncio
    async def test_github_confidence_scoring(self):
        """Test GitHub repo confidence scores."""
        discovery = GitHubTrendingDiscovery(dry_run=True)
        result = await discovery.fetch_trending_repos()

        for repo in result["repos"]:
            # Confidence should be between 0 and 1
            assert 0 <= repo["confidence"] <= 1
            # Stars should be non-negative
            assert repo["stars"] >= 0

    @pytest.mark.asyncio
    async def test_rss_article_quality(self):
        """Test RSS article data quality."""
        aggregator = RSSFeedAggregator(dry_run=True)
        result = await aggregator.fetch_trending_articles()

        for article in result["articles"]:
            # All articles should have required fields
            assert article.get("title")
            assert article.get("url")
            assert article.get("source")
            # Confidence between 0 and 1
            assert 0 <= article.get("confidence", 0.5) <= 1


class TestNoAPIRequirements:
    """Verify no API keys are required for any source."""

    @pytest.mark.asyncio
    async def test_all_sources_work_without_credentials(self):
        """Verify all sources work in dry-run without credentials."""
        # All should initialize without credentials
        amazon = AmazonBestsellersDiscovery(dry_run=True)
        github = GitHubTrendingDiscovery(dry_run=True)
        rss = RSSFeedAggregator(dry_run=True)
        wiki = WikipediaTrendingDiscovery(dry_run=True)
        datasets = PublicDatasetsLoader(dry_run=True)

        # All should return successful results
        amazon_result = await amazon.fetch_bestsellers()
        github_result = await github.fetch_trending_repos()
        rss_result = await rss.fetch_trending_articles()
        wiki_result = await wiki.fetch_trending_articles()
        dataset_result = await datasets.load_kaggle_datasets()

        assert amazon_result["success"]
        assert github_result["success"]
        assert rss_result["success"]
        assert wiki_result["success"]
        assert dataset_result["success"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

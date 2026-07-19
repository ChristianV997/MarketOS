"""Public data integration worker - coordinates all free/open data sources.

Aggregates real data from:
- Amazon bestsellers (web scraping, no API key)
- GitHub trending (public pages, no API key)
- RSS feeds (tech news, product blogs)
- Wikipedia trending articles
- Public datasets (CSV downloads from Kaggle, etc.)

All sources work in dry-run mode for testing without external dependencies.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from backend.data.repositories.product_repository import (
    DiscoveredProduct,
    ProductRepository,
    TrendSignal,
)
from backend.discovery.public_data_sources import (
    AmazonBestsellersDiscovery,
    GitHubTrendingDiscovery,
    PublicDatasetsLoader,
    RSSFeedAggregator,
    WikipediaTrendingDiscovery,
)

_log = logging.getLogger(__name__)


class PublicDataIntegrationWorker:
    """Orchestrates public data discovery from multiple free sources."""

    def __init__(
        self,
        product_repo_path: str = "data/marketos.db",
        dry_run: bool = True,
    ):
        self.repo = ProductRepository(db_path=product_repo_path)
        self.dry_run = dry_run

        self.amazon = AmazonBestsellersDiscovery(dry_run=dry_run)
        self.github = GitHubTrendingDiscovery(dry_run=dry_run)
        self.rss = RSSFeedAggregator(dry_run=dry_run)
        self.wikipedia = WikipediaTrendingDiscovery(dry_run=dry_run)
        self.datasets = PublicDatasetsLoader(dry_run=dry_run)

    async def run_public_data_ingestion(self) -> dict:
        """
        Run full public data discovery pipeline.

        Steps:
        1. Fetch from all 5 public sources in parallel
        2. Extract product signals from each source
        3. Merge signals and compute confidence scores
        4. Persist to ProductRepository
        5. Log summary metrics

        Returns:
            {
                "success": bool,
                "amazon_products": N,
                "github_repos": N,
                "rss_articles": N,
                "wikipedia_articles": N,
                "datasets_loaded": N,
                "merged_products": N,
                "total_signals": N,
            }
        """
        now = datetime.now(timezone.utc).isoformat()
        _log.info("Starting public data integration pipeline")

        try:
            # Fetch from all sources in parallel
            amazon_result, github_result, rss_result, wiki_result = await asyncio.gather(
                self.amazon.fetch_bestsellers(),
                self.github.fetch_trending_repos(),
                self.rss.fetch_trending_articles(),
                self.wikipedia.fetch_trending_articles(),
                return_exceptions=True,
            )

            # Process results
            amazon_products = (
                amazon_result.get("products", [])
                if isinstance(amazon_result, dict)
                else []
            )
            github_repos = (
                github_result.get("repos", []) if isinstance(github_result, dict) else []
            )
            rss_articles = (
                rss_result.get("articles", [])
                if isinstance(rss_result, dict)
                else []
            )
            wiki_articles = (
                wiki_result.get("articles", [])
                if isinstance(wiki_result, dict)
                else []
            )

            # Load datasets
            datasets_result = await self.datasets.load_kaggle_datasets()
            datasets = (
                datasets_result.get("datasets", [])
                if isinstance(datasets_result, dict)
                else []
            )

            # Merge all signals into product records
            merged = await self._merge_all_sources(
                amazon_products,
                github_repos,
                rss_articles,
                wiki_articles,
                datasets,
                now,
            )

            # Persist merged products
            persisted_count = 0
            signal_count = 0

            for product_dict in merged.values():
                product = DiscoveredProduct(
                    id=product_dict["id"],
                    name=product_dict["name"],
                    category=product_dict.get("category"),
                    supplier_id=product_dict.get("supplier_id"),
                    cost_usd=product_dict.get("cost_usd"),
                    suggested_retail=product_dict.get("suggested_retail"),
                    trends_mentioned=product_dict.get("trends_mentioned", 0),
                    search_interest=product_dict.get("search_interest", 0.0),
                    successful_sellers=product_dict.get("successful_sellers", 0),
                    avg_rating=product_dict.get("avg_rating"),
                    reviews_count=product_dict.get("reviews_count", 0),
                    market_saturation=product_dict.get("market_saturation", 0.5),
                    trend_direction=product_dict.get("trend_direction", "stable"),
                    supply_risk=product_dict.get("supply_risk", "moderate"),
                    discovered_from=",".join(product_dict.get("sources", [])),
                    discovered_date=now,
                    last_updated=now,
                    confidence=product_dict.get("confidence", 0.5),
                    signal_count=product_dict.get("signal_count", 0),
                )

                if await self.repo.add_discovered_product(product):
                    persisted_count += 1

                # Add individual signals
                for signal in product_dict.get("signals", []):
                    if await self.repo.add_signal(product.id, signal):
                        signal_count += 1

            _log.info(
                f"Public data ingestion complete:\n"
                f"  Amazon bestsellers: {len(amazon_products)}\n"
                f"  GitHub trending: {len(github_repos)}\n"
                f"  RSS articles: {len(rss_articles)}\n"
                f"  Wikipedia trending: {len(wiki_articles)}\n"
                f"  Datasets loaded: {len(datasets)}\n"
                f"  Merged products: {len(merged)}\n"
                f"  Persisted: {persisted_count}\n"
                f"  Total signals: {signal_count}"
            )

            return {
                "success": True,
                "amazon_products": len(amazon_products),
                "github_repos": len(github_repos),
                "rss_articles": len(rss_articles),
                "wikipedia_articles": len(wiki_articles),
                "datasets_loaded": len(datasets),
                "merged_products": len(merged),
                "persisted_products": persisted_count,
                "total_signals": signal_count,
            }

        except Exception as e:
            _log.error(f"Public data integration failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
            }

    async def _merge_all_sources(
        self,
        amazon_products: list,
        github_repos: list,
        rss_articles: list,
        wiki_articles: list,
        datasets: list,
        timestamp: str,
    ) -> dict:
        """Merge signals from all public sources."""
        import hashlib

        merged = {}

        # Process Amazon bestsellers
        for ap in amazon_products:
            name = ap["name"].lower()
            product_id = hashlib.md5(name.encode()).hexdigest()[:16]

            if product_id not in merged:
                merged[product_id] = {
                    "id": product_id,
                    "name": ap["name"],
                    "category": ap.get("category"),
                    "cost_usd": ap.get("price"),
                    "sources": ["amazon"],
                    "signals": [],
                    "trends_mentioned": ap.get("rank", 0),
                    "search_interest": 0.0,
                    "successful_sellers": 1,
                    "avg_rating": ap.get("rating", 0.0),
                    "reviews_count": ap.get("reviews", 0),
                    "confidence": ap.get("confidence", 0.85),
                    "signal_count": 0,
                }

            signal = TrendSignal(
                source="amazon",
                signal_type="bestseller_rank",
                value=float(ap.get("rank", 0)),
                confidence=ap.get("confidence", 0.85),
                timestamp=timestamp,
            )
            merged[product_id]["signals"].append(signal)
            merged[product_id]["signal_count"] += 1

        # Process GitHub repos (tech products)
        for repo in github_repos:
            name = repo["name"].lower()
            product_id = hashlib.md5(name.encode()).hexdigest()[:16]

            if product_id not in merged:
                merged[product_id] = {
                    "id": product_id,
                    "name": repo["name"],
                    "category": "technology",
                    "sources": ["github"],
                    "signals": [],
                    "trends_mentioned": 0,
                    "search_interest": 0.0,
                    "successful_sellers": 0,
                    "avg_rating": None,
                    "reviews_count": repo.get("stars", 0),
                    "confidence": repo.get("confidence", 0.80),
                    "signal_count": 0,
                }
            else:
                if "github" not in merged[product_id]["sources"]:
                    merged[product_id]["sources"].append("github")

            signal = TrendSignal(
                source="github",
                signal_type="github_stars",
                value=float(repo.get("stars", 0)),
                confidence=repo.get("confidence", 0.80),
                timestamp=timestamp,
            )
            merged[product_id]["signals"].append(signal)
            merged[product_id]["signal_count"] += 1

        # Process RSS articles (topic mentions)
        for article in rss_articles:
            title = article["title"].lower()
            product_id = hashlib.md5(title.encode()).hexdigest()[:16]

            if product_id not in merged:
                merged[product_id] = {
                    "id": product_id,
                    "name": article["title"],
                    "category": "media",
                    "sources": ["rss"],
                    "signals": [],
                    "trends_mentioned": 1,
                    "search_interest": 0.0,
                    "successful_sellers": 0,
                    "avg_rating": None,
                    "reviews_count": 0,
                    "confidence": article.get("confidence", 0.75),
                    "signal_count": 0,
                }
            else:
                if "rss" not in merged[product_id]["sources"]:
                    merged[product_id]["sources"].append("rss")
                merged[product_id]["trends_mentioned"] += 1

            signal = TrendSignal(
                source="rss",
                signal_type="article_mention",
                value=1.0,
                confidence=article.get("confidence", 0.75),
                timestamp=timestamp,
            )
            merged[product_id]["signals"].append(signal)
            merged[product_id]["signal_count"] += 1

        # Process Wikipedia articles (interest indicator)
        for article in wiki_articles:
            title = article["title"].lower()
            product_id = hashlib.md5(title.encode()).hexdigest()[:16]

            if product_id not in merged:
                merged[product_id] = {
                    "id": product_id,
                    "name": article["title"],
                    "category": article.get("category", "general"),
                    "sources": ["wikipedia"],
                    "signals": [],
                    "trends_mentioned": 0,
                    "search_interest": article.get("views", 0) / 10000.0,  # Normalize
                    "successful_sellers": 0,
                    "avg_rating": None,
                    "reviews_count": 0,
                    "confidence": article.get("confidence", 0.70),
                    "signal_count": 0,
                }
            else:
                if "wikipedia" not in merged[product_id]["sources"]:
                    merged[product_id]["sources"].append("wikipedia")

            signal = TrendSignal(
                source="wikipedia",
                signal_type="wiki_views",
                value=float(article.get("views", 0)),
                confidence=article.get("confidence", 0.70),
                timestamp=timestamp,
            )
            merged[product_id]["signals"].append(signal)
            merged[product_id]["signal_count"] += 1

        return merged


async def run_public_data_job():
    """Main entry point for scheduled public data integration."""
    worker = PublicDataIntegrationWorker(dry_run=False)
    result = await worker.run_public_data_ingestion()
    return result


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    result = asyncio.run(run_public_data_job())
    sys.exit(0 if result["success"] else 1)

"""Product discovery worker - aggregates trends from multiple sources.

Coordinates Reddit, Google Trends, and supplier catalogs to identify
trending products and compute confidence scores.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

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

_log = logging.getLogger(__name__)


class ProductDiscoveryWorker:
    """Orchestrates product discovery from multiple trend sources."""

    def __init__(
        self,
        product_repo_path: str = "data/marketos.db",
        dry_run: bool = True,
    ):
        self.repo = ProductRepository(db_path=product_repo_path)
        self.dry_run = dry_run

        self.reddit = RedditDiscovery(dry_run=dry_run)
        self.google_trends = GoogleTrendsDiscovery(dry_run=dry_run)
        self.supplier = SupplierCatalogDiscovery(dry_run=dry_run)

    async def run_daily_discovery(self) -> dict:
        """
        Run full product discovery pipeline for today.

        Steps:
        1. Fetch from all 3 sources in parallel
        2. Extract product signals from each source
        3. Merge signals and compute confidence scores
        4. Persist to ProductRepository
        5. Compute category-level statistics

        Returns:
            {
                "success": bool,
                "reddit_products": N,
                "google_trends": N,
                "supplier_products": N,
                "merged_products": N,
                "total_signals": N,
            }
        """
        now = datetime.now(timezone.utc).isoformat()
        _log.info("Starting product discovery pipeline")

        try:
            # Fetch from all sources in parallel
            reddit_result, google_result, supplier_result = await asyncio.gather(
                self.reddit.fetch_trending_products(),
                self.google_trends.fetch_trending_keywords(),
                self.supplier.fetch_trending_products(),
                return_exceptions=True,
            )

            # Process results
            reddit_products = (
                reddit_result.get("products", [])
                if isinstance(reddit_result, dict)
                else []
            )
            google_keywords = (
                google_result.get("keywords", [])
                if isinstance(google_result, dict)
                else []
            )
            supplier_products = (
                supplier_result.get("products", [])
                if isinstance(supplier_result, dict)
                else []
            )

            # Merge signals by product name
            merged = await self._merge_signals(
                reddit_products, google_keywords, supplier_products, now
            )

            # Persist merged products to repository
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
                f"Product discovery complete:\n"
                f"  Reddit products: {len(reddit_products)}\n"
                f"  Google Trends keywords: {len(google_keywords)}\n"
                f"  Supplier products: {len(supplier_products)}\n"
                f"  Merged products: {len(merged)}\n"
                f"  Persisted: {persisted_count}\n"
                f"  Total signals: {signal_count}"
            )

            return {
                "success": True,
                "reddit_products": len(reddit_products),
                "google_trends": len(google_keywords),
                "supplier_products": len(supplier_products),
                "merged_products": len(merged),
                "persisted_products": persisted_count,
                "total_signals": signal_count,
            }

        except Exception as e:
            _log.error(f"Product discovery failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
            }

    async def _merge_signals(
        self,
        reddit_products: list[dict],
        google_keywords: list[dict],
        supplier_products: list[dict],
        timestamp: str,
    ) -> dict:
        """
        Merge signals from all sources by product name.

        Returns: {product_name: {merged_data, signals: [...]}}
        """
        merged = {}

        # Process Reddit products
        for rp in reddit_products:
            name = rp["name"].lower()
            product_id = self._product_id(name)

            if product_id not in merged:
                merged[product_id] = {
                    "id": product_id,
                    "name": rp["name"],
                    "sources": ["reddit"],
                    "signals": [],
                    "trends_mentioned": 0,
                    "search_interest": 0.0,
                    "successful_sellers": 0,
                    "avg_rating": None,
                    "reviews_count": 0,
                    "confidence": 0.5,
                    "signal_count": 0,
                }

            merged[product_id]["trends_mentioned"] += rp.get("mentions", 0)
            merged[product_id]["confidence"] = max(
                merged[product_id]["confidence"],
                rp.get("confidence", 0.5),
            )

            signal = TrendSignal(
                source="reddit",
                signal_type="mention_count",
                value=float(rp.get("mentions", 0)),
                confidence=rp.get("confidence", 0.5),
                timestamp=timestamp,
            )
            merged[product_id]["signals"].append(signal)
            merged[product_id]["signal_count"] += 1

        # Process Google Trends keywords
        for gk in google_keywords:
            keyword = gk["keyword"].lower()
            product_id = self._product_id(keyword)

            if product_id not in merged:
                merged[product_id] = {
                    "id": product_id,
                    "name": gk["keyword"],
                    "category": gk.get("category"),
                    "sources": ["google_trends"],
                    "signals": [],
                    "trends_mentioned": 0,
                    "search_interest": 0.0,
                    "successful_sellers": 0,
                    "avg_rating": None,
                    "reviews_count": 0,
                    "confidence": 0.5,
                    "signal_count": 0,
                }
            else:
                if "google_trends" not in merged[product_id]["sources"]:
                    merged[product_id]["sources"].append("google_trends")
                if "category" not in merged[product_id]:
                    merged[product_id]["category"] = gk.get("category")

            # Set trend direction
            trend = gk.get("trend", "stable")
            merged[product_id]["trend_direction"] = trend

            merged[product_id]["search_interest"] = max(
                merged[product_id]["search_interest"],
                gk.get("interest", 0.0) / 100.0,  # Normalize to 0-1
            )
            merged[product_id]["confidence"] = max(
                merged[product_id]["confidence"],
                gk.get("confidence", 0.5),
            )

            signal = TrendSignal(
                source="google_trends",
                signal_type="search_interest",
                value=gk.get("interest", 0.0),
                confidence=gk.get("confidence", 0.5),
                timestamp=timestamp,
            )
            merged[product_id]["signals"].append(signal)
            merged[product_id]["signal_count"] += 1

        # Process supplier products
        for sp in supplier_products:
            name = sp["name"].lower()
            product_id = self._product_id(name)

            if product_id not in merged:
                merged[product_id] = {
                    "id": product_id,
                    "name": sp["name"],
                    "supplier_id": sp.get("supplier"),
                    "cost_usd": sp.get("price", 0.0),
                    "sources": ["supplier_catalog"],
                    "signals": [],
                    "trends_mentioned": 0,
                    "search_interest": 0.0,
                    "successful_sellers": 0,
                    "avg_rating": None,
                    "reviews_count": 0,
                    "confidence": 0.5,
                    "signal_count": 0,
                }
            else:
                if "supplier_catalog" not in merged[product_id]["sources"]:
                    merged[product_id]["sources"].append("supplier_catalog")

            merged[product_id]["successful_sellers"] += 1
            merged[product_id]["avg_rating"] = sp.get("rating", 4.0)
            merged[product_id]["reviews_count"] += sp.get("reviews", 0)
            merged[product_id]["confidence"] = max(
                merged[product_id]["confidence"],
                sp.get("confidence", 0.5),
            )

            signal = TrendSignal(
                source="supplier_catalog",
                signal_type="seller_count",
                value=float(1),  # Increment for each seller
                confidence=sp.get("confidence", 0.5),
                timestamp=timestamp,
            )
            merged[product_id]["signals"].append(signal)
            merged[product_id]["signal_count"] += 1

        return merged

    def _product_id(self, name: str) -> str:
        """Generate stable product ID from name."""
        return hashlib.md5(name.encode()).hexdigest()[:16]


async def run_discovery_job():
    """Main entry point for scheduled daily discovery."""
    worker = ProductDiscoveryWorker(dry_run=False)
    result = await worker.run_daily_discovery()
    return result


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    result = asyncio.run(run_discovery_job())
    sys.exit(0 if result["success"] else 1)

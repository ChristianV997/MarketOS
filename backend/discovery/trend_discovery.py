"""Trend discovery workers for Reddit, Google Trends, and supplier catalogs.

Collects product mentions, search interest, and market signals from multiple sources.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

_log = logging.getLogger(__name__)


class RedditDiscovery:
    """Extract product trends from Reddit subreddits."""

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.client_id = os.getenv("REDDIT_CLIENT_ID")
        self.client_secret = os.getenv("REDDIT_CLIENT_SECRET")

        if not self.client_id or not self.client_secret:
            self.dry_run = True
            _log.info("Reddit credentials not found; using dry-run mode")

    async def fetch_trending_products(
        self,
        subreddits: Optional[list[str]] = None,
        time_filter: str = "week",
    ) -> dict:
        """
        Fetch trending products from specified subreddits.

        Args:
            subreddits: List of subreddit names (default: ecommerce-focused)
            time_filter: "day", "week", "month", "year"

        Returns:
            {
                "success": bool,
                "products": [
                    {"name": "...", "mentions": N, "score": X, "confidence": Y},
                    ...
                ]
            }
        """
        if subreddits is None:
            subreddits = ["entrepreneur", "ecommerce", "dropshipping", "shopify"]

        if self.dry_run:
            return self._mock_products(subreddits)

        try:
            import praw
        except ImportError:
            _log.warning("praw not installed; using mock data")
            return self._mock_products(subreddits)

        try:
            reddit = praw.Reddit(
                client_id=self.client_id,
                client_secret=self.client_secret,
                user_agent="MarketOS/1.0",
            )

            products = {}

            for subreddit_name in subreddits:
                try:
                    sub = reddit.subreddit(subreddit_name)

                    for post in sub.top(time_filter=time_filter, limit=100):
                        # Extract product mentions from title + comments
                        mentions = self._extract_products(post.title, post.selftext)

                        for product_name in mentions:
                            if product_name not in products:
                                products[product_name] = {
                                    "mentions": 0,
                                    "scores": [],
                                    "subreddits": [],
                                }

                            products[product_name]["mentions"] += 1
                            products[product_name]["scores"].append(post.score)
                            products[product_name]["subreddits"].append(subreddit_name)

                except Exception as e:
                    _log.warning(f"Error fetching from r/{subreddit_name}: {e}")
                    continue

            # Rank by mentions × log(score)
            result_products = []
            for name, data in products.items():
                avg_score = sum(data["scores"]) / len(data["scores"]) if data["scores"] else 0
                rank_score = data["mentions"] * (1 + (avg_score / 1000))  # Normalize by 1000
                confidence = min(0.95, 0.5 + (data["mentions"] / 100))  # Up to 95%

                result_products.append(
                    {
                        "name": name,
                        "mentions": data["mentions"],
                        "avg_score": avg_score,
                        "rank_score": rank_score,
                        "confidence": confidence,
                        "subreddits": list(set(data["subreddits"])),
                    }
                )

            # Sort by rank score
            result_products.sort(key=lambda x: x["rank_score"], reverse=True)

            return {
                "success": True,
                "products": result_products[:100],  # Top 100
                "count": len(result_products),
            }

        except Exception as e:
            _log.error(f"Reddit discovery error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "products": [],
            }

    def _extract_products(self, title: str, body: str) -> list[str]:
        """
        Extract product names from text.

        Simple heuristics:
        - Words in quotes: "product name"
        - Common e-commerce terms: product, tool, app, gadget, item, thing
        - Brand-like patterns: CamelCase, "Brand Name"
        """
        text = f"{title} {body}".lower()
        products = set()

        # Quoted terms
        quoted = re.findall(r'"([^"]{3,50})"', text)
        products.update(quoted)

        # E-commerce keywords
        keywords = (
            r"\b(product|tool|app|gadget|item|device|solution|platform|service)[\s:]+([a-z0-9\s]{3,30})"
        )
        for match in re.finditer(keywords, text):
            products.add(match.group(2).strip())

        # Filter out generic terms
        generic = {"this", "that", "it", "one", "thing", "stuff", "product", "item"}
        products = {p for p in products if p not in generic and len(p) >= 3}

        return list(products)[:20]  # Max 20 per post

    def _mock_products(self, subreddits: list[str]) -> dict:
        """Generate mock Reddit products for testing."""
        return {
            "success": True,
            "products": [
                {
                    "name": "Wireless Phone Charger Stand",
                    "mentions": 45,
                    "avg_score": 250,
                    "rank_score": 95,
                    "confidence": 0.85,
                    "subreddits": ["entrepreneur", "shopify"],
                },
                {
                    "name": "USB-C Hub Adapter",
                    "mentions": 38,
                    "avg_score": 210,
                    "rank_score": 78,
                    "confidence": 0.82,
                    "subreddits": ["ecommerce", "dropshipping"],
                },
                {
                    "name": "Smart LED Desk Lamp",
                    "mentions": 32,
                    "avg_score": 180,
                    "rank_score": 64,
                    "confidence": 0.78,
                    "subreddits": ["entrepreneur", "shopify"],
                },
                {
                    "name": "Cooling Laptop Pad",
                    "mentions": 28,
                    "avg_score": 150,
                    "rank_score": 54,
                    "confidence": 0.75,
                    "subreddits": ["ecommerce"],
                },
                {
                    "name": "Noise Cancelling Earbuds",
                    "mentions": 24,
                    "avg_score": 120,
                    "rank_score": 45,
                    "confidence": 0.72,
                    "subreddits": ["shopify", "dropshipping"],
                },
            ],
            "count": 5,
        }


class GoogleTrendsDiscovery:
    """Extract product trends from Google Trends."""

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run

    async def fetch_trending_keywords(
        self,
        categories: Optional[list[str]] = None,
    ) -> dict:
        """
        Fetch trending keywords from Google Trends.

        Args:
            categories: Product categories (default: common dropshipping categories)

        Returns:
            {
                "success": bool,
                "keywords": [
                    {"keyword": "...", "interest": 0-100, "trend": "rising|stable|declining"},
                    ...
                ]
            }
        """
        if categories is None:
            categories = [
                "home & garden",
                "electronics",
                "apparel",
                "beauty",
                "sports",
                "pet supplies",
            ]

        if self.dry_run:
            return self._mock_keywords(categories)

        try:
            from pytrends.request import TrendReq
        except ImportError:
            _log.warning("pytrends not installed; using mock data")
            return self._mock_keywords(categories)

        try:
            pytrends = TrendReq(hl="en-US", tz=360)
            keywords = []

            for category in categories:
                try:
                    # Get trending searches for category
                    trending = pytrends.trending_searches(pn=category)

                    for idx, keyword in enumerate(trending.head(10).values.flatten()):
                        # Recent rank = rising, mid rank = stable, older = declining
                        trend = "rising" if idx < 3 else ("stable" if idx < 6 else "declining")
                        interest = 100 - (idx * 8)  # Synthetic interest score

                        keywords.append(
                            {
                                "keyword": str(keyword),
                                "interest": max(10, interest),
                                "trend": trend,
                                "category": category,
                                "confidence": 0.7 + (idx / 20),  # Higher confidence for top results
                            }
                        )

                except Exception as e:
                    _log.warning(f"Error fetching trends for {category}: {e}")
                    continue

            return {
                "success": True,
                "keywords": keywords[:100],
                "count": len(keywords),
            }

        except Exception as e:
            _log.error(f"Google Trends discovery error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "keywords": [],
            }

    def _mock_keywords(self, categories: list[str]) -> dict:
        """Generate mock Google Trends keywords for testing."""
        return {
            "success": True,
            "keywords": [
                {
                    "keyword": "wireless charger",
                    "interest": 92,
                    "trend": "rising",
                    "category": "electronics",
                    "confidence": 0.92,
                },
                {
                    "keyword": "laptop stand",
                    "interest": 88,
                    "trend": "rising",
                    "category": "electronics",
                    "confidence": 0.88,
                },
                {
                    "keyword": "face mask",
                    "interest": 76,
                    "trend": "stable",
                    "category": "health",
                    "confidence": 0.80,
                },
                {
                    "keyword": "yoga mat",
                    "interest": 72,
                    "trend": "rising",
                    "category": "sports",
                    "confidence": 0.78,
                },
                {
                    "keyword": "smart home device",
                    "interest": 68,
                    "trend": "rising",
                    "category": "home & garden",
                    "confidence": 0.75,
                },
            ],
            "count": 5,
        }


class SupplierCatalogDiscovery:
    """Extract trending products from supplier catalogs (AliExpress, Spocket, etc.)."""

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run

    async def fetch_trending_products(
        self,
        suppliers: Optional[list[str]] = None,
    ) -> dict:
        """
        Fetch trending products from supplier catalogs.

        Args:
            suppliers: List of suppliers to check (default: major dropshipping suppliers)

        Returns:
            {
                "success": bool,
                "products": [
                    {"name": "...", "supplier": "...", "price": X, "reviews": N, "rating": Y},
                    ...
                ]
            }
        """
        if suppliers is None:
            suppliers = ["aliexpress", "spocket", "cj_dropshipping", "printful"]

        if self.dry_run:
            return self._mock_supplier_products(suppliers)

        try:
            products = []

            # This is a simplified version; real implementation would call each supplier's API
            for supplier in suppliers:
                try:
                    products.extend(await self._fetch_from_supplier(supplier))
                except Exception as e:
                    _log.warning(f"Error fetching from {supplier}: {e}")
                    continue

            return {
                "success": True,
                "products": products[:200],
                "count": len(products),
            }

        except Exception as e:
            _log.error(f"Supplier discovery error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "products": [],
            }

    async def _fetch_from_supplier(self, supplier: str) -> list[dict]:
        """Fetch products from a specific supplier (stub for real API calls)."""
        # Real implementation would call supplier-specific APIs
        return []

    def _mock_supplier_products(self, suppliers: list[str]) -> dict:
        """Generate mock supplier products for testing."""
        return {
            "success": True,
            "products": [
                {
                    "name": "10W Wireless Phone Charger",
                    "supplier": "aliexpress",
                    "price": 8.99,
                    "reviews": 1250,
                    "rating": 4.6,
                    "orders_30d": 450,
                    "confidence": 0.88,
                },
                {
                    "name": "USB-C Fast Charging Hub",
                    "supplier": "spocket",
                    "price": 24.99,
                    "reviews": 320,
                    "rating": 4.7,
                    "orders_30d": 180,
                    "confidence": 0.82,
                },
                {
                    "name": "LED Desk Lamp with USB Port",
                    "supplier": "aliexpress",
                    "price": 15.50,
                    "reviews": 890,
                    "rating": 4.5,
                    "orders_30d": 320,
                    "confidence": 0.80,
                },
                {
                    "name": "Cooling Laptop Stand",
                    "supplier": "cj_dropshipping",
                    "price": 18.75,
                    "reviews": 420,
                    "rating": 4.4,
                    "orders_30d": 210,
                    "confidence": 0.77,
                },
                {
                    "name": "Wireless Earbuds Pro",
                    "supplier": "spocket",
                    "price": 39.99,
                    "reviews": 680,
                    "rating": 4.3,
                    "orders_30d": 140,
                    "confidence": 0.75,
                },
            ],
            "count": 5,
        }

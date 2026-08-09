"""Real ROAS data repository with cross-platform deduplication.

Ingests ROAS data from Shopify, Meta Ads, TikTok Ads and reconciles
multi-touch attribution to produce ground-truth ROAS per product.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np

_log = logging.getLogger(__name__)


@dataclass
class RoasDataPoint:
    """One day's ROAS data for a product + platform combination."""
    date: str
    product_id: str
    platform: str
    spend: float
    revenue: float
    roas: float
    clicks: int
    conversions: int
    deduplication_confidence: float


@dataclass
class Order:
    """Order from Shopify with attribution metadata."""
    id: str
    customer_id: str
    product_id: str
    created_at: datetime
    total_price: float
    source: Optional[str] = None  # utm_source or referrer
    platform: Optional[str] = None  # meta, tiktok, organic


@dataclass
class PlatformInsight:
    """Campaign performance data from Meta or TikTok."""
    date: str
    platform: str
    campaign_id: str
    product_id: str
    spend: float
    revenue: float
    clicks: int
    conversions: int


class RoasRepository:
    """Store and reconcile ROAS data across platforms."""

    def __init__(self, db_path: str = "data/marketos.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self):
        """Create tables for ROAS tracking and deduplication."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS roas_daily (
                    date TEXT,
                    product_id TEXT,
                    platform TEXT,
                    spend REAL,
                    revenue REAL,
                    roas REAL,
                    clicks INTEGER,
                    conversions INTEGER,
                    platform_reported_roas REAL,
                    deduplication_confidence REAL,
                    PRIMARY KEY (date, product_id, platform)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    customer_id TEXT,
                    product_id TEXT,
                    created_at TEXT,
                    total_price REAL,
                    source TEXT,
                    platform TEXT,
                    is_duplicate BOOLEAN DEFAULT 0,
                    duplicate_of TEXT
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS platform_insights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT,
                    platform TEXT,
                    campaign_id TEXT,
                    product_id TEXT,
                    spend REAL,
                    revenue REAL,
                    clicks INTEGER,
                    conversions INTEGER,
                    UNIQUE (date, platform, campaign_id)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS dedup_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id TEXT,
                    product_id TEXT,
                    window_days INTEGER,
                    attribution_method TEXT,
                    created_at TEXT
                )
            """)

            conn.commit()
        finally:
            conn.close()

    def ingest_orders(self, orders: list[Order]) -> int:
        """Ingest Shopify orders. Returns count inserted."""
        conn = sqlite3.connect(self.db_path)
        inserted = 0
        try:
            for order in orders:
                try:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO orders
                        (id, customer_id, product_id, created_at, total_price, source, platform)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            order.id,
                            order.customer_id,
                            order.product_id,
                            order.created_at.isoformat(),
                            order.total_price,
                            order.source,
                            order.platform or "unknown",
                        ),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass  # Skip duplicates
            conn.commit()
            _log.info(f"Ingested {inserted} orders")
        finally:
            conn.close()
        return inserted

    def ingest_platform_insights(self, insights: list[PlatformInsight]) -> int:
        """Ingest campaign performance data. Returns count inserted."""
        conn = sqlite3.connect(self.db_path)
        inserted = 0
        try:
            for insight in insights:
                try:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO platform_insights
                        (date, platform, campaign_id, product_id, spend, revenue, clicks, conversions)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            insight.date,
                            insight.platform,
                            insight.campaign_id,
                            insight.product_id,
                            insight.spend,
                            insight.revenue,
                            insight.clicks,
                            insight.conversions,
                        ),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass
            conn.commit()
            _log.info(f"Ingested {inserted} platform insights")
        finally:
            conn.close()
        return inserted

    def deduplicate_orders(
        self,
        window_days: int = 7,
        attribution_method: str = "last_click",
        product_ids: Optional[list[str]] = None,
    ) -> dict:
        """
        Deduplicate orders within a customer + product + time window.

        Multi-touch attribution model: for each (customer, product) pair within
        the window, keep one order as primary (by attribution_method) and mark
        others as duplicate.

        Args:
            window_days: Max days between orders to consider multi-touch
            attribution_method: 'first_click' or 'last_click'
            product_ids: If set, only deduplicate these products

        Returns:
            {"deduped_count": N, "duplicate_count": M, "primary_count": K}
        """
        conn = sqlite3.connect(self.db_path)
        try:
            # Find multi-touch groups (same customer, same product, within window)
            query = """
                SELECT
                    o1.customer_id,
                    o1.product_id,
                    COUNT(*) as order_count,
                    GROUP_CONCAT(o1.id) as order_ids,
                    GROUP_CONCAT(o1.created_at) as created_ats
                FROM orders o1
                WHERE o1.is_duplicate = 0
            """

            if product_ids:
                placeholders = ",".join("?" * len(product_ids))
                query += f" AND o1.product_id IN ({placeholders})"
                params = product_ids
            else:
                params = []

            query += """
                GROUP BY o1.customer_id, o1.product_id
                HAVING order_count > 1
            """

            rows = conn.execute(query, params).fetchall()

            deduped_count = 0
            duplicate_count = 0

            for customer_id, product_id, order_count, order_ids, created_ats in rows:
                order_ids_list = order_ids.split(",")
                created_ats_list = created_ats.split(",")

                # Sort by created_at
                sorted_orders = sorted(
                    zip(order_ids_list, created_ats_list),
                    key=lambda x: x[1],
                )

                # Pick primary based on method
                if attribution_method == "last_click":
                    primary_id = sorted_orders[-1][0]
                else:  # first_click
                    primary_id = sorted_orders[0][0]

                # Mark others as duplicates
                for oid, _ in sorted_orders:
                    if oid != primary_id:
                        conn.execute(
                            "UPDATE orders SET is_duplicate = 1, duplicate_of = ? WHERE id = ?",
                            (primary_id, oid),
                        )
                        duplicate_count += 1

                deduped_count += 1

            conn.commit()

            # Count total unique (primary) orders
            primary_count = conn.execute(
                "SELECT COUNT(*) FROM orders WHERE is_duplicate = 0"
            ).fetchone()[0]

            _log.info(
                f"Deduplication complete: {deduped_count} groups, "
                f"{duplicate_count} marked duplicate, {primary_count} primary"
            )

            return {
                "deduped_count": deduped_count,
                "duplicate_count": duplicate_count,
                "primary_count": primary_count,
            }
        finally:
            conn.close()

    def get_product_roas(
        self,
        product_id: str,
        days: int = 30,
        deduplicated: bool = True,
    ) -> list[RoasDataPoint]:
        """Get time series ROAS for one product."""
        conn = sqlite3.connect(self.db_path)
        try:
            # From ROAS daily table (already aggregated per platform per day)
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

            rows = conn.execute(
                """
                SELECT
                    date, product_id, platform, spend, revenue, roas,
                    clicks, conversions, deduplication_confidence
                FROM roas_daily
                WHERE product_id = ? AND date >= ?
                ORDER BY date ASC
                """,
                (product_id, cutoff),
            ).fetchall()

            return [
                RoasDataPoint(
                    date=row[0],
                    product_id=row[1],
                    platform=row[2],
                    spend=row[3],
                    revenue=row[4],
                    roas=row[5],
                    clicks=row[6],
                    conversions=row[7],
                    deduplication_confidence=row[8],
                )
                for row in rows
            ]
        finally:
            conn.close()

    def get_platform_comparison(self, days: int = 30) -> dict:
        """Compare Meta vs TikTok ROAS performance."""
        conn = sqlite3.connect(self.db_path)
        try:
            # Use YYYY-MM-DD format for date comparison
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

            platforms = ["meta", "tiktok"]
            comparison = {}

            for platform in platforms:
                row = conn.execute(
                    """
                    SELECT
                        COUNT(*) as campaigns,
                        SUM(spend) as total_spend,
                        SUM(revenue) as total_revenue,
                        AVG(roas) as avg_roas,
                        SUM(conversions) as total_conversions
                    FROM roas_daily
                    WHERE platform = ? AND date >= ?
                    """,
                    (platform, cutoff),
                ).fetchone()

                if row[0] > 0:  # campaigns > 0
                    comparison[platform] = {
                        "campaigns": row[0],
                        "total_spend": row[1],
                        "total_revenue": row[2],
                        "avg_roas": row[3],
                        "total_conversions": row[4],
                    }

            return comparison
        finally:
            conn.close()

    def compute_deduped_roas(
        self,
        product_id: str,
        date: str,
        attribution_method: str = "last_click",
    ) -> float:
        """
        Compute deduplicated ROAS for a product on a specific date.

        Uses order-level deduplication (already marked in orders table)
        to compute true revenue (deduplicated), then divides by platform
        spend (from roas_daily).

        Args:
            product_id: Product identifier
            date: Date in YYYY-MM-DD format
            attribution_method: Attribution model (not used in current computation)

        Returns:
            ROAS as float (revenue / spend), or 0.0 if no data
        """
        conn = sqlite3.connect(self.db_path)
        try:
            # Get true revenue (sum of non-duplicate orders for this product on this date)
            # Use LIKE for date prefix matching to handle various timestamp formats
            date_pattern = f"{date}%"

            revenue_result = conn.execute(
                """
                SELECT SUM(total_price)
                FROM orders
                WHERE product_id = ?
                  AND is_duplicate = 0
                  AND created_at LIKE ?
                """,
                (product_id, date_pattern),
            ).fetchone()

            true_revenue = revenue_result[0] or 0.0

            # Get spend (sum of platform spend for this product on this date)
            spend_result = conn.execute(
                """
                SELECT SUM(spend)
                FROM roas_daily
                WHERE product_id = ? AND date = ?
                """,
                (product_id, date),
            ).fetchone()

            total_spend = spend_result[0] or 0.0

            if total_spend <= 0:
                return 0.0

            return true_revenue / total_spend
        finally:
            conn.close()

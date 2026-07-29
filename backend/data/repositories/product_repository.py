"""Product discovery repository with trending signals.

Stores discovered products from multiple sources (Reddit, Google Trends, supplier catalogs)
with trend signals, market saturation, and confidence scoring.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)


@dataclass
class TrendSignal:
    """One source's signal about a product."""
    source: str  # "reddit", "google_trends", "supplier_feed", "ad_library"
    signal_type: str  # "mention_count", "search_interest", "seller_count", "avg_rating"
    value: float
    confidence: float  # 0-1
    timestamp: str


@dataclass
class DiscoveredProduct:
    """A discovered product with trend signals."""
    id: str
    name: str
    category: Optional[str]
    supplier_id: Optional[str]  # e.g., "aliexpress_123", "spocket_456"
    cost_usd: Optional[float]
    suggested_retail: Optional[float]

    # Aggregated signals
    trends_mentioned: int  # Total mentions across sources
    search_interest: float  # 0-100 from Google Trends
    successful_sellers: int  # Amazon/eBay/AliExpress count
    avg_rating: Optional[float]
    reviews_count: int

    # Risk & trend
    market_saturation: float  # 0-1 (higher = more saturated)
    trend_direction: str  # "rising", "peak", "declining", "stable"
    supply_risk: str  # "abundant", "moderate", "scarce"

    # Meta
    discovered_from: str  # Comma-separated sources
    discovered_date: str  # ISO timestamp
    last_updated: str  # ISO timestamp
    confidence: float  # 0-1 (higher = more validated)

    # Data quality
    signal_count: int  # Number of independent signals


class ProductRepository:
    """Store and query discovered products."""

    def __init__(self, db_path: str = "data/marketos.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self):
        """Create tables for product discovery."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS discovered_products (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    category TEXT,
                    supplier_id TEXT,
                    cost_usd REAL,
                    suggested_retail REAL,

                    trends_mentioned INTEGER DEFAULT 0,
                    search_interest REAL DEFAULT 0,
                    successful_sellers INTEGER DEFAULT 0,
                    avg_rating REAL,
                    reviews_count INTEGER DEFAULT 0,

                    market_saturation REAL DEFAULT 0,
                    trend_direction TEXT DEFAULT 'stable',
                    supply_risk TEXT DEFAULT 'moderate',

                    discovered_from TEXT,
                    discovered_date TEXT,
                    last_updated TEXT,
                    confidence REAL DEFAULT 0.5,
                    signal_count INTEGER DEFAULT 0,

                    UNIQUE(name, category)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS product_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    value REAL NOT NULL,
                    confidence REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (product_id) REFERENCES discovered_products(id),
                    UNIQUE(product_id, source, signal_type)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS product_status (
                    product_id TEXT PRIMARY KEY,
                    status TEXT DEFAULT 'discovered',  -- discovered, validating, validated, launched, abandoned
                    validation_notes TEXT,
                    last_status_change TEXT,
                    FOREIGN KEY (product_id) REFERENCES discovered_products(id)
                )
            """)

            conn.commit()
        finally:
            conn.close()

    async def add_discovered_product(self, product: DiscoveredProduct) -> bool:
        """Upsert a discovered product. Returns True if inserted/updated."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO discovered_products
                (id, name, category, supplier_id, cost_usd, suggested_retail,
                 trends_mentioned, search_interest, successful_sellers, avg_rating, reviews_count,
                 market_saturation, trend_direction, supply_risk,
                 discovered_from, discovered_date, last_updated, confidence, signal_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product.id,
                    product.name,
                    product.category,
                    product.supplier_id,
                    product.cost_usd,
                    product.suggested_retail,
                    product.trends_mentioned,
                    product.search_interest,
                    product.successful_sellers,
                    product.avg_rating,
                    product.reviews_count,
                    product.market_saturation,
                    product.trend_direction,
                    product.supply_risk,
                    product.discovered_from,
                    product.discovered_date,
                    product.last_updated,
                    product.confidence,
                    product.signal_count,
                ),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError as e:
            _log.warning(f"Failed to insert product {product.id}: {e}")
            return False
        finally:
            conn.close()

    async def add_signal(
        self,
        product_id: str,
        signal: TrendSignal,
    ) -> bool:
        """Add a trend signal for a product."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO product_signals
                (product_id, source, signal_type, value, confidence, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    product_id,
                    signal.source,
                    signal.signal_type,
                    signal.value,
                    signal.confidence,
                    signal.timestamp,
                ),
            )
            conn.commit()
            return True
        except Exception as e:
            _log.error(f"Failed to add signal for {product_id}: {e}")
            return False
        finally:
            conn.close()

    async def get_trending_products(
        self,
        category: Optional[str] = None,
        limit: int = 50,
        min_confidence: float = 0.6,
        trend_direction: Optional[str] = None,
    ) -> list[DiscoveredProduct]:
        """
        Get trending products, optionally filtered by category and trend direction.

        Ordering: by (confidence DESC, trends_mentioned DESC, search_interest DESC)
        """
        conn = sqlite3.connect(self.db_path)
        try:
            query = """
                SELECT
                    id, name, category, supplier_id, cost_usd, suggested_retail,
                    trends_mentioned, search_interest, successful_sellers, avg_rating, reviews_count,
                    market_saturation, trend_direction, supply_risk,
                    discovered_from, discovered_date, last_updated, confidence, signal_count
                FROM discovered_products
                WHERE confidence >= ?
            """
            params = [min_confidence]

            if category:
                query += " AND category = ?"
                params.append(category)

            if trend_direction:
                query += " AND trend_direction = ?"
                params.append(trend_direction)

            query += """
                ORDER BY
                    confidence DESC,
                    trends_mentioned DESC,
                    search_interest DESC
                LIMIT ?
            """
            params.append(limit)

            rows = conn.execute(query, params).fetchall()

            return [
                DiscoveredProduct(
                    id=row[0],
                    name=row[1],
                    category=row[2],
                    supplier_id=row[3],
                    cost_usd=row[4],
                    suggested_retail=row[5],
                    trends_mentioned=row[6],
                    search_interest=row[7],
                    successful_sellers=row[8],
                    avg_rating=row[9],
                    reviews_count=row[10],
                    market_saturation=row[11],
                    trend_direction=row[12],
                    supply_risk=row[13],
                    discovered_from=row[14],
                    discovered_date=row[15],
                    last_updated=row[16],
                    confidence=row[17],
                    signal_count=row[18],
                )
                for row in rows
            ]
        finally:
            conn.close()

    async def get_validated_products(
        self,
        min_confidence: float = 0.75,
        limit: int = 100,
    ) -> list[DiscoveredProduct]:
        """Get high-confidence products (ready for launch consideration)."""
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT
                    id, name, category, supplier_id, cost_usd, suggested_retail,
                    trends_mentioned, search_interest, successful_sellers, avg_rating, reviews_count,
                    market_saturation, trend_direction, supply_risk,
                    discovered_from, discovered_date, last_updated, confidence, signal_count
                FROM discovered_products
                WHERE confidence >= ?
                  AND signal_count >= 3
                ORDER BY confidence DESC, search_interest DESC
                LIMIT ?
                """,
                (min_confidence, limit),
            ).fetchall()

            return [
                DiscoveredProduct(
                    id=row[0],
                    name=row[1],
                    category=row[2],
                    supplier_id=row[3],
                    cost_usd=row[4],
                    suggested_retail=row[5],
                    trends_mentioned=row[6],
                    search_interest=row[7],
                    successful_sellers=row[8],
                    avg_rating=row[9],
                    reviews_count=row[10],
                    market_saturation=row[11],
                    trend_direction=row[12],
                    supply_risk=row[13],
                    discovered_from=row[14],
                    discovered_date=row[15],
                    last_updated=row[16],
                    confidence=row[17],
                    signal_count=row[18],
                )
                for row in rows
            ]
        finally:
            conn.close()

    async def get_signals_for_product(
        self,
        product_id: str,
    ) -> list[TrendSignal]:
        """Get all signals for a product."""
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT source, signal_type, value, confidence, timestamp
                FROM product_signals
                WHERE product_id = ?
                ORDER BY timestamp DESC
                """,
                (product_id,),
            ).fetchall()

            return [
                TrendSignal(
                    source=row[0],
                    signal_type=row[1],
                    value=row[2],
                    confidence=row[3],
                    timestamp=row[4],
                )
                for row in rows
            ]
        finally:
            conn.close()

    async def get_category_stats(self, category: str) -> dict:
        """Get aggregate stats for a product category."""
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) as product_count,
                    AVG(search_interest) as avg_search_interest,
                    AVG(market_saturation) as avg_saturation,
                    AVG(confidence) as avg_confidence,
                    SUM(CASE WHEN trend_direction = 'rising' THEN 1 ELSE 0 END) as rising_count
                FROM discovered_products
                WHERE category = ?
                """,
                (category,),
            ).fetchone()

            if not row:
                return {}

            return {
                "product_count": row[0],
                "avg_search_interest": row[1],
                "avg_saturation": row[2],
                "avg_confidence": row[3],
                "rising_count": row[4],
            }
        finally:
            conn.close()

    async def update_product_status(
        self,
        product_id: str,
        status: str,
        notes: Optional[str] = None,
    ) -> bool:
        """Update product validation status."""
        conn = sqlite3.connect(self.db_path)
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                INSERT OR REPLACE INTO product_status
                (product_id, status, validation_notes, last_status_change)
                VALUES (?, ?, ?, ?)
                """,
                (product_id, status, notes, now),
            )
            conn.commit()
            return True
        except Exception as e:
            _log.error(f"Failed to update status for {product_id}: {e}")
            return False
        finally:
            conn.close()

    async def get_product_status(self, product_id: str) -> Optional[dict]:
        """Get product validation status."""
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT status, validation_notes, last_status_change
                FROM product_status
                WHERE product_id = ?
                """,
                (product_id,),
            ).fetchone()

            if not row:
                return None

            return {
                "status": row[0],
                "notes": row[1],
                "last_change": row[2],
            }
        finally:
            conn.close()

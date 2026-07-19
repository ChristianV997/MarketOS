"""Daily ROAS ingestion worker.

Fetches order and campaign data from Shopify, Meta, and TikTok,
reconciles multi-touch attribution, and populates the RoasRepository.

Designed to run as a daily scheduled job (00:00 UTC).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from backend.connectors.real_data_connector import (
    MetaAdsConnector,
    ShopifyConnector,
    TikTokAdsConnector,
)
from backend.data.repositories.roas_repository import (
    Order,
    PlatformInsight,
    RoasRepository,
)

_log = logging.getLogger(__name__)


class RoasIngestionWorker:
    """Coordinates daily ROAS data ingestion from all sources."""

    def __init__(
        self,
        roas_repo_path: str = "data/marketos.db",
        dry_run: bool = True,
    ):
        self.repo = RoasRepository(db_path=roas_repo_path)
        self.dry_run = dry_run

        self.shopify = ShopifyConnector(dry_run=dry_run)
        self.meta = MetaAdsConnector(dry_run=dry_run)
        self.tiktok = TikTokAdsConnector(dry_run=dry_run)

    async def run_daily_ingestion(self, target_date: datetime | None = None):
        """
        Run full daily ingestion pipeline for a target date (default: yesterday).

        Steps:
        1. Fetch Shopify orders
        2. Fetch Meta campaign insights
        3. Fetch TikTok campaign insights
        4. Ingest all into repository
        5. Deduplicate orders within cross-platform windows
        6. Log summary

        Args:
            target_date: Date to ingest (default: yesterday in UTC)
        """
        if target_date is None:
            target_date = datetime.now(timezone.utc) - timedelta(days=1)

        # Use date in YYYY-MM-DD format for filtering
        date_str = target_date.strftime("%Y-%m-%d")
        date_start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        date_end = date_start + timedelta(days=1) - timedelta(seconds=1)

        _log.info(f"Starting ROAS ingestion for {date_str}")

        try:
            # Fetch from all sources in parallel
            shopify_result, meta_result, tiktok_result = await asyncio.gather(
                self.shopify.fetch_orders(since=date_start, until=date_end),
                self.meta.fetch_daily_insights(date=date_str),
                self.tiktok.fetch_daily_insights(date=date_str),
                return_exceptions=True,
            )

            # Process results
            shopify_orders = self._process_shopify_orders(shopify_result, date_str)
            meta_insights = self._process_platform_insights(meta_result, "meta")
            tiktok_insights = self._process_platform_insights(tiktok_result, "tiktok")

            # Ingest into repository
            shopify_count = self.repo.ingest_orders(shopify_orders)
            meta_count = self.repo.ingest_platform_insights(meta_insights)
            tiktok_count = self.repo.ingest_platform_insights(tiktok_insights)

            # Deduplicate orders
            dedup_result = self.repo.deduplicate_orders(
                window_days=7,
                attribution_method="last_click",
            )

            _log.info(
                f"ROAS ingestion complete for {date_str}:\n"
                f"  Shopify orders: {shopify_count}\n"
                f"  Meta insights: {meta_count}\n"
                f"  TikTok insights: {tiktok_count}\n"
                f"  Deduplication: {dedup_result['deduped_count']} groups, "
                f"{dedup_result['duplicate_count']} marked duplicate"
            )

            return {
                "success": True,
                "date": date_str,
                "shopify_orders": shopify_count,
                "meta_insights": meta_count,
                "tiktok_insights": tiktok_count,
                "deduplication": dedup_result,
            }

        except Exception as e:
            _log.error(f"ROAS ingestion failed for {date_str}: {e}", exc_info=True)
            return {
                "success": False,
                "date": date_str,
                "error": str(e),
            }

    def _process_shopify_orders(self, result: dict, date_str: str) -> list[Order]:
        """Convert Shopify API result to Order objects."""
        if not result.get("success"):
            _log.warning(f"Shopify fetch failed: {result.get('error')}")
            return []

        orders = []
        for order_data in result.get("orders", []):
            # One row per product in order (for product-level ROAS tracking)
            for product in order_data.get("products", []):
                order = Order(
                    id=f"{order_data['id']}-{product['handle']}",
                    customer_id=order_data.get("customer_id") or "unknown",
                    product_id=product["handle"],
                    created_at=datetime.fromisoformat(
                        order_data["created_at"].replace("Z", "+00:00")
                    ),
                    total_price=product["price"],  # Per-product price
                    source=order_data.get("utm_source"),
                    platform=self._infer_platform(order_data.get("utm_source")),
                )
                orders.append(order)

        return orders

    def _process_platform_insights(
        self,
        result: dict,
        platform: str,
    ) -> list[PlatformInsight]:
        """Convert platform API result to PlatformInsight objects."""
        if not result.get("success"):
            _log.warning(f"{platform} fetch failed: {result.get('error')}")
            return []

        insights = []
        for insight_data in result.get("insights", []):
            # Extract spend and revenue based on platform schema
            if platform == "meta":
                spend = insight_data.get("spend", 0)
                revenue = insight_data.get("purchase_conversion_value", 0)
                clicks = insight_data.get("clicks", 0)
                conversions = insight_data.get("purchase_roas", 0)  # Approximate
            else:  # tiktok
                spend = insight_data.get("spend", 0)
                revenue = insight_data.get("convert", 0) * insight_data.get("cost", 1)
                clicks = insight_data.get("cost", 0)
                conversions = insight_data.get("convert", 0)

            insight = PlatformInsight(
                date=insight_data.get("date", ""),
                platform=platform,
                campaign_id=insight_data.get("campaign_id", ""),
                product_id=insight_data.get("product_id", "unknown"),
                spend=float(spend),
                revenue=float(revenue),
                clicks=int(clicks),
                conversions=int(conversions),
            )
            insights.append(insight)

        return insights

    def _infer_platform(self, utm_source: str | None) -> str:
        """Infer platform from utm_source."""
        if not utm_source:
            return "unknown"
        utm_lower = utm_source.lower()
        if "meta" in utm_lower or "facebook" in utm_lower:
            return "meta"
        if "tiktok" in utm_lower:
            return "tiktok"
        if "organic" in utm_lower or "direct" in utm_lower:
            return "organic"
        return "unknown"


async def run_ingestion_job():
    """Main entry point for scheduled daily ingestion."""
    worker = RoasIngestionWorker(dry_run=False)
    result = await worker.run_daily_ingestion()
    return result


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    result = asyncio.run(run_ingestion_job())
    sys.exit(0 if result["success"] else 1)

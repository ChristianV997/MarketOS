"""Real data connectors for Shopify, Meta Ads, TikTok Ads.

Each connector supports both real API calls (when credentials available)
and dry-run/mock mode (fallback for testing/development).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

_log = logging.getLogger(__name__)


class BaseConnector:
    """Base class for real data connectors."""

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run


class ShopifyConnector(BaseConnector):
    """Fetch order and product data from Shopify Admin API."""

    def __init__(
        self,
        shop_url: Optional[str] = None,
        access_token: Optional[str] = None,
        dry_run: bool = True,
    ):
        super().__init__(dry_run=dry_run)
        self.shop_url = shop_url or os.getenv("SHOPIFY_STORE_URL")
        self.access_token = access_token or os.getenv("SHOPIFY_ACCESS_TOKEN")
        self.api_version = "2024-01"
        self.base_url = f"https://{self.shop_url}/admin/api/{self.api_version}"

        # Check if we can use real API
        if not self.shop_url or not self.access_token:
            self.dry_run = True
            _log.warning("Shopify credentials not found; using dry-run mode")

    async def fetch_orders(
        self,
        since: datetime,
        until: datetime,
        status: str = "any",
        limit: int = 250,
    ) -> dict:
        """
        Fetch orders from Shopify API.

        Args:
            since: Orders created after this datetime
            until: Orders created before this datetime
            status: 'any', 'fulfilled', 'pending', 'cancelled', 'refunded'
            limit: Max orders to fetch per call

        Returns:
            {
                "success": bool,
                "orders": [{"id", "created_at", "total_price", "customer_id", ...}, ...],
                "error": str if not success
            }
        """
        if self.dry_run:
            return self._mock_orders(since, until)

        try:
            import requests
        except ImportError:
            _log.error("requests library not available; using mock data")
            return self._mock_orders(since, until)

        try:
            # GraphQL query for orders with product + customer info
            query = """
            {
              orders(first: %d, query: "created_at:[%s TO %s]") {
                edges {
                  node {
                    id
                    name
                    createdAt
                    updatedAt
                    totalPrice {
                      amount
                      currencyCode
                    }
                    customer {
                      id
                      email
                    }
                    lineItems(first: 100) {
                      edges {
                        node {
                          product {
                            id
                            handle
                            title
                          }
                          quantity
                          price {
                            amount
                          }
                        }
                      }
                    }
                    fulfillmentOrders(first: 10, query: "status:scheduled OR status:in_progress") {
                      edges {
                        node {
                          status
                        }
                      }
                    }
                    attributionData {
                      utmParameters {
                        source
                        medium
                        campaign
                      }
                    }
                  }
                }
              }
            }
            """ % (
                limit,
                since.isoformat(),
                until.isoformat(),
            )

            headers = {
                "X-Shopify-Access-Token": self.access_token,
                "Content-Type": "application/json",
            }

            response = requests.post(
                f"{self.base_url}/graphql.json",
                json={"query": query},
                headers=headers,
                timeout=30,
            )

            if response.status_code != 200:
                _log.error(
                    f"Shopify API error: {response.status_code} {response.text[:200]}"
                )
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                    "orders": [],
                }

            data = response.json()

            if "errors" in data:
                _log.error(f"GraphQL error: {data['errors']}")
                return {
                    "success": False,
                    "error": str(data["errors"]),
                    "orders": [],
                }

            orders = []
            for edge in data.get("data", {}).get("orders", {}).get("edges", []):
                node = edge["node"]
                orders.append(
                    {
                        "id": node["id"],
                        "name": node["name"],
                        "created_at": node["createdAt"],
                        "customer_id": node["customer"]["id"]
                        if node.get("customer")
                        else None,
                        "customer_email": node["customer"]["email"]
                        if node.get("customer")
                        else None,
                        "total_price": float(node["totalPrice"]["amount"]),
                        "products": [
                            {
                                "id": item["node"]["product"]["id"],
                                "handle": item["node"]["product"]["handle"],
                                "title": item["node"]["product"]["title"],
                                "quantity": item["node"]["quantity"],
                                "price": float(item["node"]["price"]["amount"]),
                            }
                            for item in node.get("lineItems", {}).get("edges", [])
                        ],
                        "utm_source": node.get("attributionData", {})
                        .get("utmParameters", {})
                        .get("source"),
                    }
                )

            return {
                "success": True,
                "orders": orders,
                "count": len(orders),
            }

        except Exception as e:
            _log.error(f"Shopify connector error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "orders": [],
            }

    def _mock_orders(self, since: datetime, until: datetime) -> dict:
        """Generate mock orders for testing."""
        now = datetime.now(timezone.utc)
        return {
            "success": True,
            "orders": [
                {
                    "id": f"mock-order-{i}",
                    "name": f"Order #{1000+i}",
                    "created_at": (
                        since + timedelta(hours=i)
                    ).isoformat(),
                    "customer_id": f"cust-{i % 3}",
                    "customer_email": f"customer{i % 3}@example.com",
                    "total_price": 85.0 + (i * 10 % 50),
                    "products": [
                        {
                            "id": f"prod-{i}",
                            "handle": f"product-{i}",
                            "title": f"Mock Product {i}",
                            "quantity": 1,
                            "price": 85.0 + (i * 10 % 50),
                        }
                    ],
                    "utm_source": ["organic", "meta", "tiktok"][i % 3],
                }
                for i in range(5)
            ],
            "count": 5,
        }


class MetaAdsConnector(BaseConnector):
    """Fetch campaign performance data from Meta Ads API."""

    def __init__(
        self,
        access_token: Optional[str] = None,
        ad_account_id: Optional[str] = None,
        dry_run: bool = True,
    ):
        super().__init__(dry_run=dry_run)
        self.access_token = access_token or os.getenv("META_ACCESS_TOKEN")
        self.ad_account_id = ad_account_id or os.getenv("META_AD_ACCOUNT_ID")
        self.api_version = "v20.0"

        if not self.access_token or not self.ad_account_id:
            self.dry_run = True
            _log.warning("Meta credentials not found; using dry-run mode")

    async def fetch_daily_insights(
        self,
        date: str,
    ) -> dict:
        """
        Fetch daily campaign insights for a specific date.

        Args:
            date: YYYY-MM-DD format

        Returns:
            {
                "success": bool,
                "insights": [{"campaign_id", "spend", "revenue", "roas", ...}, ...],
                "error": str if not success
            }
        """
        if self.dry_run:
            return self._mock_insights(date)

        try:
            import requests
        except ImportError:
            _log.error("requests library not available; using mock data")
            return self._mock_insights(date)

        try:
            url = (
                f"https://graph.instagram.com/{self.api_version}/act_{self.ad_account_id}"
                f"/insights?date_start={date}&date_stop={date}"
                f"&fields=spend,impressions,clicks,purchase_roas,purchase_conversion_value"
                f"&access_token={self.access_token}"
            )

            response = requests.get(url, timeout=30)

            if response.status_code != 200:
                _log.error(f"Meta API error: {response.status_code}")
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                    "insights": [],
                }

            data = response.json()

            if "error" in data:
                _log.error(f"Meta API error: {data['error']}")
                return {
                    "success": False,
                    "error": str(data["error"]),
                    "insights": [],
                }

            return {
                "success": True,
                "insights": data.get("data", []),
                "count": len(data.get("data", [])),
            }

        except Exception as e:
            _log.error(f"Meta connector error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "insights": [],
            }

    def _mock_insights(self, date: str) -> dict:
        """Generate mock Meta insights."""
        return {
            "success": True,
            "insights": [
                {
                    "campaign_id": f"meta-campaign-{i}",
                    "date": date,
                    "spend": 500.0 + (i * 100),
                    "impressions": 5000 + (i * 500),
                    "clicks": 150 + (i * 20),
                    "purchase_roas": 2.5 + (i * 0.1),
                    "purchase_conversion_value": 1250.0 + (i * 250),
                }
                for i in range(3)
            ],
            "count": 3,
        }


class TikTokAdsConnector(BaseConnector):
    """Fetch campaign performance data from TikTok Ads API."""

    def __init__(
        self,
        access_token: Optional[str] = None,
        advertiser_id: Optional[str] = None,
        dry_run: bool = True,
    ):
        super().__init__(dry_run=dry_run)
        self.access_token = access_token or os.getenv("TIKTOK_ACCESS_TOKEN")
        self.advertiser_id = advertiser_id or os.getenv("TIKTOK_ADVERTISER_ID")
        self.api_version = "v1.3"

        if not self.access_token or not self.advertiser_id:
            self.dry_run = True
            _log.warning("TikTok credentials not found; using dry-run mode")

    async def fetch_daily_insights(self, date: str) -> dict:
        """
        Fetch daily campaign insights for a specific date.

        Args:
            date: YYYY-MM-DD format

        Returns:
            {
                "success": bool,
                "insights": [{"campaign_id", "spend", "convert", "cost", ...}, ...],
                "error": str if not success
            }
        """
        if self.dry_run:
            return self._mock_insights(date)

        try:
            import requests
        except ImportError:
            _log.error("requests library not available; using mock data")
            return self._mock_insights(date)

        try:
            url = (
                f"https://business-api.tiktok.com/open_api/{self.api_version}"
                f"/campaign/get/?advertiser_id={self.advertiser_id}"
                f"&fields=campaign_id,campaign_name,spend,convert,cost"
            )

            headers = {"Access-Token": self.access_token}

            response = requests.get(url, headers=headers, timeout=30)

            if response.status_code != 200:
                _log.error(f"TikTok API error: {response.status_code}")
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                    "insights": [],
                }

            data = response.json()

            if not data.get("data"):
                _log.error(f"TikTok API error: {data}")
                return {
                    "success": False,
                    "error": data.get("message", "Unknown error"),
                    "insights": [],
                }

            return {
                "success": True,
                "insights": data.get("data", {}).get("list", []),
                "count": len(data.get("data", {}).get("list", [])),
            }

        except Exception as e:
            _log.error(f"TikTok connector error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "insights": [],
            }

    def _mock_insights(self, date: str) -> dict:
        """Generate mock TikTok insights."""
        return {
            "success": True,
            "insights": [
                {
                    "campaign_id": f"tiktok-campaign-{i}",
                    "campaign_name": f"TikTok Campaign {i}",
                    "date": date,
                    "spend": 400.0 + (i * 80),
                    "convert": 80 + (i * 15),
                    "cost": 5.0 + (i * 0.2),
                }
                for i in range(3)
            ],
            "count": 3,
        }

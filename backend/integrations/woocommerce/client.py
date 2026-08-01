"""backend.integrations.woocommerce.client — thin WooCommerce REST API v3
HTTP client. No Protocol-mapping logic lives here (see adapter.py) — this
module only knows how to authenticate and call the Woo REST API.
"""
from __future__ import annotations

import os
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


class WooCommerceClient:
    """Basic-auth (consumer key/secret, over HTTPS) REST v3 client."""

    def __init__(self, store_url: str | None = None, *, consumer_key: str | None = None,
                 consumer_secret: str | None = None, timeout_s: float = 10.0, client: Any = None):
        self.store_url = (store_url or os.getenv("WOOCOMMERCE_STORE_URL", "")).rstrip("/")
        self.consumer_key = consumer_key or os.getenv("WOOCOMMERCE_CONSUMER_KEY", "")
        self.consumer_secret = consumer_secret or os.getenv("WOOCOMMERCE_CONSUMER_SECRET", "")
        self.timeout_s = timeout_s
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.store_url and self.consumer_key and self.consumer_secret)

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("WooCommerce is not configured; set WOOCOMMERCE_STORE_URL/CONSUMER_KEY/CONSUMER_SECRET")
        if httpx is None and self._client is None:
            raise RuntimeError("httpx is required for the WooCommerce adapter")
        client = self._client or httpx.Client(
            base_url=f"{self.store_url}/wp-json/wc/v3", timeout=self.timeout_s,
            auth=(self.consumer_key, self.consumer_secret),
        )
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"data": payload}

    def ping(self) -> bool:
        try:
            self.request("GET", "/system_status")
            return True
        except Exception:
            return False

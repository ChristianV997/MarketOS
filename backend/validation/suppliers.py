"""backend.validation.suppliers — multi-supplier sourcing layer.

Four supplier clients (CJ Dropshipping, Zendrop, Spocket, Printful) behind a
common interface.  All calls are dry-run by default (SUPPLIERS_DRY_RUN=true)
and return deterministic mock quotes derived from the product name, so the
whole validation pipeline works offline and in tests without credentials.

Production activation per supplier: set SUPPLIERS_DRY_RUN=false and supply
the supplier's API key env var (see each client class).

Public surface:
    find_best_supplier(product) → SupplierQuote  (cheapest reliable quote)
    quote_all(product)          → list[SupplierQuote]
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, asdict

from backend.patterns.errors import SupplierQuoteError

_log = logging.getLogger(__name__)

_DRY_RUN = os.getenv("SUPPLIERS_DRY_RUN", "true").lower() != "false"

# Reliability floor: quotes below this are excluded from find_best_supplier
_MIN_RELIABILITY = float(os.getenv("SUPPLIER_MIN_RELIABILITY", "0.7"))


@dataclass
class SupplierQuote:
    """One supplier's offer for a product."""
    supplier: str
    product_id: str
    product_name: str
    cost: float               # unit cost
    shipping: float           # shipping to customer
    fulfillment_days: int
    reliability: float        # 0–1 supplier track record

    @property
    def landed_cost(self) -> float:
        return round(self.cost + self.shipping, 2)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["landed_cost"] = self.landed_cost
        return d


def _stable_fraction(seed: str) -> float:
    """Deterministic pseudo-random fraction in [0, 1) from a string seed."""
    digest = hashlib.md5(seed.encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


class SupplierClient:
    """Base supplier client.  Subclasses define name, env key, and cost band.

    The mock quote is deterministic per (supplier, product) so validation
    results are reproducible across runs and in tests.
    """

    name = "base"
    api_key_env = ""
    # Mock cost band and profile — rough real-world shape per supplier
    cost_band: tuple[float, float] = (5.0, 30.0)
    shipping_band: tuple[float, float] = (1.0, 6.0)
    base_reliability = 0.85
    base_fulfillment_days = 9

    def is_configured(self) -> bool:
        return bool(self.api_key_env and os.getenv(self.api_key_env))

    def quote(self, product_name: str) -> SupplierQuote | None:
        """Return a quote for the product, or None when unavailable.

        Live failures are wrapped as SupplierQuoteError (retryable=True) so
        callers that care can distinguish "supplier had a bad moment" from a
        real bug, even though this method itself falls back to a mock quote
        either way — validation must never block on one flaky supplier.
        """
        if _DRY_RUN or not self.is_configured():
            return self._mock_quote(product_name)
        try:
            return self._live_quote(product_name)
        except Exception as exc:
            wrapped = SupplierQuoteError(
                f"{self.name} live quote failed for {product_name!r}: {exc}",
                service=self.name,
            )
            _log.warning("supplier_quote_failed supplier=%s product=%s "
                        "retryable=%s error=%s",
                        self.name, product_name, wrapped.retryable, exc)
            return self._mock_quote(product_name)

    # -- mock path -----------------------------------------------------------

    def _mock_quote(self, product_name: str) -> SupplierQuote:
        f_cost  = _stable_fraction(f"{self.name}:{product_name}:cost")
        f_ship  = _stable_fraction(f"{self.name}:{product_name}:ship")
        f_rel   = _stable_fraction(f"{self.name}:{product_name}:rel")
        lo, hi  = self.cost_band
        slo, shi = self.shipping_band
        return SupplierQuote(
            supplier=self.name,
            product_id=f"{self.name}_{hashlib.md5(product_name.encode()).hexdigest()[:10]}",
            product_name=product_name,
            cost=round(lo + f_cost * (hi - lo), 2),
            shipping=round(slo + f_ship * (shi - slo), 2),
            fulfillment_days=self.base_fulfillment_days,
            reliability=round(min(0.99, self.base_reliability + f_rel * 0.1), 2),
        )

    # -- live path (overridden per supplier) ----------------------------------

    def _live_quote(self, product_name: str) -> SupplierQuote | None:
        raise NotImplementedError


class CJDropshippingClient(SupplierClient):
    """CJ Dropshipping — https://developers.cjdropshipping.com"""
    name = "cj_dropshipping"
    api_key_env = "CJ_API_KEY"
    cost_band = (4.0, 25.0)
    shipping_band = (1.5, 5.0)
    base_reliability = 0.88
    base_fulfillment_days = 8

    def _live_quote(self, product_name: str) -> SupplierQuote | None:
        import requests
        resp = requests.get(
            "https://developers.cjdropshipping.com/api2.0/v1/product/list",
            headers={"CJ-Access-Token": os.environ[self.api_key_env]},
            params={"productNameEn": product_name, "pageSize": 1},
            timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json().get("data", {}).get("list", [])
        if not rows:
            return None
        row = rows[0]
        return SupplierQuote(
            supplier=self.name,
            product_id=str(row.get("pid", "")),
            product_name=product_name,
            cost=float(row.get("sellPrice", 0) or 0),
            shipping=float(row.get("logisticPrice", 0) or 0),
            fulfillment_days=int(row.get("deliveryTime", self.base_fulfillment_days) or self.base_fulfillment_days),
            reliability=self.base_reliability,
        )


class ZendropClient(SupplierClient):
    """Zendrop — https://zendrop.com (partner API)"""
    name = "zendrop"
    api_key_env = "ZENDROP_API_KEY"
    cost_band = (5.0, 28.0)
    shipping_band = (2.0, 6.0)
    base_reliability = 0.86
    base_fulfillment_days = 10

    def _live_quote(self, product_name: str) -> SupplierQuote | None:
        import requests
        resp = requests.get(
            "https://api.zendrop.com/v1/products",
            headers={"Authorization": f"Bearer {os.environ[self.api_key_env]}"},
            params={"search": product_name, "limit": 1},
            timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json().get("data", [])
        if not rows:
            return None
        row = rows[0]
        return SupplierQuote(
            supplier=self.name,
            product_id=str(row.get("id", "")),
            product_name=product_name,
            cost=float(row.get("cost", 0) or 0),
            shipping=float(row.get("shipping_cost", 0) or 0),
            fulfillment_days=int(row.get("processing_days", self.base_fulfillment_days) or self.base_fulfillment_days),
            reliability=self.base_reliability,
        )


class SpocketClient(SupplierClient):
    """Spocket — US/EU-focused suppliers, faster shipping, higher cost."""
    name = "spocket"
    api_key_env = "SPOCKET_API_KEY"
    cost_band = (8.0, 35.0)
    shipping_band = (3.0, 8.0)
    base_reliability = 0.90
    base_fulfillment_days = 5

    def _live_quote(self, product_name: str) -> SupplierQuote | None:
        import requests
        resp = requests.get(
            "https://api.spocket.co/api/v1/products",
            headers={"Authorization": f"Bearer {os.environ[self.api_key_env]}"},
            params={"query": product_name, "per_page": 1},
            timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json().get("products", [])
        if not rows:
            return None
        row = rows[0]
        return SupplierQuote(
            supplier=self.name,
            product_id=str(row.get("id", "")),
            product_name=product_name,
            cost=float(row.get("cost", 0) or 0),
            shipping=float(row.get("shipping_cost", 0) or 0),
            fulfillment_days=self.base_fulfillment_days,
            reliability=self.base_reliability,
        )


class PrintfulClient(SupplierClient):
    """Printful — print-on-demand; higher unit cost, near-perfect reliability."""
    name = "printful"
    api_key_env = "PRINTFUL_API_KEY"
    cost_band = (10.0, 40.0)
    shipping_band = (3.5, 9.0)
    base_reliability = 0.95
    base_fulfillment_days = 6

    def _live_quote(self, product_name: str) -> SupplierQuote | None:
        import requests
        resp = requests.get(
            "https://api.printful.com/products",
            headers={"Authorization": f"Bearer {os.environ[self.api_key_env]}"},
            params={"search": product_name},
            timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json().get("result", [])
        if not rows:
            return None
        row = rows[0]
        return SupplierQuote(
            supplier=self.name,
            product_id=str(row.get("id", "")),
            product_name=product_name,
            cost=float(row.get("price", 0) or 0),
            shipping=4.5,   # Printful flat-rate estimate; refined at order time
            fulfillment_days=self.base_fulfillment_days,
            reliability=self.base_reliability,
        )


_CLIENTS: list[SupplierClient] = [
    CJDropshippingClient(),
    ZendropClient(),
    SpocketClient(),
    PrintfulClient(),
]


def quote_all(product_name: str) -> list[SupplierQuote]:
    """Collect quotes from every supplier concurrently (None results dropped).

    Live supplier calls are network-bound (~1-3s each); querying all four in
    a thread pool turns worst-case ~12s sequential into ~3s.  Result order
    stays deterministic (client registration order), so downstream scoring
    and tests are unaffected.
    """
    from concurrent.futures import ThreadPoolExecutor

    def _safe_quote(client: SupplierClient) -> SupplierQuote | None:
        try:
            return client.quote(product_name)
        except Exception as exc:
            _log.debug("supplier_quote_error supplier=%s error=%s", client.name, exc)
            return None

    with ThreadPoolExecutor(max_workers=len(_CLIENTS)) as pool:
        results = list(pool.map(_safe_quote, _CLIENTS))
    return [q for q in results if q is not None]


def find_best_supplier(product_name: str) -> SupplierQuote | None:
    """Cheapest landed cost among suppliers above the reliability floor.

    Falls back to the most reliable quote when nothing clears the floor,
    and returns None only when no supplier produced any quote at all.
    """
    quotes = quote_all(product_name)
    if not quotes:
        return None
    reliable = [q for q in quotes if q.reliability >= _MIN_RELIABILITY]
    pool = reliable if reliable else quotes
    return min(pool, key=lambda q: q.landed_cost)

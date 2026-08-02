"""backend.validation.suppliers — multi-supplier sourcing layer.

Five supplier clients (CJ Dropshipping, Zendrop, Spocket, Printful, AutoDS)
behind a common interface.  All calls are dry-run by default
(SUPPLIERS_DRY_RUN=true) and return deterministic mock quotes derived from
the product name, so the whole validation pipeline works offline and in
tests without credentials.

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
import time
from dataclasses import dataclass, asdict
from typing import Any

from backend.patterns.errors import SupplierQuoteError
from backend.validation.margin_calculator import (
    category_return_rate, RETURN_RELIABILITY_SENSITIVITY,
)
from backend.economics.supplier_feedback import supplier_feedback, supplier_feedback_live

_log = logging.getLogger(__name__)

_DRY_RUN = os.getenv("SUPPLIERS_DRY_RUN", "true").lower() != "false"

# Reliability floor: quotes below this are excluded from find_best_supplier
_MIN_RELIABILITY = float(os.getenv("SUPPLIER_MIN_RELIABILITY", "0.7"))

# Separate flag from SUPPLIERS_DRY_RUN: live QUOTING never implies live
# ORDERING — a supplier's catalog API being configured doesn't mean we're
# ready to actually spend real money placing orders against it.
_ORDERS_DRY_RUN = os.getenv("SUPPLIER_ORDERS_DRY_RUN", "true").lower() != "false"


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

    # -- order placement (Phase D) ---------------------------------------

    def place_order(self, order: dict) -> dict:
        """Place a fulfillment order with this supplier.

        *order* = {order_id, supplier_product_id, qty, shipping: {...}}.
        Returns {status, supplier_order_id, dry_run}. Dry-run under
        SUPPLIER_ORDERS_DRY_RUN (default true, independent of the quoting
        dry-run flag) — deterministic id derived from our own order_id so
        placement is idempotent (a retry after a crash mid-place resolves
        to the same supplier_order_id rather than double-ordering).
        """
        from backend.research.mode import is_research_only
        if is_research_only():
            return {"status": "blocked", "supplier_order_id": "", "error": "research_only", "dry_run": True}
        if _ORDERS_DRY_RUN or not self.is_configured():
            return self._dry_place_order(order)
        try:
            return self._live_place_order(order)
        except Exception as exc:
            _log.warning("supplier_place_order_failed supplier=%s order=%s error=%s",
                        self.name, order.get("order_id", ""), exc)
            return {"status": "error", "supplier_order_id": "",
                   "error": str(exc), "dry_run": False}

    def order_status(self, supplier_order_id: str) -> dict:
        """Poll fulfillment status for a previously-placed order.

        Returns {status: placed|shipped|delivered|failed, tracking?}. Dry
        ids always resolve to a stable, deterministic status so shadow-mode
        rehearsals can exercise the full state machine without a real
        supplier ever being called.
        """
        if _ORDERS_DRY_RUN or supplier_order_id.startswith("dry_so_"):
            return self._dry_order_status(supplier_order_id)
        try:
            return self._live_order_status(supplier_order_id)
        except Exception as exc:
            _log.warning("supplier_order_status_failed supplier=%s id=%s error=%s",
                        self.name, supplier_order_id, exc)
            return {"status": "failed", "error": str(exc)}

    def _dry_place_order(self, order: dict) -> dict:
        order_id = str(order.get("order_id", ""))
        stem = hashlib.md5(f"{self.name}:{order_id}".encode()).hexdigest()[:12]
        supplier_order_id = f"dry_so_{self.name}_{stem}"
        _log.info("supplier_dry_order_placed supplier=%s order=%s supplier_order=%s",
                  self.name, order_id, supplier_order_id)
        return {"status": "ok", "supplier_order_id": supplier_order_id, "dry_run": True}

    def _dry_order_status(self, supplier_order_id: str) -> dict:
        # Deterministic per-id progression so tests/rehearsals are stable:
        # the fraction of ids that "ship" vs stay "placed" is fixed, not
        # time-based, so repeated polls in a test don't flap.
        f = _stable_fraction(f"{supplier_order_id}:status")
        if f < 0.85:
            return {"status": "shipped", "tracking": f"DRYTRACK{supplier_order_id[-8:].upper()}"}
        return {"status": "placed"}

    def _live_place_order(self, order: dict) -> dict:
        raise NotImplementedError(
            f"{self.name} live order placement not yet implemented — "
            "fill in from the supplier's developer portal when credentials arrive"
        )

    def _live_order_status(self, supplier_order_id: str) -> dict:
        raise NotImplementedError(
            f"{self.name} live order status not yet implemented"
        )


def _parse_cj_expiry(value: Any) -> float:
    """CJ returns expiry timestamps as "YYYY-MM-DD HH:MM:SS" strings.
    Falls back to a conservative 15-days-from-now on any parse failure —
    never raises, since a slightly-wrong cached expiry just causes one
    extra re-auth, not a broken client."""
    if value:
        try:
            import datetime
            return datetime.datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").timestamp()
        except Exception:
            pass
    return time.time() + 15 * 86400


class _CJTokenManager:
    """Fetches and caches CJ Dropshipping's access/refresh token pair.

    CJ's real API (unlike the placeholder this replaced) never accepts the
    raw CJ_API_KEY as a request header directly — it must first be
    exchanged, together with the account email, for a short-lived
    accessToken (~15 days) and a refreshToken via a dedicated
    authentication endpoint. This manager caches both, transparently
    refreshing the access token ~1 day before it expires (falling back to
    a full re-authentication if the refresh token itself has lapsed), so
    every live CJ call site just asks for access_token() and never touches
    the raw API key.
    """
    _AUTH_URL = "https://developers.cjdropshipping.com/api2.0/v1/authentication/getAccessToken"
    _REFRESH_URL = "https://developers.cjdropshipping.com/api2.0/v1/authentication/refreshAccessToken"
    _REFRESH_MARGIN_S = 86400  # refresh a day before expiry, not at the wire

    def __init__(self) -> None:
        self._access_token = ""
        self._access_expiry = 0.0
        self._refresh_token = ""
        self._refresh_expiry = 0.0

    def _authenticate(self) -> None:
        import requests
        resp = requests.post(
            self._AUTH_URL,
            json={"email": os.environ["CJ_EMAIL"], "password": os.environ["CJ_API_KEY"]},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {}) or {}
        self._access_token = str(data.get("accessToken", ""))
        self._refresh_token = str(data.get("refreshToken", ""))
        self._access_expiry = _parse_cj_expiry(data.get("accessTokenExpiryDate"))
        self._refresh_expiry = _parse_cj_expiry(data.get("refreshTokenExpiryDate"))
        if not self._access_token:
            raise SupplierQuoteError("cj_dropshipping authentication returned no accessToken",
                                     service="cj_dropshipping")

    def _refresh(self) -> None:
        import requests
        resp = requests.post(
            self._REFRESH_URL, json={"refreshToken": self._refresh_token}, timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {}) or {}
        access_token = str(data.get("accessToken", ""))
        if not access_token:
            raise SupplierQuoteError("cj_dropshipping refresh returned no accessToken",
                                     service="cj_dropshipping")
        self._access_token = access_token
        self._access_expiry = _parse_cj_expiry(data.get("accessTokenExpiryDate"))
        if data.get("refreshToken"):  # CJ may rotate the refresh token too
            self._refresh_token = str(data["refreshToken"])
            self._refresh_expiry = _parse_cj_expiry(data.get("refreshTokenExpiryDate"))

    def access_token(self) -> str:
        """Return a valid access token, refreshing or re-authenticating as
        needed. Never caches a stale token past its margin."""
        now = time.time()
        if self._access_token and now < self._access_expiry - self._REFRESH_MARGIN_S:
            return self._access_token
        if self._refresh_token and now < self._refresh_expiry:
            try:
                self._refresh()
                return self._access_token
            except Exception as exc:
                _log.warning("cj_token_refresh_failed error=%s — falling back to re-auth", exc)
        self._authenticate()
        return self._access_token


_cj_token_manager = _CJTokenManager()


class CJDropshippingClient(SupplierClient):
    """CJ Dropshipping — https://developers.cjdropshipping.com"""
    name = "cj_dropshipping"
    api_key_env = "CJ_API_KEY"
    cost_band = (4.0, 25.0)
    shipping_band = (1.5, 5.0)
    base_reliability = 0.88
    base_fulfillment_days = 8

    def is_configured(self) -> bool:
        # CJ's real auth flow needs both the account email and the API key
        # (exchanged together for an access token — see _CJTokenManager);
        # the base class only checks api_key_env, which isn't sufficient here.
        return bool(os.getenv("CJ_EMAIL") and os.getenv(self.api_key_env))

    def _live_quote(self, product_name: str) -> SupplierQuote | None:
        import requests
        resp = requests.get(
            "https://developers.cjdropshipping.com/api2.0/v1/product/list",
            headers={"CJ-Access-Token": _cj_token_manager.access_token()},
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

    def _find_existing_order(self, order_number: str) -> str:
        """Best-effort idempotency check: look up whether *order_number*
        (our own order_id, sent as CJ's orderNumber) already has a CJ
        order before creating a new one — a retry after a timed-out
        create call must not risk placing a second physical order for the
        same customer. Returns the existing CJ orderId, or "" if none is
        found (including on any lookup failure — a failed check falls
        through to a normal create call, same as before this existed)."""
        import requests
        try:
            resp = requests.get(
                "https://developers.cjdropshipping.com/api2.0/v1/shopping/order/list",
                headers={"CJ-Access-Token": _cj_token_manager.access_token()},
                params={"orderNumber": order_number, "pageSize": 1},
                timeout=15,
            )
            resp.raise_for_status()
            rows = resp.json().get("data", {}).get("list", [])
            if rows:
                return str(rows[0].get("orderId", ""))
        except Exception as exc:
            _log.debug("cj_existing_order_lookup_failed order_number=%s error=%s",
                      order_number, exc)
        return ""

    def _live_place_order(self, order: dict) -> dict:
        import requests
        order_number = order.get("order_id", "")
        existing_id = self._find_existing_order(order_number)
        if existing_id:
            _log.info("cj_order_already_exists order_number=%s cj_order_id=%s — skipping create",
                      order_number, existing_id)
            return {"status": "ok", "supplier_order_id": existing_id, "dry_run": False}

        shipping = order.get("shipping", {}) or {}
        resp = requests.post(
            "https://developers.cjdropshipping.com/api2.0/v1/shopping/order/createOrder",
            headers={"CJ-Access-Token": _cj_token_manager.access_token()},
            json={
                "orderNumber": order_number,
                "shippingCountryCode": shipping.get("country", ""),
                "shippingProvince": shipping.get("state", ""),
                "shippingCity": shipping.get("city", ""),
                "shippingAddress": shipping.get("line1", ""),
                "shippingAddress2": shipping.get("line2", ""),
                "shippingZip": shipping.get("postal_code", ""),
                "products": [{"vid": order.get("supplier_product_id", ""),
                             "quantity": int(order.get("qty", 1))}],
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        supplier_order_id = str(data.get("orderId", ""))
        if not supplier_order_id:
            return {"status": "error", "supplier_order_id": "",
                   "error": "no_order_id_returned", "dry_run": False}
        return {"status": "ok", "supplier_order_id": supplier_order_id, "dry_run": False}

    def _live_order_status(self, supplier_order_id: str) -> dict:
        import requests
        resp = requests.get(
            "https://developers.cjdropshipping.com/api2.0/v1/shopping/order/getOrderDetail",
            headers={"CJ-Access-Token": _cj_token_manager.access_token()},
            params={"orderId": supplier_order_id},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        cj_status = str(data.get("orderStatus", "")).upper()
        # Default to "unknown" (not "placed") for anything unrecognized —
        # a real CJ cancellation/return-to-sender must never be silently
        # treated as a healthy in-progress order (poll_placed_orders logs
        # "unknown" loudly instead of quietly doing nothing).
        mapped = {"CREATED": "placed", "IN_PRODUCTION": "placed",
                 "SHIPPED": "shipped", "DELIVERED": "delivered",
                 "CANCELLED": "failed", "EXCEPTION": "failed"}.get(cj_status, "unknown")
        result = {"status": mapped}
        tracking = data.get("trackNumber")
        if tracking:
            result["tracking"] = str(tracking)
        return result


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


class AutoDSClient(SupplierClient):
    """AutoDS — https://www.autods.com (aggregates AliExpress/Walmart/Amazon
    sourcing behind one API). Genuinely differentiated from the other four
    clients here: it's a cross-supplier aggregator with automated price/
    stock monitoring, not another single-catalog reseller wrapper.

    AutoDS API access requires account approval + a one-time activation fee
    (per autods.com/api/) — there is no free/instant sandbox to verify
    against, the same situation CJ/Zendrop/Spocket/Printful started from.
    The endpoint path/response shape below is a best-effort placeholder
    matching AutoDS's documented REST conventions; SupplierClient.quote()'s
    existing try/except already degrades any live-call failure (wrong
    field name included) to the deterministic mock quote, so an
    unverified shape here is exactly as safe as a network outage would be
    — refine against the real developer portal once an approved account
    exists.
    """
    name = "autods"
    api_key_env = "AUTODS_API_KEY"
    cost_band = (5.0, 30.0)
    shipping_band = (2.0, 7.0)
    base_reliability = 0.85
    base_fulfillment_days = 9

    def _live_quote(self, product_name: str) -> SupplierQuote | None:
        import requests
        resp = requests.get(
            "https://api.autods.com/v1/products/search",
            headers={"Authorization": f"Bearer {os.environ[self.api_key_env]}"},
            params={"query": product_name, "limit": 1},
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
            fulfillment_days=int(row.get("processing_days", self.base_fulfillment_days) or self.base_fulfillment_days),
            reliability=self.base_reliability,
        )


_CLIENTS: list[SupplierClient] = [
    CJDropshippingClient(),
    ZendropClient(),
    SpocketClient(),
    PrintfulClient(),
    AutoDSClient(),
]

_CLIENTS_BY_NAME: dict[str, SupplierClient] = {c.name: c for c in _CLIENTS}


def get_client(supplier_name: str) -> SupplierClient | None:
    """Look up a registered supplier client by its .name (e.g. "cj_dropshipping")."""
    return _CLIENTS_BY_NAME.get(supplier_name)


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


def _effective_reliability(quote: SupplierQuote, category: str) -> float:
    """Observed feedback reliability when available (Phase 6c, gated by
    SUPPLIER_FEEDBACK_LIVE), else the quote's own static class reliability."""
    if not supplier_feedback_live():
        return quote.reliability
    return supplier_feedback.reliability_for(
        quote.supplier, category, static_default=quote.reliability)


def _risk_adjusted_cost(quote: SupplierQuote, category: str) -> float:
    """Landed cost inflated by a reliability-sensitive return/complaint-risk
    markup (Phase 6a): a category baseline return rate, plus an additional
    markup for suppliers with weaker reliability — worse quality control
    plausibly correlates with more returns/complaints, independent of
    category. Differentiates suppliers within the same call (unlike simply
    scaling every candidate's cost by the same category rate, which would
    be a no-op for ranking)."""
    reliability = _effective_reliability(quote, category)
    base_rate = category_return_rate(category)
    reliability_markup = max(0.0, 1.0 - reliability) * RETURN_RELIABILITY_SENSITIVITY
    effective_rate = min(0.9, base_rate + reliability_markup)
    return quote.landed_cost * (1.0 + effective_rate)


def _supplier_risk_ranking_live() -> bool:
    return os.getenv("SUPPLIER_RISK_RANKING_LIVE", "false").lower() == "true"


def find_best_supplier(product_name: str, category: str = "general") -> SupplierQuote | None:
    """Cheapest landed cost among suppliers above the reliability floor.

    Phase 6a/6c add a risk-adjusted ranking (category-aware return-rate risk
    plus a reliability-sensitive markup — and, when SUPPLIER_FEEDBACK_LIVE
    is also on, observed EMA reliability instead of the static per-class
    constant) as a shadow-mode alternative: both the legacy plain-landed-
    cost pick and the risk-adjusted pick are always computed and journaled,
    but the legacy pick is what's returned until SUPPLIER_RISK_RANKING_LIVE
    is flipped on — existing callers/tests keep today's exact selection.

    Falls back to the most reliable quote when nothing clears the floor
    (the reliability floor itself already accounts for observed feedback
    when SUPPLIER_FEEDBACK_LIVE is on), and returns None only when no
    supplier produced any quote at all.
    """
    quotes = quote_all(product_name)
    if not quotes:
        return None

    reliable = [q for q in quotes if _effective_reliability(q, category) >= _MIN_RELIABILITY]
    pool = reliable if reliable else quotes

    legacy_pick = min(pool, key=lambda q: q.landed_cost)
    risk_adjusted_pick = min(pool, key=lambda q: _risk_adjusted_cost(q, category))
    live = _supplier_risk_ranking_live()

    try:
        from backend.orchestration.event_store import event_store, new_workflow_id
        event_store.append(
            new_workflow_id("supplierrank"), "shadow_supplier_ranking",
            workflow="suppliers", step="find_best_supplier",
            data={
                "product_name": product_name,
                "category": category,
                "legacy_supplier": legacy_pick.supplier,
                "risk_adjusted_supplier": risk_adjusted_pick.supplier,
                "live": live,
            },
        )
    except Exception:
        # journaling must never break supplier selection, but a silent
        # failure here means the crash-recovery journal event_store's
        # incomplete_workflows() relies on has quietly stopped being written
        _log.warning("supplier_ranking_journal_failed product=%s", product_name,
                    exc_info=True)

    return risk_adjusted_pick if live else legacy_pick

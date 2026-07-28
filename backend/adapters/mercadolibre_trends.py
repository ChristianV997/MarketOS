"""backend.adapters.mercadolibre_trends — MercadoLibre product signal adapter.

Uses MercadoLibre's genuine free, public, unauthenticated REST API
(no API key needed for catalog search — only OAuth is required for
seller-specific actions, which this adapter never touches):

    https://api.mercadolibre.com/sites/{site_id}/search?q={query}

MercadoLibre has no dedicated "trending"/"bestsellers" endpoint, only
search — so this adapter uses `sold_quantity` on a curated set of seed
category queries as a popularity proxy, the same design choice
`amazon_bestsellers.py` makes by scraping a fixed category list rather
than a single global feed.

Registers itself with the SignalEngine as "mercadolibre".
"""
from __future__ import annotations

import logging
import math
import os
import time
from typing import Any

_log = logging.getLogger(__name__)

_CACHE: list[dict] = []
_CACHE_TS: float = 0.0
_CACHE_TTL = 3600  # 1 hour — catalog popularity doesn't churn as fast as social trends

_SITES = os.getenv("MERCADOLIBRE_SITES", "MLA,MLM,MLB").split(",")
_QUERIES = os.getenv(
    "MERCADOLIBRE_QUERIES",
    "electronica,hogar,belleza,deportes,mascotas,bebes",
).split(",")

_ENDPOINT = "https://api.mercadolibre.com/sites/{site_id}/search"
_REQUEST_LIMIT = 20
_TIMEOUT_S = 8

# log-scale normaliser cap (items with ~5k units sold score ~= 1.0)
_LOG_CAP = math.log(5_000 + 1)


def _fetch_site_query(site_id: str, query: str) -> list[dict]:
    """Fetch one (site, query) page of search results. Raises on HTTP/network error."""
    import requests
    url = _ENDPOINT.format(site_id=site_id)
    resp = requests.get(url, params={"q": query, "limit": _REQUEST_LIMIT}, timeout=_TIMEOUT_S)
    resp.raise_for_status()
    return resp.json().get("results", [])


def _item_to_signal(item: dict, site_id: str) -> dict | None:
    """Map one MercadoLibre catalog item to a SignalEngine-compatible signal."""
    title = str(item.get("title", "")).strip()
    if not title:
        return None

    price = float(item.get("price", 0.0) or 0.0)
    sold_quantity = int(item.get("sold_quantity", 0) or 0)
    available_quantity = int(item.get("available_quantity", 0) or 0)

    score = min(1.0, math.log(sold_quantity + 1) / _LOG_CAP)
    # Velocity proxy: how much of available stock has already sold (0-1);
    # default 0.5 when available_quantity is unknown/zero (avoid div-by-zero).
    velocity = (
        min(1.0, sold_quantity / available_quantity)
        if available_quantity > 0 else 0.5
    )

    return {
        "product": title[:120],
        "score": round(score, 4),
        "velocity": round(velocity, 4),
        "source": "mercadolibre",
        "platform": "mercadolibre",
        "market": site_id,
        "price": price,
        "permalink": item.get("permalink", ""),
        "category": item.get("category_id", ""),
    }


def fetch() -> list[dict]:
    """Return MercadoLibre catalog-popularity signals; cached for 1 hour.

    Never raises: each (site, query) pair is fetched independently and a
    failure on one never drops the others. Returns [] only if every pair
    fails.
    """
    global _CACHE, _CACHE_TS
    if _CACHE and (time.time() - _CACHE_TS) < _CACHE_TTL:
        return _CACHE

    signals: list[dict] = []
    for site_id in (s.strip() for s in _SITES if s.strip()):
        for query in (q.strip() for q in _QUERIES if q.strip()):
            try:
                items = _fetch_site_query(site_id, query)
                for item in items:
                    signal = _item_to_signal(item, site_id)
                    if signal:
                        signals.append(signal)
                _log.info("mercadolibre_adapter_ok site=%s query=%s items=%d",
                          site_id, query, len(items))
            except Exception as exc:
                _log.warning("mercadolibre_adapter_failed site=%s query=%s error=%s",
                             site_id, query, exc)

    if signals:
        _CACHE = signals
        _CACHE_TS = time.time()
        _log.info("mercadolibre_signals_fetched count=%d", len(signals))
    return signals


def register(signal_engine: Any) -> None:
    """Register this adapter with the provided SignalEngine instance."""
    signal_engine.register_source("mercadolibre", fetch)
    try:
        from backend.discovery.registry import discovery_registry
        discovery_registry.register("mercadolibre", credential_env_vars=[], requires_auth=False)
    except Exception:
        pass
    _log.info("mercadolibre_adapter_registered sites=%s", _SITES)

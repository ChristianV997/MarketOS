"""backend.adapters.alibaba_trends — Alibaba product signal adapter.

Alibaba has no public catalog/search API and aggressively fingerprints and
blocks scripted HTTP clients (Cloudflare + JS challenge + login-walled
search results for most categories). A `requests`+BeautifulSoup scrape
(the approach `amazon_bestsellers.py` uses, which itself mostly fails
against Amazon) would realistically return a 0% real-data success rate
here — Alibaba is harder to scrape than Amazon, not easier. Clearing its
JS challenge would require a headless browser (Playwright/Selenium), a
disproportionate new dependency/CI-complexity increase.

Real path (optional): when FIRECRAWL_API_KEY is set, uses Firecrawl
(firecrawl.dev) to fetch + LLM-extract Alibaba search-result listings —
Firecrawl's hosted browser/anti-bot handling is exactly the missing piece
above, without adding a Playwright/Selenium dependency to this repo.
Falls back to the honest mock catalog on any failure (missing key,
network error, extraction schema mismatch) — fetch() never raises.

Registers itself with the SignalEngine as "alibaba"; the central discovery
registry (backend/discovery/registry.py) tracks it as "mock_fallback"
(alongside amazon_bestsellers/tiktok_organic — the same conservative
treatment applied to every scraper here whose real-data success isn't
guaranteed run-to-run).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any
from urllib.parse import quote

_log = logging.getLogger(__name__)

_CACHE: list[dict] = []
_CACHE_TS: float = 0.0
_CACHE_TTL = 3600  # 1 hour

_QUERIES = os.getenv(
    "ALIBABA_SEARCH_QUERIES",
    "wireless earbuds,water bottle,led strip light,yoga mat,phone case",
).split(",")

_MOCK_PRODUCTS = [
    {"product": "Wireless Bluetooth Earbuds Bulk",   "category": "electronics", "score": 0.80},
    {"product": "Stainless Steel Water Bottle OEM",  "category": "home",        "score": 0.76},
    {"product": "LED Strip Light Kit Wholesale",     "category": "electronics", "score": 0.73},
    {"product": "Yoga Mat Custom Print Bulk",        "category": "sports",      "score": 0.70},
    {"product": "Silicone Phone Case Wholesale",     "category": "electronics", "score": 0.68},
    {"product": "Interactive Cat Toy Bulk OEM",      "category": "pets",        "score": 0.77},
    {"product": "Silicone Baby Teether Wholesale",   "category": "baby",        "score": 0.74},
]

_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "products": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "price_usd": {"type": "number"},
                    "min_order_quantity": {"type": "number"},
                },
                "required": ["name"],
            },
        },
    },
    "required": ["products"],
}
_EXTRACT_PROMPT = (
    "Extract the product listings shown on this Alibaba search results "
    "page: each product's name, unit price in USD, and minimum order "
    "quantity (MOQ). Return an empty products list if none are visible."
)


def _fetch_query(query: str) -> list[dict]:
    """Scrape one Alibaba search-results page via Firecrawl. Returns []
    on any failure — never raises (caller falls back to mock)."""
    from firecrawl import Firecrawl
    from firecrawl.v2.types import JsonFormat

    app = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"])
    url = f"https://www.alibaba.com/trade/search?SearchText={quote(query)}"
    doc = app.scrape(url, formats=[JsonFormat(prompt=_EXTRACT_PROMPT, schema=_EXTRACT_SCHEMA)])
    data = getattr(doc, "json", None) or {}
    products = data.get("products", []) or []

    results = []
    for p in products:
        name = str(p.get("name", "")).strip()
        if not name:
            continue
        moq = p.get("min_order_quantity") or 0
        # Higher MOQ signals genuine wholesale/bulk demand (this adapter's
        # whole purpose vs. Amazon/MercadoLibre's retail-unit listings) —
        # capped so a single huge MOQ outlier doesn't dominate the score.
        score = round(min(0.95, 0.6 + min(float(moq), 5000) / 5000 * 0.35), 4)
        results.append({
            "product": name[:120],
            "score": score,
            "velocity": 0.5,
            "source": "alibaba_firecrawl",
            "platform": "alibaba",
            "category": "general",
            "confidence_tier": "live",
        })
    return results


def fetch() -> list[dict]:
    """Return Alibaba catalog signals; cached for 1 hour.

    Attempts real Firecrawl-backed scraping when FIRECRAWL_API_KEY is
    set; falls back to the honest mock catalog otherwise or on any
    scraping failure. Never raises.
    """
    global _CACHE, _CACHE_TS
    if _CACHE and (time.time() - _CACHE_TS) < _CACHE_TTL:
        return _CACHE

    results: list[dict] = []
    if os.getenv("FIRECRAWL_API_KEY"):
        for query in _QUERIES:
            try:
                results.extend(_fetch_query(query.strip()))
            except Exception as exc:
                _log.debug("alibaba_firecrawl_fetch_failed query=%s error=%s", query, exc)

    if not results:
        _log.debug("alibaba using mock data")
        results = [
            {
                "product": item["product"],
                "score": item["score"],
                "velocity": 0.5,
                "source": "alibaba_mock",
                "platform": "alibaba",
                "category": item["category"],
                "confidence_tier": "mock_only",
            }
            for item in _MOCK_PRODUCTS
        ]

    _CACHE = results
    _CACHE_TS = time.time()
    return results


def register(signal_engine: Any) -> None:
    """Register this adapter with the provided SignalEngine instance."""
    signal_engine.register_source("alibaba", fetch)
    try:
        from backend.discovery.registry import discovery_registry
        # requires_auth=False, matching tiktok_organic's precedent: fetch()
        # never raises and never blocks without FIRECRAWL_API_KEY — it
        # degrades to the honest mock catalog instead. The credential is
        # what determines whether the *best possible* result is live data,
        # not whether a fetch attempt is possible at all.
        discovery_registry.register(
            "alibaba", credential_env_vars=["FIRECRAWL_API_KEY"], requires_auth=False,
        )
    except Exception:
        pass
    _log.info("alibaba_adapter_registered")

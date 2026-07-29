"""backend.adapters.amazon_bestsellers — Amazon Best Sellers signal adapter.

Scrapes Amazon Best Sellers pages for category top-sellers.
Falls back to mock data when network is unavailable or blocked.

Registers itself with the SignalEngine as "amazon_bestsellers".
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

_log = logging.getLogger(__name__)

_CACHE: list[dict] = []
_CACHE_TS: float = 0.0
_CACHE_TTL = 3600  # 1 hour

_CATEGORIES = os.getenv(
    "AMAZON_BESTSELLER_CATEGORIES",
    "beauty,electronics,home-kitchen,sports-outdoors,toys-games,pet-supplies,baby-products",
).split(",")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_MOCK_PRODUCTS = [
    {"product": "Wireless Earbuds Pro",    "category": "electronics",     "rank": 1, "score": 0.95},
    {"product": "Vitamin D3 5000 IU",      "category": "health",          "rank": 2, "score": 0.92},
    {"product": "Air Fryer XL 5.8QT",      "category": "home-kitchen",    "rank": 3, "score": 0.88},
    {"product": "Resistance Bands Set",    "category": "sports-outdoors", "rank": 4, "score": 0.85},
    {"product": "LED Strip Lights",        "category": "home-kitchen",    "rank": 5, "score": 0.82},
    {"product": "Portable Charger 20000",  "category": "electronics",     "rank": 6, "score": 0.80},
    {"product": "Collagen Peptides",       "category": "health",          "rank": 7, "score": 0.78},
    {"product": "Yoga Mat Non Slip",       "category": "sports-outdoors", "rank": 8, "score": 0.75},
    {"product": "Automatic Pet Feeder",       "category": "pet-supplies",   "rank": 1, "score": 0.90},
    {"product": "Dog Puzzle Slow Feeder Bowl", "category": "pet-supplies",  "rank": 2, "score": 0.86},
    {"product": "Pet Grooming Deshedding Glove", "category": "pet-supplies", "rank": 3, "score": 0.83},
    {"product": "Silicone Baby Feeding Set",  "category": "baby-products", "rank": 1, "score": 0.89},
    {"product": "Baby Bath Toy Set",          "category": "baby-products", "rank": 2, "score": 0.84},
]


def _parse_page(html: str, category: str) -> list[dict]:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        items = []
        for i, el in enumerate(soup.select(".zg-item-immersion")[:10], start=1):
            title_el = el.select_one(".p13n-sc-truncate") or el.select_one("._cDEzb_p13n-sc-css-line-clamp-3_g3dy1")
            if title_el:
                title = title_el.get_text(strip=True)[:120]
                items.append({
                    "product":  title,
                    "category": category,
                    "rank":     i,
                    "score":    round(max(0.1, 1.0 - i * 0.08), 2),
                    "source":   "amazon_bestsellers",
                    "platform": "amazon",
                })
        return items
    except Exception:
        return []


def _fetch_category(category: str) -> list[dict]:
    try:
        import requests
        url = f"https://www.amazon.com/Best-Sellers/{category}/zgbs/"
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        if resp.status_code == 200:
            return _parse_page(resp.text, category)
    except Exception as exc:
        _log.debug("amazon_fetch_failed category=%s error=%s", category, exc)
    return []


def fetch() -> list[dict]:
    """Return Amazon best-seller signals; cached for 1 hour."""
    global _CACHE, _CACHE_TS
    if _CACHE and (time.time() - _CACHE_TS) < _CACHE_TTL:
        return _CACHE

    results: list[dict] = []
    for cat in _CATEGORIES:
        results.extend(_fetch_category(cat.strip()))
        time.sleep(0.5)  # polite crawl rate

    if not results:
        _log.debug("amazon_bestsellers using mock data")
        results = [dict(r, source="amazon_bestsellers_mock") for r in _MOCK_PRODUCTS]

    _CACHE = results
    _CACHE_TS = time.time()
    return results


def register(signal_engine: Any) -> None:
    """Register this adapter with the provided SignalEngine instance."""
    signal_engine.register_source("amazon_bestsellers", fetch)
    try:
        from backend.discovery.registry import discovery_registry
        discovery_registry.register("amazon_bestsellers", credential_env_vars=[], requires_auth=False)
    except Exception:
        pass
    _log.info("amazon_bestsellers adapter registered")

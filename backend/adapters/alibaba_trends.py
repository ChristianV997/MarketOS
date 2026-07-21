"""backend.adapters.alibaba_trends — Alibaba product signal adapter (mock-only).

Alibaba has no public catalog/search API and aggressively fingerprints and
blocks scripted HTTP clients (Cloudflare + JS challenge + login-walled
search results for most categories). A `requests`+BeautifulSoup scrape
(the approach `amazon_bestsellers.py` uses, which itself mostly fails
against Amazon) would realistically return a 0% real-data success rate
here — Alibaba is harder to scrape than Amazon, not easier. Clearing its
JS challenge would require a headless browser (Playwright/Selenium), a
disproportionate new dependency/CI-complexity increase for a
discovery-consolidation pass.

This adapter is therefore **intentionally mock-only** — it exists so
Alibaba appears in the source list (never silently omitted) with an
honest status, rather than being scraped unreliably and passed off as
real. A future real implementation (headless-browser scraping) is a
drop-in swap of `fetch()`'s body; the signal shape and `register()`
contract stay the same.

Registers itself with the SignalEngine as "alibaba"; the central
discovery registry (backend/discovery/registry.py) marks this source's
status as "mock_only", never "live".
"""
from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)

_MOCK_PRODUCTS = [
    {"product": "Wireless Bluetooth Earbuds Bulk",   "category": "electronics", "score": 0.80},
    {"product": "Stainless Steel Water Bottle OEM",  "category": "home",        "score": 0.76},
    {"product": "LED Strip Light Kit Wholesale",     "category": "electronics", "score": 0.73},
    {"product": "Yoga Mat Custom Print Bulk",        "category": "sports",      "score": 0.70},
    {"product": "Silicone Phone Case Wholesale",     "category": "electronics", "score": 0.68},
]


def fetch() -> list[dict]:
    """Return mock Alibaba catalog signals. No network call — see module docstring."""
    return [
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


def register(signal_engine: Any) -> None:
    """Register this adapter with the provided SignalEngine instance."""
    signal_engine.register_source("alibaba", fetch)
    try:
        from backend.discovery.registry import discovery_registry
        discovery_registry.register("alibaba", credential_env_vars=[], requires_auth=False)
    except Exception:
        pass
    _log.info("alibaba_adapter_registered status=mock_only")

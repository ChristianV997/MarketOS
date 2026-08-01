"""Bridge optional OSS providers into the canonical commerce loop.

This module deliberately owns no ranking or execution logic. It only turns
provider records into the existing signal/product/offer inputs and degrades to
an empty batch when an optional service is unavailable.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Mapping, Sequence

from backend.contracts.adapters import SidecarContext
from backend.integrations.medusa import MedusaCommerceAdapter
from backend.adapters.research.crawl4ai import Crawl4AIResearchAdapter

try:
    from prometheus_client import Counter, Histogram
    _oss_cache_hits = Counter("marketos_oss_provider_cache_hits_total", "OSS provider cache hits", ["provider"])
    _oss_refreshes = Counter("marketos_oss_provider_refreshes_total", "OSS provider refreshes", ["provider"])
    _oss_failures = Counter("marketos_oss_provider_failures_total", "OSS provider failures", ["provider"])
    _oss_refresh_duration = Histogram("marketos_oss_provider_refresh_duration_seconds", "OSS provider refresh duration", ["provider"])
except ImportError:  # pragma: no cover
    _oss_cache_hits = _oss_refreshes = _oss_failures = _oss_refresh_duration = None

_research_cache: dict[tuple[str, bool], tuple[float, list[dict[str, Any]]]] = {}


def clear_oss_cache() -> None:
    _research_cache.clear()


def _retryable(exc: Exception) -> bool:
    """Classify transport failures without retrying unsafe requests."""
    if isinstance(exc, (PermissionError, ValueError, TypeError)):
        return False
    return isinstance(exc, (TimeoutError, ConnectionError, OSError)) or exc.__class__.__name__ in {
        "ConnectError", "ReadTimeout", "RemoteProtocolError", "HTTPStatusError",
    }


async def _discover_with_retry(research: Any, url: str, *, context: SidecarContext) -> list[dict[str, Any]]:
    retries = max(0, min(int(os.getenv("MARKETOS_OSS_MAX_RETRIES", "2")), 5))
    backoff_s = max(0.0, float(os.getenv("MARKETOS_OSS_RETRY_BACKOFF_S", "0.25")))
    for attempt in range(retries + 1):
        try:
            return list(await research.discover(url, context=context))
        except Exception as exc:
            if attempt >= retries or not _retryable(exc):
                raise
            await asyncio.sleep(backoff_s * (2 ** attempt))


async def _collect_research_records(
    urls: Sequence[str],
    *,
    research: Any,
    context: SidecarContext,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    """Fetch uncached research URLs concurrently with a strict upper bound."""
    provider_name = getattr(research, "name", "research")
    ttl_s = max(0.0, float(os.getenv("MARKETOS_OSS_CACHE_TTL_S", "300")))
    max_concurrency = max(1, min(int(os.getenv("MARKETOS_OSS_MAX_CONCURRENCY", "4")), 20))
    records_by_url: dict[str, list[dict[str, Any]]] = {}
    failures: dict[str, str] = {}
    pending: list[str] = []
    now = time.monotonic()
    for url in dict.fromkeys(urls):
        cache_key = (url, bool(context.dry_run))
        cached = _research_cache.get(cache_key)
        if cached and now - cached[0] < ttl_s:
            records_by_url[url] = list(cached[1])
            if _oss_cache_hits is not None:
                _oss_cache_hits.labels(provider=provider_name).inc()
        else:
            pending.append(url)

    semaphore = asyncio.Semaphore(max_concurrency)

    async def fetch(url: str) -> tuple[str, list[dict[str, Any]] | None, str | None, float]:
        started = time.monotonic()
        try:
            async with semaphore:
                records = await _discover_with_retry(research, url, context=context)
            return url, records, None, time.monotonic() - started
        except Exception as exc:
            return url, None, str(exc), time.monotonic() - started

    for url, records, error, duration in await asyncio.gather(*(fetch(url) for url in pending)):
        if records is not None:
            _research_cache[(url, bool(context.dry_run))] = (time.monotonic(), list(records))
            records_by_url[url] = records
            if _oss_refreshes is not None:
                _oss_refreshes.labels(provider=provider_name).inc()
                _oss_refresh_duration.labels(provider=provider_name).observe(duration)
        else:
            if _oss_failures is not None:
                _oss_failures.labels(provider=provider_name).inc()
            failures[f"research:{url}"] = error or "unknown research failure"
    return records_by_url, failures


def _research_signal(record: Mapping[str, Any]) -> dict[str, Any] | None:
    name = str(record.get("name") or record.get("product_name") or "").strip()
    if not name:
        return None
    quality = dict(record.get("quality") or {})
    source_ref = str(record.get("url") or record.get("source_ref") or "")
    if quality.get("provenance") == "live" and source_ref:
        quality.setdefault("attribution", "attributed")
        quality.setdefault("source_ref", source_ref)
    signal = {
        "signal_id": str(record.get("signal_id") or record.get("url") or name),
        "product_id": str(record.get("product_id") or name),
        "product": name,
        "raw_text": str(record.get("content") or record.get("description") or name),
        "source": str(record.get("source") or "oss_research"),
        "score": float(record.get("score", 0.0) or 0.0),
        "quality": quality,
        "metadata": {
            "source_ref": source_ref,
            "currency": str(record.get("currency") or "USD").upper(),
        },
    }
    for field in ("selling_price", "price", "unit_cost", "shipping_cost", "fulfillment_days", "inventory_units"):
        if field in record:
            signal[field] = record[field]
    return signal


def collect_oss_inputs(
    urls: Sequence[str],
    *,
    research: Crawl4AIResearchAdapter | None = None,
    commerce: MedusaCommerceAdapter | None = None,
    context: SidecarContext | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Collect optional provider data as canonical loop inputs.

    Provider failures are returned as metadata and never become live evidence.
    The caller can merge the signal batch with existing signals and retain the
    current MarketOS ranking/execution path.
    """
    context = context or SidecarContext(dry_run=True)
    research = research or Crawl4AIResearchAdapter()
    commerce = commerce or MedusaCommerceAdapter()
    signals: list[dict[str, Any]] = []
    research_products: dict[str, Any] = {}
    research_offers: dict[str, Any] = {}
    records_by_url, failures = asyncio.run(_collect_research_records(tuple(urls), research=research, context=context))
    for url in dict.fromkeys(urls):
        records = records_by_url.get(url, [])
        signals.extend(filter(None, (_research_signal(record) for record in records)))
        normalizer = getattr(research, "normalize_candidates", None)
        if callable(normalizer):
            for candidate in normalizer(records):
                research_products[candidate.product_id] = candidate
        offer_normalizer = getattr(research, "normalize_supplier_offers", None)
        if callable(offer_normalizer):
            for offer in offer_normalizer(records):
                research_offers.setdefault(offer.product_id, offer)

    # Research facts make the candidate usable even without Medusa. When the
    # commerce sidecar is live, its catalog remains the source of truth for
    # matching IDs/prices and replaces any same-ID external observation.
    products: dict[str, Any] = dict(research_products)
    offers: dict[str, Any] = dict(research_offers)
    if commerce.configured:
        try:
            rows = commerce.list_products()
            medusa_products = {candidate.product_id: candidate for candidate in commerce.normalize_products(rows)}
            products.update(medusa_products)
            if medusa_products:
                if hasattr(commerce, "get_offers"):
                    normalized_offers = commerce.get_offers(tuple(medusa_products))
                else:
                    inventory = commerce.get_inventory(tuple(medusa_products))
                    normalized_offers = commerce.normalize_inventory(inventory)
                for offer in normalized_offers:
                    existing = offers.get(offer.product_id)
                    # A zero cost in Medusa means "not configured", so do not
                    # erase a source-attributed supplier cost with an unknown.
                    if existing is None or offer.unit_cost > 0 or existing.unit_cost <= 0:
                        offers[offer.product_id] = offer
        except Exception as exc:
            if _oss_failures is not None:
                _oss_failures.labels(provider=getattr(commerce, "name", "commerce")).inc()
            failures["commerce"] = str(exc)
    return signals, products, {
        "offers": offers,
        "failures": failures,
        "research_products": len(research_products),
        "research_offers": len(research_offers),
    }

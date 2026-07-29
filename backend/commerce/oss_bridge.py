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
        "metadata": {"source_ref": source_ref},
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
    failures: dict[str, Any] = {}
    for url in urls:
        provider_name = getattr(research, "name", "research")
        ttl_s = max(0.0, float(os.getenv("MARKETOS_OSS_CACHE_TTL_S", "300")))
        cache_key = (url, bool(context.dry_run))
        cached = _research_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < ttl_s:
            records = cached[1]
            if _oss_cache_hits is not None:
                _oss_cache_hits.labels(provider=provider_name).inc()
            signals.extend(filter(None, (_research_signal(record) for record in records)))
            continue
        started = time.monotonic()
        try:
            records = asyncio.run(_discover_with_retry(research, url, context=context))
            _research_cache[cache_key] = (time.monotonic(), list(records))
            if _oss_refreshes is not None:
                _oss_refreshes.labels(provider=provider_name).inc()
                _oss_refresh_duration.labels(provider=provider_name).observe(time.monotonic() - started)
            signals.extend(filter(None, (_research_signal(record) for record in records)))
        except Exception as exc:
            if _oss_failures is not None:
                _oss_failures.labels(provider=provider_name).inc()
            failures[f"research:{url}"] = str(exc)

    products: dict[str, Any] = {}
    offers: dict[str, Any] = {}
    if commerce.configured:
        try:
            rows = commerce.list_products()
            products = {candidate.product_id: candidate for candidate in commerce.normalize_products(rows)}
            if products:
                inventory = commerce.get_inventory(tuple(products))
                offers = {offer.product_id: offer for offer in commerce.normalize_inventory(inventory)}
        except Exception as exc:
            if _oss_failures is not None:
                _oss_failures.labels(provider=getattr(commerce, "name", "commerce")).inc()
            failures["commerce"] = str(exc)
    return signals, products, {"offers": offers, "failures": failures}

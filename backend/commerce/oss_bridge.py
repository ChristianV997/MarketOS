"""Bridge optional OSS providers into the canonical commerce loop.

This module deliberately owns no ranking or execution logic. It only turns
provider records into the existing signal/product/offer inputs and degrades to
an empty batch when an optional service is unavailable.
"""
from __future__ import annotations

import asyncio
from typing import Any, Mapping, Sequence

from backend.contracts.adapters import SidecarContext
from backend.integrations.medusa import MedusaCommerceAdapter
from backend.adapters.research.crawl4ai import Crawl4AIResearchAdapter


def _research_signal(record: Mapping[str, Any]) -> dict[str, Any] | None:
    name = str(record.get("name") or record.get("product_name") or "").strip()
    if not name:
        return None
    quality = dict(record.get("quality") or {})
    return {
        "signal_id": str(record.get("signal_id") or record.get("url") or name),
        "product_id": str(record.get("product_id") or name),
        "product": name,
        "raw_text": str(record.get("content") or record.get("description") or name),
        "source": str(record.get("source") or "oss_research"),
        "score": float(record.get("score", 0.0) or 0.0),
        "quality": quality,
        "metadata": {"source_ref": record.get("url") or record.get("source_ref", "")},
    }


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
        try:
            records = asyncio.run(research.discover(url, context=context))
            signals.extend(filter(None, (_research_signal(record) for record in records)))
        except Exception as exc:
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
            failures["commerce"] = str(exc)
    return signals, products, {"offers": offers, "failures": failures}

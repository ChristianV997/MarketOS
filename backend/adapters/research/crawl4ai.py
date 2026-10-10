"""Optional Crawl4AI research adapter.

The dependency is intentionally lazy so the MarketOS API remains lightweight
and usable when the optional browser worker is not installed.
"""
from __future__ import annotations

import os
import hashlib
import asyncio
import json
import math
import re
import time
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlparse
from urllib import robotparser

from backend.contracts.adapters import AdapterHealth, SidecarContext
from evaluation.contracts import DataQuality, ProductCandidate, SupplierOffer


PHASE1_JS_RENDER_ENV = "MARKETOS_PHASE1_JS_RENDER"
CRAWL4AI_BROWSER_CHANNEL_ENV = "MARKETOS_CRAWL4AI_BROWSER_CHANNEL"


def phase1_js_render_enabled() -> bool:
    """Return whether the operator explicitly enabled the Phase 1 fallback.

    The existing adapter remains usable as a dry-run/optional OSS adapter.  A
    real browser-rendered fetch is deliberately a second gate, because it is
    heavier than the bounded static transport and can download browser
    assets.  Callers must still provide ``CRAWL4AI_ALLOWED_DOMAINS`` and the
    adapter continues to enforce robots.txt.
    """
    return os.getenv(PHASE1_JS_RENDER_ENV, "0").strip() == "1"


def crawl4ai_browser_channel() -> str | None:
    """Return an explicitly selected local Playwright browser channel.

    Crawl4AI normally uses Playwright's bundled Chromium. Some operator
    images have a usable Chrome channel but not the optional
    ``chromium-headless-shell`` payload. Selecting that channel remains a
    local-runtime-only override; it neither broadens the URL allowlist nor
    changes the default optional-worker behavior.
    """
    value = os.getenv(CRAWL4AI_BROWSER_CHANNEL_ENV, "").strip()
    return value or None


class Crawl4AIResearchAdapter:
    name = "crawl4ai"

    def __init__(self, *, allowed_domains: set[str] | None = None, max_content_chars: int = 200_000, respect_robots: bool = True, user_agent: str = "MarketOSResearch/1.0"):
        self.allowed_domains = allowed_domains or set(filter(None, os.getenv("CRAWL4AI_ALLOWED_DOMAINS", "").split(",")))
        self.max_content_chars = max_content_chars
        self.respect_robots = respect_robots
        self.user_agent = user_agent
        self._raw_cache: dict[tuple[str, bool], tuple[float, dict[str, Any]]] = {}

    def health(self) -> AdapterHealth:
        try:
            import crawl4ai  # noqa: F401
        except ImportError:
            return AdapterHealth(self.name, configured=False, reachable=False, detail="optional dependency is not installed")
        return AdapterHealth(self.name, configured=True, reachable=True, capabilities=("web_crawl", "structured_extraction", "cache"))

    @staticmethod
    def _product_records_from_jsonld(
        html: Any, url: str, *, fetched_at: float | None = None, retrieval_mode: str = "unknown",
    ) -> list[dict[str, Any]]:
        """Extract only explicit schema.org Product evidence from a page.

        JSON-LD is deterministic, requires no model credentials, and avoids
        treating arbitrary page prose as a product claim. Pages without valid
        Product objects intentionally yield no ranking evidence.
        """
        if not isinstance(html, str) or not html:
            return []
        scripts = re.findall(
            r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        objects: list[Mapping[str, Any]] = []

        def visit(value: Any) -> None:
            if isinstance(value, Mapping):
                nested = value.get("@graph")
                if isinstance(nested, list):
                    for item in nested:
                        visit(item)
                raw_type = value.get("@type", "")
                types = raw_type if isinstance(raw_type, list) else [raw_type]
                if any(str(item).strip().lower() == "product" for item in types):
                    objects.append(value)
                return
            if isinstance(value, list):
                for item in value:
                    visit(item)

        for script in scripts:
            try:
                visit(json.loads(script.strip()))
            except (TypeError, ValueError):
                continue

        records: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for product in objects:
            name = str(product.get("name") or "").strip()
            if not name:
                continue
            offers = product.get("offers")
            offer_rows = offers if isinstance(offers, list) else [offers]
            offer = next((item for item in offer_rows if isinstance(item, Mapping)), {})
            raw_price = None
            if isinstance(offer, Mapping):
                raw_price = offer.get("price")
                if raw_price is None:
                    raw_price = offer.get("lowPrice")
            if raw_price is None:
                raw_price = product.get("price")
            try:
                price = float(raw_price) if raw_price not in (None, "") else None
                if price is not None and not math.isfinite(price):
                    price = None
            except (TypeError, ValueError):
                price = None
            product_id = str(product.get("sku") or product.get("mpn") or product.get("productID") or "").strip()
            dedupe_key = (product_id, name.casefold())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            brand = product.get("brand")
            brand_name = str(brand.get("name") or "").strip() if isinstance(brand, Mapping) else str(brand or "").strip()
            raw_currency = (offer.get("priceCurrency") or product.get("priceCurrency")) if isinstance(offer, Mapping) else product.get("priceCurrency")
            currency = str(raw_currency).strip().upper() if raw_currency not in (None, "") else None
            record: dict[str, Any] = {
                "name": name,
                "url": str(product.get("url") or url),
                "source": "crawl4ai",
                "selling_price": price,
                "currency": currency,
                "shipping_currency": None,
                "availability": str(offer.get("availability") or "") if isinstance(offer, Mapping) else "",
                "brand": brand_name,
                "description": str(product.get("description") or ""),
                "fetched_at": fetched_at,
                "retrieval_mode": retrieval_mode,
                "quality": {"provenance": "public_page", "attribution": "attributed", "source_ref": url},
            }
            if product_id:
                record["product_id"] = product_id
            # Additive fields for competitor-listing comparison (Competition
            # Intelligence Engine) — never read by the pre-existing supplier/
            # candidate normalizers above, so this cannot change their output.
            rating = product.get("aggregateRating")
            if isinstance(rating, Mapping):
                try:
                    record["rating"] = float(rating.get("ratingValue"))
                except (TypeError, ValueError):
                    pass
                try:
                    record["review_count"] = int(rating.get("reviewCount") or rating.get("ratingCount"))
                except (TypeError, ValueError):
                    pass
            seller = offer.get("seller") if isinstance(offer, Mapping) else None
            seller_name = str(seller.get("name") or "").strip() if isinstance(seller, Mapping) else str(seller or "").strip()
            if seller_name:
                record["seller"] = seller_name
            image = product.get("image")
            if isinstance(image, list) and image:
                record["image"] = str(image[0])
            elif isinstance(image, str) and image:
                record["image"] = image
            shipping_details = offer.get("shippingDetails") if isinstance(offer, Mapping) else None
            shipping_rate = shipping_details.get("shippingRate") if isinstance(shipping_details, Mapping) else None
            if isinstance(shipping_rate, Mapping):
                raw_shipping = shipping_rate.get("value")
                if raw_shipping is not None:
                    try:
                        shipping_cost = float(raw_shipping)
                    except (TypeError, ValueError):
                        shipping_cost = math.nan
                    if math.isfinite(shipping_cost) and shipping_cost >= 0:
                        record["shipping_cost"] = shipping_cost
                        raw_shipping_currency = shipping_rate.get("currency")
                        record["shipping_currency"] = (
                            str(raw_shipping_currency).strip().upper()
                            if raw_shipping_currency not in (None, "") else None
                        )
                    else:
                        record["shipping_cost_status"] = "malformed"
            records.append(record)
        return records

    @staticmethod
    def _normalized_structured_records(
        structured: Any, url: str, *, fetched_at: float | None = None, retrieval_mode: str = "unknown",
    ) -> list[dict[str, Any]]:
        rows = structured if isinstance(structured, list) else [structured]
        normalized: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            name = str(row.get("name") or row.get("product_name") or "").strip()
            if not name:
                continue
            normalized.append({
                **row,
                "name": name,
                "url": row.get("url") or url,
                "source": "crawl4ai",
                "fetched_at": fetched_at,
                "retrieval_mode": retrieval_mode,
                "quality": {"provenance": "public_page", "attribution": "attributed", "source_ref": str(row.get("url") or url)},
            })
        return normalized

    def _raw_cache_get(self, url: str, *, dry_run: bool) -> dict[str, Any] | None:
        cached = self._raw_cache.get((url, dry_run))
        ttl_s = max(0.0, float(os.getenv("CRAWL4AI_RAW_CACHE_TTL_S", "900")))
        if cached and time.monotonic() - cached[0] < ttl_s:
            return dict(cached[1])
        if cached:
            self._raw_cache.pop((url, dry_run), None)
        return None

    def _raw_cache_put(self, url: str, raw: Mapping[str, Any], *, dry_run: bool) -> None:
        max_entries = max(1, min(int(os.getenv("CRAWL4AI_RAW_CACHE_MAX_ENTRIES", "100")), 1000))
        key = (url, dry_run)
        self._raw_cache[key] = (time.monotonic(), dict(raw))
        if len(self._raw_cache) > max_entries:
            oldest = min(self._raw_cache, key=lambda item: self._raw_cache[item][0])
            self._raw_cache.pop(oldest, None)

    def _records_from_raw(self, raw: Mapping[str, Any], url: str) -> list[dict[str, Any]]:
        fetched_at = raw.get("fetched_at")
        retrieval_mode = str(raw.get("retrieval_mode") or "unknown")
        extracted = raw.get("extracted_content")
        if extracted:
            try:
                structured = json.loads(extracted) if isinstance(extracted, str) else extracted
            except (TypeError, ValueError):
                structured = None
            normalized = self._normalized_structured_records(
                structured, url, fetched_at=fetched_at, retrieval_mode=retrieval_mode,
            ) if structured is not None else []
            if normalized:
                return normalized
        return self._product_records_from_jsonld(
            raw.get("html", ""), url, fetched_at=fetched_at, retrieval_mode=retrieval_mode,
        )

    @staticmethod
    def _public_page_quality(record: Mapping[str, Any], source_ref: str) -> DataQuality | None:
        retrieval_mode = str(record.get("retrieval_mode") or "unknown")
        if retrieval_mode not in {"fresh_fetch", "cache_hit"}:
            return None
        raw_fetched_at = record.get("fetched_at")
        if raw_fetched_at is None:
            return None
        try:
            fetched_at = float(raw_fetched_at)
            if not math.isfinite(fetched_at) or fetched_at < 0:
                return None
            observed_at = datetime.fromtimestamp(fetched_at, tz=timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            return None
        return DataQuality(
            provenance="public_page", attribution="attributed" if source_ref else "unknown",
            completeness="partial", observed_at=observed_at, source_ref=source_ref,
            retrieval_mode=retrieval_mode,
        )

    async def discover(self, url: str, *, context: SidecarContext) -> list[dict[str, Any]]:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not hostname:
            raise ValueError("research URL must be an absolute HTTP(S) URL")
        if not context.dry_run and not self.allowed_domains:
            raise PermissionError("live research requires CRAWL4AI_ALLOWED_DOMAINS")
        if not context.dry_run and not any(
            hostname == domain.strip().lower().lstrip(".")
            or hostname.endswith("." + domain.strip().lower().lstrip("."))
            for domain in self.allowed_domains
        ):
            raise PermissionError(f"research domain is not allowlisted: {hostname}")
        if not context.dry_run and self.respect_robots:
            robots = robotparser.RobotFileParser(f"{parsed.scheme}://{hostname}/robots.txt")
            try:
                robots.read()
            except Exception as exc:
                raise PermissionError(f"robots.txt could not be verified for {hostname}") from exc
            if not robots.can_fetch(self.user_agent, url):
                raise PermissionError(f"robots.txt disallows research URL: {url}")
        if context.dry_run:
            return [{"url": url, "source": self.name, "dry_run": True, "quality": {"provenance": "simulated"}}]
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig
        except ImportError as exc:
            raise RuntimeError("Crawl4AI is not installed; install the reviewed optional OSS profile") from exc

        cached_raw = self._raw_cache_get(url, dry_run=False)
        if cached_raw is not None:
            cached_raw["retrieval_mode"] = "cache_hit" if cached_raw.get("fetched_at") is not None else "cache_hit_timestamp_unknown"
            return self._records_from_raw(cached_raw, url)

        channel = crawl4ai_browser_channel()
        # Crawl4AI's Rich console logger emits Unicode arrows that can fail on
        # Windows CP1252 consoles before a browser navigation starts. This
        # optional worker already reports outcomes through canonical evidence,
        # so keep its third-party console output quiet and deterministic.
        browser_config = BrowserConfig(
            chrome_channel=channel or "chromium",
            channel=channel or "chromium",
            verbose=False,
        )
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url)
        fetched_at = time.time()
        raw = {
            "extracted_content": getattr(result, "extracted_content", None),
            "html": getattr(result, "html", "") or "",
            "fetched_at": fetched_at,
            "retrieval_mode": "fresh_fetch",
        }
        self._raw_cache_put(url, raw, dry_run=False)
        records = self._records_from_raw(raw, url)
        if records:
            return records
        # Do not turn arbitrary markdown into product evidence. The raw page
        # remains under Crawl4AI's own cache; this boundary emits only records
        # that satisfy the canonical product contract.
        return []

    def discover_sync(self, url: str, *, context: SidecarContext) -> list[dict[str, Any]]:
        """Synchronous bridge for the existing sync evidence adapters.

        The Phase 1 evidence paths are intentionally synchronous.  Keep the
        bridge narrow and fail closed if a caller tries to invoke it from an
        already-running event loop rather than nesting or patching asyncio.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.discover(url, context=context))
        raise RuntimeError("Crawl4AI sync bridge cannot run inside an active event loop")

    @staticmethod
    def normalize_candidates(records: list[dict[str, Any]]) -> list[ProductCandidate]:
        """Convert crawler records into the single MarketOS product contract.

        Extraction is intentionally conservative: a crawler record without a
        usable name is rejected rather than becoming false product evidence.
        Prices are accepted only when already normalized by the extractor.
        """
        candidates: list[ProductCandidate] = []
        for record in records:
            name = str(record.get("name") or record.get("product_name") or "").strip()
            if not name:
                continue
            source_ref = str(record.get("url") or record.get("source_ref") or "")
            product_id = str(record.get("product_id") or hashlib.sha256(f"{source_ref}:{name}".encode()).hexdigest()[:24])
            quality = Crawl4AIResearchAdapter._public_page_quality(record, source_ref)
            currency = str(record.get("currency") or "").strip().upper()
            if quality is None or not currency:
                continue
            raw_price = record.get("selling_price", record.get("price"))
            if raw_price is None or isinstance(raw_price, bool):
                continue
            try:
                price = float(raw_price)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(price) or price <= 0:
                continue
            candidates.append(ProductCandidate(
                product_id=product_id,
                name=name,
                currency=currency,
                selling_price=price,
                source_signal_ids=(source_ref,) if source_ref else (),
                quality=quality,
            ))
        return candidates

    @staticmethod
    def normalize_supplier_offers(records: list[dict[str, Any]]) -> list[SupplierOffer]:
        """Turn explicitly extracted supplier costs into economics evidence.

        A public product price is a selling price, not a supplier cost. This
        method intentionally requires an explicit ``unit_cost``/``wholesale``
        field and refuses to infer it from any product-page price.
        """
        offers: list[SupplierOffer] = []
        for record in records:
            product_id = str(record.get("product_id") or "").strip()
            if not product_id:
                continue
            raw_cost = record.get("unit_cost", record.get("wholesale_price", record.get("supplier_price")))
            if raw_cost is None or isinstance(raw_cost, bool):
                continue
            try:
                unit_cost = float(raw_cost)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(unit_cost) or unit_cost <= 0:
                continue
            raw_shipping = record.get("shipping_cost")
            if raw_shipping is None or isinstance(raw_shipping, bool):
                continue
            try:
                shipping_cost = float(raw_shipping)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(shipping_cost) or shipping_cost < 0:
                continue
            currency = str(record.get("currency") or "").strip().upper()
            shipping_currency = str(record.get("shipping_currency") or "").strip().upper()
            if not currency or currency != shipping_currency:
                continue
            try:
                fulfillment_days = int(record["fulfillment_days"]) if record.get("fulfillment_days") is not None else None
            except (TypeError, ValueError):
                fulfillment_days = None
            try:
                inventory_units = int(record["inventory_units"]) if record.get("inventory_units") is not None else None
            except (TypeError, ValueError):
                inventory_units = None
            source_ref = str(record.get("url") or record.get("source_ref") or "")
            quality = Crawl4AIResearchAdapter._public_page_quality(record, source_ref)
            if quality is None:
                continue
            supplier_id = str(record.get("supplier_id") or record.get("supplier_name") or urlparse(source_ref).hostname or "crawl4ai-supplier").strip()
            offers.append(SupplierOffer(
                supplier_id=supplier_id,
                product_id=product_id,
                unit_cost=unit_cost,
                shipping_cost=shipping_cost,
                fulfillment_days=fulfillment_days,
                inventory_units=inventory_units,
                currency=currency,
                quality=quality,
            ))
        return offers

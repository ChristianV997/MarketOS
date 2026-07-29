"""Optional Crawl4AI research adapter.

The dependency is intentionally lazy so the MarketOS API remains lightweight
and usable when the optional browser worker is not installed.
"""
from __future__ import annotations

import os
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlparse
from urllib import robotparser

from backend.contracts.adapters import AdapterHealth, SidecarContext
from evaluation.contracts import DataQuality, ProductCandidate, SupplierOffer


class Crawl4AIResearchAdapter:
    name = "crawl4ai"

    def __init__(self, *, allowed_domains: set[str] | None = None, max_content_chars: int = 200_000, respect_robots: bool = True, user_agent: str = "MarketOSResearch/1.0"):
        self.allowed_domains = allowed_domains or set(filter(None, os.getenv("CRAWL4AI_ALLOWED_DOMAINS", "").split(",")))
        self.max_content_chars = max_content_chars
        self.respect_robots = respect_robots
        self.user_agent = user_agent

    def health(self) -> AdapterHealth:
        try:
            import crawl4ai  # noqa: F401
        except ImportError:
            return AdapterHealth(self.name, configured=False, reachable=False, detail="optional dependency is not installed")
        return AdapterHealth(self.name, configured=True, reachable=True, capabilities=("web_crawl", "structured_extraction", "cache"))

    @staticmethod
    def _product_records_from_jsonld(html: Any, url: str) -> list[dict[str, Any]]:
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

        retrieved_at = datetime.now(timezone.utc).isoformat()
        records: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for product in objects:
            name = str(product.get("name") or "").strip()
            if not name:
                continue
            offers = product.get("offers")
            offer_rows = offers if isinstance(offers, list) else [offers]
            offer = next((item for item in offer_rows if isinstance(item, Mapping)), {})
            raw_price = offer.get("price", offer.get("lowPrice", product.get("price", 0.0))) if isinstance(offer, Mapping) else product.get("price", 0.0)
            try:
                price = float(raw_price or 0.0)
            except (TypeError, ValueError):
                price = 0.0
            product_id = str(product.get("sku") or product.get("mpn") or product.get("productID") or "").strip()
            dedupe_key = (product_id, name.casefold())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            brand = product.get("brand")
            brand_name = str(brand.get("name") or "").strip() if isinstance(brand, Mapping) else str(brand or "").strip()
            record: dict[str, Any] = {
                "name": name,
                "url": str(product.get("url") or url),
                "source": "crawl4ai",
                "selling_price": max(0.0, price),
                "currency": str(offer.get("priceCurrency") or product.get("priceCurrency") or "USD").upper() if isinstance(offer, Mapping) else str(product.get("priceCurrency") or "USD").upper(),
                "availability": str(offer.get("availability") or "") if isinstance(offer, Mapping) else "",
                "brand": brand_name,
                "description": str(product.get("description") or ""),
                "retrieved_at": retrieved_at,
                "quality": {"provenance": "live", "attribution": "attributed", "source_ref": url},
            }
            if product_id:
                record["product_id"] = product_id
            records.append(record)
        return records

    @staticmethod
    def _normalized_structured_records(structured: Any, url: str) -> list[dict[str, Any]]:
        rows = structured if isinstance(structured, list) else [structured]
        retrieved_at = datetime.now(timezone.utc).isoformat()
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
                "retrieved_at": row.get("retrieved_at") or retrieved_at,
                "quality": {"provenance": "live", "attribution": "attributed", "source_ref": str(row.get("url") or url)},
            })
        return normalized

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
            from crawl4ai import AsyncWebCrawler
        except ImportError as exc:
            raise RuntimeError("Crawl4AI is not installed; install the reviewed optional OSS profile") from exc

        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url)
        extracted = getattr(result, "extracted_content", None)
        if extracted:
            try:
                structured = json.loads(extracted) if isinstance(extracted, str) else extracted
            except (TypeError, ValueError) as exc:
                raise ValueError("Crawl4AI returned malformed structured extraction") from exc
            normalized = self._normalized_structured_records(structured, url)
            if normalized:
                return normalized
        jsonld_records = self._product_records_from_jsonld(getattr(result, "html", ""), url)
        if jsonld_records:
            return jsonld_records
        # Do not turn arbitrary markdown into product evidence. The raw page
        # remains under Crawl4AI's own cache; this boundary emits only records
        # that satisfy the canonical product contract.
        return []

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
            raw_quality = record.get("quality") or {}
            quality = raw_quality if isinstance(raw_quality, DataQuality) else DataQuality(
                provenance=str(raw_quality.get("provenance", "unknown")),
                attribution="attributed" if source_ref else "unknown",
                source_ref=source_ref,
            )
            try:
                price = float(record.get("selling_price", record.get("price", 0.0)) or 0.0)
            except (TypeError, ValueError):
                price = 0.0
            candidates.append(ProductCandidate(
                product_id=product_id,
                name=name,
                currency=str(record.get("currency", "USD")),
                selling_price=max(0.0, price),
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
            try:
                unit_cost = float(raw_cost)
            except (TypeError, ValueError):
                continue
            if unit_cost <= 0:
                continue
            try:
                shipping_cost = max(0.0, float(record.get("shipping_cost", 0.0) or 0.0))
            except (TypeError, ValueError):
                shipping_cost = 0.0
            try:
                fulfillment_days = int(record["fulfillment_days"]) if record.get("fulfillment_days") is not None else None
            except (TypeError, ValueError):
                fulfillment_days = None
            try:
                inventory_units = int(record["inventory_units"]) if record.get("inventory_units") is not None else None
            except (TypeError, ValueError):
                inventory_units = None
            source_ref = str(record.get("url") or record.get("source_ref") or "")
            supplier_id = str(record.get("supplier_id") or record.get("supplier_name") or urlparse(source_ref).hostname or "crawl4ai-supplier").strip()
            offers.append(SupplierOffer(
                supplier_id=supplier_id,
                product_id=product_id,
                unit_cost=unit_cost,
                shipping_cost=shipping_cost,
                fulfillment_days=fulfillment_days,
                inventory_units=inventory_units,
                currency=str(record.get("currency") or "USD").upper(),
                quality=DataQuality(provenance="live", attribution="attributed" if source_ref else "unknown", source_ref=source_ref),
            ))
        return offers

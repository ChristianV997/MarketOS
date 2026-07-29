"""Optional Crawl4AI research adapter.

The dependency is intentionally lazy so the MarketOS API remains lightweight
and usable when the optional browser worker is not installed.
"""
from __future__ import annotations

import os
import hashlib
import json
from typing import Any
from urllib.parse import urlparse
from urllib import robotparser

from backend.contracts.adapters import AdapterHealth, SidecarContext
from evaluation.contracts import DataQuality, ProductCandidate


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
            rows = structured if isinstance(structured, list) else [structured]
            normalized: list[dict[str, Any]] = []
            for row in rows:
                if isinstance(row, dict):
                    normalized.append({
                        **row,
                        "url": row.get("url") or url,
                        "source": self.name,
                        "quality": {"provenance": "live", "source_ref": url},
                    })
            if normalized:
                return normalized
        markdown = (getattr(result, "markdown", "") or "")[: self.max_content_chars]
        return [{
            "url": url,
            "content": markdown,
            "source": self.name,
            "quality": {"provenance": "live", "source_ref": url},
        }]

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

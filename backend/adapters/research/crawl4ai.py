"""Optional Crawl4AI research adapter.

The dependency is intentionally lazy so the MarketOS API remains lightweight
and usable when the optional browser worker is not installed.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from backend.contracts.adapters import AdapterHealth, SidecarContext


class Crawl4AIResearchAdapter:
    name = "crawl4ai"

    def __init__(self, *, allowed_domains: set[str] | None = None, max_content_chars: int = 200_000):
        self.allowed_domains = allowed_domains or set(filter(None, os.getenv("CRAWL4AI_ALLOWED_DOMAINS", "").split(",")))
        self.max_content_chars = max_content_chars

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
        if not context.dry_run and self.allowed_domains and not any(
            hostname == domain.strip().lower().lstrip(".")
            or hostname.endswith("." + domain.strip().lower().lstrip("."))
            for domain in self.allowed_domains
        ):
            raise PermissionError(f"research domain is not allowlisted: {hostname}")
        if context.dry_run:
            return [{"url": url, "source": self.name, "dry_run": True, "quality": {"provenance": "simulated"}}]
        try:
            from crawl4ai import AsyncWebCrawler
        except ImportError as exc:
            raise RuntimeError("Crawl4AI is not installed; install the reviewed optional OSS profile") from exc

        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url)
        markdown = (getattr(result, "markdown", "") or "")[: self.max_content_chars]
        return [{
            "url": url,
            "content": markdown,
            "source": self.name,
            "quality": {"provenance": "live", "source_ref": url},
        }]

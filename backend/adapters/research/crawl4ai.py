"""Optional Crawl4AI research adapter.

The dependency is intentionally lazy so the MarketOS API remains lightweight
and usable when the optional browser worker is not installed.
"""
from __future__ import annotations

from typing import Any

from backend.contracts.adapters import AdapterHealth, SidecarContext


class Crawl4AIResearchAdapter:
    name = "crawl4ai"

    def health(self) -> AdapterHealth:
        try:
            import crawl4ai  # noqa: F401
        except ImportError:
            return AdapterHealth(self.name, configured=False, reachable=False, detail="optional dependency is not installed")
        return AdapterHealth(self.name, configured=True, reachable=True, capabilities=("web_crawl", "structured_extraction", "cache"))

    async def discover(self, url: str, *, context: SidecarContext) -> list[dict[str, Any]]:
        if context.dry_run:
            return [{"url": url, "source": self.name, "dry_run": True, "quality": {"provenance": "simulated"}}]
        try:
            from crawl4ai import AsyncWebCrawler
        except ImportError as exc:
            raise RuntimeError("Crawl4AI is not installed; install the reviewed optional OSS profile") from exc

        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url)
        markdown = getattr(result, "markdown", "") or ""
        return [{
            "url": url,
            "content": markdown,
            "source": self.name,
            "quality": {"provenance": "live", "source_ref": url},
        }]

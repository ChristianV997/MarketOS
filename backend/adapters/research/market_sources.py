"""Research-store wrappers for the existing public market signal adapters."""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Any, Callable

from backend.adapters.mercadolibre_trends import fetch as fetch_mercadolibre
from backend.adapters.amazon_bestsellers import fetch as fetch_amazon_bestsellers
from backend.adapters.reddit_trends import fetch_reddit_signals
from backend.adapters.tiktok_organic import fetch as fetch_tiktok_organic
from backend.adapters.youtube_trends import fetch_youtube_signals
from backend.adapters.research.base import ResearchSourceAdapter
from backend.adapters.research.trend_source_v1 import AdapterFetchError


def _float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _intent(topic: str) -> str:
    lowered = topic.casefold()
    if any(token in lowered for token in ("buy", "price", "deal", "coupon", "shop", "sale")):
        return "buy"
    if any(token in lowered for token in ("vs", "versus", "compare", "best")):
        return "compare"
    if any(token in lowered for token in ("how", "what", "guide", "review", "tutorial")):
        return "research"
    return "unknown"


class _SignalResearchAdapter(ResearchSourceAdapter):
    """Adapt a SignalEngine-compatible public source to research records."""

    fetcher: Callable[[], list[dict[str, Any]]]
    name: str
    confidence_env: str

    def __init__(self) -> None:
        self.confidence_baseline = min(1.0, max(0.0, _float_env(self.confidence_env, 0.5)))

    def fetch(self) -> list[dict[str, Any]]:
        return self.fetcher()

    def to_canonical(
        self,
        raw_record: dict[str, Any],
        *,
        fetched_at: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(raw_record, dict):
            raise AdapterFetchError("schema", "research source record must be an object")
        topic = str(raw_record.get("product") or raw_record.get("title") or "").strip()
        if not topic:
            raise AdapterFetchError("schema", "research source record missing product topic")
        try:
            velocity = float(raw_record.get("velocity", 0.0) or 0.0)
        except (TypeError, ValueError) as exc:
            raise AdapterFetchError("schema", "research source velocity is not numeric") from exc
        if not math.isfinite(velocity):
            raise AdapterFetchError("schema", "research source velocity is not finite")
        return {
            "topic": topic,
            "intent": _intent(topic),
            "velocity": min(1.0, max(0.0, velocity)),
            "competition": None,
            "source": self.name,
            "freshness_ts": (fetched_at or datetime.now(timezone.utc)).isoformat(),
            "confidence": self.confidence_baseline,
            "raw": {
                "signal": raw_record,
                "competition_evidence": "unavailable",
            },
        }


class RedditResearchAdapter(_SignalResearchAdapter):
    name = "reddit"
    fetcher = staticmethod(fetch_reddit_signals)
    confidence_env = "PILLAR_A_SOURCE_REDDIT_CONFIDENCE_BASELINE"


class MercadoLibreResearchAdapter(_SignalResearchAdapter):
    name = "mercadolibre"
    fetcher = staticmethod(fetch_mercadolibre)
    confidence_env = "PILLAR_A_SOURCE_MERCADOLIBRE_CONFIDENCE_BASELINE"


class YouTubeResearchAdapter(_SignalResearchAdapter):
    name = "youtube_trends"
    fetcher = staticmethod(fetch_youtube_signals)
    confidence_env = "PILLAR_A_SOURCE_YOUTUBE_CONFIDENCE_BASELINE"


class _RealOnlySignalResearchAdapter(_SignalResearchAdapter):
    """Reject synthetic fallback records from research ingestion."""

    synthetic_sources: frozenset[str] = frozenset()

    def fetch(self) -> list[dict[str, Any]]:
        records = self.fetcher()
        real_records = [
            record for record in records
            if not isinstance(record, dict)
            or str(record.get("source", "")) not in self.synthetic_sources
        ]
        if records and not real_records:
            raise AdapterFetchError(
                "unavailable",
                f"{self.name} returned synthetic fallback data",
                context={"record_count": len(records)},
            )
        return real_records


class AmazonBestsellersResearchAdapter(_RealOnlySignalResearchAdapter):
    name = "amazon_bestsellers"
    fetcher = staticmethod(fetch_amazon_bestsellers)
    synthetic_sources = frozenset({"amazon_bestsellers_mock"})
    confidence_env = "PILLAR_A_SOURCE_AMAZON_CONFIDENCE_BASELINE"


class TikTokOrganicResearchAdapter(_RealOnlySignalResearchAdapter):
    name = "tiktok_organic"
    fetcher = staticmethod(fetch_tiktok_organic)
    synthetic_sources = frozenset({"tiktok_mock"})
    confidence_env = "PILLAR_A_SOURCE_TIKTOK_CONFIDENCE_BASELINE"

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from backend.adapters.research.base import ResearchSourceAdapter

try:
    import trendspyg as _trendspyg
except ImportError:  # pragma: no cover
    _trendspyg = None

_log = logging.getLogger(__name__)


ERROR_AUTH = "auth"
ERROR_RATE_LIMIT = "rate_limit"
ERROR_SERVER = "server"
ERROR_SCHEMA = "schema"
ERROR_UNKNOWN = "unknown"


class AdapterFetchError(RuntimeError):
    def __init__(self, error_type: str, message: str, context: dict[str, Any] | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.context = context or {}
        self.retryable = error_type in {ERROR_RATE_LIMIT, ERROR_SERVER}


def classify_http_error(status_code: int) -> str:
    if status_code in {401, 403}:
        return ERROR_AUTH
    if status_code == 429:
        return ERROR_RATE_LIMIT
    if status_code >= 500:
        return ERROR_SERVER
    return ERROR_UNKNOWN


def _parse_traffic(value: str | None) -> float:
    if not value:
        return 0.0
    token = value.strip().replace(",", "").rstrip("+")
    match = re.match(r"^(\d+(?:\.\d+)?)([KMB])?$", token, flags=re.IGNORECASE)
    if not match:
        return 0.0
    base = float(match.group(1))
    scale = (match.group(2) or "").upper()
    if scale == "K":
        base *= 1_000
    elif scale == "M":
        base *= 1_000_000
    elif scale == "B":
        base *= 1_000_000_000
    return base


class GoogleTrendsAdapterV1(ResearchSourceAdapter):
    name = "google_trends_v1"
    endpoint = "https://trends.google.com/trends/api/dailytrends"

    def __init__(
        self,
        *,
        max_pages: int = 1,
        geo: str = "US",
        language: str = "en-US",
        timezone_offset: int = 0,
        timeout_seconds: int = 15,
        velocity_baseline: float = 1000.0,
        confidence_baseline: float = 0.7,
    ):
        self.max_pages = max(1, max_pages)
        self.geo = geo
        self.language = language
        self.timezone_offset = timezone_offset
        self.timeout_seconds = timeout_seconds
        self.velocity_baseline = max(1.0, float(velocity_baseline))
        self.confidence_baseline = min(1.0, max(0.0, float(confidence_baseline)))

    def _fetch_via_trendspyg(self) -> list[dict[str, Any]]:
        """Fetch current trending topics via trendspyg's RSS downloader —
        an actively maintained library using Google's public RSS feed —
        instead of hand-scraping the undocumented dailytrends JSON
        endpoint. No Selenium/browser dependency (unlike trendspyg's
        interest-over-time function): the RSS path is plain HTTP+XML.

        Reshapes trendspyg's {'trend', 'traffic', 'news_articles', ...}
        records into the legacy dailytrends record shape
        ({"title": {"query": ...}, "formattedTraffic": ..., "articles": ...})
        so to_canonical() below — its intent classification and velocity/
        competition derivation — needs no changes at all.
        """
        trends = _trendspyg.download_google_trends_rss(
            geo=self.geo,
            output_format="dict",
            include_images=False,
            include_articles=True,
            max_articles_per_trend=10,
            cache=True,
        )
        return [
            {
                "title": {"query": t.get("trend", "")},
                "formattedTraffic": t.get("traffic", ""),
                "articles": t.get("news_articles", []) or [],
            }
            for t in trends
        ]

    def _request(self, date_cursor: datetime) -> dict[str, Any]:
        params = {
            "hl": self.language,
            "tz": self.timezone_offset,
            "geo": self.geo,
            "ns": 15,
            "ed": date_cursor.strftime("%Y%m%d"),
        }
        response = requests.get(self.endpoint, params=params, timeout=self.timeout_seconds)
        if response.status_code != 200:
            error_type = classify_http_error(response.status_code)
            raise AdapterFetchError(
                error_type,
                f"trend source request failed with status {response.status_code}",
                context={"status_code": response.status_code, "endpoint": self.endpoint},
            )

        payload = response.text.strip()
        if payload.startswith(")]}'"):
            payload = payload[4:].strip()
        try:
            return response.json() if payload == response.text else requests.models.complexjson.loads(payload)
        except Exception as err:
            raise AdapterFetchError(ERROR_SCHEMA, f"invalid trend payload: {err}") from err

    def fetch(self) -> list[dict[str, Any]]:
        if _trendspyg is not None:
            try:
                return self._fetch_via_trendspyg()
            except Exception as exc:
                _log.warning("trendspyg_fetch_failed_falling_back_to_legacy error=%s", exc)
        return self._fetch_legacy()

    def _fetch_legacy(self) -> list[dict[str, Any]]:
        """Hand-rolled scrape of Google's undocumented dailytrends JSON
        endpoint — the pre-trendspyg fetch path, kept as a fallback for
        when trendspyg isn't installed or its RSS call fails. Also the
        only path with day-by-day pagination (max_pages > 1); trendspyg's
        RSS feed only ever returns "current" trends, no historical paging.
        """
        records: list[dict[str, Any]] = []
        cursor = datetime.now(timezone.utc)
        for _ in range(self.max_pages):
            page_payload = self._request(cursor)
            days = (
                page_payload.get("default", {})
                .get("trendingSearchesDays", [])
            )
            if not days:
                break
            page_records = days[0].get("trendingSearches", [])
            if not isinstance(page_records, list):
                raise AdapterFetchError(ERROR_SCHEMA, "trendingSearches must be a list")
            records.extend(page_records)
            cursor = cursor - timedelta(days=1)
        return records

    def to_canonical(self, raw_record: dict[str, Any], fetched_at: datetime | None = None) -> dict[str, Any]:
        if not isinstance(raw_record, dict):
            raise AdapterFetchError(ERROR_SCHEMA, "raw trend record must be an object")

        topic = str(raw_record.get("title", {}).get("query", "")).strip()
        if not topic:
            raise AdapterFetchError(ERROR_SCHEMA, "trend record missing topic query")

        traffic = _parse_traffic(raw_record.get("formattedTraffic"))
        baseline = self.velocity_baseline if self.velocity_baseline else 1.0
        velocity = round((traffic - baseline) / baseline, 4)
        articles = raw_record.get("articles", []) or []
        competition = min(1.0, len(articles) / 10.0)

        lowered = topic.lower()
        if any(token in lowered for token in ("buy", "price", "deal", "coupon", "shop")):
            intent = "buy"
        elif any(token in lowered for token in ("vs", "versus", "compare", "best")):
            intent = "compare"
        elif any(token in lowered for token in ("how", "what", "guide", "review", "tutorial")):
            intent = "research"
        else:
            intent = "unknown"

        ts = (fetched_at or datetime.now(timezone.utc)).isoformat()
        return {
            "topic": topic,
            "intent": intent,
            "velocity": velocity,
            "competition": round(competition, 4),
            "source": self.name,
            "freshness_ts": ts,
            "confidence": self.confidence_baseline,
            "raw": raw_record,
        }


# ── SignalEngine adapter surface ────────────────────────────────────────────
#
# Self-contained fetch()+register() pair, matching the convention used by
# every other adapter in backend/adapters/ (reddit_trends.py,
# amazon_bestsellers.py, tiktok_organic.py): module-level cache, never raises
# out of fetch(), returns [] on total failure.
#
# Note: to_canonical() returns a plain dict with a "topic" key (there is no
# "keyword" attribute) — SignalEngine's signals key on "product" instead, so
# fields are mapped explicitly below rather than passed through as-is.

_CACHE_TTL_S = 1800  # 30 minutes — daily-trends data doesn't move faster than this
_CACHE: list[dict] = []
_CACHE_TS = 0.0


def fetch_google_trends_signals() -> list[dict]:
    """Fetch and cache Google Trends daily-trending signals for SignalEngine.

    Falls back to an empty list on any network/parsing failure (never
    crashes the engine); one malformed record is skipped rather than
    dropping the whole batch.
    """
    global _CACHE, _CACHE_TS
    now = time.time()
    if _CACHE and (now - _CACHE_TS) < _CACHE_TTL_S:
        return list(_CACHE)

    adapter = GoogleTrendsAdapterV1()
    fetched_at = datetime.now(timezone.utc)
    signals: list[dict] = []
    try:
        raw_records = adapter.fetch()
    except Exception as exc:
        _log.warning("google_trends_adapter_fetch_failed error=%s", exc)
        return []

    for raw in raw_records:
        try:
            canonical = adapter.to_canonical(raw, fetched_at=fetched_at)
        except AdapterFetchError as exc:
            _log.debug("google_trends_record_skipped error=%s", exc)
            continue
        signals.append({
            "product": canonical["topic"],
            "score": canonical.get("confidence", 0.6),
            "velocity": max(0.0, min(1.0, canonical.get("velocity", 0.5))),
            "source": "google_trends",
            "platform": "google",
        })

    if signals:
        _CACHE = signals
        _CACHE_TS = now
        _log.info("google_trends_signals_fetched count=%d", len(signals))
    return signals


def register(engine: Any) -> None:
    """Register this adapter with a SignalEngine instance."""
    engine.register_source("google_trends", fetch_google_trends_signals)
    try:
        from backend.discovery.registry import discovery_registry
        discovery_registry.register("google_trends", credential_env_vars=[], requires_auth=False)
    except Exception:
        pass
    _log.info("google_trends_adapter_registered")

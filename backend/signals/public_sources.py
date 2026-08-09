"""Bounded no-auth public RSS ingestion, manually invoked only.

The adapter targets the public Google News RSS search feed. It uses no cookie,
token, account, browser, pagination, or mutation API. A caller must explicitly
set ``allow_network=True``; fixtures and cache paths stay deterministic.
"""
from __future__ import annotations

import html
import logging
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as element_tree
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable

from backend.contracts.events import Event
from backend.events.repository import EventRepository

from .public_signal_cache import PublicSignalCache
from .public_signal_models import PublicSignal, PublicSignalIngestionResult, signal_identifier

RSS_SOURCE = "google_news_rss"
RSS_URL_TEMPLATE = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
DEFAULT_TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 1_000_000
MAX_RECORDS = 25
USER_AGENT = "MarketOS-PublicSignalPilot/1.0 (+https://github.com/ChristianV997/MarketOS)"

_log = logging.getLogger(__name__)
_TAG = re.compile(r"<[^>]+>")


def build_rss_url(query: str) -> str:
    return RSS_URL_TEMPLATE.format(query=urllib.parse.quote_plus(query.strip()))


def _excerpt(value: str, maximum: int = 500) -> str:
    return _TAG.sub("", html.unescape(value or "")).strip()[:maximum]


def _observed_at(value: str) -> float:
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, IndexError):
        return 0.0


def normalize_rss_xml(xml_text: str, query: str, *, source_url: str, limit: int = MAX_RECORDS) -> tuple[list[PublicSignal], list[str]]:
    """Deterministically parse a small RSS document; malformed items are skipped."""
    warnings: list[str] = []
    try:
        root = element_tree.fromstring(xml_text)
    except element_tree.ParseError:
        return [], ["invalid_rss_xml"]
    normalized: list[PublicSignal] = []
    seen: set[str] = set()
    for item in root.findall("./channel/item"):
        title = _excerpt(item.findtext("title", ""))
        link = (item.findtext("link", "") or "").strip()
        if not title or not link:
            warnings.append("skipped_partial_item")
            continue
        signal_id = signal_identifier(RSS_SOURCE, query, link, title)
        if signal_id in seen:
            warnings.append("deduplicated_item")
            continue
        seen.add(signal_id)
        rank = len(normalized) + 1
        source_name = _excerpt(item.findtext("source", "")) or "Google News RSS"
        description = _excerpt(item.findtext("description", ""))
        observed = _observed_at(item.findtext("pubDate", ""))
        normalized.append(PublicSignal(
            signal_id=signal_id, source=RSS_SOURCE, source_url=source_url, observed_at=observed,
            query=query, title=title, description=description, score=round(1.0 / rank, 6), rank=rank,
            category="public_news", tags=["public_rss", "advisory"], evidence_url=link,
            raw_ref=link, raw_excerpt=description,
            attribution={"publisher": source_name, "feed": "Google News RSS", "access": "public_no_auth"},
            quality={"source_local_score": True, "limitations": ["news coverage is not proof of demand, revenue, or product viability"]},
            metadata={"published_at_text": item.findtext("pubDate", ""), "network_source": "public_rss"},
        ))
        if len(normalized) >= max(1, min(int(limit), MAX_RECORDS)):
            break
    return normalized, warnings


def _http_get(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml;q=0.9"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310: fixed public allowlisted host
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("rss_response_too_large")
    return body.decode("utf-8", errors="replace")


def ingest_public_rss(
    query: str,
    *,
    limit: int = 10,
    allow_network: bool = False,
    cache: PublicSignalCache | None = None,
    fetcher: Callable[[str, int], str] | None = None,
    fixture_xml: str | None = None,
) -> PublicSignalIngestionResult:
    """Fetch public RSS only when expressly authorized; use stale cache on failure."""
    query = query.strip()
    if not query:
        return PublicSignalIngestionResult(RSS_SOURCE, query, "blocked", [], "none", errors=["query_required"])
    limit = max(1, min(int(limit), MAX_RECORDS))
    url = build_rss_url(query)
    if fixture_xml is not None:
        signals, warnings = normalize_rss_xml(fixture_xml, query, source_url=url, limit=limit)
        return PublicSignalIngestionResult(RSS_SOURCE, query, "fixture", signals, "fixture", warnings, source_url=url)
    if not allow_network:
        cached = cache.load(RSS_SOURCE, query) if cache else None
        if cached:
            signals = [PublicSignal.from_dict(item) for item in cached.get("signals", [])][:limit]
            return PublicSignalIngestionResult(RSS_SOURCE, query, "stale_cache", signals, "stale", ["network_not_allowed"], source_url=url)
        return PublicSignalIngestionResult(RSS_SOURCE, query, "blocked", [], "none", errors=["network_not_allowed_use_allow_network_or_fixtures"], source_url=url)
    try:
        xml_text = (fetcher or _http_get)(url, DEFAULT_TIMEOUT_SECONDS)
        signals, warnings = normalize_rss_xml(xml_text, query, source_url=url, limit=limit)
        if cache and signals:
            cache.save(RSS_SOURCE, query, [item.to_dict() for item in signals], url)
        return PublicSignalIngestionResult(RSS_SOURCE, query, "succeeded", signals, "fresh", warnings, network_used=True, source_url=url)
    except Exception as exc:
        _log.warning("public_rss_fetch_failed query=%s error=%s", query, type(exc).__name__)
        cached = cache.load(RSS_SOURCE, query) if cache else None
        if cached:
            signals = [PublicSignal.from_dict(item) for item in cached.get("signals", [])][:limit]
            return PublicSignalIngestionResult(RSS_SOURCE, query, "stale_cache", signals, "stale", [f"network_failure:{type(exc).__name__}"], source_url=url)
        return PublicSignalIngestionResult(RSS_SOURCE, query, "degraded", [], "none", errors=[f"network_failure:{type(exc).__name__}"], network_used=True, source_url=url)


def public_signal_event(signal: PublicSignal, workspace_id: str = "public-signal-dry-run", *, cache_status: str = "none") -> Event:
    return Event(
        event_id=f"event:{signal.signal_id}", workspace_id=workspace_id, aggregate_type="public_signal",
        aggregate_id=signal.signal_id, event_type="public_signal_observed", schema_version=1,
        occurred_at=signal.observed_at, correlation_id=f"public-rss:{signal.query.strip().lower()}",
        source="backend.signals.public_sources", payload=signal.to_dict(),
        metadata={"dry_run": True, "advisory": True, "no_credentials": True, "public_source": True,
                  "non_authoritative": True, "no_launch_authority": True, "no_spend_authority": True,
                  "cache_status": cache_status, "source_url": signal.source_url},
    )


def append_public_signal_events(signals: list[PublicSignal], repository: EventRepository, *, workspace_id: str, cache_status: str) -> list[str]:
    """Append only canonical public observations to an explicitly supplied repository."""
    return [result.event_id for result in repository.append_many([public_signal_event(item, workspace_id, cache_status=cache_status) for item in signals])]


def public_rss_readiness(cache: PublicSignalCache | None = None, query: str = "") -> dict[str, Any]:
    cache_info = cache.readiness(RSS_SOURCE, query) if cache else {"cache_available": False, "last_success": None, "cached_signal_count": 0}
    return {"source": RSS_SOURCE, "requires_credentials": False, "network_required": True, "configured": True,
            "status": "ready", "reason": "public_no_auth_manual_invocation", "allowed_actions": ["read_public_only"],
            "forbidden_actions": ["write", "publish", "spend", "mutate", "login", "credentialed_fetch"], **cache_info}

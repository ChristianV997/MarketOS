"""backend.adapters.research.competition_evidence — public, no-auth
competitor product-listing evidence.

Phase 1 Competition Intelligence source layer. Generalizes the SSRF-safe
fetch/robots/cache/JSON-LD pattern already established by
``backend.adapters.research.cj_public_evidence`` to *arbitrary* public
retail listings (Google Shopping, Amazon, Etsy, AliExpress, manufacturer
pages, Shopify/WooCommerce storefronts, or any other public product page an
operator supplies a URL for) — no credentials, no authentication, no
provider mutation, no browser automation.

Unlike ``cj_public_evidence`` (one fixed supplier host, ``ALLOWED_HOSTS``),
this module cannot use a fixed host allowlist: competitor listings can be
on any public storefront domain. It keeps the same SSRF safety guarantee
(scheme check + DNS resolution + private/loopback/link-local/reserved/
multicast rejection) without the host restriction, and reuses
``Crawl4AIResearchAdapter._product_records_from_jsonld`` for extraction —
extended additively (rating/review_count/seller/image/shipping_cost keys)
rather than duplicated, since a competitor listing needs fields
``cj_public_evidence`` never needed.

A competitor's displayed price is a *selling* price — exactly the
intelligence this module exists to observe — never treated as a supplier
cost (see ``Crawl4AIResearchAdapter.normalize_supplier_offers``'s identical
caution). Every field is paired with a provenance status in
``field_status``; nothing here fabricates a value a page didn't actually
expose.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import socket
import time
from dataclasses import dataclass, field as dataclass_field
from typing import Any
from urllib import robotparser
from urllib.parse import urlparse

from backend.adapters.research.crawl4ai import Crawl4AIResearchAdapter
from backend.contracts.adapters import AdapterHealth, SidecarContext

_log = logging.getLogger(__name__)

SOURCE_PREFIX = "competitor_public_page"
DEFAULT_TIMEOUT_S = 10
MAX_RESPONSE_BYTES = 2_000_000
USER_AGENT = "MarketOS-CompetitionIntelligence/1.0 (+https://github.com/ChristianV997/MarketOS)"

# Field-level provenance vocabulary for competitor evidence. Distinct from
# cj_public_evidence.FIELD_STATUSES (no "unavailable"/"conflicting" here;
# "missing" plays that role) — see docs/COMPETITION_INTELLIGENCE.md for why
# the two vocabularies were kept separate rather than unified.
FIELD_STATUSES = ("observed", "derived", "assumed", "missing", "malformed", "stale")

_EVIDENCE_FIELDS = (
    "title", "price", "currency", "availability", "shipping_cost", "brand",
    "seller", "rating", "review_count", "variant_count", "image",
)

# Labels only — never used to restrict which hosts may be fetched (an
# operator may supply any public storefront URL). Used solely to tag
# CompetitorOffer.source with a recognizable name when the caller doesn't
# specify one explicitly.
KNOWN_SOURCE_LABELS = {
    "google_shopping": ("google.com", "shopping.google.com"),
    "amazon": ("amazon.com",),
    "etsy": ("etsy.com",),
    "aliexpress": ("aliexpress.com",),
    "shopify_storefront": (),
    "woocommerce_storefront": (),
    "manufacturer": (),
}


@dataclass(frozen=True)
class CompetitorOffer:
    """One observed public competitor listing, with field-level provenance."""

    source: str
    source_url: str
    crawl_timestamp: float
    external_listing_id: str
    title: str
    field_status: dict[str, str] = dataclass_field(default_factory=dict)
    price: float | None = None
    currency: str = "USD"
    availability: str = ""
    shipping_cost: float | None = None
    brand: str = ""
    seller: str = ""
    rating: float | None = None
    review_count: int | None = None
    variant_count: int | None = None
    image: str = ""
    extraction_method: str = "jsonld_schema_org_product"
    confidence: float = 0.0
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source, "source_url": self.source_url, "crawl_timestamp": self.crawl_timestamp,
            "external_listing_id": self.external_listing_id, "title": self.title,
            "field_status": dict(self.field_status), "price": self.price, "currency": self.currency,
            "availability": self.availability, "shipping_cost": self.shipping_cost, "brand": self.brand,
            "seller": self.seller, "rating": self.rating, "review_count": self.review_count,
            "variant_count": self.variant_count, "image": self.image,
            "extraction_method": self.extraction_method, "confidence": self.confidence,
            "warnings": list(self.warnings),
        }


def _degraded(source_url: str, *, source: str, reason: str, extraction_method: str = "none") -> CompetitorOffer:
    """A structurally valid, fully-honest "observed nothing" result — the
    fallback for every rejected/blocked/failed path, never an exception the
    caller must special-case."""
    return CompetitorOffer(
        source=source, source_url=source_url, crawl_timestamp=time.time(),
        external_listing_id=hashlib.sha256(source_url.encode()).hexdigest()[:16],
        title="", field_status={name: "missing" for name in _EVIDENCE_FIELDS},
        extraction_method=extraction_method, confidence=0.0, warnings=(reason,),
    )


def _validate_public_url(url: str) -> str:
    """Return the validated hostname, or raise ValueError/PermissionError.

    Same SSRF-by-DNS-rebinding guard as cj_public_evidence._validate_public_url
    (resolve, reject private/loopback/link-local/reserved/multicast) but
    without a fixed host allowlist, since competitor listings may be on any
    public storefront domain an operator supplies.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("evidence URL must be http(s)")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("evidence URL has no hostname")
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise PermissionError(f"could not resolve evidence host: {hostname}") from exc
    for info in infos:
        addr = info[4][0]
        ip = ipaddress.ip_address(addr)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise PermissionError(f"evidence host resolves to a disallowed network: {hostname} -> {addr}")
    return hostname


def _check_robots(hostname: str, url: str) -> None:
    robots = robotparser.RobotFileParser(f"https://{hostname}/robots.txt")
    try:
        robots.read()
    except Exception as exc:  # noqa: BLE001 - an unverifiable robots.txt must block, not silently proceed
        raise PermissionError(f"robots.txt could not be verified for {hostname}") from exc
    if not robots.can_fetch(USER_AGENT, url):
        raise PermissionError(f"robots.txt disallows evidence URL: {url}")


_CACHE: dict[str, tuple[float, str]] = {}


def _cache_get(url: str) -> str | None:
    ttl_s = max(0.0, float(os.getenv("COMPETITION_EVIDENCE_CACHE_TTL_S", "900")))
    cached = _CACHE.get(url)
    if cached and time.monotonic() - cached[0] < ttl_s:
        return cached[1]
    if cached:
        _CACHE.pop(url, None)
    return None


def _cache_put(url: str, html: str) -> None:
    max_entries = max(1, min(int(os.getenv("COMPETITION_EVIDENCE_CACHE_MAX_ENTRIES", "100")), 1000))
    _CACHE[url] = (time.monotonic(), html)
    if len(_CACHE) > max_entries:
        oldest = min(_CACHE, key=lambda key: _CACHE[key][0])
        _CACHE.pop(oldest, None)


def _bounded_get(url: str, *, timeout: int = DEFAULT_TIMEOUT_S) -> str:
    """Bounded GET: fixed timeout, response-size cap, no automatic redirect
    following (a redirect target is unvalidated by definition)."""
    import requests

    response = requests.get(
        url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        timeout=timeout, stream=True, allow_redirects=False,
    )
    if response.status_code in (301, 302, 303, 307, 308):
        raise PermissionError(f"evidence fetch does not follow redirects: {url}")
    response.raise_for_status()
    total = 0
    chunks: list[bytes] = []
    for chunk in response.iter_content(chunk_size=65536):
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise ValueError("competition_evidence_response_too_large")
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", errors="replace")


def _label_source(hostname: str, source_hint: str) -> str:
    if source_hint:
        return source_hint
    for label, hosts in KNOWN_SOURCE_LABELS.items():
        if any(hostname == host or hostname.endswith("." + host) for host in hosts):
            return label
    return "public_storefront"


def _extract_from_jsonld(html: str, url: str, *, source: str) -> CompetitorOffer | None:
    """Reuses Crawl4AIResearchAdapter's JSON-LD Product parser (extended
    additively with rating/review_count/seller/image/shipping_cost — see
    crawl4ai.py) rather than a second parser. A page without a valid
    schema.org Product object yields no evidence, never a guess."""
    records = Crawl4AIResearchAdapter._product_records_from_jsonld(html, url)
    if not records:
        return None
    record = records[0]
    field_status = {name: "missing" for name in _EVIDENCE_FIELDS}
    if record.get("name"):
        field_status["title"] = "observed"
    if record.get("selling_price"):
        field_status["price"] = "observed"
        field_status["currency"] = "observed"
    if record.get("availability"):
        field_status["availability"] = "observed"
    if record.get("brand"):
        field_status["brand"] = "observed"
    if record.get("seller"):
        field_status["seller"] = "observed"
    if record.get("rating") is not None:
        field_status["rating"] = "observed"
    if record.get("review_count") is not None:
        field_status["review_count"] = "observed"
    if record.get("image"):
        field_status["image"] = "observed"
    if record.get("shipping_cost") is not None:
        field_status["shipping_cost"] = "observed"
    # No general schema.org Product signal reliably exposes variant count
    # for a single listing page; never guessed.
    confidence = round(sum(1 for status in field_status.values() if status == "observed") / len(field_status), 3)
    warnings = () if field_status["price"] == "observed" else ("price_not_found_in_structured_data",)
    return CompetitorOffer(
        source=source, source_url=url, crawl_timestamp=time.time(),
        external_listing_id=str(record.get("product_id") or hashlib.sha256(url.encode()).hexdigest()[:16]),
        title=str(record.get("name", "")), field_status=field_status,
        price=record.get("selling_price") or None, currency=str(record.get("currency", "USD")),
        availability=str(record.get("availability", "")), shipping_cost=record.get("shipping_cost"),
        brand=str(record.get("brand", "")), seller=str(record.get("seller", "")),
        rating=record.get("rating"), review_count=record.get("review_count"), image=str(record.get("image", "")),
        extraction_method="jsonld_schema_org_product", confidence=confidence, warnings=warnings,
    )


def fetch_competitor_offer(url: str, *, source: str = "", context: SidecarContext) -> CompetitorOffer:
    """Never raises. Always returns a structurally valid CompetitorOffer —
    degraded (all fields "missing") on any rejection, block, or failure."""
    try:
        hostname = _validate_public_url(url)
    except (ValueError, PermissionError) as exc:
        return _degraded(url, source=source or "public_storefront", reason=f"rejected:{exc}")
    resolved_source = _label_source(hostname, source)
    if context.dry_run:
        return _degraded(url, source=resolved_source, reason="dry_run_simulated", extraction_method="simulated")
    try:
        _check_robots(hostname, url)
    except PermissionError as exc:
        return _degraded(url, source=resolved_source, reason=f"robots_blocked:{exc}")
    html = _cache_get(url)
    if html is None:
        try:
            html = _bounded_get(url)
        except Exception as exc:  # noqa: BLE001 - network boundary must degrade, never raise
            _log.warning("competition_evidence_fetch_failed url=%s error=%s", url, type(exc).__name__)
            return _degraded(url, source=resolved_source, reason=f"fetch_failed:{type(exc).__name__}")
        _cache_put(url, html)
    offer = _extract_from_jsonld(html, url, source=resolved_source)
    if offer is None:
        return _degraded(url, source=resolved_source, reason="no_structured_product_data_found")
    return offer


def score_offers(offers: list[CompetitorOffer], query: str) -> list[dict[str, Any]]:
    """Deterministic competitor-listing comparison, ranked highest-relevance
    first. Unknown fields reduce confidence; never treated as favorable
    evidence and never silently become an assumption."""
    query_tokens = {token for token in query.lower().split() if token}
    scored: list[dict[str, Any]] = []
    for offer in offers:
        title_tokens = {token for token in offer.title.lower().split() if token}
        relevance = len(query_tokens & title_tokens) / max(1, len(query_tokens))
        observed = sum(1 for status in offer.field_status.values() if status == "observed")
        completeness = observed / max(1, len(offer.field_status))
        missing = sorted(name for name, status in offer.field_status.items() if status == "missing")
        composite = round(relevance * 0.4 + completeness * 0.4 + offer.confidence * 0.2, 4)
        scored.append({
            "listing_id": offer.external_listing_id, "title": offer.title, "source": offer.source,
            "source_url": offer.source_url, "relevance_score": round(relevance, 4),
            "evidence_completeness": round(completeness, 4), "extraction_confidence": offer.confidence,
            "composite_score": composite, "missing_evidence": missing,
        })
    return sorted(scored, key=lambda item: item["composite_score"], reverse=True)


def health() -> AdapterHealth:
    return AdapterHealth(
        SOURCE_PREFIX, configured=True, reachable=False,
        capabilities=("public_page_fetch", "jsonld_extraction", "cache", "multi_source"),
        detail="live reachability to competitor storefronts not verified in this environment; see docs/COMPETITION_INTELLIGENCE.md",
    )


__all__ = [
    "CompetitorOffer", "FIELD_STATUSES", "KNOWN_SOURCE_LABELS", "SOURCE_PREFIX",
    "fetch_competitor_offer", "health", "score_offers",
]

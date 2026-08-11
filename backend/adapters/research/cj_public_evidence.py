"""backend.adapters.research.cj_public_evidence — public, no-auth CJ
Dropshipping product-page evidence.

Phase 1 selected supplier evidence source (public pages only — no login, no
API key, no session). This is deliberately a *different* data path from
``backend.validation.suppliers.CJDropshippingClient``, which already wraps
CJ's authenticated catalog API and requires ``CJ_EMAIL``/``CJ_API_KEY``.
Nothing here talks to that authenticated API or duplicates its token
management; the two are related only by supplier name and are never
silently conflated (``source`` on every record here is ``cj_public_page``,
never ``cj_dropshipping``).

Extraction transport is plain ``requests`` + a regex-based JSON-LD
(schema.org ``Product``) parser reused from
``backend.adapters.research.crawl4ai.Crawl4AIResearchAdapter`` — Crawl4AI
itself (Playwright-based) was evaluated and deliberately not adopted for
this module; see docs/CJ_PUBLIC_SUPPLIER_EVIDENCE.md for the evidence
behind that decision (network egress to cjdropshipping.com is blocked by
this development sandbox's own policy, so browser-based extraction could
not be verified here, Crawl4AI already sits in
``requirements-oss.txt``/``docs/oss/LICENSE_MANIFEST.yml`` as an
optional/pending-review dependency rather than an installed one, and
``requests``/``beautifulsoup4``/``lxml`` are already first-class
dependencies — this module needs none of the three additionally).

Every field on ``CJProductEvidence`` is paired with a provenance status in
``field_status`` (see FIELD_STATUSES). Nothing here fabricates a plausible
value for a field the page didn't actually expose — an unresolved field is
reported ``"unavailable"``, never guessed.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import re
import socket
import time
from dataclasses import dataclass, field as dataclass_field
from typing import Any
from urllib import robotparser
from urllib.parse import quote_plus, urlparse

from backend.adapters.research.crawl4ai import Crawl4AIResearchAdapter, phase1_js_render_enabled
from backend.contracts.adapters import AdapterHealth, SidecarContext
from evaluation.contracts import DataQuality, ProductCandidate, SupplierOffer

_log = logging.getLogger(__name__)

SOURCE = "cj_public_page"
ALLOWED_HOSTS = {"cjdropshipping.com", "www.cjdropshipping.com"}
SEARCH_URL_TEMPLATE = "https://www.cjdropshipping.com/search?keyword={query}"
DEFAULT_TIMEOUT_S = 10
MAX_RESPONSE_BYTES = 2_000_000
USER_AGENT = "MarketOS-SupplierEvidence/1.0 (+https://github.com/ChristianV997/MarketOS)"

# Field-level provenance vocabulary. A field is "observed" only when the
# page's own structured data supplied it — never inferred to fill a gap.
FIELD_STATUSES = ("observed", "derived", "assumed", "unavailable", "malformed", "stale", "conflicting")

_EVIDENCE_FIELDS = (
    "title", "price", "sku", "category", "variants", "weight_kg", "inventory_status",
    "warehouse_origin", "shipping_cost", "estimated_delivery_days", "quality_evidence",
    "rating", "reviews_count", "images", "description",
)


@dataclass(frozen=True)
class CJProductEvidence:
    """One CJ public product-page observation with field-level provenance."""

    source: str
    source_url: str
    observed_at: float
    external_product_id: str
    title: str
    field_status: dict[str, str] = dataclass_field(default_factory=dict)
    sku: str = ""
    category: str = ""
    price: float | None = None
    currency: str = "USD"
    variants: tuple[dict[str, Any], ...] = ()
    weight_kg: float | None = None
    inventory_status: str = "unavailable_publicly"
    warehouse_origin: str = ""
    shipping_cost: float | None = None
    estimated_delivery_days: int | None = None
    quality_evidence: str = ""
    rating: float | None = None
    reviews_count: int | None = None
    images: tuple[str, ...] = ()
    description: str = ""
    extraction_method: str = "jsonld_schema_org_product"
    confidence: float = 0.0
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source, "source_url": self.source_url, "observed_at": self.observed_at,
            "external_product_id": self.external_product_id, "title": self.title, "sku": self.sku,
            "category": self.category, "price": self.price, "currency": self.currency,
            "variants": [dict(v) for v in self.variants], "weight_kg": self.weight_kg,
            "inventory_status": self.inventory_status, "warehouse_origin": self.warehouse_origin,
            "shipping_cost": self.shipping_cost, "estimated_delivery_days": self.estimated_delivery_days,
            "quality_evidence": self.quality_evidence, "rating": self.rating, "reviews_count": self.reviews_count,
            "images": list(self.images), "description": self.description,
            "field_status": dict(self.field_status), "extraction_method": self.extraction_method,
            "confidence": self.confidence, "warnings": list(self.warnings),
        }


def _degraded(source_url: str, *, reason: str, extraction_method: str = "none") -> CJProductEvidence:
    """A structurally valid, fully-honest "observed nothing" result — the
    fallback for every rejected/blocked/failed path below, never an
    exception the caller must handle specially."""
    return CJProductEvidence(
        source=SOURCE, source_url=source_url, observed_at=time.time(),
        external_product_id=hashlib.sha256(source_url.encode()).hexdigest()[:16],
        title="", field_status={name: "unavailable" for name in _EVIDENCE_FIELDS},
        extraction_method=extraction_method, confidence=0.0, warnings=(reason,),
    )


def _validate_public_url(url: str) -> str:
    """Return the validated hostname, or raise ValueError/PermissionError.

    Resolves DNS and rejects private/loopback/link-local/reserved/multicast
    destinations (SSRF-by-DNS-rebinding guard, not just a string check on
    the literal hostname), and restricts the host to the one selected
    Phase 1 supplier source.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("evidence URL must be http(s)")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("evidence URL has no hostname")
    if not any(hostname == host or hostname.endswith("." + host) for host in ALLOWED_HOSTS):
        raise PermissionError(f"host is not the selected Phase 1 supplier source: {hostname}")
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
    ttl_s = max(0.0, float(os.getenv("CJ_EVIDENCE_CACHE_TTL_S", "900")))
    cached = _CACHE.get(url)
    if cached and time.monotonic() - cached[0] < ttl_s:
        return cached[1]
    if cached:
        _CACHE.pop(url, None)
    return None


def _cache_put(url: str, html: str) -> None:
    max_entries = max(1, min(int(os.getenv("CJ_EVIDENCE_CACHE_MAX_ENTRIES", "100")), 1000))
    _CACHE[url] = (time.monotonic(), html)
    if len(_CACHE) > max_entries:
        oldest = min(_CACHE, key=lambda key: _CACHE[key][0])
        _CACHE.pop(oldest, None)


def _bounded_get(url: str, *, timeout: int = DEFAULT_TIMEOUT_S) -> str:
    """Bounded GET: fixed timeout, response-size cap, no automatic redirect
    following (a redirect target is unvalidated by definition, so this
    rejects rather than silently trusting it)."""
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
            raise ValueError("cj_evidence_response_too_large")
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", errors="replace")


def _evidence_from_record(record: dict[str, Any], url: str, *, extraction_method: str) -> CJProductEvidence:
    """Map one shared normalized Product record into supplier evidence."""
    field_status = {name: "unavailable" for name in _EVIDENCE_FIELDS}
    if record.get("name"):
        field_status["title"] = "observed"
    if record.get("selling_price"):
        field_status["price"] = "observed"
    if record.get("product_id"):
        field_status["sku"] = "observed"
    if record.get("availability"):
        field_status["inventory_status"] = "observed"
    if record.get("description"):
        field_status["description"] = "observed"
    if record.get("rating") is not None:
        field_status["rating"] = "observed"
    if record.get("review_count") is not None:
        field_status["reviews_count"] = "observed"
    if record.get("image"):
        field_status["images"] = "observed"
    if record.get("shipping_cost") is not None:
        field_status["shipping_cost"] = "observed"
    confidence = round(sum(1 for status in field_status.values() if status == "observed") / len(field_status), 3)
    warnings = () if field_status["price"] == "observed" else ("price_not_found_in_structured_data",)
    image = record.get("image")
    images = (str(image),) if image else ()
    return CJProductEvidence(
        source=SOURCE, source_url=url, observed_at=time.time(),
        external_product_id=str(record.get("product_id") or hashlib.sha256(url.encode()).hexdigest()[:16]),
        title=str(record.get("name", "")), field_status=field_status,
        sku=str(record.get("product_id", "")),
        price=record.get("selling_price") or None, currency=str(record.get("currency", "USD")),
        inventory_status=str(record.get("availability") or "unavailable_publicly"),
        shipping_cost=record.get("shipping_cost"),
        rating=record.get("rating"), reviews_count=record.get("review_count"),
        images=images, description=str(record.get("description", "")),
        extraction_method=extraction_method, confidence=confidence, warnings=warnings,
    )


def _extract_from_jsonld(html: str, url: str) -> CJProductEvidence | None:
    """Reuses Crawl4AIResearchAdapter's JSON-LD Product parser rather than
    duplicating it — the same conservative rule applies: a page without a
    valid schema.org Product object yields no evidence, never a guess."""
    records = Crawl4AIResearchAdapter._product_records_from_jsonld(html, url)
    if not records:
        return None
    return _evidence_from_record(records[0], url, extraction_method="jsonld_schema_org_product")


def _extract_with_optional_js_render(url: str, *, context: SidecarContext) -> CJProductEvidence | None:
    """Try the explicitly enabled, allowlisted Crawl4AI fallback."""
    if context.dry_run or not phase1_js_render_enabled():
        return None
    try:
        records = Crawl4AIResearchAdapter().discover_sync(url, context=context)
    except Exception as exc:  # noqa: BLE001 - optional boundary must degrade
        _log.warning("cj_evidence_js_render_failed error=%s", type(exc).__name__)
        return None
    if not records:
        return None
    return _evidence_from_record(records[0], url, extraction_method="crawl4ai_js_rendered_structured_product")


def fetch_product_evidence(url: str, *, context: SidecarContext) -> CJProductEvidence:
    """Never raises. Always returns a structurally valid CJProductEvidence —
    degraded (all fields "unavailable") on any rejection, block, or
    failure, so callers never need a special error path."""
    try:
        hostname = _validate_public_url(url)
    except (ValueError, PermissionError) as exc:
        return _degraded(url, reason=f"rejected:{exc}")
    if context.dry_run:
        return _degraded(url, reason="dry_run_simulated", extraction_method="simulated")
    try:
        _check_robots(hostname, url)
    except PermissionError as exc:
        return _degraded(url, reason=f"robots_blocked:{exc}")
    html = _cache_get(url)
    fetch_failure: str | None = None
    if html is None:
        try:
            html = _bounded_get(url)
        except Exception as exc:  # noqa: BLE001 - network boundary must degrade, never raise
            _log.warning("cj_evidence_fetch_failed url=%s error=%s", url, type(exc).__name__)
            fetch_failure = f"fetch_failed:{type(exc).__name__}"
        else:
            _cache_put(url, html)
    evidence = _extract_from_jsonld(html, url) if html is not None else None
    if evidence is None:
        rendered = _extract_with_optional_js_render(url, context=context)
        if rendered is not None:
            return rendered
        return _degraded(url, reason=fetch_failure or "no_structured_product_data_found")
    return evidence


def build_search_url(query: str) -> str:
    return SEARCH_URL_TEMPLATE.format(query=quote_plus(query.strip()))


def discover_candidate_urls(query: str, *, context: SidecarContext, max_results: int = 5) -> list[str]:
    """Best-effort discovery of CJ product URLs for a query.

    UNVERIFIED in this development environment: CJ's search-results page
    may render product cards via client-side JS, which a plain HTTP GET
    cannot execute — this could not be confirmed here because outbound
    network access to cjdropshipping.com is blocked by this sandbox's own
    egress policy (see docs/CJ_PUBLIC_SUPPLIER_EVIDENCE.md). This function
    looks for plain ``<a href="/product/...">`` links in whatever HTML is
    returned; if the page is JS-rendered this will legitimately return an
    empty list rather than guessing, and operator-supplied product URLs
    remain the reliable Phase 1 path (see fetch_product_evidence).
    """
    search_url = build_search_url(query)
    try:
        hostname = _validate_public_url(search_url)
    except (ValueError, PermissionError):
        return []
    if context.dry_run:
        return []
    try:
        _check_robots(hostname, search_url)
        html = _cache_get(search_url)
        if html is None:
            html = _bounded_get(search_url)
            _cache_put(search_url, html)
    except Exception as exc:  # noqa: BLE001 - discovery degrades to empty, never raises
        _log.info("cj_discovery_unavailable query=%s error=%s", query, type(exc).__name__)
        return []
    urls: list[str] = []
    for match in re.finditer(r'href=["\'](https://www\.cjdropshipping\.com/product/[^"\'#?]+)', html):
        candidate = match.group(1)
        if candidate not in urls:
            urls.append(candidate)
        if len(urls) >= max_results:
            break
    return urls


def to_supplier_offer(evidence: CJProductEvidence, *, supplier_id: str = SOURCE) -> SupplierOffer | None:
    """None when no observed cost evidence exists.

    Unlike a general-purpose retail-site crawl (where a page price is a
    *selling* price to end consumers, not a wholesale cost — see
    Crawl4AIResearchAdapter.normalize_supplier_offers's caution), a CJ
    Dropshipping product page's price genuinely is what MarketOS would pay
    to source the item: CJ is a wholesale/dropship supplier catalog, not a
    retail storefront selling to the public. Treating that observed price
    as unit_cost is therefore correct here, not an inference.
    """
    if evidence.price is None or evidence.field_status.get("price") != "observed":
        return None
    incomplete = any(status == "unavailable" for status in evidence.field_status.values())
    return SupplierOffer(
        supplier_id=supplier_id, product_id=evidence.external_product_id,
        unit_cost=evidence.price, shipping_cost=evidence.shipping_cost or 0.0,
        fulfillment_days=evidence.estimated_delivery_days,
        currency=evidence.currency,
        quality=DataQuality(
            provenance="live", attribution="attributed", source_ref=evidence.source_url,
            completeness="partial" if incomplete else "complete",
        ),
    )


def to_product_candidate(evidence: CJProductEvidence) -> ProductCandidate | None:
    if not evidence.title:
        return None
    return ProductCandidate(
        product_id=evidence.external_product_id, name=evidence.title, currency=evidence.currency,
        selling_price=evidence.price or 0.0, source_signal_ids=(evidence.source_url,),
        quality=DataQuality(
            provenance="live" if evidence.field_status.get("title") == "observed" else "unknown",
            attribution="attributed", source_ref=evidence.source_url,
        ),
    )


def score_candidates(evidences: list[CJProductEvidence], query: str) -> list[dict[str, Any]]:
    """Deterministic supplier-evidence comparison, ranked highest first.

    Unknown fields reduce confidence; they are never treated as favorable
    evidence and never silently become a zero-cost/zero-risk assumption.
    """
    query_tokens = {token for token in query.lower().split() if token}
    scored: list[dict[str, Any]] = []
    for evidence in evidences:
        title_tokens = {token for token in evidence.title.lower().split() if token}
        relevance = len(query_tokens & title_tokens) / max(1, len(query_tokens))
        observed = sum(1 for status in evidence.field_status.values() if status == "observed")
        completeness = observed / max(1, len(evidence.field_status))
        missing = sorted(name for name, status in evidence.field_status.items() if status == "unavailable")
        conflicting = sorted(name for name, status in evidence.field_status.items() if status == "conflicting")
        composite = round(relevance * 0.4 + completeness * 0.4 + evidence.confidence * 0.2, 4)
        scored.append({
            "product_id": evidence.external_product_id, "title": evidence.title,
            "source_url": evidence.source_url, "relevance_score": round(relevance, 4),
            "evidence_completeness": round(completeness, 4), "extraction_confidence": evidence.confidence,
            "composite_score": composite, "missing_evidence": missing, "conflicting_evidence": conflicting,
            "assumptions_still_required": [name for name in missing if name in
                                            {"weight_kg", "shipping_cost", "warehouse_origin", "estimated_delivery_days"}],
        })
    return sorted(scored, key=lambda item: item["composite_score"], reverse=True)


def health() -> AdapterHealth:
    return AdapterHealth(
        SOURCE, configured=True, reachable=False,
        capabilities=("public_page_fetch", "jsonld_extraction", "cache"),
        detail="live reachability to cjdropshipping.com not verified in this environment; see docs/CJ_PUBLIC_SUPPLIER_EVIDENCE.md",
    )


__all__ = [
    "CJProductEvidence", "FIELD_STATUSES", "SOURCE",
    "build_search_url", "discover_candidate_urls", "fetch_product_evidence",
    "health", "score_candidates", "to_product_candidate", "to_supplier_offer",
]

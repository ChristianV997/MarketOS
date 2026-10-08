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
import math
import os
import re
import socket
import time
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timezone
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
    "title", "price", "currency", "sku", "category", "variants", "weight_kg", "inventory_status",
    "inventory_quantity", "warehouse_origin", "shipping_cost", "shipping_currency", "estimated_delivery_days", "quality_evidence",
    "rating", "reviews_count", "images", "description",
)


@dataclass(frozen=True)
class CJProductEvidence:
    """One CJ page observation; timestamps denote fetch time, not page update time."""

    source: str
    source_url: str
    observed_at: float | None
    external_product_id: str
    title: str
    fetched_at: float | None = None
    field_status: dict[str, str] = dataclass_field(default_factory=dict)
    sku: str = ""
    category: str = ""
    price: float | None = None
    currency: str | None = None
    variants: tuple[dict[str, Any], ...] = ()
    weight_kg: float | None = None
    inventory_status: str = "unavailable_publicly"
    inventory_quantity: int | None = None
    warehouse_origin: str = ""
    shipping_cost: float | None = None
    shipping_currency: str | None = None
    estimated_delivery_days: int | None = None
    quality_evidence: str = ""
    rating: float | None = None
    reviews_count: int | None = None
    images: tuple[str, ...] = ()
    description: str = ""
    extraction_method: str = "jsonld_schema_org_product"
    confidence: float = 0.0
    warnings: tuple[str, ...] = ()
    fetch_provenance: str = "unknown"

    def __post_init__(self) -> None:
        # Keep the legacy name while exposing the timestamp's retrieval semantics explicitly.
        if self.fetched_at is None and self.observed_at is not None:
            object.__setattr__(self, "fetched_at", self.observed_at)
        elif self.observed_at is None and self.fetched_at is not None:
            object.__setattr__(self, "observed_at", self.fetched_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source, "source_url": self.source_url, "observed_at": self.observed_at,
            "fetched_at": self.fetched_at,
            "fetch_provenance": self.fetch_provenance,
            "external_product_id": self.external_product_id, "title": self.title, "sku": self.sku,
            "category": self.category, "price": self.price, "currency": self.currency,
            "variants": [dict(v) for v in self.variants], "weight_kg": self.weight_kg,
            "inventory_status": self.inventory_status, "inventory_quantity": self.inventory_quantity,
            "warehouse_origin": self.warehouse_origin,
            "shipping_cost": self.shipping_cost, "shipping_currency": self.shipping_currency,
            "estimated_delivery_days": self.estimated_delivery_days,
            "quality_evidence": self.quality_evidence, "rating": self.rating, "reviews_count": self.reviews_count,
            "images": list(self.images), "description": self.description,
            "field_status": dict(self.field_status), "extraction_method": self.extraction_method,
            "confidence": self.confidence, "warnings": list(self.warnings),
        }


def _degraded(
    source_url: str,
    *,
    reason: str,
    extraction_method: str = "none",
    observed_at: float | None = None,
    fetch_provenance: str = "not_fetched",
) -> CJProductEvidence:
    """A structurally valid, fully-honest "observed nothing" result — the
    fallback for every rejected/blocked/failed path below, never an
    exception the caller must handle specially."""
    return CJProductEvidence(
        source=SOURCE, source_url=source_url, observed_at=observed_at,
        external_product_id=hashlib.sha256(source_url.encode()).hexdigest()[:16],
        title="", fetched_at=observed_at, field_status={name: "unavailable" for name in _EVIDENCE_FIELDS},
        extraction_method=extraction_method, confidence=0.0, warnings=(reason,),
        fetch_provenance=fetch_provenance,
    )


def _validate_public_url(url: str) -> str:
    """Return the validated hostname, or raise ValueError/PermissionError.

    Only the two selected supplier hosts are accepted. The hostname must
    match exactly: a suffix or subdomain is not the allowlisted site.
    Credentials, cleartext, and non-443 ports are rejected. DNS is checked
    for the host that will actually be contacted, not for the raw input.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("evidence URL must be https")
    if parsed.username is not None or parsed.password is not None or parsed.port not in (None, 443):
        raise PermissionError("evidence URL target is not allowed")
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if hostname not in ALLOWED_HOSTS:
        raise PermissionError("host is not the selected Phase 1 supplier source")
    if parsed.scheme != "https":
        raise ValueError("evidence URL must be https")
    connect_host = "www.cjdropshipping.com"
    try:
        infos = socket.getaddrinfo(connect_host, 443)
    except socket.gaierror as exc:
        raise PermissionError("could not resolve evidence host") from exc
    for info in infos:
        addr = info[4][0]
        ip = ipaddress.ip_address(addr)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise PermissionError("evidence host resolves to a disallowed network")
    return hostname


def _safe_request_url(url: str) -> str:
    """Rebuild a request URL whose host is the constant supplier origin."""
    _validate_public_url(url)
    parsed = urlparse(url)
    path = parsed.path or "/"
    if not path.startswith("/") or path.startswith("//") or "\\" in path or "\r" in url or "\n" in url:
        raise PermissionError("evidence URL target is not allowed")
    safe = "https://www.cjdropshipping.com" + path
    if parsed.query:
        safe += "?" + parsed.query
    return safe


def _check_robots(hostname: str, url: str) -> None:
    robots = robotparser.RobotFileParser(f"https://{hostname}/robots.txt")
    try:
        robots.read()
    except Exception as exc:  # noqa: BLE001 - an unverifiable robots.txt must block, not silently proceed
        raise PermissionError(f"robots.txt could not be verified for {hostname}") from exc
    if not robots.can_fetch(USER_AGENT, url):
        raise PermissionError(f"robots.txt disallows evidence URL: {url}")


_CacheEntry = tuple[float, str] | tuple[float, str, float | None]
_CACHE: dict[str, _CacheEntry] = {}


def _cache_get(url: str) -> tuple[str, float | None] | None:
    ttl_s = max(0.0, float(os.getenv("CJ_EVIDENCE_CACHE_TTL_S", "900")))
    cached = _CACHE.get(url)
    if cached and time.monotonic() - cached[0] < ttl_s:
        fetched_at = cached[2] if len(cached) == 3 else None
        return cached[1], fetched_at
    if cached:
        _CACHE.pop(url, None)
    return None


def _cache_put(url: str, html: str, *, fetched_at: float | None = None) -> None:
    max_entries = max(1, min(int(os.getenv("CJ_EVIDENCE_CACHE_MAX_ENTRIES", "100")), 1000))
    _CACHE[url] = (time.monotonic(), html, fetched_at)
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


def _evidence_from_record(
    record: dict[str, Any],
    url: str,
    *,
    extraction_method: str,
    observed_at: float | None = None,
    fetch_provenance: str = "unknown",
) -> CJProductEvidence:
    """Map one shared normalized Product record into supplier evidence."""
    field_status = {name: "unavailable" for name in _EVIDENCE_FIELDS}
    if record.get("name"):
        field_status["title"] = "observed"
    raw_price = record.get("selling_price")
    price: float | None = None
    if raw_price is not None:
        try:
            parsed_price = float(raw_price)
        except (TypeError, ValueError):
            parsed_price = math.nan
        if math.isfinite(parsed_price):
            price = parsed_price
            field_status["price"] = "observed"
        else:
            field_status["price"] = "malformed"
    raw_currency = record.get("currency")
    currency = str(raw_currency).strip().upper() if isinstance(raw_currency, str) and raw_currency.strip() else None
    if currency is not None:
        field_status["currency"] = "observed"
    elif raw_currency is not None:
        field_status["currency"] = "malformed"
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
    raw_shipping = record.get("shipping_cost")
    shipping_cost: float | None = None
    if raw_shipping is not None:
        try:
            parsed_shipping = float(raw_shipping)
        except (TypeError, ValueError):
            parsed_shipping = math.nan
        if math.isfinite(parsed_shipping) and parsed_shipping >= 0:
            shipping_cost = parsed_shipping
            field_status["shipping_cost"] = "observed"
        else:
            field_status["shipping_cost"] = "malformed"
    elif record.get("shipping_cost_status") == "malformed":
        field_status["shipping_cost"] = "malformed"
    raw_shipping_currency = record.get("shipping_currency")
    shipping_currency = (
        str(raw_shipping_currency).strip().upper()
        if isinstance(raw_shipping_currency, str) and raw_shipping_currency.strip() else None
    )
    if shipping_currency is not None:
        field_status["shipping_currency"] = "observed"
    elif raw_shipping_currency is not None:
        field_status["shipping_currency"] = "malformed"
    confidence = round(sum(1 for status in field_status.values() if status == "observed") / len(field_status), 3)
    warnings = []
    if price is None:
        warnings.append(
            "price_malformed_in_structured_data"
            if field_status["price"] == "malformed" else "price_not_found_in_structured_data"
        )
    elif price <= 0:
        warnings.append("price_not_usable_as_supplier_cost")
    if price is not None and currency is None:
        warnings.append("price_currency_unavailable")
    if field_status["shipping_cost"] == "malformed":
        warnings.append("shipping_cost_malformed_in_structured_data")
    if shipping_cost is not None and shipping_currency is None:
        warnings.append("shipping_currency_unavailable")
    image = record.get("image")
    images = (str(image),) if image else ()
    return CJProductEvidence(
        source=SOURCE, source_url=url, observed_at=observed_at,
        external_product_id=str(record.get("product_id") or hashlib.sha256(url.encode()).hexdigest()[:16]),
        title=str(record.get("name", "")), fetched_at=observed_at, field_status=field_status,
        sku=str(record.get("product_id", "")),
        price=price, currency=currency,
        inventory_status=str(record.get("availability") or "unavailable_publicly"),
        shipping_cost=shipping_cost, shipping_currency=shipping_currency,
        rating=record.get("rating"), reviews_count=record.get("review_count"),
        images=images, description=str(record.get("description", "")),
        extraction_method=extraction_method, confidence=confidence, warnings=tuple(warnings),
        fetch_provenance=fetch_provenance,
    )


def _extract_from_jsonld(
    html: str,
    url: str,
    *,
    observed_at: float | None = None,
    fetch_provenance: str = "unknown",
) -> CJProductEvidence | None:
    """Reuses Crawl4AIResearchAdapter's JSON-LD Product parser rather than
    duplicating it — the same conservative rule applies: a page without a
    valid schema.org Product object yields no evidence, never a guess."""
    records = Crawl4AIResearchAdapter._product_records_from_jsonld(html, url)
    if not records:
        return None
    return _evidence_from_record(
        records[0], url, extraction_method="jsonld_schema_org_product",
        observed_at=observed_at, fetch_provenance=fetch_provenance,
    )


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
    record = records[0]
    fetched_at: float | None = None
    try:
        raw_fetched_at = record.get("fetched_at")
        fetched_at = float(raw_fetched_at) if raw_fetched_at is not None else None
        if fetched_at is not None and not math.isfinite(fetched_at):
            fetched_at = None
    except (TypeError, ValueError):
        fetched_at = None
    fetch_provenance = str(record.get("retrieval_mode") or "unknown")
    if fetched_at is None or fetch_provenance not in {"fresh_fetch", "cache_hit"}:
        fetched_at = None
        fetch_provenance = "renderer_timestamp_unavailable"
    return _evidence_from_record(
        record, url, observed_at=fetched_at,
        extraction_method="crawl4ai_js_rendered_structured_product",
        fetch_provenance=fetch_provenance,
    )


def fetch_product_evidence(url: str, *, context: SidecarContext) -> CJProductEvidence:
    """Never raises. Always returns a structurally valid CJProductEvidence —
    degraded (all fields "unavailable") on any rejection, block, or
    failure, so callers never need a special error path."""
    try:
        safe_url = _safe_request_url(url)
    except (ValueError, PermissionError) as exc:
        return _degraded(url, reason=f"rejected:{exc}")
    if context.dry_run:
        return _degraded(url, reason="dry_run_simulated", extraction_method="simulated")
    try:
        _check_robots("www.cjdropshipping.com", safe_url)
    except PermissionError as exc:
        return _degraded(url, reason=f"robots_blocked:{exc}")
    cached = _cache_get(safe_url)
    fetch_failure: str | None = None
    html: str | None = None
    fetched_at: float | None = None
    fetch_provenance = "fetch_failed"
    if cached is not None:
        html, fetched_at = cached
        fetch_provenance = "cache_hit" if fetched_at is not None else "cache_hit_timestamp_unknown"
    else:
        try:
            html = _bounded_get(safe_url)
        except Exception as exc:  # noqa: BLE001 - network boundary must degrade, never raise
            _log.warning("cj_evidence_fetch_failed error=%s", type(exc).__name__)
            fetch_failure = f"fetch_failed:{type(exc).__name__}"
        else:
            fetched_at = time.time()
            fetch_provenance = "fresh_fetch"
            _cache_put(safe_url, html, fetched_at=fetched_at)
    evidence = (
        _extract_from_jsonld(
            html, safe_url, observed_at=fetched_at, fetch_provenance=fetch_provenance,
        )
        if html is not None else None
    )
    if evidence is None:
        rendered = _extract_with_optional_js_render(safe_url, context=context)
        if rendered is not None:
            return rendered
        return _degraded(
            safe_url,
            reason=fetch_failure or "no_structured_product_data_found",
            observed_at=fetched_at,
            fetch_provenance=fetch_provenance,
        )
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
        safe_url = _safe_request_url(search_url)
    except (ValueError, PermissionError):
        return []
    if context.dry_run:
        return []
    try:
        _check_robots("www.cjdropshipping.com", safe_url)
        cached = _cache_get(safe_url)
        if cached is not None:
            html, _ = cached
        else:
            html = _bounded_get(safe_url)
            _cache_put(safe_url, html, fetched_at=time.time())
    except Exception as exc:  # noqa: BLE001 - discovery degrades to empty, never raises
        _log.info("cj_discovery_unavailable error=%s", type(exc).__name__)
        return []
    urls: list[str] = []
    for match in re.finditer(r'href=["\'](https://www\.cjdropshipping\.com/product/[^"\'#?]+)', html):
        candidate = match.group(1)
        if candidate not in urls:
            urls.append(candidate)
        if len(urls) >= max_results:
            break
    return urls


def _has_known_fetch(evidence: CJProductEvidence) -> bool:
    if evidence.source != SOURCE or evidence.fetch_provenance not in {"fresh_fetch", "cache_hit"}:
        return False
    fetched_at = evidence.fetched_at if evidence.fetched_at is not None else evidence.observed_at
    if fetched_at is None:
        return False
    try:
        timestamp = float(fetched_at)
        return math.isfinite(timestamp) and timestamp >= 0
    except (TypeError, ValueError):
        return False


def _quality_from_evidence(evidence: CJProductEvidence) -> DataQuality:
    """Public-page quality only; use the original fetch time and retrieval mode."""
    if not _has_known_fetch(evidence):
        raise ValueError("public-page quality requires known fetch provenance and timestamp")
    fetched_at = evidence.fetched_at if evidence.fetched_at is not None else evidence.observed_at
    if fetched_at is None:
        raise ValueError("public-page quality requires an observation timestamp")
    observed_at = float(fetched_at)
    return DataQuality(
        provenance="public_page",
        attribution="attributed",
        completeness="partial",
        source_ref=evidence.source_url,
        observed_at=datetime.fromtimestamp(observed_at, tz=timezone.utc),
        retrieval_mode=evidence.fetch_provenance,
    )


def _observed_number(evidence: CJProductEvidence, field_name: str) -> float | None:
    """Return an observed numeric field, preserving explicit zeros. Missing stays None."""
    if evidence.field_status.get(field_name) != "observed":
        return None
    value = getattr(evidence, field_name, None)
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def to_supplier_offer(evidence: CJProductEvidence, *, supplier_id: str = SOURCE) -> SupplierOffer | None:
    """None when observed unit cost or shipping cannot be represented honestly.

    A public CJ page can expose a candidate catalog price, but that
    observation is not authenticated supplier-live proof. Preserve that
    distinction in DataQuality so generic commerce gates do not accept it as
    live-attributed evidence.

    ``SupplierOffer.shipping_cost`` is a non-optional float in evaluation
    contracts, so a missing shipping observation must not become ``0.0``
    (free shipping). Callers that need nullable shipping use
    ``SupplierEvidenceResult`` instead.
    """
    unit_cost = _observed_number(evidence, "price")
    shipping_cost = _observed_number(evidence, "shipping_cost")
    if (
        not _has_known_fetch(evidence)
        or unit_cost is None
        or unit_cost <= 0
        or shipping_cost is None
        or shipping_cost < 0
        or not evidence.currency
        or not evidence.shipping_currency
        or evidence.currency != evidence.shipping_currency
    ):
        return None
    return SupplierOffer(
        supplier_id=supplier_id, product_id=evidence.external_product_id,
        unit_cost=unit_cost, shipping_cost=shipping_cost,
        fulfillment_days=evidence.estimated_delivery_days,
        currency=evidence.currency,
        quality=_quality_from_evidence(evidence),
    )


def to_product_candidate(evidence: CJProductEvidence) -> ProductCandidate | None:
    """Return a priced public-page candidate; never encode a missing price as 0."""
    if (
        not _has_known_fetch(evidence)
        or not evidence.title
        or not evidence.currency
    ):
        return None
    price = _observed_number(evidence, "price")
    if price is None or price <= 0:
        return None
    return ProductCandidate(
        product_id=evidence.external_product_id, name=evidence.title, currency=evidence.currency,
        selling_price=price, source_signal_ids=(evidence.source_url,),
        quality=_quality_from_evidence(evidence),
    )


def score_candidates(evidences: list[CJProductEvidence], query: str) -> list[dict[str, Any]]:
    """Deterministic public-page-evidence comparison, ranked highest first.

    Unknown fields reduce confidence; they are never treated as favorable
    evidence and never silently become a zero-cost/zero-risk assumption.
    These scores are public-page observations, never supplier-live proof.
    """
    query_tokens = {token for token in query.lower().split() if token}
    scored: list[dict[str, Any]] = []
    for evidence in evidences:
        title_tokens = {token for token in evidence.title.lower().split() if token}
        relevance = len(query_tokens & title_tokens) / max(1, len(query_tokens))
        observed = sum(1 for status in evidence.field_status.values() if status == "observed")
        completeness = observed / max(1, len(evidence.field_status))
        missing = sorted(name for name, status in evidence.field_status.items() if status == "unavailable")
        invalid = sorted(
            name for name, status in evidence.field_status.items()
            if status == "malformed" or (name == "price" and status == "observed" and evidence.price is not None and evidence.price <= 0)
        )
        conflicting = sorted(name for name, status in evidence.field_status.items() if status == "conflicting")
        composite = round(relevance * 0.4 + completeness * 0.4 + evidence.confidence * 0.2, 4)
        scored.append({
            "product_id": evidence.external_product_id, "title": evidence.title,
            "source_url": evidence.source_url, "relevance_score": round(relevance, 4),
            "evidence_completeness": round(completeness, 4), "extraction_confidence": evidence.confidence,
            "evidence_mode": "public_page_observation", "supplier_live_proof": False,
            "composite_score": composite, "missing_evidence": missing, "invalid_evidence": invalid,
            "conflicting_evidence": conflicting,
            "assumptions_still_required": [name for name in (*missing, *invalid) if name in
                                            {"price", "weight_kg", "shipping_cost", "warehouse_origin", "estimated_delivery_days"}],
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

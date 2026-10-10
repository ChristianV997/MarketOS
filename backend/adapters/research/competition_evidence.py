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

import csv
import hashlib
import io
import ipaddress
import json
import logging
import os
import re
import socket
import time
import unicodedata
from dataclasses import dataclass, field as dataclass_field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from urllib import robotparser
from urllib.parse import urlparse

from backend.adapters.research.crawl4ai import Crawl4AIResearchAdapter, phase1_js_render_enabled
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


def _offer_from_record(record: dict[str, Any], url: str, *, source: str, extraction_method: str) -> CompetitorOffer:
    """Map one shared normalized Product record into competitor evidence."""
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
        extraction_method=extraction_method, confidence=confidence, warnings=warnings,
    )


def _extract_from_jsonld(html: str, url: str, *, source: str) -> CompetitorOffer | None:
    """Reuses Crawl4AIResearchAdapter's JSON-LD Product parser (extended
    additively with rating/review_count/seller/image/shipping_cost — see
    crawl4ai.py) rather than a second parser. A page without a valid
    schema.org Product object yields no evidence, never a guess."""
    records = Crawl4AIResearchAdapter._product_records_from_jsonld(html, url)
    if not records:
        return None
    return _offer_from_record(records[0], url, source=source, extraction_method="jsonld_schema_org_product")


def _extract_with_optional_js_render(url: str, *, source: str, context: SidecarContext) -> CompetitorOffer | None:
    """Try the explicitly enabled, allowlisted Crawl4AI fallback."""
    if context.dry_run or not phase1_js_render_enabled():
        return None
    try:
        records = Crawl4AIResearchAdapter().discover_sync(url, context=context)
    except Exception as exc:  # noqa: BLE001 - optional boundary must degrade
        _log.warning("competition_evidence_js_render_failed error=%s", type(exc).__name__)
        return None
    if not records:
        return None
    return _offer_from_record(records[0], url, source=source, extraction_method="crawl4ai_js_rendered_structured_product")


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
    fetch_failure: str | None = None
    if html is None:
        try:
            html = _bounded_get(url)
        except Exception as exc:  # noqa: BLE001 - network boundary must degrade, never raise
            _log.warning("competition_evidence_fetch_failed url=%s error=%s", url, type(exc).__name__)
            fetch_failure = f"fetch_failed:{type(exc).__name__}"
        else:
            _cache_put(url, html)
    offer = _extract_from_jsonld(html, url, source=resolved_source) if html is not None else None
    if offer is None:
        rendered = _extract_with_optional_js_render(url, source=resolved_source, context=context)
        if rendered is not None:
            return rendered
        return _degraded(url, source=resolved_source, reason=fetch_failure or "no_structured_product_data_found")
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


_CANDIDATE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_LISTING_ID = _CANDIDATE_ID
_PII_HEADERS = {
    "email", "phone", "name", "customer", "customer name", "address", "notes", "note",
    "billing name", "billing address", "shipping name", "shipping address",
}
_PII_HEADER_TOKENS = {"email", "e-mail", "phone", "mobile", "tel", "telephone", "fax", "whatsapp"}
_EMAIL = re.compile(
    r"(?i)(?<![\w])[a-z0-9._%+\-]{1,64}\s*@\s*[a-z0-9][a-z0-9.\-]{0,80}\.[a-z]{2,24}(?![\w])"
)
_OBFUSCATED_EMAIL = re.compile(
    r"(?i)(?<![\w])[a-z0-9._%+\-]{1,64}\s*(?:\(\s*at\s*\)|\[\s*at\s*\]|\{\s*at\s*\})\s*"
    r"[a-z0-9][a-z0-9.\-]{0,80}\.[a-z]{2,24}(?![\w])"
)
_OBFUSCATED_DOT_EMAIL = re.compile(
    r"(?i)(?<![\w])[a-z0-9._%+\-]{1,64}\s*"
    r"(?:\(\s*at\s*\)|\[\s*at\s*\]|\{\s*at\s*\}|\bat\b)\s*"
    r"[a-z0-9][a-z0-9\-]{0,62}\s*"
    r"(?:\(\s*dot\s*\)|\[\s*dot\s*\]|\{\s*dot\s*\}|\bdot\b)\s*"
    r"[a-z]{2,24}(?![\w])"
)
_NANP = re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?(?:\([2-9]\d{2}\)[-.\s]?|[2-9]\d{2}[-.\s]?)[2-9]\d{2}[-.\s]?\d{4}(?!\d)")
_INTL_PHONE = re.compile(r"(?<!\w)(?:\+|00|011)\d{1,3}(?:[-.\s()]+\d{2,4}){2,5}(?!\d)")
_E164 = re.compile(r"(?<!\w)(?:\+|00|011)\d{8,15}(?!\d)")
_CONTACT_SCHEME = re.compile(r"(?i)(?:mailto|tel)\s*:")
_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff\u2060\u180e"), None)
_DASHES = str.maketrans({"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2212": "-"})
_MAPPED_HEADERS = {
    "listing id": "listing_id", "external listing id": "listing_id", "listing_id": "listing_id",
    "title": "title", "price": "price", "currency": "currency", "availability": "availability",
    "shipping cost": "shipping_cost", "shipping_cost": "shipping_cost", "brand": "brand",
    "seller": "seller", "rating": "rating", "review count": "review_count",
    "variant count": "variant_count", "source url": "source_url", "source": "source",
    "candidate id": "candidate_id", "image": "image",
}


def _csv_header(value: str) -> str:
    text = " ".join(value.strip().lower().replace("_", " ").split())
    return text


def _contact_surface(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).translate(_INVISIBLE).translate(_DASHES)
    text = re.sub(r"(?i)&#x0*40;", "@", text)
    text = text.replace("&" + "amp;#64;", "@").replace("&#64;", "@")
    return text.replace("%2540", "@").replace("%40", "@")


def _is_product_identifier_title(value: str) -> bool:
    """Recognize a standalone, check-digit-valid GTIN title."""
    text = _contact_surface(value).strip()
    if re.fullmatch(r"[0-9]+", text) is None or len(text) not in {8, 12, 13, 14}:
        return False
    digits = [int(digit) for digit in text]
    weighted_sum = sum(
        digit * (3 if index % 2 == 0 else 1)
        for index, digit in enumerate(reversed(digits[:-1]))
    )
    return (10 - weighted_sum % 10) % 10 == digits[-1]


def _contact_like(value: str, *, allow_product_identifier: bool = False) -> bool:
    """High-confidence email or phone only. Ordinary product text, including '@' and SKUs, stays."""
    if not value:
        return False
    text = _contact_surface(value)
    if allow_product_identifier and _is_product_identifier_title(text):
        return False
    if (
        _CONTACT_SCHEME.search(text)
        or _EMAIL.search(text)
        or _OBFUSCATED_EMAIL.search(text)
        or _OBFUSCATED_DOT_EMAIL.search(text)
        or _NANP.search(text)
        or _E164.search(text)
    ):
        return True
    match = _INTL_PHONE.search(text)
    if match is not None and len(re.sub(r"\D", "", match.group(0))) >= 8:
        return True
    digits = re.sub(r"\D", "", text)
    return not re.search(r"[a-zA-Z]", text) and 10 <= len(digits) <= 15


def _header_is_sensitive(header: str) -> bool:
    if _contact_like(header):
        return True
    digits = re.sub(r"\D", "", header)
    return not re.search(r"[a-z]", header) and 10 <= len(digits) <= 15


def _public_header(header: str) -> str:
    if _header_is_sensitive(header) or not re.fullmatch(r"[a-z0-9 ]{1,48}", header):
        return "redacted"
    return header


def _manual_rejection(row_number: int | None, code: str, field_name: str = "") -> dict[str, Any]:
    item: dict[str, Any] = {"code": code}
    if row_number is not None:
        item["row_number"] = row_number
    if field_name:
        item["field"] = field_name
    return item


def _manual_amount(raw: str) -> tuple[float | None, str | None]:
    text = raw.strip()
    if text == "":
        return None, None
    negative = text.startswith("(") and text.endswith(")")
    cleaned = text.strip("()").replace("$", "").replace(",", "").strip()
    if cleaned.startswith("-"):
        negative = True
        cleaned = cleaned[1:].strip()
    try:
        value = Decimal(cleaned)
    except Exception:
        return None, "malformed_amount"
    if not value.is_finite() or abs(value) > Decimal("1000000000000"):
        return None, "malformed_amount"
    quantized = float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return (-quantized if negative else quantized), None


def _classify_manual_header(header: str) -> str:
    tokens = set(header.split())
    if (
        _header_is_sensitive(header)
        or header in _PII_HEADERS
        or bool(tokens & _PII_HEADER_TOKENS)
        or header.startswith("billing ")
        or header.startswith("shipping address")
    ):
        return "pii"
    if header in _MAPPED_HEADERS:
        return "mapped"
    return "unsupported"


def import_manual_competitor_csv(
    text: str,
    *,
    candidate_id: str,
    max_bytes: int = MAX_RESPONSE_BYTES,
    max_rows: int = 10_000,
) -> dict[str, Any]:
    """Parse an operator CSV into competitor offers. Does not fetch or resolve hosts.

    ``candidate_id`` must be supplied explicitly. Titles and seller names are never
    used as that id. Blank amounts stay missing; explicit zero stays zero.
    """
    if not isinstance(candidate_id, str) or not _CANDIDATE_ID.fullmatch(candidate_id) or _contact_like(candidate_id):
        return _manual_result(None, (_manual_rejection(None, "invalid_candidate_id"),))
    if len(text.encode("utf-8")) > max_bytes:
        return _manual_result(candidate_id, (_manual_rejection(None, "file_too_large"),))
    try:
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = list(reader.fieldnames or [])
        raw_rows = list(enumerate(reader, start=2))
    except csv.Error:
        return _manual_result(candidate_id, (_manual_rejection(None, "invalid_csv"),))
    if not fieldnames:
        return _manual_result(candidate_id, (_manual_rejection(None, "empty_csv"),))
    headers = [_csv_header(name) for name in fieldnames if name and name.strip()]
    if any(not name or not name.strip() for name in fieldnames) or len(headers) != len(set(headers)):
        return _manual_result(candidate_id, (_manual_rejection(None, "invalid_header"),))
    unsupported = [header for header in headers if _classify_manual_header(header) == "unsupported"]
    if unsupported:
        return _manual_result(candidate_id, tuple(
            _manual_rejection(None, "unsupported_column", _public_header(header)) for header in sorted(set(unsupported))
        ))
    pii_headers = sorted(header for header in headers if _classify_manual_header(header) == "pii")
    rejections: list[dict[str, Any]] = []
    offers: dict[str, dict[str, Any]] = {}
    conflicts: set[str] = set()
    row_count = 0
    for row_number, raw in raw_rows:
        row_count += 1
        if row_count > max_rows:
            return _manual_result(candidate_id, (_manual_rejection(None, "row_limit_exceeded"),))
        if raw is None or any(key is None for key in raw):
            return _manual_result(candidate_id, (_manual_rejection(row_number, "unsupported_column", "extra"),))
        cells = {_csv_header(key): (value or "") for key, value in raw.items() if key}
        mapped = {_MAPPED_HEADERS[header]: value for header, value in cells.items() if header in _MAPPED_HEADERS}
        row_candidate = mapped.get("candidate_id", "").strip()
        if row_candidate and row_candidate != candidate_id:
            rejections.append(_manual_rejection(row_number, "conflicting_candidate"))
            conflicts.add("__file__")
            continue
        listing_id = mapped.get("listing_id", "").strip()
        if not _LISTING_ID.fullmatch(listing_id):
            rejections.append(_manual_rejection(row_number, "malformed_identity", "listing id"))
            continue
        title = " ".join(mapped.get("title", "").split()).strip()
        seller = " ".join(mapped.get("seller", "").split()).strip()
        brand = " ".join(mapped.get("brand", "").split()).strip()
        availability = " ".join(mapped.get("availability", "").split()).strip()
        source_url_raw = mapped.get("source_url", "").strip()
        source_raw = mapped.get("source", "").strip()
        image_raw = mapped.get("image", "").strip()
        price_raw = mapped.get("price", "")
        shipping_raw = mapped.get("shipping_cost", "")
        rating_raw = mapped.get("rating", "")
        if any(_contact_like(value) for value in (
            (
                title
                if _contact_like(title, allow_product_identifier=True)
                else ""
            ),
            seller, brand, listing_id, availability, source_url_raw, source_raw, image_raw,
            price_raw, shipping_raw, rating_raw,
        )):
            rejections.append(_manual_rejection(row_number, "contact_data_rejected"))
            conflicts.add(listing_id)
            continue
        price, price_error = _manual_amount(mapped.get("price", ""))
        shipping, shipping_error = _manual_amount(mapped.get("shipping_cost", ""))
        rating, rating_error = _manual_amount(mapped.get("rating", ""))
        if price_error or shipping_error or rating_error:
            rejections.append(_manual_rejection(row_number, price_error or shipping_error or rating_error or "malformed_amount", "price"))
            conflicts.add(listing_id)
            continue
        currency_raw = mapped.get("currency", "").strip().upper()
        if currency_raw and not _CURRENCY.fullmatch(currency_raw):
            rejections.append(_manual_rejection(row_number, "malformed_currency", "currency"))
            conflicts.add(listing_id)
            continue
        review_raw = mapped.get("review_count", "").strip()
        variant_raw = mapped.get("variant_count", "").strip()
        review_count = variant_count = None
        if review_raw:
            if not re.fullmatch(r"\d{1,9}", review_raw):
                rejections.append(_manual_rejection(row_number, "malformed_amount", "review count"))
                conflicts.add(listing_id)
                continue
            review_count = int(review_raw)
        if variant_raw:
            if not re.fullmatch(r"\d{1,9}", variant_raw):
                rejections.append(_manual_rejection(row_number, "malformed_amount", "variant count"))
                conflicts.add(listing_id)
                continue
            variant_count = int(variant_raw)
        source_url = mapped.get("source_url", "").strip()
        if source_url:
            parsed = urlparse(source_url)
            if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or _contact_like(source_url):
                rejections.append(_manual_rejection(row_number, "malformed_identity", "source url"))
                conflicts.add(listing_id)
                continue
        source = mapped.get("source", "").strip().lower().replace(" ", "_")
        if source and not re.fullmatch(r"[a-z0-9_]{1,40}", source):
            rejections.append(_manual_rejection(row_number, "malformed_identity", "source"))
            conflicts.add(listing_id)
            continue
        incoming = {
            "listing_id": listing_id,
            "title": title[:160],
            "price": price,
            "currency": currency_raw,
            "shipping_cost": shipping,
            "availability": " ".join(mapped.get("availability", "").split())[:40],
            "brand": brand[:80],
            "seller": seller[:80],
            "rating": rating,
            "review_count": review_count,
            "variant_count": variant_count,
            "source_url": source_url[:300],
            "source": source or "manual_competitor_csv",
            "image": "",
        }
        image = mapped.get("image", "").strip()
        if image and not _contact_like(image) and image.startswith("https://"):
            incoming["image"] = image[:300]
        current = offers.get(listing_id)
        if current is None:
            offers[listing_id] = incoming
            continue
        if current != incoming:
            rejections.append(_manual_rejection(row_number, "conflicting_listing", "listing id"))
            conflicts.add(listing_id)
    if "__file__" in conflicts:
        return _manual_result(candidate_id, tuple(rejections))
    for listing_id in conflicts:
        offers.pop(listing_id, None)
    if not offers:
        if not rejections:
            rejections.append(_manual_rejection(None, "no_data_rows"))
        return _manual_result(candidate_id, tuple(rejections))
    built = tuple(_manual_offer(item) for _, item in sorted(offers.items()))
    warnings = ["manual_evidence: operator CSV, not a live competitor fetch"]
    if pii_headers:
        safe = [_public_header(header) for header in pii_headers]
        warnings.append("pii_columns_dropped:" + ",".join(sorted(set(safe))))
    return _manual_result(candidate_id, tuple(rejections), offers=built, warnings=tuple(warnings))


def _manual_offer(item: dict[str, Any]) -> CompetitorOffer:
    field_status = {name: "missing" for name in _EVIDENCE_FIELDS}
    if item["title"]:
        field_status["title"] = "observed"
    if item["price"] is not None:
        field_status["price"] = "observed"
    if item["currency"]:
        field_status["currency"] = "observed"
    if item["availability"]:
        field_status["availability"] = "observed"
    if item["shipping_cost"] is not None:
        field_status["shipping_cost"] = "observed"
    if item["brand"]:
        field_status["brand"] = "observed"
    if item["seller"]:
        field_status["seller"] = "observed"
    if item["rating"] is not None:
        field_status["rating"] = "observed"
    if item["review_count"] is not None:
        field_status["review_count"] = "observed"
    if item["variant_count"] is not None:
        field_status["variant_count"] = "observed"
    if item["image"]:
        field_status["image"] = "observed"
    observed = sum(status == "observed" for status in field_status.values())
    return CompetitorOffer(
        source=item["source"],
        source_url=item["source_url"],
        crawl_timestamp=0.0,
        external_listing_id=item["listing_id"],
        title=item["title"],
        field_status=field_status,
        price=item["price"],
        currency=item["currency"],
        availability=item["availability"],
        shipping_cost=item["shipping_cost"],
        brand=item["brand"],
        seller=item["seller"],
        rating=item["rating"],
        review_count=item["review_count"],
        variant_count=item["variant_count"],
        image=item["image"],
        extraction_method="manual_csv",
        confidence=round(observed / len(field_status), 3),
        warnings=("manual_import",),
    )


def _manual_result(
    candidate_id: str | None,
    rejections: tuple[dict[str, Any], ...],
    *,
    offers: tuple[CompetitorOffer, ...] = (),
    warnings: tuple[str, ...] = (),
) -> dict[str, Any]:
    body = {
        "candidate_id": candidate_id,
        "evidence_class": "manual",
        "evidence_state": "manual_import",
        "live_validated": False,
        "network_calls": False,
        "provider_calls": False,
        "offer_count": len(offers),
        "offers": [offer.to_dict() for offer in offers],
        "rejections": [dict(item) for item in rejections],
        "warnings": list(warnings),
        "status": "accepted" if offers else "rejected",
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    body["fingerprint"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return body


def health() -> AdapterHealth:
    return AdapterHealth(
        SOURCE_PREFIX, configured=True, reachable=False,
        capabilities=("public_page_fetch", "jsonld_extraction", "cache", "multi_source"),
        detail="live reachability to competitor storefronts not verified in this environment; see docs/COMPETITION_INTELLIGENCE.md",
    )


__all__ = [
    "CompetitorOffer", "FIELD_STATUSES", "KNOWN_SOURCE_LABELS", "SOURCE_PREFIX",
    "fetch_competitor_offer", "health", "import_manual_competitor_csv", "score_offers",
]

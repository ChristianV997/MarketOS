"""Offline Mercado Libre listing evidence; the legacy live fetch is blocked.

Injected fixture transports normalize sanitized search snapshots. Listings never
become sales velocity, supplier proof, calibrated confidence, or launch authority.
See docs/MERCADOLIBRE_RESEARCH_EVIDENCE.md for limits and official references.
"""
from __future__ import annotations

import json
import logging
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import fields
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.parse import urlsplit

from evaluation.commerce.marketplace_trends import MarketplaceTrendEvidence

_log = logging.getLogger(__name__)
_SITES = ("MLA", "MLM", "MLB")
_QUERIES = ("electronica", "hogar", "belleza", "deportes", "mascotas", "bebes")
_DOMAINS = {
    "MLA": "mercadolibre.com.ar", "MLM": "mercadolibre.com.mx",
    "MLB": "mercadolivre.com.br", "MLC": "mercadolibre.cl",
    "MCO": "mercadolibre.com.co", "MLU": "mercadolibre.com.uy",
    "MPE": "mercadolibre.com.pe",
}
_ENDPOINT = "https://api.mercadolibre.com/sites/{site_id}/search"
_REQUEST_LIMIT = 20
MAX_RESPONSE_BYTES = 256 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_REQUESTS = 18
_SECRET_KEY = re.compile(r"token|secret|password|credential|authorization|cookie|api[_-]?key|raw[_-]?(?:html|payload)|internal[_-]?prompt|source[_-]?code|formula", re.I)
_SECRET_VALUE = re.compile(r"bearer\s+|sk[_-](?:live|test|proj)[_-]|gh[pousr]_|xox[baprs]-|-----BEGIN", re.I)
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_PAGE_ERRORS = frozenset({
    "auth_required", "access_denied", "rate_limited", "upstream_unavailable",
    "malformed_response", "response_size_exceeded", "result_bounds_exceeded",
    "payload_too_complex", "unsafe_payload", "non_finite_payload",
})
_PARTIAL_WARNINGS = _PAGE_ERRORS | {"source_timeout", "transport_unavailable", "listing_rejected", "conflicting_listing_observations"}


class FixtureSearchTransport(Protocol):
    """Trusted offline test/import seam; implementations must not use network."""

    def get(self, url: str, *, params: dict[str, Any], timeout: float) -> Any: ...


class MercadoLibreEvidenceError(ValueError):
    """Stable, non-reflective normalization error."""


def _error(code: str, error_type: str = "schema") -> Exception:
    # Deferred to avoid research.__init__ -> market_sources -> this module cycle.
    from backend.adapters.research.trend_source_v1 import AdapterFetchError

    return AdapterFetchError(error_type, code, context={"code": code})


def _text(value: Any, *, code: str, limit: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise MercadoLibreEvidenceError(code)
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise MercadoLibreEvidenceError(code)
    value = value.strip()
    if (not value and not allow_empty) or _SECRET_VALUE.search(value) or re.search(r"<[^>]*>", value):
        raise MercadoLibreEvidenceError(code)
    return value


def _screen(value: Any, depth: int = 0, count: list[int] | None = None) -> None:
    count = count if count is not None else [0]
    count[0] += 1
    if depth > 10 or count[0] > 10_000:
        raise MercadoLibreEvidenceError("payload_too_complex")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or _SECRET_KEY.search(key):
                raise MercadoLibreEvidenceError("unsafe_payload")
            _screen(child, depth + 1, count)
    elif isinstance(value, list):
        for child in value:
            _screen(child, depth + 1, count)
    elif isinstance(value, str) and _SECRET_VALUE.search(value):
        raise MercadoLibreEvidenceError("unsafe_payload")
    elif isinstance(value, float) and not math.isfinite(value):
        raise MercadoLibreEvidenceError("non_finite_payload")


def _site(value: Any) -> str:
    if not isinstance(value, str) or value not in _DOMAINS:
        raise MercadoLibreEvidenceError("invalid_site")
    return value


def _observed_at(value: Any) -> str | None:
    if value is None:
        return None
    text = _text(value, code="invalid_observed_at", limit=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError):
        raise MercadoLibreEvidenceError("invalid_observed_at") from None


def _number(value: Any, field: str, *, integer: bool = False) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise MercadoLibreEvidenceError(f"invalid_{field}")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > Decimal("1e15"):
            raise ValueError
        if integer and amount != amount.to_integral_value():
            raise ValueError
        if integer:
            return int(amount)
        result = float(amount)
        if Decimal(str(result)) != amount:
            raise ValueError
        return 0.0 if amount == 0 else result
    except (InvalidOperation, ValueError, OverflowError):
        raise MercadoLibreEvidenceError(f"invalid_{field}") from None


def _permalink(value: Any, site: str) -> str | None:
    if value is None:
        return None
    text = _text(value, code="invalid_permalink", limit=2048)
    try:
        parsed = urlsplit(text)
        host = parsed.hostname or ""
        domain = _DOMAINS[site]
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError
        if host != domain and not host.endswith("." + domain):
            raise ValueError
        if parsed.query or parsed.fragment or "\\" in text:
            raise ValueError
    except ValueError:
        raise MercadoLibreEvidenceError("invalid_permalink") from None
    return text


def _item_to_signal(
    item: Mapping[str, Any], site_id: str, *, query: str = "",
    observed_at: str | None = None, evidence_mode: str = "fixture",
) -> dict[str, Any]:
    """Compatibility-shaped observation; unknown score/velocity stay None."""
    site_id = _site(site_id)
    if evidence_mode not in {"fixture", "manual_import"}:
        raise MercadoLibreEvidenceError("invalid_evidence_mode")
    query = _text(query, code="invalid_query", limit=120, allow_empty=True)
    observed_at = _observed_at(observed_at)
    if not isinstance(item, Mapping):
        raise MercadoLibreEvidenceError("invalid_listing")
    _screen(item)
    identity = item.get("id")
    if not isinstance(identity, str) or not re.fullmatch(site_id + r"[0-9]{1,20}", identity):
        raise MercadoLibreEvidenceError("invalid_listing_identity")
    if item.get("site_id") not in (None, site_id):
        raise MercadoLibreEvidenceError("listing_site_mismatch")
    title = _text(item.get("title"), code="invalid_title", limit=240)
    currency = item.get("currency_id")
    if currency is not None and (not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency)):
        raise MercadoLibreEvidenceError("invalid_currency")
    price = _number(item.get("price"), "price")
    sold = _number(item.get("sold_quantity"), "sold_quantity", integer=True)
    available = _number(item.get("available_quantity"), "available_quantity", integer=True)
    variation = _number(item.get("variation_id"), "variation_id", integer=True)
    shipping = item.get("shipping")
    if shipping is not None and not isinstance(shipping, Mapping):
        raise MercadoLibreEvidenceError("invalid_shipping")
    free_shipping = shipping.get("free_shipping") if shipping is not None else None
    if free_shipping is not None and not isinstance(free_shipping, bool):
        raise MercadoLibreEvidenceError("invalid_shipping")
    category = item.get("category_id")
    if category is not None:
        category = _text(category, code="invalid_category", limit=64)
        if not re.fullmatch(site_id + r"[0-9]+", category):
            raise MercadoLibreEvidenceError("invalid_category")
    warnings = [
        "listing_is_not_supplier_proof",
        "listing_is_not_demand_measurement",
        "sales_velocity_unavailable",
        "confidence_unavailable",
    ]
    for field, value in (("price", price), ("currency", currency), ("observation_time", observed_at)):
        if value is None:
            warnings.append(f"{field}_unavailable")
    if price == 0:
        warnings.append("explicit_zero_price_is_not_a_free_offer_claim")
    if sold is not None:
        warnings.append("reported_sold_quantity_has_no_verified_time_window")
    if available is not None:
        warnings.append("available_quantity_is_referential_not_exact_inventory")
    source_ref = f"https://api.mercadolibre.com/items/{identity}"
    if variation is not None:
        source_ref += f"#variation-{variation}"
    values = {"price": price, "currency": currency, "observed_at": observed_at, "sold_quantity": sold, "available_quantity": available, "shipping_claim": free_shipping}
    return {
        "product": title, "source": "mercadolibre", "platform": "mercadolibre",
        "market": site_id, "site_id": site_id, "listing_id": identity,
        "variation_id": variation, "candidate_id": None, "category": category,
        "query": query, "permalink": _permalink(item.get("permalink"), site_id),
        "source_ref": source_ref, **values,
        "price_status": evidence_mode if price is not None else "unavailable",
        "quantity_precision": "provider_reference", "score": None, "velocity": None,
        "confidence": None, "region": None, "language": None,
        "evidence_mode": evidence_mode, "status": evidence_mode,
        "field_provenance": {key: evidence_mode if value is not None else "unavailable" for key, value in values.items()},
        "warnings": sorted(warnings), "supplier_proof": False,
        "read_only": True, "network_calls": False, "mutated": False,
    }


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MercadoLibreEvidenceError("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise MercadoLibreEvidenceError("non_finite_payload")


def _response_items(response: Any) -> list[Any]:
    try:
        status = response.status_code
        if isinstance(status, bool) or not isinstance(status, int):
            raise MercadoLibreEvidenceError("malformed_response")
        if status != 200:
            code = {401: "auth_required", 403: "access_denied", 429: "rate_limited"}.get(status, "upstream_unavailable")
            raise MercadoLibreEvidenceError(code)
        body = bytearray()
        for chunk in response.iter_content(chunk_size=4096):
            if not isinstance(chunk, bytes):
                raise MercadoLibreEvidenceError("malformed_response")
            if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                raise MercadoLibreEvidenceError("response_size_exceeded")
            body.extend(chunk)
        try:
            payload = json.loads(body.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_reject_constant, parse_float=Decimal)
        except (UnicodeError, ValueError, RecursionError):
            raise MercadoLibreEvidenceError("malformed_response") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise MercadoLibreEvidenceError("malformed_response")
        _screen(payload)
        rows = payload["results"]
        if len(rows) > _REQUEST_LIMIT:
            raise MercadoLibreEvidenceError("result_bounds_exceeded")
        return rows
    finally:
        try:
            response.close()
        except Exception:
            pass


def fetch(
    *, transport: FixtureSearchTransport | None = None, sites: Sequence[str] | None = None,
    queries: Sequence[str] | None = None, observed_at: str | None = None,
    evidence_mode: str = "fixture", max_pages: int = 1, timeout_seconds: float = 8.0,
) -> list[dict[str, Any]]:
    """Normalize offline responses; no-argument production use is blocked.

    Successful empty responses are [], while failure with no usable observations
    raises existing AdapterFetchError. Partial results carry stable warnings.
    No global cache, retry, credential lookup, or live HTTP fallback exists.
    """
    if transport is None:
        raise _error("mercadolibre_live_access_blocked", "unavailable")
    sites = sites if sites is not None else _SITES
    queries = queries if queries is not None else _QUERIES
    if not isinstance(sites, (list, tuple)) or not isinstance(queries, (list, tuple)):
        raise MercadoLibreEvidenceError("invalid_request")
    if not sites or len(sites) > 3 or not queries or len(queries) > 6:
        raise MercadoLibreEvidenceError("request_bounds_exceeded")
    sites = tuple(dict.fromkeys(_site(site) for site in sites))
    queries = tuple(dict.fromkeys(_text(query, code="invalid_query", limit=120) for query in queries))
    if type(max_pages) is not int or not 1 <= max_pages <= 3 or len(sites) * len(queries) * max_pages > MAX_REQUESTS:
        raise MercadoLibreEvidenceError("request_bounds_exceeded")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 8:
        raise MercadoLibreEvidenceError("invalid_timeout")
    observed_at = _observed_at(observed_at)
    if evidence_mode not in {"fixture", "manual_import"}:
        raise MercadoLibreEvidenceError("invalid_evidence_mode")
    records: dict[str, dict[str, Any]] = {}
    quarantined: set[str] = set()
    failures: set[str] = set()
    for site in sites:
        for query in queries:
            for page in range(max_pages):
                try:
                    response = transport.get(_ENDPOINT.format(site_id=site), params={"q": query, "limit": _REQUEST_LIMIT, "offset": page * _REQUEST_LIMIT}, timeout=float(timeout_seconds))
                    items = _response_items(response)
                except TimeoutError:
                    failures.add("source_timeout")
                    break
                except MercadoLibreEvidenceError as exc:
                    failures.add(str(exc) if str(exc) in _PAGE_ERRORS else "malformed_response")
                    break
                except Exception:
                    failures.add("transport_unavailable")
                    break
                for item in items:
                    try:
                        record = _item_to_signal(item, site, query=query, observed_at=observed_at, evidence_mode=evidence_mode)
                    except (ValueError, TypeError):
                        failures.add("listing_rejected")
                        continue
                    key = record["source_ref"]
                    prior = records.get(key)
                    comparison = {name: value for name, value in record.items() if name != "query"}
                    if prior is not None and comparison != {name: value for name, value in prior.items() if name != "query"}:
                        quarantined.add(key)
                        records.pop(key)
                        failures.add("conflicting_listing_observations")
                    elif key not in quarantined:
                        if prior is not None:
                            record["query"] = min(prior["query"], record["query"])
                        records[key] = record
                if len(items) < _REQUEST_LIMIT:
                    break
    if failures and not records:
        raise _error(sorted(failures)[0], "unavailable")
    result = [records[key] for key in sorted(records)]
    for record in result:
        if failures:
            record["status"] = "partial"
            record["warnings"] = sorted(set(record["warnings"]) | failures)
    if len(json.dumps(result, sort_keys=True, allow_nan=False).encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise _error("output_size_exceeded")
    if failures:
        _log.warning("mercadolibre_fixture_partial failures=%d records=%d", len(failures), len(result))
    return result


def to_marketplace_evidence(
    item: Mapping[str, Any], site_id: str, *, candidate_id: str, query: str | None = None,
    observed_at: str | None = None, evidence_mode: str | None = None,
) -> MarketplaceTrendEvidence:
    """Project a snapshot row or fetched observation with explicit binding."""
    cleaned_id = _text(candidate_id, code="invalid_candidate_binding", limit=128)
    if cleaned_id != candidate_id or not _ID.fullmatch(candidate_id):
        raise MercadoLibreEvidenceError("invalid_candidate_binding")
    if not isinstance(item, Mapping):
        raise MercadoLibreEvidenceError("invalid_listing")
    prior = item if "listing_id" in item else None
    if prior is not None:
        _screen(prior)
        if prior.get("source") != "mercadolibre" or prior.get("site_id") != site_id:
            raise MercadoLibreEvidenceError("listing_site_mismatch")
        if prior.get("read_only") is not True or prior.get("network_calls") is not False or prior.get("mutated") is not False:
            raise MercadoLibreEvidenceError("invalid_offline_observation")
        if prior.get("candidate_id") not in (None, candidate_id):
            raise MercadoLibreEvidenceError("candidate_binding_mismatch")
        if prior.get("evidence_mode") not in {"fixture", "manual_import"}:
            raise MercadoLibreEvidenceError("invalid_evidence_mode")
        if evidence_mode is not None and evidence_mode != prior.get("evidence_mode"):
            raise MercadoLibreEvidenceError("evidence_mode_mismatch")
        if observed_at is not None and _observed_at(observed_at) != _observed_at(prior.get("observed_at")):
            raise MercadoLibreEvidenceError("observation_time_mismatch")
        if query is not None and query != prior.get("query"):
            raise MercadoLibreEvidenceError("query_mismatch")
        query, observed_at, evidence_mode = prior.get("query"), prior.get("observed_at"), prior.get("evidence_mode")
        item = {
            "id": prior.get("listing_id"), "site_id": site_id, "title": prior.get("product"),
            "price": prior.get("price"), "currency_id": prior.get("currency"),
            "sold_quantity": prior.get("sold_quantity"), "available_quantity": prior.get("available_quantity"),
            "variation_id": prior.get("variation_id"), "permalink": prior.get("permalink"),
            "category_id": prior.get("category"), "shipping": {"free_shipping": prior.get("shipping_claim")},
        }
    record = _item_to_signal(item, site_id, query=query if query is not None else "", observed_at=observed_at, evidence_mode=evidence_mode if evidence_mode is not None else "fixture")
    if prior is not None:
        if record["source_ref"] != prior.get("source_ref"):
            raise MercadoLibreEvidenceError("source_identity_mismatch")
        warnings = prior.get("warnings")
        if not isinstance(warnings, list) or len(warnings) > 32 or any(not isinstance(value, str) for value in warnings):
            raise MercadoLibreEvidenceError("invalid_observation_warnings")
        record["warnings"] = sorted(set(record["warnings"]) | (set(warnings) & _PARTIAL_WARNINGS))
    provenance = {field.name: "unavailable" for field in fields(MarketplaceTrendEvidence)}
    for name, value in {
        "source_url": record["source_ref"], "query": record["query"],
        "site_id": site_id, "category_id": record["category"],
        "sold_count_text": record["sold_quantity"], "availability": record["available_quantity"],
        "shipping_signal": record["shipping_claim"], "price": record["price"],
        "currency": record["currency"], "observed_at": record["observed_at"],
    }.items():
        provenance[name] = record["evidence_mode"] if value is not None and value != "" else "unavailable"
    shipping = record["shipping_claim"]
    return MarketplaceTrendEvidence(
        candidate_id=candidate_id, query=record["query"], marketplace="mercadolibre",
        source_type="mercadolibre_trends_snapshot", site_id=site_id,
        category_id=record["category"] or "", source_url=record["source_ref"],
        evidence_mode=record["evidence_mode"], price=record["price"], currency=record["currency"] or "",
        sold_count_text="" if record["sold_quantity"] is None else str(record["sold_quantity"]),
        availability="" if record["available_quantity"] is None else f"provider_reference:{record['available_quantity']}",
        shipping_signal="" if shipping is None else f"free_shipping_claim:{str(shipping).lower()}",
        source_confidence=0.0, field_provenance=provenance,
        observed_at=record["observed_at"] or "", warnings=tuple(record["warnings"]),
    )


def project_marketplace_evidence(
    records: Sequence[Mapping[str, Any]], *, candidate_bindings: Mapping[str, str],
) -> list[MarketplaceTrendEvidence]:
    """Guard the whole observation batch before canonical report deduplication."""
    if not isinstance(records, (list, tuple)) or len(records) > MAX_REQUESTS * _REQUEST_LIMIT:
        raise MercadoLibreEvidenceError("result_bounds_exceeded")
    if not isinstance(candidate_bindings, Mapping) or len(candidate_bindings) > MAX_REQUESTS * _REQUEST_LIMIT:
        raise MercadoLibreEvidenceError("invalid_candidate_binding")
    selected: dict[str, MarketplaceTrendEvidence] = {}
    observations: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping) or "listing_id" not in record or not isinstance(record.get("source_ref"), str):
            raise MercadoLibreEvidenceError("invalid_listing_identity")
        key = record["source_ref"]
        evidence = to_marketplace_evidence(record, record.get("site_id"), candidate_id=candidate_bindings.get(key))
        comparison = {name: value for name, value in record.items() if name != "query"}
        if key in observations and observations[key] != comparison:
            raise MercadoLibreEvidenceError("conflicting_listing_observations")
        observations[key] = comparison
        if key not in selected or evidence.query < selected[key].query:
            selected[key] = evidence
    return [selected[key] for key in sorted(selected)]


def register(signal_engine: Any) -> None:
    """Keep the existing registration, with blocked source health observable."""
    signal_engine.register_source("mercadolibre", fetch)
    from backend.discovery.registry import discovery_registry

    discovery_registry.register("mercadolibre", credential_env_vars=[], requires_auth=True)

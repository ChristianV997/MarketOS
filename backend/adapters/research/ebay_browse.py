"""Bounded eBay Browse API evidence adapter.

The adapter is transport-injected so tests never need eBay credentials or a
network.  The transport owns authentication; this module only builds bounded
Browse API requests and normalizes returned fields into MarketOS' existing
``MarketplaceTrendEvidence`` contract.  Current listings are competition and
pricing evidence only: this adapter never infers sales, bestseller status, or
demand from a Browse API response.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlparse

from backend.contracts.adapters import AdapterHealth
from evaluation.commerce.marketplace_trends import MarketplaceTrendEvidence, build_report

ADAPTER_NAME = "ebay_browse"
BROWSE_PATH = "/buy/browse/v1/item_summary/search"
DEFAULT_MARKETPLACE_ID = "EBAY_US"
DEFAULT_TIMEOUT_S = 10.0
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50
MAX_PAGES = 3
MAX_QUERY_LENGTH = 160
MAX_VARIANTS = 25


class EbayBrowseTransport(Protocol):
    def __call__(self, request: "EbayBrowseRequest", *, timeout_s: float) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class EbayBrowseConfig:
    """Non-secret provider settings.  ``credential_ref`` is only a reference."""

    credential_ref: str = ""
    marketplace_id: str = DEFAULT_MARKETPLACE_ID
    enabled: bool = True
    allow_network: bool = False
    approval_granted: bool = False
    timeout_s: float = DEFAULT_TIMEOUT_S
    page_size: int = DEFAULT_PAGE_SIZE
    max_pages: int = MAX_PAGES

    def __post_init__(self) -> None:
        if not 0.1 <= self.timeout_s <= 30.0:
            raise ValueError("timeout_s must be between 0.1 and 30 seconds")
        if not 1 <= self.page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
        if not 1 <= self.max_pages <= MAX_PAGES:
            raise ValueError(f"max_pages must be between 1 and {MAX_PAGES}")
        if not self.marketplace_id or len(self.marketplace_id) > 20:
            raise ValueError("marketplace_id is required and bounded")

    @property
    def configured(self) -> bool:
        return bool(self.credential_ref.strip() and self.marketplace_id.strip())

    @property
    def ready_for_transport(self) -> bool:
        return self.enabled and self.configured and self.allow_network and self.approval_granted


@dataclass(frozen=True)
class EbayBrowseRequest:
    """Sanitized request description; credentials are deliberately absent."""

    path: str
    marketplace_id: str
    query: str
    params: Mapping[str, str]


@dataclass(frozen=True)
class EbayBrowseListing:
    item_id: str
    candidate_id: str
    query: str
    title: str
    source_url: str
    price: float | None = None
    currency: str = ""
    availability: str = ""
    shipping_cost: float | None = None
    shipping_currency: str = ""
    variants: tuple[Mapping[str, Any], ...] = ()
    field_provenance: Mapping[str, str] = field(default_factory=dict)
    evidence_class: str = "current_listing_competition"

    def to_marketplace_evidence(self) -> MarketplaceTrendEvidence:
        provenance = dict(self.field_provenance)
        if self.shipping_cost is not None:
            provenance["shipping_signal"] = "observed"
        return MarketplaceTrendEvidence(
            candidate_id=self.candidate_id,
            query=self.query,
            marketplace="ebay",
            source_type="ebay_public_listing_snapshot",
            source_url=self.source_url,
            evidence_mode="live_readonly",
            price=self.price,
            currency=self.currency or "USD",
            availability=self.availability,
            shipping_signal=(f"{self.shipping_cost:g} {self.shipping_currency}" if self.shipping_cost is not None else ""),
            source_confidence=0.8,
            field_provenance=provenance,
            warnings=("current_listing_not_sales_or_demand_proof",),
            observed_at="provider_retrieved",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "candidate_id": self.candidate_id,
            "query": self.query,
            "title": self.title,
            "source_url": self.source_url,
            "price": self.price,
            "currency": self.currency,
            "availability": self.availability,
            "shipping_cost": self.shipping_cost,
            "shipping_currency": self.shipping_currency,
            "variants": [dict(item) for item in self.variants],
            "field_provenance": dict(self.field_provenance),
            "evidence_class": self.evidence_class,
        }


@dataclass(frozen=True)
class EbayBrowseResult:
    status: str
    candidate_id: str
    query: str
    pages_attempted: int = 0
    listings: tuple[EbayBrowseListing, ...] = ()
    warnings: tuple[str, ...] = ()
    error_code: str = ""
    network_calls: bool = False

    @property
    def evidence(self) -> tuple[MarketplaceTrendEvidence, ...]:
        return tuple(item.to_marketplace_evidence() for item in self.listings)

    def marketplace_report(self) -> dict[str, Any]:
        report = build_report(list(self.evidence), evidence_mode="live_readonly").to_dict()
        report["network_calls"] = self.network_calls
        report["warnings"] = list(dict.fromkeys(list(report.get("warnings", [])) + list(self.warnings)))
        return report

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "candidate_id": self.candidate_id,
            "query": self.query,
            "pages_attempted": self.pages_attempted,
            "listings": [item.to_dict() for item in self.listings],
            "evidence": [item.to_dict() for item in self.evidence],
            "marketplace_report": self.marketplace_report(),
            "warnings": list(self.warnings),
            "error_code": self.error_code,
            "network_calls": self.network_calls,
            "read_only": True,
            "mutated": False,
        }


def _text(value: Any, limit: int = MAX_QUERY_LENGTH) -> str:
    return " ".join(str(value or "").split())[:limit]


def _candidate_id(brief: Mapping[str, Any]) -> str:
    return _text(brief.get("candidate_id") or brief.get("id") or brief.get("product_query") or brief.get("query"), 100)


def brief_query(brief: Mapping[str, Any]) -> str:
    """Derive one bounded Browse query from an existing research brief."""
    query = _text(brief.get("product_query") or brief.get("query") or brief.get("candidate") or brief.get("product_name"))
    category = _text(brief.get("category"), 60)
    market = _text(brief.get("target_market"), 60)
    language = _text(brief.get("language"), 20)
    parts = [part for part in (query, category, market, language) if part]
    return _text(" ".join(parts))


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        number = float(value)
        return number if number >= 0 else None
    except (TypeError, ValueError):
        return None


def _safe_url(value: Any) -> str:
    text = _text(value, 500)
    try:
        parsed = urlparse(text)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        return ""
    return text


def _variants(item: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw = item.get("localizedAspects") or item.get("variations") or item.get("aspects")
    if not isinstance(raw, list):
        return ()
    values: list[Mapping[str, Any]] = []
    for value in raw[:MAX_VARIANTS]:
        if isinstance(value, Mapping):
            values.append({str(key): item_value for key, item_value in value.items() if str(key)[:40] in {"name", "value", "localizedName", "localizedValue"}})
    return tuple(values)


def _normalize_listing(item: Any, *, candidate_id: str, query: str) -> EbayBrowseListing | None:
    if not isinstance(item, Mapping):
        return None
    item_id = _text(item.get("itemId"), 120)
    if not item_id:
        return None
    title = _text(item.get("title"), 240)
    price_value = item.get("price")
    price = price_value if isinstance(price_value, Mapping) else {}
    shipping = item.get("shippingOptions")
    shipping_row = shipping[0] if isinstance(shipping, list) and shipping and isinstance(shipping[0], Mapping) else {}
    shipping_value = shipping_row.get("shippingCost")
    shipping_price = shipping_value if isinstance(shipping_value, Mapping) else {}
    source_url = _safe_url(item.get("itemWebUrl"))
    field_provenance: dict[str, str] = {}
    if title:
        field_provenance["title"] = "observed"
    if _number(price.get("value")) is not None:
        field_provenance["price"] = "observed"
    if price.get("currency"):
        field_provenance["currency"] = "observed"
    if source_url:
        field_provenance["source_url"] = "observed"
    availability = _text(item.get("estimatedAvailabilityStatus") or item.get("availability"), 80)
    if availability:
        field_provenance["availability"] = "observed"
    if _number(shipping_price.get("value")) is not None:
        field_provenance["shipping_cost"] = "observed"
    return EbayBrowseListing(
        item_id=item_id,
        candidate_id=candidate_id,
        query=query,
        title=title,
        source_url=source_url,
        price=_number(price.get("value")),
        currency=_text(price.get("currency"), 12).upper(),
        availability=availability,
        shipping_cost=_number(shipping_price.get("value")),
        shipping_currency=_text(shipping_price.get("currency"), 12).upper(),
        variants=_variants(item),
        field_provenance=field_provenance,
    )


class EbayBrowseAdapter:
    def __init__(self, config: EbayBrowseConfig | None = None, *, transport: EbayBrowseTransport | None = None, clock: Callable[[], float] = time.time) -> None:
        self.config = config or EbayBrowseConfig()
        self.transport = transport
        self._clock = clock

    def health(self) -> AdapterHealth:
        if not self.config.enabled:
            return AdapterHealth(ADAPTER_NAME, False, False, ("search_listings",), detail="disabled")
        if not self.config.configured:
            return AdapterHealth(ADAPTER_NAME, False, False, ("search_listings",), detail="unconfigured")
        if not self.config.ready_for_transport:
            return AdapterHealth(ADAPTER_NAME, True, False, ("search_listings",), detail="network or approval gate required")
        return AdapterHealth(ADAPTER_NAME, True, self.transport is not None, ("search_listings",), detail="transport injected" if self.transport else "transport missing")

    def search_brief(self, brief: Mapping[str, Any]) -> EbayBrowseResult:
        candidate_id = _candidate_id(brief)
        query = brief_query(brief)
        if not candidate_id or not query:
            return EbayBrowseResult("invalid_brief", candidate_id, query, warnings=("candidate_id_and_query_required",), error_code="invalid_brief")
        if not self.config.enabled:
            return EbayBrowseResult("disabled", candidate_id, query, warnings=("adapter_disabled",), error_code="disabled")
        if not self.config.configured:
            return EbayBrowseResult("unconfigured", candidate_id, query, warnings=("credential_reference_and_marketplace_required",), error_code="unconfigured")
        if not self.config.allow_network or not self.config.approval_granted:
            return EbayBrowseResult("network_gate_required", candidate_id, query, warnings=("network_and_approval_gate_required",), error_code="network_gate_required")
        if self.transport is None:
            return EbayBrowseResult("unconfigured", candidate_id, query, warnings=("transport_not_configured",), error_code="unconfigured")

        listings: list[EbayBrowseListing] = []
        seen: set[str] = set()
        warnings: list[str] = ["current_listings_are_not_bestseller_or_verified_demand_evidence"]
        pages = 0
        try:
            for page in range(self.config.max_pages):
                pages += 1
                offset = page * self.config.page_size
                request = EbayBrowseRequest(BROWSE_PATH, self.config.marketplace_id, query, {"q": query, "limit": str(self.config.page_size), "offset": str(offset)})
                payload = self.transport(request, timeout_s=self.config.timeout_s)
                if not isinstance(payload, Mapping):
                    return EbayBrowseResult("malformed_response", candidate_id, query, pages, tuple(listings), tuple(warnings + ["response_not_an_object"]), "malformed_response", True)
                rows = payload.get("itemSummaries")
                if rows is None:
                    rows = payload.get("items")
                if not isinstance(rows, list):
                    return EbayBrowseResult("malformed_response", candidate_id, query, pages, tuple(listings), tuple(warnings + ["item_summaries_not_a_list"]), "malformed_response", True)
                for raw in rows:
                    listing = _normalize_listing(raw, candidate_id=candidate_id, query=query)
                    if listing and listing.item_id not in seen:
                        seen.add(listing.item_id)
                        listings.append(listing)
                if len(rows) < self.config.page_size:
                    break
            if pages >= self.config.max_pages and listings:
                warnings.append("pagination_cap_reached")
        except TimeoutError:
            return EbayBrowseResult("timeout", candidate_id, query, pages, tuple(listings), tuple(warnings + ["provider_timeout"]), "timeout", True)
        except PermissionError:
            return EbayBrowseResult("auth_failed", candidate_id, query, pages, tuple(listings), tuple(warnings + ["provider_authorization_failed"]), "auth_failed", True)
        except Exception:
            return EbayBrowseResult("transport_error", candidate_id, query, pages, tuple(listings), tuple(warnings + ["provider_request_failed_details_withheld"]), "transport_error", True)
        return EbayBrowseResult("ok", candidate_id, query, pages, tuple(listings), tuple(warnings), network_calls=True)


def search_brief(brief: Mapping[str, Any], *, config: EbayBrowseConfig | None = None, transport: EbayBrowseTransport | None = None) -> EbayBrowseResult:
    """Convenience entry point for the existing research-brief seam."""
    return EbayBrowseAdapter(config, transport=transport).search_brief(brief)


__all__ = ["EbayBrowseAdapter", "EbayBrowseConfig", "EbayBrowseListing", "EbayBrowseRequest", "EbayBrowseResult", "brief_query", "search_brief"]

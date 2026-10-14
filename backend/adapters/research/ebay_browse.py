"""Bounded eBay Browse API evidence adapter.

The adapter is transport-injected so tests never need eBay credentials or a
network.  Fixture/fake transports remain demo/test only and cannot be reported
as live.  A separate live HTTP transport exists for the official Browse
``item_summary/search`` read, but network use stays blocked until Approval
Ledger authorization, credential-reference resolution, and explicit
``allow_network`` all pass.  This module never reads or logs secret values,
never infers USD/FX for missing currency, and never fabricates confidence.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlparse

from backend.contracts.adapters import AdapterHealth
from evaluation.commerce.marketplace_trends import MarketplaceTrendEvidence, build_report

ADAPTER_NAME = "ebay_browse"
BROWSE_PATH = "/buy/browse/v1/item_summary/search"
DEFAULT_MARKETPLACE_ID = "EBAY_US"
DEFAULT_API_BASE = "https://api.ebay.com"
DEFAULT_TIMEOUT_S = 10.0
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50
MAX_PAGES = 3
MAX_QUERY_LENGTH = 160
MAX_VARIANTS = 25
MAX_RETRIES = 0  # explicit zero until a reviewed retry policy exists

# Official Buy marketplace IDs used with X-EBAY-C-MARKETPLACE-ID.
# Source: eBay Buy Browse / marketplace ID documentation.
SUPPORTED_MARKETPLACE_IDS = frozenset(
    {
        "EBAY_US",
        "EBAY_GB",
        "EBAY_DE",
        "EBAY_AU",
        "EBAY_CA",
        "EBAY_FR",
        "EBAY_IT",
        "EBAY_ES",
        "EBAY_AT",
        "EBAY_BE",
        "EBAY_CH",
        "EBAY_IE",
        "EBAY_NL",
        "EBAY_PL",
        "EBAY_HK",
        "EBAY_SG",
        "EBAY_MY",
        "EBAY_PH",
        "EBAY_TW",
        "EBAY_MOTORS_US",
    }
)

TRANSPORT_KIND_FIXTURE = "fixture"
TRANSPORT_KIND_LIVE = "live"

_LIVE_PREREQUISITES = (
    "Approval Ledger provider_call simulation must authorize live network use",
    "credential reference configured (secret value never read in this module)",
    "allow_network explicitly enabled by the caller",
    "live EbayBrowseTransport injected (or LiveEbayBrowseTransport with token resolver)",
    "terms/privacy and output-contract gates completed outside this adapter",
    "timeout/retry policy reviewed (MAX_RETRIES is currently 0)",
)


class EbayBrowseRateLimitError(RuntimeError):
    """Raised by live transport when the provider returns HTTP 429."""


class EbayBrowseTransport(Protocol):
    """Callable transport.  Fixture implementations must set kind='fixture'."""

    kind: str

    def __call__(self, request: "EbayBrowseRequest", *, timeout_s: float) -> Mapping[str, Any]: ...


class CredentialTokenResolver(Protocol):
    """Resolve a credential reference to a bearer token.

    Implementations must not log or persist the token.  This adapter never
    opens env files or secret stores itself.
    """

    def __call__(self, credential_ref: str) -> str: ...


@dataclass(frozen=True)
class EbayBrowseAuthorizationDecision:
    """Result of consulting the canonical Approval Ledger simulation.

    Offline ledger mode cannot grant live provider execution; ``authorized``
    stays False until a future human-approved live policy exists.
    """

    authorized: bool
    request_type: str
    simulation_result: str
    can_be_approved_now: bool
    blocking_reasons: tuple[str, ...]
    missing_conditions: tuple[str, ...]
    source: str = "approval_ledger_simulate_action"

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorized": self.authorized,
            "request_type": self.request_type,
            "simulation_result": self.simulation_result,
            "can_be_approved_now": self.can_be_approved_now,
            "blocking_reasons": list(self.blocking_reasons),
            "missing_conditions": list(self.missing_conditions),
            "source": self.source,
            "live_prerequisites": list(_LIVE_PREREQUISITES),
        }


def evaluate_ebay_browse_authorization(*, requested_budget: float = 0.0) -> EbayBrowseAuthorizationDecision:
    """Consult Approval Ledger ``simulate_action('provider_call')``.

    Never treats a caller boolean as authorization.  Offline simulation
    results are never promoted to live network authority.
    """
    from evaluation.companyos.approval_ledger import simulate_action

    simulation = simulate_action("provider_call", requested_budget=requested_budget)
    reasons = list(simulation.blocking_reasons)
    # Draft-only / blocked / missing-condition outcomes never authorize live I/O.
    if simulation.result != "would_auto_allow_draft":
        reasons.append(f"approval_simulation:{simulation.result}")
    reasons.append("offline_approval_ledger_cannot_authorize_live_provider_calls")
    return EbayBrowseAuthorizationDecision(
        authorized=False,
        request_type=simulation.request_type,
        simulation_result=simulation.result,
        can_be_approved_now=False,
        blocking_reasons=tuple(dict.fromkeys(reasons)),
        missing_conditions=tuple(simulation.missing_conditions),
    )


@dataclass(frozen=True)
class EbayBrowseConfig:
    """Non-secret provider settings.  ``credential_ref`` is only a reference."""

    credential_ref: str = ""
    marketplace_id: str = DEFAULT_MARKETPLACE_ID
    enabled: bool = True
    allow_network: bool = False
    transport_kind: str = TRANSPORT_KIND_FIXTURE
    timeout_s: float = DEFAULT_TIMEOUT_S
    page_size: int = DEFAULT_PAGE_SIZE
    max_pages: int = MAX_PAGES
    api_base: str = DEFAULT_API_BASE
    authorization: EbayBrowseAuthorizationDecision | None = None

    def __post_init__(self) -> None:
        if not 0.1 <= self.timeout_s <= 30.0:
            raise ValueError("timeout_s must be between 0.1 and 30 seconds")
        if not 1 <= self.page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
        if not 1 <= self.max_pages <= MAX_PAGES:
            raise ValueError(f"max_pages must be between 1 and {MAX_PAGES}")
        marketplace = self.marketplace_id.strip().upper()
        if marketplace not in SUPPORTED_MARKETPLACE_IDS:
            raise ValueError("marketplace_id must be a supported EBAY_* marketplace id")
        if self.transport_kind not in {TRANSPORT_KIND_FIXTURE, TRANSPORT_KIND_LIVE}:
            raise ValueError("transport_kind must be 'fixture' or 'live'")
        object.__setattr__(self, "marketplace_id", marketplace)

    @property
    def configured(self) -> bool:
        return bool(self.credential_ref.strip() and self.marketplace_id.strip())

    @property
    def evidence_mode(self) -> str:
        return "live_readonly" if self.transport_kind == TRANSPORT_KIND_LIVE else "fixture"

    def authorization_decision(self) -> EbayBrowseAuthorizationDecision:
        """Return the live-authorization decision.

        Always consults the Approval Ledger simulation.  A caller-supplied
        decision may add detail for denied paths but can never escalate to
        ``authorized=True`` when the ledger remains fail-closed.
        """
        ledger = evaluate_ebay_browse_authorization()
        if self.authorization is None:
            return ledger
        if self.authorization.authorized and not ledger.authorized:
            return ledger
        return self.authorization

    @property
    def ready_for_live_transport(self) -> bool:
        decision = self.authorization_decision()
        return (
            self.enabled
            and self.configured
            and self.allow_network
            and self.transport_kind == TRANSPORT_KIND_LIVE
            and decision.authorized
        )


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
    marketplace_id: str = DEFAULT_MARKETPLACE_ID
    price: float | None = None
    currency: str = ""
    availability: str = ""
    shipping_cost: float | None = None
    shipping_currency: str = ""
    variants: tuple[Mapping[str, Any], ...] = ()
    field_provenance: Mapping[str, str] = field(default_factory=dict)
    evidence_class: str = "current_listing_competition"
    evidence_mode: str = "fixture"
    observed_at: str = "fixture_deterministic"

    def to_marketplace_evidence(self) -> MarketplaceTrendEvidence:
        provenance = dict(self.field_provenance)
        if self.shipping_cost is not None:
            provenance["shipping_signal"] = "observed"
        if not self.currency:
            provenance.setdefault("currency", "unavailable")
        # MarketplaceTrendEvidence forbids network_calls=True on rows.
        return MarketplaceTrendEvidence(
            candidate_id=self.candidate_id,
            query=self.query,
            marketplace="ebay",
            source_type="ebay_public_listing_snapshot",
            site_id=self.marketplace_id,
            source_url=self.source_url,
            evidence_mode=self.evidence_mode,
            price=self.price,
            currency=self.currency,
            availability=self.availability,
            shipping_signal=(f"{self.shipping_cost:g} {self.shipping_currency}".strip() if self.shipping_cost is not None else ""),
            source_confidence=0.0,
            field_provenance=provenance,
            warnings=("current_listing_not_sales_or_demand_proof",),
            observed_at=self.observed_at,
            network_calls=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "candidate_id": self.candidate_id,
            "query": self.query,
            "title": self.title,
            "source_url": self.source_url,
            "marketplace_id": self.marketplace_id,
            "price": self.price,
            "currency": self.currency,
            "availability": self.availability,
            "shipping_cost": self.shipping_cost,
            "shipping_currency": self.shipping_currency,
            "variants": [dict(item) for item in self.variants],
            "field_provenance": dict(self.field_provenance),
            "evidence_class": self.evidence_class,
            "evidence_mode": self.evidence_mode,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True)
class EbayBrowseResult:
    status: str
    candidate_id: str
    query: str
    marketplace_id: str = DEFAULT_MARKETPLACE_ID
    transport_kind: str = TRANSPORT_KIND_FIXTURE
    pages_attempted: int = 0
    listings: tuple[EbayBrowseListing, ...] = ()
    warnings: tuple[str, ...] = ()
    error_code: str = ""
    network_calls: bool = False
    authorization: EbayBrowseAuthorizationDecision | None = None

    @property
    def evidence(self) -> tuple[MarketplaceTrendEvidence, ...]:
        return tuple(item.to_marketplace_evidence() for item in self.listings)

    def marketplace_report(self) -> dict[str, Any]:
        mode = "live_readonly" if self.transport_kind == TRANSPORT_KIND_LIVE and self.network_calls else "fixture"
        report = build_report(list(self.evidence), evidence_mode=mode).to_dict()
        report["network_calls"] = self.network_calls
        report["transport_kind"] = self.transport_kind
        report["marketplace_id"] = self.marketplace_id
        if self.authorization is not None:
            report["authorization"] = self.authorization.to_dict()
        report["warnings"] = list(dict.fromkeys(list(report.get("warnings", [])) + list(self.warnings)))
        return report

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "candidate_id": self.candidate_id,
            "query": self.query,
            "marketplace_id": self.marketplace_id,
            "transport_kind": self.transport_kind,
            "pages_attempted": self.pages_attempted,
            "listings": [item.to_dict() for item in self.listings],
            "evidence": [item.to_dict() for item in self.evidence],
            "marketplace_report": self.marketplace_report(),
            "warnings": list(self.warnings),
            "error_code": self.error_code,
            "network_calls": self.network_calls,
            "authorization": self.authorization.to_dict() if self.authorization else None,
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


def _currency_code(value: Any) -> str:
    """Retain ISO-like currency codes only; never default missing values to USD."""
    text = _text(value, 12).upper()
    if len(text) == 3 and text.isalpha():
        return text
    return ""


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
            values.append(
                {
                    str(key): item_value
                    for key, item_value in value.items()
                    if str(key)[:40] in {"name", "value", "localizedName", "localizedValue"}
                }
            )
    return tuple(values)


def _transport_kind(transport: EbayBrowseTransport | None, config: EbayBrowseConfig) -> str:
    if transport is not None:
        kind = getattr(transport, "kind", None)
        if kind in {TRANSPORT_KIND_FIXTURE, TRANSPORT_KIND_LIVE}:
            return str(kind)
    return config.transport_kind


def _normalize_listing(
    item: Any,
    *,
    candidate_id: str,
    query: str,
    marketplace_id: str,
    evidence_mode: str,
    observed_at: str,
) -> tuple[EbayBrowseListing | None, tuple[str, ...]]:
    if not isinstance(item, Mapping):
        return None, ()
    item_id = _text(item.get("itemId"), 120)
    if not item_id:
        return None, ()
    warnings: list[str] = []
    raw_marketplace = _text(item.get("marketplaceId") or item.get("listingMarketplaceId"), 20).upper()
    if raw_marketplace and raw_marketplace not in SUPPORTED_MARKETPLACE_IDS:
        warnings.append("listing_marketplace_unrecognized")
    if raw_marketplace and raw_marketplace != marketplace_id:
        warnings.append("listing_marketplace_mismatch")
        # Keep the requested marketplace scope; do not silently adopt the row's id.
    title = _text(item.get("title"), 240)
    price_value = item.get("price")
    price = price_value if isinstance(price_value, Mapping) else {}
    shipping = item.get("shippingOptions")
    shipping_row = shipping[0] if isinstance(shipping, list) and shipping and isinstance(shipping[0], Mapping) else {}
    shipping_value = shipping_row.get("shippingCost")
    shipping_price = shipping_value if isinstance(shipping_value, Mapping) else {}
    source_url = _safe_url(item.get("itemWebUrl"))
    currency = _currency_code(price.get("currency"))
    shipping_currency = _currency_code(shipping_price.get("currency"))
    field_provenance: dict[str, str] = {"marketplace_id": "observed"}
    if title:
        field_provenance["title"] = "observed"
    if _number(price.get("value")) is not None:
        field_provenance["price"] = "observed"
    if currency:
        field_provenance["currency"] = "observed"
    else:
        field_provenance["currency"] = "unavailable"
    if source_url:
        field_provenance["source_url"] = "observed"
    availability = _text(item.get("estimatedAvailabilityStatus") or item.get("availability"), 80)
    if availability:
        field_provenance["availability"] = "observed"
    if _number(shipping_price.get("value")) is not None:
        field_provenance["shipping_cost"] = "observed"
    listing = EbayBrowseListing(
        item_id=item_id,
        candidate_id=candidate_id,
        query=query,
        title=title,
        source_url=source_url,
        marketplace_id=marketplace_id,
        price=_number(price.get("value")),
        currency=currency,
        availability=availability,
        shipping_cost=_number(shipping_price.get("value")),
        shipping_currency=shipping_currency,
        variants=_variants(item),
        field_provenance=field_provenance,
        evidence_mode=evidence_mode,
        observed_at=observed_at,
    )
    return listing, tuple(warnings)


@dataclass
class FixtureEbayBrowseTransport:
    """In-memory Browse-shaped payload for tests/demos.  Never live evidence."""

    payload: Mapping[str, Any]
    kind: str = TRANSPORT_KIND_FIXTURE

    def __call__(self, request: EbayBrowseRequest, *, timeout_s: float) -> Mapping[str, Any]:
        del request, timeout_s
        return self.payload


@dataclass
class LiveEbayBrowseTransport:
    """Official Browse API GET transport (read-only item_summary/search).

    Authentication uses a caller-supplied token resolver keyed by
    ``credential_ref``.  This class never opens secret stores, never logs
    tokens, and never performs write/order/inventory operations.
    """

    credential_ref: str
    token_resolver: CredentialTokenResolver
    api_base: str = DEFAULT_API_BASE
    kind: str = TRANSPORT_KIND_LIVE
    opener: Callable[[urllib.request.Request, float], Any] | None = None

    def __call__(self, request: EbayBrowseRequest, *, timeout_s: float) -> Mapping[str, Any]:
        token = self.token_resolver(self.credential_ref)
        if not token or not str(token).strip():
            raise PermissionError("credential_reference_resolved_empty")
        query = urllib.parse.urlencode(dict(request.params))
        url = f"{self.api_base.rstrip('/')}{request.path}?{query}"
        http_request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {str(token).strip()}",
                "X-EBAY-C-MARKETPLACE-ID": request.marketplace_id,
                "Accept": "application/json",
                "User-Agent": "MarketOS-EbayBrowseAdapter/1.0",
            },
        )
        open_url = self.opener or (lambda req, timeout: urllib.request.urlopen(req, timeout=timeout))
        try:
            with open_url(http_request, timeout_s) as response:
                body = response.read()
                status = getattr(response, "status", None) or response.getcode()
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise PermissionError("provider_authorization_failed") from None
            if exc.code == 429:
                raise EbayBrowseRateLimitError("provider_rate_limited") from None
            raise RuntimeError("provider_http_error") from None
        except TimeoutError:
            raise
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise TimeoutError("provider_timeout") from None
            raise RuntimeError("provider_transport_error") from None
        if status == 429:
            raise EbayBrowseRateLimitError("provider_rate_limited")
        if status in {401, 403}:
            raise PermissionError("provider_authorization_failed")
        if status != 200:
            raise RuntimeError("provider_http_error")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("provider_response_not_json") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("provider_response_not_object")
        return payload


class EbayBrowseAdapter:
    def __init__(
        self,
        config: EbayBrowseConfig | None = None,
        *,
        transport: EbayBrowseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config or EbayBrowseConfig()
        self.transport = transport
        self._clock = clock

    def health(self) -> AdapterHealth:
        if not self.config.enabled:
            return AdapterHealth(ADAPTER_NAME, False, False, ("search_listings",), detail="disabled")
        if self.config.transport_kind == TRANSPORT_KIND_FIXTURE:
            return AdapterHealth(
                ADAPTER_NAME,
                True,
                self.transport is not None,
                ("search_listings",),
                detail="fixture_transport_only",
            )
        if not self.config.configured:
            return AdapterHealth(ADAPTER_NAME, False, False, ("search_listings",), detail="unconfigured")
        if not self.config.ready_for_live_transport:
            return AdapterHealth(ADAPTER_NAME, True, False, ("search_listings",), detail="live_authorization_or_network_gate_required")
        return AdapterHealth(
            ADAPTER_NAME,
            True,
            self.transport is not None,
            ("search_listings",),
            detail="transport injected" if self.transport else "transport missing",
        )

    def _observed_at(self, transport_kind: str) -> str:
        if transport_kind == TRANSPORT_KIND_LIVE:
            return datetime.fromtimestamp(self._clock(), tz=timezone.utc).isoformat().replace("+00:00", "Z")
        return "fixture_deterministic"

    def _empty(
        self,
        status: str,
        candidate_id: str,
        query: str,
        *,
        warnings: tuple[str, ...] = (),
        error_code: str = "",
        network_calls: bool = False,
        pages: int = 0,
        listings: tuple[EbayBrowseListing, ...] = (),
        authorization: EbayBrowseAuthorizationDecision | None = None,
        transport_kind: str | None = None,
    ) -> EbayBrowseResult:
        return EbayBrowseResult(
            status=status,
            candidate_id=candidate_id,
            query=query,
            marketplace_id=self.config.marketplace_id,
            transport_kind=transport_kind or self.config.transport_kind,
            pages_attempted=pages,
            listings=listings,
            warnings=warnings,
            error_code=error_code or status,
            network_calls=network_calls,
            authorization=authorization,
        )

    def search_brief(self, brief: Mapping[str, Any]) -> EbayBrowseResult:
        candidate_id = _candidate_id(brief)
        query = brief_query(brief)
        transport_kind = _transport_kind(self.transport, self.config)
        authorization = self.config.authorization_decision() if transport_kind == TRANSPORT_KIND_LIVE else None

        if not candidate_id or not query:
            return self._empty(
                "invalid_brief",
                candidate_id,
                query,
                warnings=("candidate_id_and_query_required",),
                authorization=authorization,
                transport_kind=transport_kind,
            )
        if not self.config.enabled:
            return self._empty(
                "disabled",
                candidate_id,
                query,
                warnings=("adapter_disabled",),
                authorization=authorization,
                transport_kind=transport_kind,
            )

        if transport_kind == TRANSPORT_KIND_LIVE:
            if not self.config.configured:
                return self._empty(
                    "unconfigured",
                    candidate_id,
                    query,
                    warnings=("credential_reference_and_marketplace_required",),
                    authorization=authorization,
                    transport_kind=transport_kind,
                )
            if not self.config.allow_network:
                return self._empty(
                    "network_gate_required",
                    candidate_id,
                    query,
                    warnings=("network_gate_required",),
                    authorization=authorization,
                    transport_kind=transport_kind,
                )
            if authorization is None or not authorization.authorized:
                return self._empty(
                    "approval_denied",
                    candidate_id,
                    query,
                    warnings=("approval_ledger_denied_live_provider_call", *_LIVE_PREREQUISITES),
                    error_code="approval_denied",
                    authorization=authorization,
                    transport_kind=transport_kind,
                )

        if self.transport is None:
            return self._empty(
                "unconfigured",
                candidate_id,
                query,
                warnings=("transport_not_configured",),
                authorization=authorization,
                transport_kind=transport_kind,
            )

        # Fixture transport must never claim live evidence even if misconfigured.
        if transport_kind == TRANSPORT_KIND_FIXTURE and self.config.transport_kind == TRANSPORT_KIND_LIVE:
            return self._empty(
                "transport_kind_mismatch",
                candidate_id,
                query,
                warnings=("fixture_transport_cannot_satisfy_live_config",),
                error_code="transport_kind_mismatch",
                authorization=authorization,
                transport_kind=TRANSPORT_KIND_FIXTURE,
            )

        evidence_mode = "live_readonly" if transport_kind == TRANSPORT_KIND_LIVE else "fixture"
        observed_at = self._observed_at(transport_kind)
        network_calls = transport_kind == TRANSPORT_KIND_LIVE
        listings: list[EbayBrowseListing] = []
        seen: set[str] = set()
        warnings: list[str] = ["current_listings_are_not_bestseller_or_verified_demand_evidence"]
        if transport_kind == TRANSPORT_KIND_FIXTURE:
            warnings.append("fixture_or_fake_transport_is_not_live_proof")
        pages = 0
        try:
            for page in range(self.config.max_pages):
                pages += 1
                offset = page * self.config.page_size
                request = EbayBrowseRequest(
                    BROWSE_PATH,
                    self.config.marketplace_id,
                    query,
                    {"q": query, "limit": str(self.config.page_size), "offset": str(offset)},
                )
                payload = self.transport(request, timeout_s=self.config.timeout_s)
                if not isinstance(payload, Mapping):
                    return self._empty(
                        "malformed_response",
                        candidate_id,
                        query,
                        warnings=tuple(warnings + ["response_not_an_object"]),
                        error_code="malformed_response",
                        network_calls=network_calls,
                        pages=pages,
                        listings=tuple(listings),
                        authorization=authorization,
                        transport_kind=transport_kind,
                    )
                rows = payload.get("itemSummaries")
                if rows is None:
                    rows = payload.get("items")
                if not isinstance(rows, list):
                    return self._empty(
                        "malformed_response",
                        candidate_id,
                        query,
                        warnings=tuple(warnings + ["item_summaries_not_a_list"]),
                        error_code="malformed_response",
                        network_calls=network_calls,
                        pages=pages,
                        listings=tuple(listings),
                        authorization=authorization,
                        transport_kind=transport_kind,
                    )
                for raw in rows:
                    listing, listing_warnings = _normalize_listing(
                        raw,
                        candidate_id=candidate_id,
                        query=query,
                        marketplace_id=self.config.marketplace_id,
                        evidence_mode=evidence_mode,
                        observed_at=observed_at,
                    )
                    warnings.extend(listing_warnings)
                    if listing and listing.item_id not in seen:
                        seen.add(listing.item_id)
                        listings.append(listing)
                if len(rows) < self.config.page_size:
                    break
            if pages >= self.config.max_pages and listings:
                warnings.append("pagination_cap_reached")
        except TimeoutError:
            return self._empty(
                "timeout",
                candidate_id,
                query,
                warnings=tuple(warnings + ["provider_timeout"]),
                error_code="timeout",
                network_calls=network_calls,
                pages=pages,
                listings=tuple(listings),
                authorization=authorization,
                transport_kind=transport_kind,
            )
        except PermissionError:
            return self._empty(
                "auth_failed",
                candidate_id,
                query,
                warnings=tuple(warnings + ["provider_authorization_failed"]),
                error_code="auth_failed",
                network_calls=network_calls,
                pages=pages,
                listings=tuple(listings),
                authorization=authorization,
                transport_kind=transport_kind,
            )
        except EbayBrowseRateLimitError:
            return self._empty(
                "rate_limited",
                candidate_id,
                query,
                warnings=tuple(warnings + ["provider_rate_limited"]),
                error_code="rate_limited",
                network_calls=network_calls,
                pages=pages,
                listings=tuple(listings),
                authorization=authorization,
                transport_kind=transport_kind,
            )
        except Exception:
            return self._empty(
                "transport_error",
                candidate_id,
                query,
                warnings=tuple(warnings + ["provider_request_failed_details_withheld"]),
                error_code="transport_error",
                network_calls=network_calls,
                pages=pages,
                listings=tuple(listings),
                authorization=authorization,
                transport_kind=transport_kind,
            )
        return EbayBrowseResult(
            status="ok",
            candidate_id=candidate_id,
            query=query,
            marketplace_id=self.config.marketplace_id,
            transport_kind=transport_kind,
            pages_attempted=pages,
            listings=tuple(listings),
            warnings=tuple(dict.fromkeys(warnings)),
            network_calls=network_calls,
            authorization=authorization,
        )


def search_brief(
    brief: Mapping[str, Any],
    *,
    config: EbayBrowseConfig | None = None,
    transport: EbayBrowseTransport | None = None,
) -> EbayBrowseResult:
    """Convenience entry point for the existing research-brief seam."""
    return EbayBrowseAdapter(config, transport=transport).search_brief(brief)


__all__ = [
    "ADAPTER_NAME",
    "BROWSE_PATH",
    "CredentialTokenResolver",
    "EbayBrowseAdapter",
    "EbayBrowseAuthorizationDecision",
    "EbayBrowseConfig",
    "EbayBrowseListing",
    "EbayBrowseRateLimitError",
    "EbayBrowseRequest",
    "EbayBrowseResult",
    "FixtureEbayBrowseTransport",
    "LiveEbayBrowseTransport",
    "MAX_PAGE_SIZE",
    "MAX_RETRIES",
    "SUPPORTED_MARKETPLACE_IDS",
    "TRANSPORT_KIND_FIXTURE",
    "TRANSPORT_KIND_LIVE",
    "brief_query",
    "evaluate_ebay_browse_authorization",
    "search_brief",
]

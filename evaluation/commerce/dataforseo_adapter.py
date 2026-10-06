"""Deterministic, fixture-backed DataForSEO read-only adapter.

This is a concrete provider plan and parser, not a transport client.  It
never loads credentials, creates requests, calls DataForSEO, stores raw
responses, or grants live execution authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from evaluation.companyos.approval_ledger import REQUEST_TYPES
from evaluation.companyos.credential_registry import build_credential_registry
from evaluation.companyos.provider_registry import build_provider_registry
from evaluation.secret_markers import contains_boundary_prefixed_sk_token

REQUEST_KINDS = (
    "serp_google_organic_snapshot",
    "serp_google_shopping_snapshot",
    "keyword_demand_snapshot",
    "competitor_serp_snapshot",
    "dry_run_fixture_parse",
)
REQUEST_STATUSES = (
    "fixture_only",
    "dry_run_ready",
    "approval_required",
    "blocked_missing_credential",
    "blocked_missing_approval",
    "blocked_terms_privacy",
    "blocked_live_mode",
)
READINESS_STATES = ("not_ready", "fixture_ready", "dry_run_ready", "approval_ready_later", "blocked")
EVIDENCE_CATEGORIES = (
    "SearchDemandEvidence",
    "CompetitorSearchEvidence",
    "ShoppingResultEvidence",
    "MarketplaceTrendEvidence",
    "ConsumerAttentionEvidence",
    "ProviderRunEvidence",
)
STOP_CONDITIONS = (
    "approval_missing",
    "credential_missing",
    "budget_cap_reached",
    "terms_review_missing",
    "privacy_review_missing",
    "unexpected_schema",
    "fixture_contract_failed",
    "live_mode_requested",
    "network_attempted",
    "raw_payload_detected",
)
_SECRET_KEYS = frozenset({
    "actual_secret_value", "api_key", "raw_api_key", "raw_oauth_token", "oauth_token",
    "access_token", "refresh_token", "password", "private_key", "private_key_material",
    "authorization", "cookie", "cookies",
})
_RAW_KEYS = frozenset({"raw_payload", "raw_html", "html", "body", "response_body", "javascript", "browser_trace"})


def _clean(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _clean(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_clean(item) for item in value]
    return value


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)





def _secret_like(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(str(key).lower().replace("-", "_") in _SECRET_KEYS | _RAW_KEYS or _secret_like(item) for key, item in value.items())
    if isinstance(value, (tuple, list, set)):
        return any(_secret_like(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return "-----begin " in lowered or "bearer " in lowered or contains_boundary_prefixed_sk_token(value) or any(marker in lowered for marker in ("ghp_", "xoxb-", "aiza"))
    return False


def _number(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int | None = None) -> int | None:
    number = _number(value)
    return default if number is None else int(number)


@dataclass(frozen=True)
class DataForSEOKeywordTask:
    keyword: str
    location_code_placeholder: str = "TBD"
    language_code: str = "en"
    device: str = "desktop"

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class DataForSEOSerpTask:
    keyword: str
    request_kind: str = "serp_google_organic_snapshot"
    location_code_placeholder: str = "TBD"
    language_code: str = "en"
    device: str = "desktop"

    def __post_init__(self) -> None:
        if self.request_kind not in {"serp_google_organic_snapshot", "competitor_serp_snapshot"}:
            raise ValueError("invalid DataForSEO SERP request kind")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class DataForSEOShoppingTask:
    keyword: str
    location_code_placeholder: str = "TBD"
    language_code: str = "en"
    device: str = "desktop"

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class DataForSEORequestPlan:
    provider_id: str
    request_plan_id: str
    request_kind: str
    endpoint_placeholder: str
    keywords: tuple[str, ...]
    location_code_placeholder: str
    language_code: str
    device: str
    max_requests: int
    max_items: int
    max_cost: float
    monthly_budget_cap: float
    credential_reference_id: str
    approval_request_type: str
    terms_review_required: bool
    privacy_review_required: bool
    live_request_created: bool
    network_calls: bool
    sdk_used: bool
    raw_payload_stored: bool
    schedule_enabled: bool
    status: str

    def __post_init__(self) -> None:
        if self.provider_id != "dataforseo":
            raise ValueError("DataForSEO adapter must use provider_id dataforseo")
        if self.request_kind not in REQUEST_KINDS:
            raise ValueError(f"unsupported request kind: {self.request_kind}")
        if self.status not in REQUEST_STATUSES:
            raise ValueError(f"unsupported request status: {self.status}")
        if self.approval_request_type not in REQUEST_TYPES:
            raise ValueError("approval request type must reuse Approval Ledger vocabulary")
        if any((self.live_request_created, self.network_calls, self.sdk_used, self.raw_payload_stored, self.schedule_enabled)):
            raise ValueError("DataForSEO request plans are offline, unscheduled, and raw-payload-free")
        if self.max_requests < 1 or self.max_items < 1 or self.max_cost < 0 or self.monthly_budget_cap < 0:
            raise ValueError("DataForSEO request bounds must be non-negative and useful")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class DataForSEOResponseFixture:
    fixture_id: str
    request_kind: str
    source_file: str
    schema_status: str
    task_count: int
    record_count: int
    sanitized: bool
    raw_payload_stored: bool
    raw_html_stored: bool

    def __post_init__(self) -> None:
        if not self.sanitized or self.raw_payload_stored or self.raw_html_stored:
            raise ValueError("DataForSEO fixture metadata must be sanitized")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class DataForSEONormalizedSearchSignal:
    source_provider: str
    source_method: str
    request_kind: str
    candidate_id: str
    query: str
    rank: int | None
    title: str
    url_placeholder: str
    domain_placeholder: str
    price: float | None
    currency: str | None
    rating: float | None
    review_count: int | None
    snippet: str
    detected_competitor: bool
    commercial_intent_score: float
    evidence_category: str
    confidence: str
    limitations: tuple[str, ...]
    terms_notes: str
    privacy_notes: str
    can_feed_reports: bool

    def __post_init__(self) -> None:
        if self.evidence_category not in EVIDENCE_CATEGORIES:
            raise ValueError("unsupported DataForSEO evidence category")
        if not 0 <= self.commercial_intent_score <= 1:
            raise ValueError("commercial intent score must be between zero and one")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class DataForSEONormalizedShoppingSignal(DataForSEONormalizedSearchSignal):
    seller_placeholder: str = "TBD"
    availability: str = "unavailable"

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class DataForSEOCompetitorSignal:
    source_provider: str
    source_method: str
    request_kind: str
    candidate_id: str
    query: str
    competitor_name: str
    domain_placeholder: str
    rank: int | None
    price: float | None
    currency: str | None
    commercial_intent_score: float
    evidence_category: str
    confidence: str
    limitations: tuple[str, ...]
    terms_notes: str
    privacy_notes: str
    can_feed_reports: bool

    def __post_init__(self) -> None:
        if self.evidence_category != "CompetitorSearchEvidence":
            raise ValueError("competitor signals must use CompetitorSearchEvidence")
        if not 0 <= self.commercial_intent_score <= 1:
            raise ValueError("commercial intent score must be between zero and one")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class DataForSEOParseResult:
    fixture: DataForSEOResponseFixture
    search_signals: tuple[DataForSEONormalizedSearchSignal, ...]
    shopping_signals: tuple[DataForSEONormalizedShoppingSignal, ...]
    competitor_signals: tuple[DataForSEOCompetitorSignal, ...]
    warnings: tuple[str, ...]
    parse_status: str
    raw_payload_stored: bool

    def __post_init__(self) -> None:
        if self.raw_payload_stored:
            raise ValueError("parse result cannot retain raw payload")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class DataForSEOApprovalReadiness:
    provider_registered: bool
    credential_reference_exists: bool
    secret_value_absent: bool
    approval_required: bool
    approval_request_type: str
    budget_cap_set: bool
    terms_review_complete: bool
    privacy_review_complete: bool
    fixture_output_contract_tested: bool
    live_mode_blocked: bool
    readiness_state: str
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.approval_request_type not in REQUEST_TYPES:
            raise ValueError("approval type must reuse Approval Ledger vocabulary")
        if self.readiness_state not in READINESS_STATES:
            raise ValueError("unsupported DataForSEO readiness state")
        if not self.secret_value_absent or not self.live_mode_blocked:
            raise ValueError("DataForSEO readiness must be secret-free and live-blocked")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class DataForSEOCredentialReadiness:
    provider_id: str
    credential_reference_id: str
    reference_exists: bool
    secret_value_absent: bool
    status: str
    notes: str

    def __post_init__(self) -> None:
        if self.provider_id != "dataforseo" or not self.secret_value_absent:
            raise ValueError("credential readiness must be DataForSEO metadata only")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class DataForSEOCostEstimate:
    estimated_cost_per_request_min: float
    estimated_cost_per_request_max: float
    estimated_cost_per_run_min: float
    estimated_cost_per_run_max: float
    monthly_budget_cap: float
    currency: str
    assumption_note: str
    overage_risk: str
    stop_conditions: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.estimated_cost_per_request_min < 0 or self.estimated_cost_per_request_max < self.estimated_cost_per_request_min:
            raise ValueError("invalid DataForSEO request cost band")
        if self.monthly_budget_cap < self.estimated_cost_per_run_max:
            raise ValueError("monthly budget must cover at least one bounded run")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class DataForSEORateLimitPlan:
    max_keywords_per_run: int
    max_requests_per_run: int
    max_results_per_keyword: int
    max_runs_per_day: int
    rate_limit_notes: str
    stop_conditions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class DataForSEOTermsPrivacyStatus:
    terms_review_required: bool
    terms_review_complete: bool
    privacy_review_required: bool
    privacy_review_complete: bool
    data_minimization_note: str
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class DataForSEOOutputContract:
    contract_id: str
    accepted_request_kinds: tuple[str, ...]
    normalized_models: tuple[str, ...]
    required_fields: tuple[str, ...]
    raw_payload_allowed: bool
    raw_html_allowed: bool
    provenance_required: bool
    fixture_tested: bool

    def __post_init__(self) -> None:
        if self.raw_payload_allowed or self.raw_html_allowed:
            raise ValueError("DataForSEO output contract cannot accept raw payloads or HTML")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class DataForSEOAdapterSafetySummary:
    read_only: bool
    live_request_created: bool
    network_calls: bool
    credentials_loaded: bool
    sdk_used: bool
    raw_payload_stored: bool
    raw_html_stored: bool
    scraping_performed: bool
    fail_closed: bool

    def __post_init__(self) -> None:
        if not self.read_only or any((self.live_request_created, self.network_calls, self.credentials_loaded, self.sdk_used, self.raw_payload_stored, self.raw_html_stored, self.scraping_performed)):
            raise ValueError("DataForSEO adapter must remain offline and read-only")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class DataForSEOAdapterReport:
    report_version: str
    generated_at: str
    request_plan: DataForSEORequestPlan
    keyword_tasks: tuple[DataForSEOKeywordTask, ...]
    serp_tasks: tuple[DataForSEOSerpTask, ...]
    shopping_tasks: tuple[DataForSEOShoppingTask, ...]
    response_fixtures: tuple[DataForSEOResponseFixture, ...]
    parse_result: DataForSEOParseResult
    approval_readiness: DataForSEOApprovalReadiness
    credential_readiness: DataForSEOCredentialReadiness
    cost_estimate: DataForSEOCostEstimate
    rate_limit_plan: DataForSEORateLimitPlan
    terms_privacy_status: DataForSEOTermsPrivacyStatus
    output_contract: DataForSEOOutputContract
    safety_summary: DataForSEOAdapterSafetySummary
    marketplace_trend_signals: tuple[dict[str, Any], ...]
    consumer_attention_signals: tuple[dict[str, Any], ...]
    opportunity_search_context: dict[str, Any]
    product_validation_search_summary: dict[str, Any]
    blocked_live_activation: tuple[str, ...]
    next_best_action: str

    def to_marketplace_trend_signals(self) -> tuple[dict[str, Any], ...]:
        return self.marketplace_trend_signals

    def to_consumer_attention_signals(self) -> tuple[dict[str, Any], ...]:
        return self.consumer_attention_signals

    def to_opportunity_search_context(self) -> dict[str, Any]:
        return self.opportunity_search_context

    def to_product_validation_search_summary(self) -> dict[str, Any]:
        return self.product_validation_search_summary

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)

    def to_markdown(self) -> str:
        lines = [
            "# DataForSEO Read-Only Intelligence Adapter", "", "## Executive Summary", "",
            f"- Request kind: **{self.request_plan.request_kind}**", f"- Keywords: **{len(self.request_plan.keywords)}**",
            f"- Parse status: **{self.parse_result.parse_status}**", f"- Search signals: **{len(self.parse_result.search_signals)}**",
            f"- Shopping signals: **{len(self.parse_result.shopping_signals)}**", f"- Competitor signals: **{len(self.parse_result.competitor_signals)}**",
            f"- Readiness: **{self.approval_readiness.readiness_state}**", "- Mode: **offline fixture/dry-run only**", "",
            "## Request Plan", "", f"- Endpoint placeholder: `{self.request_plan.endpoint_placeholder}`",
            f"- Max requests/items/cost: **{self.request_plan.max_requests}/{self.request_plan.max_items}/${self.request_plan.max_cost:.2f}**",
            f"- Approval request type: `{self.request_plan.approval_request_type}`", "- Live request/network/SDK/schedule/raw payload: **false**", "",
            "## Normalized Signals", "", "| Query | Type | Rank | Price | Intent | Confidence |", "|---|---|---:|---:|---:|---|",
        ]
        for item in (*self.parse_result.search_signals, *self.parse_result.shopping_signals):
            lines.append(f"| {item.query} | {item.evidence_category} | {item.rank or '—'} | {item.price or '—'} | {item.commercial_intent_score:.2f} | {item.confidence} |")
        lines += ["", "## Approval and Credential Readiness", "", f"- Provider registered: **{self.approval_readiness.provider_registered}**", f"- Credential reference: **{self.credential_readiness.status}**", f"- Terms/privacy: **{len(self.terms_privacy_status.blockers)} blocker(s)**", "- Live activation: **blocked**", ""]
        lines += ["## Cost and Rate Limits", "", f"- Request band: **${self.cost_estimate.estimated_cost_per_request_min:.2f}-${self.cost_estimate.estimated_cost_per_request_max:.2f}**", f"- Run band: **${self.cost_estimate.estimated_cost_per_run_min:.2f}-${self.cost_estimate.estimated_cost_per_run_max:.2f}**", f"- Monthly cap: **${self.cost_estimate.monthly_budget_cap:.2f}**", f"- Limits: **{self.rate_limit_plan.max_keywords_per_run} keywords / {self.rate_limit_plan.max_requests_per_run} requests / {self.rate_limit_plan.max_results_per_keyword} results / {self.rate_limit_plan.max_runs_per_day} runs/day**", ""]
        lines += ["## Commerce Dry-Run Context", "", f"- Marketplace signals: **{len(self.marketplace_trend_signals)}**", f"- Consumer-attention signals: **{len(self.consumer_attention_signals)}**", f"- Search context: `{self.opportunity_search_context['evidence_mode']}`", ""]
        lines += ["## Blocked Live Activation", ""] + [f"- {item}" for item in self.blocked_live_activation] + ["", "## Next Best Action", "", self.next_best_action, "", "## Safety Boundaries", "", "No credentials are loaded, no network or SDK call occurs, and no raw provider response or HTML is retained.", ""]
        return "\n".join(lines)


def _record_from_item(item: Mapping[str, Any], *, candidate_id: str, query: str, request_kind: str, category: str, index: int) -> DataForSEONormalizedSearchSignal:
    if _secret_like(item):
        raise ValueError("secret-like or raw provider fields are not accepted")
    rank = _integer(item.get("rank", item.get("position")))
    title = str(item.get("title", item.get("name", "Synthetic result")))[:240]
    price = _number(item.get("price"))
    rating = _number(item.get("rating"))
    reviews = _integer(item.get("review_count", item.get("reviews")))
    url_placeholder = str(item.get("url_placeholder", "TBD"))
    domain = str(item.get("domain_placeholder", item.get("domain", "TBD")))
    snippet = str(item.get("snippet", item.get("description", "Synthetic fixture result.")))[:400]
    commercial = _number(item.get("commercial_intent_score"), None)
    if commercial is None:
        commercial = min(1.0, 0.35 + (0.15 if price is not None else 0) + (0.15 if item.get("shopping") else 0) + (0.1 if rank and rank <= 10 else 0))
    return DataForSEONormalizedSearchSignal("dataforseo", "sanitized_fixture_parser", request_kind, candidate_id, query, rank, title, url_placeholder, domain, price, str(item.get("currency", "USD")) if price is not None else None, rating, reviews, snippet, bool(item.get("detected_competitor", False)), round(commercial, 3), category, "fixture", ("Synthetic fixture; not live search proof.", "Rank and price are normalized assumptions from fixture fields."), "DataForSEO terms review required before activation.", "No personal data retained; only aggregate/product signals are kept.", True)


def parse_dataforseo_fixture(payload: Mapping[str, Any], *, request_kind: str = "serp_google_organic_snapshot", source_file: str = "fixture://dataforseo") -> DataForSEOParseResult:
    """Parse a sanitized DataForSEO-shaped fixture and discard its input shape."""
    if _secret_like(payload):
        raise ValueError("secret-like or raw DataForSEO fixture is not accepted")
    if request_kind not in REQUEST_KINDS:
        raise ValueError(f"unsupported request kind: {request_kind}")
    if not isinstance(payload, Mapping) or payload.get("fixture_mode") is not True:
        raise ValueError("DataForSEO fixtures must explicitly set fixture_mode=true")
    tasks = payload.get("tasks", ())
    if not isinstance(tasks, Sequence) or isinstance(tasks, (str, bytes)):
        raise ValueError("DataForSEO fixture tasks must be a list")
    searches: list[DataForSEONormalizedSearchSignal] = []
    shopping: list[DataForSEONormalizedShoppingSignal] = []
    competitors: list[DataForSEOCompetitorSignal] = []
    warnings: list[str] = []
    for task_index, task in enumerate(tasks, 1):
        if not isinstance(task, Mapping):
            warnings.append(f"task_{task_index}_ignored_non_mapping")
            continue
        query = str(task.get("query", task.get("keyword", "unknown query")))
        candidate_id = str(task.get("candidate_id", query.lower().replace(" ", "-")))
        items = task.get("items", task.get("results", ()))
        if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
            raise ValueError("DataForSEO fixture task items must be a list")
        for index, raw_item in enumerate(items, 1):
            if not isinstance(raw_item, Mapping):
                warnings.append(f"{candidate_id}_item_{index}_ignored_non_mapping")
                continue
            # Fixtures may intentionally contain both organic and shopping
            # rows, even when the request plan is a shopping snapshot.  Use
            # the row-level marker when present so mixed dry-runs preserve
            # both evidence families instead of coercing every result.
            is_shopping = bool(raw_item.get("shopping", False))
            category = "ShoppingResultEvidence" if is_shopping else "SearchDemandEvidence"
            normalized = _record_from_item(raw_item, candidate_id=candidate_id, query=query, request_kind=request_kind, category=category, index=index)
            if category == "ShoppingResultEvidence":
                shopping.append(DataForSEONormalizedShoppingSignal(**normalized.to_dict(), seller_placeholder=str(raw_item.get("seller_placeholder", raw_item.get("seller", "TBD"))), availability=str(raw_item.get("availability", "unavailable"))))
            else:
                searches.append(normalized)
            if request_kind in {"competitor_serp_snapshot", "serp_google_shopping_snapshot"} or raw_item.get("detected_competitor"):
                competitors.append(DataForSEOCompetitorSignal("dataforseo", "sanitized_fixture_parser", request_kind, candidate_id, query, str(raw_item.get("competitor_name", raw_item.get("domain", "Synthetic competitor"))), str(raw_item.get("domain_placeholder", raw_item.get("domain", "TBD"))), normalized.rank, normalized.price, normalized.currency, normalized.commercial_intent_score, "CompetitorSearchEvidence", "fixture", ("Synthetic competitor signal; not live competitive proof.",), "Terms review required before live use.", "No personal data retained.", True))
    if not tasks:
        warnings.append("empty_fixture_results")
    fixture = DataForSEOResponseFixture(str(payload.get("fixture_id", "dataforseo-fixture")), request_kind, source_file, "valid" if tasks else "empty", len(tasks), len(searches) + len(shopping), True, False, False)
    return DataForSEOParseResult(fixture, tuple(searches), tuple(shopping), tuple(competitors), tuple(warnings), "empty" if not tasks else "parsed", False)


def _default_payload(request_kind: str, keywords: Sequence[str]) -> dict[str, Any]:
    return {"fixture_id": "dataforseo-default-synthetic", "fixture_mode": True, "request_kind": request_kind, "tasks": [{"candidate_id": keyword.lower().replace(" ", "-"), "query": keyword, "items": [{"title": f"Synthetic result for {keyword}", "rank": index + 1, "domain": "example.invalid", "price": 29.99 + index, "currency": "USD", "review_count": 24 + index, "rating": 4.2, "snippet": "Synthetic fixture result for deterministic testing.", "shopping": request_kind == "serp_google_shopping_snapshot", "detected_competitor": request_kind in {"competitor_serp_snapshot", "serp_google_shopping_snapshot"}} for index in range(2)]} for keyword in keywords]}


def _plan(request_kind: str, keywords: tuple[str, ...], *, live_requested: bool, max_keywords: int = 10, max_requests: int = 10, max_items: int = 100, max_cost: float = 2.0, monthly_budget_cap: float = 50.0) -> DataForSEORequestPlan:
    return DataForSEORequestPlan("dataforseo", "dataforseo-request-plan-v1", request_kind, {"serp_google_organic_snapshot": "/serp/google/organic/task_post", "serp_google_shopping_snapshot": "/serp/google/shopping/task_post", "keyword_demand_snapshot": "/keywords_data/google_ads/search_volume/task_post", "competitor_serp_snapshot": "/serp/google/organic/task_post", "dry_run_fixture_parse": "fixture://dataforseo"}[request_kind], keywords[:max_keywords], "TBD", "en", "desktop", min(max_requests, max(1, len(keywords))), max_items, max_cost, monthly_budget_cap, "credential-dataforseo", "provider_call", True, True, False, False, False, False, False, "blocked_live_mode" if live_requested else "dry_run_ready")


def build_dataforseo_adapter_report(*, generated_at: str = "offline-deterministic", request_kind: str = "serp_google_organic_snapshot", keywords: Sequence[str] = ("mini thermal printer",), payload: Mapping[str, Any] | None = None, source_file: str = "fixture://dataforseo-default", live_read_only: bool = False, max_keywords: int = 10, max_requests: int = 10, max_items: int = 100, max_cost: float = 2.0, monthly_budget_cap: float = 50.0) -> DataForSEOAdapterReport:
    if request_kind not in REQUEST_KINDS:
        raise ValueError(f"unsupported request kind: {request_kind}")
    clean_keywords = tuple(dict.fromkeys(str(item).strip() for item in keywords if str(item).strip()))[:max_keywords] or ("mini thermal printer",)
    plan = _plan(request_kind, clean_keywords, live_requested=live_read_only, max_keywords=max_keywords, max_requests=max_requests, max_items=max_items, max_cost=max_cost, monthly_budget_cap=monthly_budget_cap)
    parsed = parse_dataforseo_fixture(payload or _default_payload(request_kind, clean_keywords), request_kind=request_kind, source_file=source_file)
    providers = build_provider_registry(generated_at=generated_at)
    credentials = build_credential_registry(generated_at=generated_at)
    provider_registered = any(item.provider_id == "dataforseo" for item in providers.providers)
    reference_exists = any(item.credential_id == "credential-dataforseo" for item in credentials.credentials)
    credential = DataForSEOCredentialReadiness("dataforseo", "credential-dataforseo", reference_exists, True, "metadata_only", "No secret is loaded or validated.")
    terms = DataForSEOTermsPrivacyStatus(True, False, True, False, "Retain only aggregate search/product signals; omit identifiers and raw responses.", ("terms_review_missing", "privacy_review_missing"))
    blockers = ["approval_missing", "terms_review_missing", "privacy_review_missing"]
    if not reference_exists:
        blockers.insert(0, "credential_missing")
    if live_read_only:
        blockers.insert(0, "live_mode_requested")
    readiness_state = "blocked" if live_read_only else "dry_run_ready"
    readiness = DataForSEOApprovalReadiness(provider_registered, reference_exists, True, True, "provider_call", True, False, False, True, True, readiness_state, tuple(dict.fromkeys(blockers)))
    cost = DataForSEOCostEstimate(max(0.01, max_cost / max(1, max_requests * 4)), max_cost / max(1, max_requests), max_cost / 2, max_cost, monthly_budget_cap, "USD", "Synthetic configurable planning band; verify current provider pricing before activation.", "Unexpected pagination, result volume, or provider overage may exceed the cap.", STOP_CONDITIONS)
    rate = DataForSEORateLimitPlan(max_keywords, max_requests, max_items, 10, "Future transport must use bounded batches and backoff; no requests occur now.", STOP_CONDITIONS)
    output = DataForSEOOutputContract("dataforseo-normalized-evidence-v1", REQUEST_KINDS, ("DataForSEONormalizedSearchSignal", "DataForSEONormalizedShoppingSignal", "DataForSEOCompetitorSignal"), ("source_provider", "source_method", "request_kind", "candidate_id", "query", "rank", "title", "url_placeholder", "domain_placeholder", "confidence", "limitations", "terms_notes", "privacy_notes", "can_feed_reports"), False, False, True, True)
    marketplace = tuple({"source_provider": item.source_provider, "source_method": item.source_method, "candidate_id": item.candidate_id, "query": item.query, "price": item.price, "currency": item.currency, "rank": item.rank, "evidence_category": "MarketplaceTrendEvidence", "confidence": item.confidence, "limitations": list(item.limitations), "can_feed_reports": True} for item in parsed.shopping_signals)
    attention = tuple({"source_provider": item.source_provider, "source_method": item.source_method, "candidate_id": item.candidate_id, "query": item.query, "hook": item.title, "keyword": item.query, "keyword_intent": "commercial", "source_confidence": item.confidence, "evidence_category": "ConsumerAttentionEvidence", "limitations": list(item.limitations), "can_feed_reports": True} for item in parsed.search_signals)
    search_context = {"evidence_mode": "fixture_demo", "provider": "dataforseo", "queries": list(clean_keywords), "search_signal_count": len(parsed.search_signals), "shopping_signal_count": len(parsed.shopping_signals), "competitor_signal_count": len(parsed.competitor_signals), "supplier_proof": False, "network_calls": False, "limitations": ["fixture/manual evidence is not live search proof"]}
    summary = {"provider": "dataforseo", "evidence_mode": "fixture_demo", "queries": list(clean_keywords), "ranked_results": len(parsed.search_signals) + len(parsed.shopping_signals), "competitor_results": len(parsed.competitor_signals), "pricing_observed": sum(1 for item in (*parsed.search_signals, *parsed.shopping_signals) if item.price is not None), "confidence": "fixture", "next_action": "validate_provider_access_and_terms_before_live_read_only_run"}
    blocked_live = tuple(dict.fromkeys(("DataForSEO live transport is not implemented.", "credential reference is metadata-only", "Approval Ledger provider_call approval is missing", "terms review is incomplete", "privacy review is incomplete", "network and SDK use are disabled", "raw provider payload storage is forbidden", "live_mode_requested" if live_read_only else "")))
    return DataForSEOAdapterReport("dataforseo-readonly-adapter-v1", generated_at, plan, tuple(DataForSEOKeywordTask(keyword, plan.location_code_placeholder, plan.language_code, plan.device) for keyword in clean_keywords), tuple(DataForSEOSerpTask(keyword, request_kind if request_kind in {"serp_google_organic_snapshot", "competitor_serp_snapshot"} else "serp_google_organic_snapshot", plan.location_code_placeholder, plan.language_code, plan.device) for keyword in clean_keywords), tuple(DataForSEOShoppingTask(keyword, plan.location_code_placeholder, plan.language_code, plan.device) for keyword in clean_keywords) if request_kind == "serp_google_shopping_snapshot" else (), (parsed.fixture,), parsed, readiness, credential, cost, rate, terms, output, DataForSEOAdapterSafetySummary(True, False, False, False, False, False, False, False, True), marketplace, attention, search_context, summary, tuple(item for item in blocked_live if item), "Keep DataForSEO in dry-run mode; assign an owner, configure a secret-manager reference, complete terms/privacy review, and obtain Approval Ledger approval before any future live read-only transport.")


def to_marketplace_trend_signals(report: DataForSEOAdapterReport) -> tuple[dict[str, Any], ...]:
    return report.to_marketplace_trend_signals()


def to_consumer_attention_signals(report: DataForSEOAdapterReport) -> tuple[dict[str, Any], ...]:
    return report.to_consumer_attention_signals()


def to_opportunity_search_context(report: DataForSEOAdapterReport) -> dict[str, Any]:
    return report.to_opportunity_search_context()


def to_product_validation_search_summary(report: DataForSEOAdapterReport) -> dict[str, Any]:
    return report.to_product_validation_search_summary()


__all__ = [
    "REQUEST_KINDS", "REQUEST_STATUSES", "READINESS_STATES", "EVIDENCE_CATEGORIES", "STOP_CONDITIONS",
    "DataForSEOAdapterReport", "DataForSEORequestPlan", "DataForSEOKeywordTask", "DataForSEOSerpTask", "DataForSEOShoppingTask", "DataForSEOResponseFixture", "DataForSEOParseResult", "DataForSEONormalizedSearchSignal", "DataForSEONormalizedShoppingSignal", "DataForSEOCompetitorSignal", "DataForSEOApprovalReadiness", "DataForSEOCredentialReadiness", "DataForSEOCostEstimate", "DataForSEORateLimitPlan", "DataForSEOTermsPrivacyStatus", "DataForSEOOutputContract", "DataForSEOAdapterSafetySummary", "parse_dataforseo_fixture", "build_dataforseo_adapter_report", "to_marketplace_trend_signals", "to_consumer_attention_signals", "to_opportunity_search_context", "to_product_validation_search_summary",
]

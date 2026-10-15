"""Read-only Google Ads Keyword Planner historical-demand adapter.

Official sources reviewed 2026-10-14 (Google Ads API primary docs only):

- Keyword planning overview (historical metrics refresh monthly; stricter rate limits):
  https://developers.google.com/google-ads/api/docs/keyword-planning/overview
- GenerateKeywordIdeas (KeywordSeed 1–20, up to 10 geo target constants,
  pagination up to 10,000 results per page):
  https://developers.google.com/google-ads/api/docs/keyword-planning/generate-keyword-ideas
- GenerateKeywordHistoricalMetrics (up to 10,000 keywords, up to 10 geos):
  https://developers.google.com/google-ads/api/docs/keyword-planning/generate-historical-metrics
- Quotas (1 request/second/CID for ideas, historical metrics, and forecast metrics):
  https://developers.google.com/google-ads/api/docs/best-practices/quotas
- Sunset timetable (v26 released 2026-10-14, sunset November 2027):
  https://developers.google.com/google-ads/api/docs/sunset-dates
- Developer token sunset (2026-09-09); access level follows the Google Cloud project:
  https://developers.google.com/google-ads/api/docs/api-policy/developer-token
- OAuth scope on the v26 GenerateKeywordIdeas RPC:
  https://www.googleapis.com/auth/adwords

This module plans and parses historical Google Search metrics only. It does not
call Google, read credentials, store customer ids, or turn monthly searches into
sales, observed demand, marketplace truth, Trends relative interest, purchase
intent, or forecast conversions. Operational collection never invents fixture
keywords when live data is blocked.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from evaluation.companyos.approval_ledger import REQUEST_TYPES
from evaluation.secret_markers import contains_boundary_prefixed_sk_token

PROVIDER_ID = "google_ads_keyword_planner"
EVIDENCE_CATEGORY = "GoogleAdsHistoricalKeywordDemand"
DOCUMENTED_API_VERSION = "v26"
OAUTH_SCOPE = "https://www.googleapis.com/auth/adwords"
PRIMARY_DOCS = (
    "https://developers.google.com/google-ads/api/docs/keyword-planning/overview",
    "https://developers.google.com/google-ads/api/docs/keyword-planning/generate-keyword-ideas",
    "https://developers.google.com/google-ads/api/docs/keyword-planning/generate-historical-metrics",
    "https://developers.google.com/google-ads/api/docs/best-practices/quotas",
    "https://developers.google.com/google-ads/api/docs/sunset-dates",
    "https://developers.google.com/google-ads/api/docs/api-policy/developer-token",
    "https://developers.google.com/google-ads/api/reference/rpc/v26/KeywordPlanIdeaService/GenerateKeywordIdeas",
)

# Published request caps. Adapter caps are stricter and are not Google limits.
API_MAX_SEED_KEYWORDS = 20
API_MAX_HISTORICAL_KEYWORDS = 10000
API_MAX_GEO_TARGETS = 10
API_MAX_PAGE_RESULTS = 10000
API_IDEAS_QPS_PER_CID = 1
ADAPTER_MAX_KEYWORDS = 50
ADAPTER_MAX_PAGE_SIZE = 100
ADAPTER_MAX_PAGES = 2

METHODS = ("generate_keyword_ideas", "generate_keyword_historical_metrics")
NETWORKS = ("GOOGLE_SEARCH", "GOOGLE_SEARCH_AND_PARTNERS")
ACCESS_LEVELS = ("test", "explorer", "basic", "standard")
APPROVAL_REQUEST_TYPE = "provider_call"
UNAVAILABLE_FIELDS = (
    "published_unit_price",
    "account_currency",
    "forecast_clicks",
    "forecast_cost_micros",
    "forecast_conversions",
    "purchase_intent",
    "sales",
    "trends_relative_interest",
    "search_growth_signal",
)

_SECRET_KEYS = frozenset({
    "actual_secret_value", "api_key", "raw_api_key", "raw_oauth_token", "oauth_token",
    "access_token", "refresh_token", "password", "private_key", "private_key_material",
    "authorization", "cookie", "cookies", "developer_token", "client_secret",
    "customer_id", "login_customer_id", "refresh_token",
})
_RAW_KEYS = frozenset({
    "raw_payload", "raw_html", "html", "body", "response_body", "javascript", "browser_trace",
})
_FORBIDDEN_FALLBACK_KEYS = frozenset({
    "fixture_keywords", "manual_keywords", "fallback_keywords", "default_keywords",
    "results", "observations",
})
_FABRICATED_LABEL_KEYS = frozenset({
    "currency", "currency_code", "sales", "revenue", "orders", "purchase_intent",
    "observed_demand", "relative_interest", "trends_relative_interest",
    "search_growth_signal", "marketplace_truth", "product_attention", "demand",
})
_MONTH_NUMBERS = {
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "MAY": 5, "JUNE": 6,
    "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
}


class GoogleAdsKeywordDemandError(ValueError):
    """Raised for secret material or a request that must not be echoed."""


class KeywordDemandTransport(Protocol):
    def execute(self, plan: "KeywordDemandRequestPlan") -> "KeywordDemandTransportResult":
        """Return parsed observations. Must not be a live socket in this module."""


def _clean(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _clean(getattr(value, key)) for key in value.__dataclass_fields__}
    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_clean(item) for item in value]
    return value


def _secret_like(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).lower().replace("-", "_") in _SECRET_KEYS | _RAW_KEYS
            or _secret_like(item)
            for key, item in value.items()
        )
    if isinstance(value, (tuple, list)):
        return any(_secret_like(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return (
            "-----begin " in lowered
            or "bearer " in lowered
            or contains_boundary_prefixed_sk_token(value)
            or any(marker in lowered for marker in ("ghp_", "ya29.", "sk_live_", "sk_test_"))
        )
    return False


def _resource(value: str, kind: str) -> str:
    text = str(value or "").strip()
    prefix = "geoTargetConstants/" if kind == "geo" else "languageConstants/"
    if not text.startswith(prefix):
        raise GoogleAdsKeywordDemandError(f"{kind} resource name is not in the published form")
    suffix = text[len(prefix):]
    if not suffix.isdigit() or not 1 <= len(suffix) <= 12:
        raise GoogleAdsKeywordDemandError(f"{kind} resource name is not in the published form")
    return text


def _keywords(value: Any, *, limit: int) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise GoogleAdsKeywordDemandError("keywords must be a list")
    cleaned: list[str] = []
    for item in value:
        text = " ".join(str(item or "").split())
        if not text or any(ord(char) < 32 for char in text):
            raise GoogleAdsKeywordDemandError("keyword text is empty or unsafe")
        if len(text) > 80:
            raise GoogleAdsKeywordDemandError("keyword text exceeds 80 characters")
        if text not in cleaned:
            cleaned.append(text)
    if len(cleaned) > limit:
        raise GoogleAdsKeywordDemandError(f"keyword list exceeds adapter cap of {limit}")
    return tuple(cleaned)


def _optional_int(value: Any, *, name: str, minimum: int | None = None, maximum: int | None = None) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise GoogleAdsKeywordDemandError(f"{name} must be an integer or null")
    if minimum is not None and value < minimum:
        raise GoogleAdsKeywordDemandError(f"{name} is below the published range")
    if maximum is not None and value > maximum:
        raise GoogleAdsKeywordDemandError(f"{name} is above the published range")
    return value


@dataclass(frozen=True)
class KeywordDemandAuthorization:
    """Metadata-only gates. This object never carries a token or customer id."""

    approval_status: str = "missing"
    credential_reference_present: bool = False
    cloud_project_access_level: str | None = None
    terms_review_complete: bool = False
    privacy_review_complete: bool = False
    quota_limit_acknowledged: bool = False
    cost_unknown_acknowledged: bool = False
    keyword_research_use_permitted: bool = False
    target_account_environment: str | None = None

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.approval_status != "approved":
            blockers.append("approval_missing")
        if APPROVAL_REQUEST_TYPE not in REQUEST_TYPES:
            blockers.append("approval_type_not_in_ledger")
        if not self.credential_reference_present:
            blockers.append("credential_reference_missing")
        level = str(self.cloud_project_access_level or "").strip().lower()
        if level not in ACCESS_LEVELS:
            blockers.append("cloud_project_access_level_missing")
        if not self.terms_review_complete or not self.privacy_review_complete:
            blockers.append("terms_or_privacy_review_missing")
        if not self.quota_limit_acknowledged:
            blockers.append("quota_limit_not_acknowledged")
        if not self.cost_unknown_acknowledged:
            blockers.append("published_cost_unknown_not_acknowledged")
        if not self.keyword_research_use_permitted:
            blockers.append("keyword_research_permitted_use_missing")
        environment = str(self.target_account_environment or "").strip().lower()
        if environment not in {"test", "production"}:
            blockers.append("account_environment_unspecified")
        elif environment == "production" and level == "test":
            blockers.append("test_access_is_not_production_access")
        return tuple(blockers)


@dataclass(frozen=True)
class MonthlySearchVolume:
    year: int
    month: str
    monthly_searches: int | None

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class KeywordHistoricalDemand:
    """One historical keyword metric row. Counts stay null when Google omits them."""

    keyword: str
    close_variants: tuple[str, ...]
    avg_monthly_searches: int | None
    monthly_search_volumes: tuple[MonthlySearchVolume, ...]
    competition: str | None
    competition_index: int | None
    low_top_of_page_bid_micros: int | None
    high_top_of_page_bid_micros: int | None
    average_cpc_micros: int | None
    search_count_unit: str
    bid_unit: str
    currency: None
    currency_known: bool
    metric_kind: str
    metric_scope: str
    evidence_claim: str
    keyword_role: str
    freshness: str
    observation_window: str
    year_month_range: tuple[str, str] | None
    available_for_canonical_scoring: bool
    search_growth_signal: None
    purchase_intent: None
    forecast_clicks: None
    forecast_cost: None
    forecast_conversions: None

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class KeywordDemandRequestPlan:
    provider_id: str
    api_version: str
    method: str
    endpoint_template: str
    keywords: tuple[str, ...]
    url_seed: str | None
    geo_target_constants: tuple[str, ...]
    all_locations: bool
    language_constant: str | None
    language_unspecified: bool
    keyword_plan_network: str
    page_size: int
    max_pages: int
    include_average_cpc: bool
    include_adult_keywords: bool
    year_month_range: tuple[str, str] | None
    as_of: str | None
    customer_reference_id: str
    oauth_scope: str
    developer_token_required: bool
    qps_per_cid: int
    live_request_created: bool
    network_calls: bool
    status: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class KeywordDemandTransportResult:
    status: str
    observations: tuple[KeywordHistoricalDemand, ...]
    warnings: tuple[str, ...]
    pages_read: int
    truncated: bool
    network_calls: bool
    credentials_loaded: bool

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class GoogleAdsKeywordDemandReport:
    report_version: str
    generated_at: str
    provider_id: str
    evidence_category: str
    result_status: str
    request_plan: KeywordDemandRequestPlan | None
    observations: tuple[KeywordHistoricalDemand, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    attention_projection: Mapping[str, Any]
    read_only: bool
    network_calls: bool
    credentials_loaded: bool
    mutated: bool
    live_transport_implemented: bool
    unavailable_fields: tuple[str, ...]
    live_evidence: bool = False
    fixture_fallback: bool = False
    evidence_lineage: str = "not_live"

    def to_dict(self) -> dict[str, Any]:
        payload = _clean(self)
        payload["attention_projection"] = dict(self.attention_projection)
        return payload


def _year_month(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if len(text) != 7 or text[4] != "-" or not (text[:4].isdigit() and text[5:7].isdigit()):
        raise GoogleAdsKeywordDemandError("year_month must be YYYY-MM")
    month = int(text[5:7])
    if not 1 <= month <= 12:
        raise GoogleAdsKeywordDemandError("year_month must be YYYY-MM")
    return text


def _validate_url(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if len(text) > 300 or any(ord(char) < 32 for char in text):
        raise GoogleAdsKeywordDemandError("url seed is unsafe")
    lowered = text.lower()
    if not lowered.startswith(("https://", "http://")):
        raise GoogleAdsKeywordDemandError("url seed must be http(s)")
    if "@" in text.split("/", 3)[2] if "://" in text else False:
        raise GoogleAdsKeywordDemandError("url seed must not carry userinfo")
    if any(marker in lowered for marker in ("javascript:", "data:", "access_token=", "api_key=")):
        raise GoogleAdsKeywordDemandError("url seed must not carry secrets")
    return text


def _ym_index(value: str) -> int:
    return int(value[:4]) * 12 + int(value[5:7])


def _normalized_keys(mapping: Mapping[str, Any]) -> set[str]:
    return {str(key).lower().replace("-", "_") for key in mapping}


def build_request_plan(request: Mapping[str, Any]) -> KeywordDemandRequestPlan:
    if not isinstance(request, Mapping) or _secret_like(request):
        raise GoogleAdsKeywordDemandError("secret-like or raw keyword request is not accepted")
    if any(key in request for key in _FORBIDDEN_FALLBACK_KEYS):
        raise GoogleAdsKeywordDemandError("fixture or manual keyword fallback is not accepted")
    if _normalized_keys(request) & _FABRICATED_LABEL_KEYS:
        raise GoogleAdsKeywordDemandError("fabricated metric label is not accepted")
    method = str(request.get("method") or "").strip()
    if method == "generate_keyword_forecast_metrics":
        raise GoogleAdsKeywordDemandError("forecast metrics are not historical demand")
    if method not in METHODS:
        raise GoogleAdsKeywordDemandError(
            "method must be generate_keyword_ideas or generate_keyword_historical_metrics"
        )
    if "site_seed" in request:
        raise GoogleAdsKeywordDemandError("site seed can return an unbounded idea set and is not accepted")
    if method == "generate_keyword_ideas":
        limit = API_MAX_SEED_KEYWORDS
    else:
        limit = ADAPTER_MAX_KEYWORDS
    keywords = _keywords(request.get("keywords"), limit=limit)
    url_seed = _validate_url(request.get("url_seed"))
    if method == "generate_keyword_ideas" and not keywords and not url_seed:
        raise GoogleAdsKeywordDemandError("keyword ideas require a keyword seed, a url seed, or both")
    if method == "generate_keyword_ideas" and keywords and len(keywords) > API_MAX_SEED_KEYWORDS:
        raise GoogleAdsKeywordDemandError("keyword seed exceeds 20")
    if method == "generate_keyword_historical_metrics" and (not keywords or url_seed):
        raise GoogleAdsKeywordDemandError("historical metrics require keywords and no url seed")
    all_locations = request.get("all_locations") is True
    raw_geos = request.get("geo_target_constants") or ()
    if isinstance(raw_geos, str) or not isinstance(raw_geos, Sequence):
        raise GoogleAdsKeywordDemandError("geo_target_constants must be a list")
    geos = tuple(_resource(item, "geo") for item in raw_geos)
    if len(geos) > API_MAX_GEO_TARGETS:
        raise GoogleAdsKeywordDemandError("geo target list exceeds 10")
    if not geos and not all_locations:
        raise GoogleAdsKeywordDemandError("geography is required unless all_locations is explicit")
    if geos and all_locations:
        raise GoogleAdsKeywordDemandError("all_locations cannot be combined with geo targets")
    language_unspecified = request.get("language_unspecified") is True
    language = request.get("language_constant")
    language_constant = None if language in (None, "") else _resource(str(language), "language")
    if language_constant and language_unspecified:
        raise GoogleAdsKeywordDemandError("language cannot be both set and unspecified")
    if not language_constant and not language_unspecified:
        raise GoogleAdsKeywordDemandError("language is required unless language_unspecified is explicit")
    network = str(request.get("keyword_plan_network") or "").strip()
    if network not in NETWORKS:
        raise GoogleAdsKeywordDemandError("keyword_plan_network must be explicit")
    page_size = request.get("page_size", ADAPTER_MAX_PAGE_SIZE)
    page_size_int = _optional_int(page_size, name="page_size", minimum=1, maximum=ADAPTER_MAX_PAGE_SIZE)
    max_pages = _optional_int(request.get("max_pages", 1), name="max_pages", minimum=1, maximum=ADAPTER_MAX_PAGES)
    start = _year_month(request.get("year_month_start"))
    end = _year_month(request.get("year_month_end"))
    if (start is None) ^ (end is None):
        raise GoogleAdsKeywordDemandError("year_month range needs both start and end")
    if start and end and end < start:
        raise GoogleAdsKeywordDemandError("year_month range ends before it starts")
    as_of = _year_month(request.get("as_of"))
    if start and end and as_of is not None:
        if _ym_index(end) > _ym_index(as_of):
            raise GoogleAdsKeywordDemandError("year_month range is after as_of")
        if _ym_index(as_of) - _ym_index(start) > 48:
            raise GoogleAdsKeywordDemandError("year_month range is outside the published monthly retention")
    customer_reference = str(request.get("customer_reference_id") or "credential-google-ads-customer").strip()
    if customer_reference.isdigit() or _secret_like(customer_reference):
        raise GoogleAdsKeywordDemandError("customer reference must be a metadata id, not an account id")
    return KeywordDemandRequestPlan(
        provider_id=PROVIDER_ID,
        api_version=DOCUMENTED_API_VERSION,
        method=method,
        endpoint_template=(
            "https://googleads.googleapis.com/v26/customers/{customer_reference}:generateKeywordIdeas"
            if method == "generate_keyword_ideas"
            else "https://googleads.googleapis.com/v26/customers/{customer_reference}:generateKeywordHistoricalMetrics"
        ),
        keywords=keywords,
        url_seed=url_seed,
        geo_target_constants=geos,
        all_locations=all_locations,
        language_constant=language_constant,
        language_unspecified=language_unspecified,
        keyword_plan_network=network,
        page_size=page_size_int or 1,
        max_pages=max_pages or 1,
        include_average_cpc=request.get("include_average_cpc") is True,
        include_adult_keywords=request.get("include_adult_keywords") is True,
        year_month_range=(start, end) if start and end else None,
        as_of=as_of,
        customer_reference_id=customer_reference[:80],
        oauth_scope=OAUTH_SCOPE,
        developer_token_required=False,
        qps_per_cid=API_IDEAS_QPS_PER_CID,
        live_request_created=False,
        network_calls=False,
        status="planned",
    )


def _month_point(row: Mapping[str, Any]) -> MonthlySearchVolume:
    year = _optional_int(row.get("year"), name="year", minimum=2000, maximum=2100)
    month = str(row.get("month") or "").strip().upper()
    if year is None or month not in _MONTH_NUMBERS:
        raise GoogleAdsKeywordDemandError("monthly search volume needs a year and month")
    searches = _optional_int(row.get("monthly_searches"), name="monthly_searches", minimum=0)
    return MonthlySearchVolume(year, month, searches)


def _competition(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip().upper()
    if not text.isascii() or not text.replace("_", "").isalpha() or len(text) > 40:
        raise GoogleAdsKeywordDemandError("competition must be an enum token or null")
    return text


def _keyword_role(
    keyword: str,
    variants: tuple[str, ...],
    requested: Sequence[str],
    method: str,
) -> str:
    wanted = {" ".join(item.split()).casefold() for item in requested if str(item).strip()}
    if not wanted:
        return "unscoped_row"
    canonical = " ".join(keyword.split()).casefold()
    variant_names = {" ".join(item.split()).casefold() for item in variants}
    if canonical in wanted:
        return "requested_keyword"
    if variant_names & wanted:
        return "close_variant_of_requested_keyword"
    if method == "generate_keyword_ideas":
        return "idea_suggestion"
    raise GoogleAdsKeywordDemandError("keyword is not in the request")


def _freshness(as_of: str | None, year_month_range: tuple[str, str] | None) -> str:
    if as_of is None:
        return "unverified_no_reference_clock"
    if year_month_range:
        return "requested_window_not_a_provider_timestamp"
    return "trailing_12_months_unverified_against_provider"


def _reject_fabricated_labels(mapping: Mapping[str, Any]) -> None:
    if _normalized_keys(mapping) & _FABRICATED_LABEL_KEYS:
        raise GoogleAdsKeywordDemandError("fabricated metric label is not accepted")


def parse_historical_result(
    row: Mapping[str, Any],
    *,
    year_month_range: tuple[str, str] | None,
    requested_keywords: Sequence[str] = (),
    method: str = "generate_keyword_historical_metrics",
    as_of: str | None = None,
) -> KeywordHistoricalDemand:
    if _secret_like(row):
        raise GoogleAdsKeywordDemandError("secret-like keyword result is not accepted")
    _reject_fabricated_labels(row)
    keyword = " ".join(str(row.get("text") or row.get("keyword") or "").split())
    if not keyword:
        raise GoogleAdsKeywordDemandError("keyword result text is required")
    metrics = row.get("keyword_idea_metrics", row.get("keyword_metrics"))
    if metrics is None:
        metrics = {}
    if not isinstance(metrics, Mapping):
        raise GoogleAdsKeywordDemandError("keyword metrics must be an object or null")
    _reject_fabricated_labels(metrics)
    volumes_raw = metrics.get("monthly_search_volumes") or ()
    if isinstance(volumes_raw, str) or not isinstance(volumes_raw, Sequence):
        raise GoogleAdsKeywordDemandError("monthly_search_volumes must be a list")
    volumes = tuple(_month_point(item) for item in volumes_raw if isinstance(item, Mapping))
    if len(volumes) != len(tuple(volumes_raw)):
        raise GoogleAdsKeywordDemandError("monthly search volume row was not an object")
    if as_of is not None:
        as_of_index = _ym_index(as_of)
        for point in volumes:
            point_index = point.year * 12 + _MONTH_NUMBERS[point.month]
            if point_index > as_of_index or as_of_index - point_index > 48:
                raise GoogleAdsKeywordDemandError("monthly search point is outside the published retention window")
    if year_month_range:
        window = f"{year_month_range[0]}/{year_month_range[1]}"
    elif volumes:
        window = "monthly_points_as_returned"
    elif "avg_monthly_searches" in metrics and metrics.get("avg_monthly_searches") is not None:
        window = "trailing_12_months_or_unspecified_range"
    else:
        window = "unavailable"
    variants_raw = row.get("close_variants") or ()
    if isinstance(variants_raw, str) or not isinstance(variants_raw, Sequence):
        variants: tuple[str, ...] = ()
    else:
        variants = tuple(
            " ".join(str(item).split())[:80]
            for item in variants_raw
            if str(item).strip()
        )[:5]
    avg_monthly_searches = _optional_int(
        metrics.get("avg_monthly_searches"), name="avg_monthly_searches", minimum=0,
    )
    low_bid = _optional_int(
        metrics.get("low_top_of_page_bid_micros"), name="low_top_of_page_bid_micros", minimum=0,
    )
    high_bid = _optional_int(
        metrics.get("high_top_of_page_bid_micros"), name="high_top_of_page_bid_micros", minimum=0,
    )
    average_cpc = _optional_int(metrics.get("average_cpc_micros"), name="average_cpc_micros", minimum=0)
    has_count = avg_monthly_searches is not None or any(point.monthly_searches is not None for point in volumes)
    has_bid = any(value is not None for value in (low_bid, high_bid, average_cpc))
    return KeywordHistoricalDemand(
        keyword=keyword[:80],
        close_variants=variants,
        avg_monthly_searches=avg_monthly_searches,
        monthly_search_volumes=volumes,
        competition=_competition(metrics.get("competition")),
        competition_index=_optional_int(
            metrics.get("competition_index"), name="competition_index", minimum=0, maximum=100,
        ),
        low_top_of_page_bid_micros=low_bid,
        high_top_of_page_bid_micros=high_bid,
        average_cpc_micros=average_cpc,
        search_count_unit="approximate_monthly_searches" if has_count else "unavailable",
        bid_unit="micros" if has_bid else "unavailable",
        currency=None,
        currency_known=False,
        metric_kind="approximate_historical_search_metric",
        metric_scope="keyword_planner_historical_search",
        evidence_claim="approximate_google_search_history_not_sales_or_marketplace_truth",
        keyword_role=_keyword_role(keyword, variants, requested_keywords, method),
        freshness=_freshness(as_of, year_month_range),
        observation_window=window,
        year_month_range=year_month_range,
        available_for_canonical_scoring=False,
        search_growth_signal=None,
        purchase_intent=None,
        forecast_clicks=None,
        forecast_cost=None,
        forecast_conversions=None,
    )


def _declared_target_mismatch(
    payload: Mapping[str, Any],
    *,
    geo_target_constants: Sequence[str],
    all_locations: bool,
    language_constant: str | None,
    language_unspecified: bool,
) -> bool:
    if "geo_target_constants" in payload:
        declared = payload.get("geo_target_constants")
        if isinstance(declared, str) or not isinstance(declared, Sequence):
            return True
        declared_geos = tuple(str(item) for item in declared)
        if all_locations or declared_geos != tuple(geo_target_constants):
            return True
    declared_language = payload.get("language", payload.get("language_constant"))
    if declared_language not in (None, ""):
        if language_unspecified or str(declared_language) != (language_constant or ""):
            return True
    return False


def parse_keyword_demand_page(
    payload: Mapping[str, Any],
    *,
    year_month_range: tuple[str, str] | None,
    requested_keywords: Sequence[str] = (),
    method: str = "generate_keyword_historical_metrics",
    as_of: str | None = None,
    geo_target_constants: Sequence[str] = (),
    all_locations: bool = False,
    language_constant: str | None = None,
    language_unspecified: bool = False,
) -> tuple[tuple[KeywordHistoricalDemand, ...], str | None, tuple[str, ...]]:
    if not isinstance(payload, Mapping) or _secret_like(payload):
        raise GoogleAdsKeywordDemandError("secret-like or raw keyword page is not accepted")
    if _declared_target_mismatch(
        payload,
        geo_target_constants=geo_target_constants,
        all_locations=all_locations,
        language_constant=language_constant,
        language_unspecified=language_unspecified,
    ):
        return (), None, ("targeting_mismatch",)
    rows = payload.get("results")
    if rows is None:
        rows = ()
    if isinstance(rows, str) or not isinstance(rows, Sequence):
        raise GoogleAdsKeywordDemandError("results must be a list")
    observations: list[KeywordHistoricalDemand] = []
    warnings: list[str] = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, Mapping):
            warnings.append(f"result_{index}_ignored_non_mapping")
            continue
        try:
            observations.append(parse_historical_result(
                row,
                year_month_range=year_month_range,
                requested_keywords=requested_keywords,
                method=method,
                as_of=as_of,
            ))
        except GoogleAdsKeywordDemandError as exc:
            warnings.append(f"result_{index}_{exc}")
    token = payload.get("next_page_token")
    next_token = str(token).strip() if isinstance(token, str) and token.strip() else None
    if next_token and _secret_like(next_token):
        raise GoogleAdsKeywordDemandError("page token is not accepted")
    return tuple(observations), next_token, tuple(warnings)


def attention_projection(
    observations: Sequence[KeywordHistoricalDemand],
    identity_links: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Do not write monthly searches into search_growth_signal.

    The canonical attention score treats that field as a bounded 0–1 growth
    input. Absolute monthly counts are a different metric and stay here.
    """
    links = {}
    ignored: list[str] = []
    for raw_key, raw_value in (identity_links or {}).items():
        key = " ".join(str(raw_key).split())
        value = str(raw_value).strip()
        if key.lower() in {"candidate_id_hint", "hint"} or key.lower().endswith("_hint"):
            ignored.append("candidate_id_hint_ignored")
            continue
        if not key or not value or value.casefold() == key.casefold():
            ignored.append("identity_link_rejected")
            continue
        if key in links:
            ignored.append("duplicate_identity_link_ignored")
            continue
        links[key] = value
    rows = []
    for item in observations:
        rows.append({
            "keyword": item.keyword,
            "keyword_role": item.keyword_role,
            "candidate_id": links.get(item.keyword),
            "avg_monthly_searches": item.avg_monthly_searches,
            "search_count_unit": item.search_count_unit,
            "competition_index": item.competition_index,
            "observation_window": item.observation_window,
            "freshness": item.freshness,
            "currency": None,
            "currency_known": False,
            "evidence_claim": item.evidence_claim,
            "search_growth_signal": None,
            "available_for_canonical_scoring": False,
        })
    return {
        "status": "source_specific_only",
        "available_for_canonical_scoring": False,
        "reason": (
            "avg_monthly_searches is an approximate historical count in monthly searches, "
            "not a 0-1 search_growth_signal, Trends relative interest, sales, or purchase intent."
        ),
        "canonical_schema_mutated": False,
        "identity_links_applied": sorted(key for key in links if any(item.keyword == key for item in observations)),
        "warnings": sorted(set(ignored)),
        "rows": rows,
    }


def classify_provider_error(payload: Mapping[str, Any]) -> str:
    """Classify a sanitized Ads error object. Message text is never copied."""
    if not isinstance(payload, Mapping) or _secret_like(payload):
        raise GoogleAdsKeywordDemandError("secret-like provider error is not accepted")
    codes: list[str] = []
    error = payload.get("error")
    if isinstance(error, str):
        codes.append(error)
    elif isinstance(error, Mapping):
        for key in ("status", "code"):
            if error.get(key) not in (None, ""):
                codes.append(str(error.get(key)))
        details = error.get("details") or ()
        if isinstance(details, Sequence) and not isinstance(details, (str, bytes)):
            for item in details:
                if not isinstance(item, Mapping):
                    continue
                nested = item.get("errors") or ()
                if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
                    for err in nested:
                        if not isinstance(err, Mapping):
                            continue
                        code = err.get("error_code")
                        if isinstance(code, Mapping):
                            codes.extend(f"{name}:{value}" for name, value in code.items())
                        elif code not in (None, ""):
                            codes.append(str(code))
    elif payload.get("status") not in (None, ""):
        codes.append(str(payload.get("status")))
    blob = " ".join(codes).upper()
    if not blob.strip():
        return "not_an_error"
    if "RESOURCE_EXHAUSTED" in blob or "QUOTA_ERROR" in blob:
        return "rate_limited"
    if "DEADLINE_EXCEEDED" in blob or blob.strip() in {"TIMED_OUT", "TIMEOUT"}:
        return "timed_out"
    if any(mark in blob for mark in ("UNAUTHENTICATED", "PERMISSION_DENIED", "AUTHORIZATION_ERROR")):
        return "authorization_unavailable"
    return "provider_error"


class DisabledLiveTransport:
    """Operational transport. It never opens a socket and never invents keywords."""

    def execute(self, plan: KeywordDemandRequestPlan) -> KeywordDemandTransportResult:
        del plan
        return KeywordDemandTransportResult(
            status="blocked_live_transport_not_implemented",
            observations=(),
            warnings=("live_transport_not_implemented",),
            pages_read=0,
            truncated=False,
            network_calls=False,
            credentials_loaded=False,
        )


class FakeGoogleAdsKeywordTransport:
    """Test double. Pages are synthetic and are not used by the operational CLI."""

    def __init__(self, pages: Sequence[Mapping[str, Any]]) -> None:
        self._pages = tuple(pages)
        self.calls = 0

    def execute(self, plan: KeywordDemandRequestPlan) -> KeywordDemandTransportResult:
        self.calls += 1
        if self.calls > 1:
            raise GoogleAdsKeywordDemandError("fake transport is single-shot")
        observations: list[KeywordHistoricalDemand] = []
        warnings: list[str] = []
        token: str | None = None
        pages_read = 0
        truncated = False
        for page in self._pages:
            if pages_read >= plan.max_pages:
                truncated = True
                warnings.append("adapter_page_cap_reached")
                break
            if isinstance(page, Mapping) and "error" in page:
                classified = classify_provider_error(page)
                warnings.append(classified)
                if not observations:
                    return KeywordDemandTransportResult(
                        classified, (), tuple(dict.fromkeys(warnings)), pages_read, False, False, False,
                    )
                truncated = True
                warnings.append("stopped_after_provider_error")
                break
            parsed, token, page_warnings = parse_keyword_demand_page(
                page,
                year_month_range=plan.year_month_range,
                requested_keywords=plan.keywords,
                method=plan.method,
                as_of=plan.as_of,
                geo_target_constants=plan.geo_target_constants,
                all_locations=plan.all_locations,
                language_constant=plan.language_constant,
                language_unspecified=plan.language_unspecified,
            )
            observations.extend(parsed[: plan.page_size])
            if len(parsed) > plan.page_size:
                warnings.append("adapter_page_size_cap_applied")
                truncated = True
            warnings.extend(page_warnings)
            pages_read += 1
            if not token:
                break
        if token:
            truncated = True
            warnings.append("next_page_not_read")
        status = "incomplete" if truncated else "collected" if observations else "unavailable"
        return KeywordDemandTransportResult(
            status,
            tuple(observations),
            tuple(dict.fromkeys(warnings)),
            pages_read,
            truncated,
            False,
            False,
        )


def _empty_projection() -> dict[str, Any]:
    return attention_projection(())


def _blocked(
    status: str,
    blockers: tuple[str, ...],
    *,
    generated_at: str,
    plan: KeywordDemandRequestPlan | None = None,
    warnings: tuple[str, ...] = (),
) -> GoogleAdsKeywordDemandReport:
    return GoogleAdsKeywordDemandReport(
        report_version="google-ads-keyword-demand-v1",
        generated_at=generated_at,
        provider_id=PROVIDER_ID,
        evidence_category=EVIDENCE_CATEGORY,
        result_status=status,
        request_plan=plan,
        observations=(),
        blockers=blockers,
        warnings=warnings,
        attention_projection=_empty_projection(),
        read_only=True,
        network_calls=False,
        credentials_loaded=False,
        mutated=False,
        live_transport_implemented=False,
        unavailable_fields=UNAVAILABLE_FIELDS,
    )


def collect_google_ads_keyword_demand(
    request: Mapping[str, Any],
    authorization: KeywordDemandAuthorization | None = None,
    *,
    transport: KeywordDemandTransport | None = None,
    identity_links: Mapping[str, str] | None = None,
    generated_at: str = "offline-deterministic",
) -> GoogleAdsKeywordDemandReport:
    """Operational entry. Missing gates return blocked/unavailable and no keywords.

    A transport is called only after the gates pass. The default transport still
    does not perform a live call. Tests may inject FakeGoogleAdsKeywordTransport.
    """
    if _secret_like(request):
        raise GoogleAdsKeywordDemandError("secret-like or raw keyword request is not accepted")
    try:
        plan = build_request_plan(request)
    except GoogleAdsKeywordDemandError as exc:
        message = str(exc)
        status = "rejected" if "secret" in message or "fallback" in message else "unavailable"
        return _blocked(status, (message.replace(" ", "_"),), generated_at=generated_at)
    if identity_links is not None and _secret_like(identity_links):
        raise GoogleAdsKeywordDemandError("secret-like identity link is not accepted")
    gates = authorization or KeywordDemandAuthorization()
    blockers = gates.blockers()
    if blockers:
        return _blocked("blocked", blockers, generated_at=generated_at, plan=plan)
    active = transport or DisabledLiveTransport()
    result = active.execute(plan)
    if result.network_calls or result.credentials_loaded:
        raise GoogleAdsKeywordDemandError("transport must not load credentials or mark a network call from this module")
    observations = result.observations
    warnings = result.warnings
    if isinstance(active, FakeGoogleAdsKeywordTransport):
        status = {
            "collected": "synthetic_not_live",
            "incomplete": "synthetic_incomplete",
            "unavailable": "synthetic_unavailable",
        }.get(result.status, result.status)
        lineage = "synthetic_test_transport"
        warnings = tuple(dict.fromkeys((*warnings, "synthetic_test_transport_not_live_evidence")))
    elif result.observations or result.status in {"collected", "live", "live_collected"}:
        return _blocked(
            "rejected_non_live_promotion",
            ("non_live_transport_cannot_promote_observations",),
            generated_at=generated_at,
            plan=plan,
            warnings=("fixture_to_live_promotion_rejected",),
        )
    else:
        status = result.status
        lineage = (
            "live_transport_not_implemented"
            if status == "blocked_live_transport_not_implemented"
            else "not_live"
        )
        observations = ()
    projection = attention_projection(observations, identity_links)
    return GoogleAdsKeywordDemandReport(
        report_version="google-ads-keyword-demand-v1",
        generated_at=generated_at,
        provider_id=PROVIDER_ID,
        evidence_category=EVIDENCE_CATEGORY,
        result_status=status,
        request_plan=plan,
        observations=observations,
        blockers=() if status == "collected" else (status,),
        warnings=warnings,
        attention_projection=projection,
        read_only=True,
        network_calls=False,
        credentials_loaded=False,
        mutated=False,
        live_transport_implemented=False,
        unavailable_fields=UNAVAILABLE_FIELDS,
        evidence_lineage=lineage,
    )


__all__ = [
    "PROVIDER_ID",
    "DOCUMENTED_API_VERSION",
    "OAUTH_SCOPE",
    "DisabledLiveTransport",
    "FakeGoogleAdsKeywordTransport",
    "GoogleAdsKeywordDemandError",
    "GoogleAdsKeywordDemandReport",
    "KeywordDemandAuthorization",
    "KeywordHistoricalDemand",
    "attention_projection",
    "collect_google_ads_keyword_demand",
    "classify_provider_error",
    "parse_historical_result",
]

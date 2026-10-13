"""Official Google Trends organic search-interest adapter (fixture / dry-run).

Primary-source evaluation (Google Search Central, public pages only):
Google published an official Google Trends API **alpha**. Access requires an
alpha-tester application and is limited. Detailed API reference pages are
access-gated for accepted testers (public help notes a 404 without access).
Public landing/blog pages do **not** publish GA status, quotas, pricing,
OAuth scopes, endpoint URLs, or complete method/field schemas.

Confirmed on those public pages: consistently scaled **search interest**
(not absolute counts; not the Trends website's per-request 0–100 rescale),
rolling ~1800-day (~5y) window, data up to about 2 days ago, aggregations
daily/weekly/monthly/yearly, and ISO 3166-2 region/sub-region geos.

This module implements only the repository-permitted contract / fixture /
fake-transport layer for that relative-interest evidence category.
It never uses Pytrends, browser scraping, undocumented endpoints, proxies,
credentials, or live network calls.

Normalized values are relative / consistently scaled search interest only —
never search volume, sales, supplier proof, purchase intent, or launch
evidence. Missing observations stay unavailable / incomplete; they are
never coerced to zero.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from evaluation.companyos.approval_ledger import REQUEST_TYPES
from evaluation.secret_markers import contains_boundary_prefixed_sk_token

PROVIDER_ID = "google_trends_official"
EVIDENCE_CATEGORY = "OrganicSearchInterestEvidence"
PRIMARY_DOCS = (
    "https://developers.google.com/search/apis/trends",
    "https://developers.google.com/search/blog/2025/07/trends-api",
    "https://developers.google.com/search/apis/trends/help/cant-access-docs",
)

# Public docs: rolling ~1800-day (~5y) window; data up to ~2 days ago.
MAX_LOOKBACK_DAYS = 1800
DATA_LAG_DAYS = 2
STALE_AFTER_DAYS = 180

# Adapter request-shape vocabulary only — not confirmed Google RPC/method names.
# Public alpha pages describe time-series interest + geo breakdowns without
# publishing method identifiers.
REQUEST_KINDS = (
    "interest_over_time",
    "interest_by_region",
    "dry_run_fixture_parse",
)
TIME_RESOLUTIONS = ("DAY", "WEEK", "MONTH", "YEAR")
COLLECTION_STATUSES = (
    "collected",
    "unavailable",
    "disabled_by_policy",
    "incomplete",
    "stale",
    "rate_limited",
    "quota_exhausted",
    "unsupported_access",
    "malformed",
    "rejected",
    "blocked_live_mode",
    "fixture_only",
    "dry_run_ready",
)
OBSERVATION_STATUSES = (
    "collected",
    "unavailable",
    "disabled_by_policy",
    "incomplete",
    "stale",
)
READINESS_STATES = (
    "not_ready",
    "fixture_ready",
    "dry_run_ready",
    "blocked",
    "unsupported_access",
)
UNAVAILABLE_FIELDS = (
    "absolute_search_volume",
    "purchase_intent",
    "sales_or_demand_proof",
    "supplier_proof",
    "launch_evidence",
    "published_quota",
    "published_unit_pricing",
    "ga_sla",
    "public_oauth_scope_list",
    "public_endpoint_url",
    "public_method_schema",
    "public_auth_method_details",
    "language_filter_confirmed_on_public_docs",
    "website_0_100_rescale",
)

_SECRET_KEYS = frozenset({
    "actual_secret_value", "api_key", "raw_api_key", "raw_oauth_token", "oauth_token",
    "access_token", "refresh_token", "password", "private_key", "private_key_material",
    "authorization", "cookie", "cookies",
})
_RAW_KEYS = frozenset({
    "raw_payload", "raw_html", "html", "body", "response_body", "javascript", "browser_trace",
})


class GoogleTrendsInterestAdapterError(ValueError):
    """Raised for contract, schema, secret, or policy violations."""


def _clean(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _clean(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_clean(item) for item in value]
    return value


def _secret_like(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).lower().replace("-", "_") in _SECRET_KEYS | _RAW_KEYS
            or _secret_like(str(key))
            or _secret_like(item)
            for key, item in value.items()
        )
    if isinstance(value, (tuple, list, set)):
        return any(_secret_like(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return (
            "-----begin " in lowered
            or "bearer " in lowered
            or contains_boundary_prefixed_sk_token(value)
            or any(marker in lowered for marker in ("ghp_", "xoxb-", "aiza", "sk_live_", "sk_test_"))
        )
    return False


def _parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        raise GoogleTrendsInterestAdapterError("date value is required")
    if text.endswith("Z"):
        text = text[:-1]
    try:
        if "T" in text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise GoogleTrendsInterestAdapterError("date must be ISO-8601") from exc


def validate_geography(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        raise GoogleTrendsInterestAdapterError("geography is required")
    if text in {"WORLD", "WORLDWIDE", "GLOBAL"}:
        return "WORLD"
    # ISO 3166-1 alpha-2 or ISO 3166-2 (country-subdivision).
    if len(text) == 2 and text.isalpha():
        return text
    if len(text) >= 4 and text[2] == "-" and text.replace("-", "").isalnum():
        return text
    raise GoogleTrendsInterestAdapterError("geography must be ISO 3166-1/3166-2 or WORLD")


def validate_date_window(
    start: Any,
    end: Any,
    *,
    reference_date: Any | None = None,
    enforce_provider_lag: bool = True,
) -> dict[str, Any]:
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    reference = _parse_date(reference_date) if reference_date else date.today()
    if end_date < start_date:
        return {"valid": False, "reason": "end_before_start", "span_days": 0}
    span = (end_date - start_date).days
    if span > MAX_LOOKBACK_DAYS:
        return {
            "valid": False,
            "reason": f"lookback_exceeds_{MAX_LOOKBACK_DAYS}_days",
            "span_days": span,
        }
    latest_allowed = reference - timedelta(days=DATA_LAG_DAYS)
    if enforce_provider_lag and end_date > latest_allowed:
        return {
            "valid": False,
            "reason": f"end_within_provider_lag_{DATA_LAG_DAYS}_days",
            "span_days": span,
        }
    return {
        "valid": True,
        "reason": "ok",
        "span_days": span,
        "latest_allowed": latest_allowed.isoformat(),
    }


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise GoogleTrendsInterestAdapterError("boolean is not a relative interest value")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise GoogleTrendsInterestAdapterError("relative_interest must be numeric or null") from exc
    if number != number:  # NaN
        raise GoogleTrendsInterestAdapterError("relative_interest must be finite")
    return number


@dataclass(frozen=True)
class GoogleTrendsAccessAssessment:
    provider_id: str
    official_api_exists: bool
    commercially_generally_available: bool
    alpha_application_required: bool
    primary_documentation: tuple[str, ...]
    supported_geographies_note: str
    supported_time_window_note: str
    supported_aggregations: tuple[str, ...]
    quotas_published: bool
    costs_published: bool
    unavailable_fields: tuple[str, ...]
    pytrends_allowed: bool
    browser_scraping_allowed: bool
    undocumented_endpoints_allowed: bool
    suitability_summary: str
    alternative_considered: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class GoogleTrendsInterestObservation:
    source_provider: str
    source_method: str
    term: str
    geography: str
    language: str
    time_resolution: str
    observation_period_start: str
    observation_period_end: str
    relative_interest: float | None
    metric_kind: str
    absolute_search_volume: None
    purchase_intent: None
    status: str
    freshness_state: str
    provenance: str
    method: str
    collected_at: str | None
    limitations: tuple[str, ...]
    evidence_category: str
    can_feed_attention_reports: bool

    def __post_init__(self) -> None:
        if self.source_provider != PROVIDER_ID:
            raise GoogleTrendsInterestAdapterError("observation provider mismatch")
        if self.metric_kind != "relative_search_interest":
            raise GoogleTrendsInterestAdapterError("metric must be relative_search_interest")
        if self.absolute_search_volume is not None or self.purchase_intent is not None:
            raise GoogleTrendsInterestAdapterError("absolute volume and purchase intent are unavailable fields")
        if self.status not in OBSERVATION_STATUSES:
            raise GoogleTrendsInterestAdapterError(f"unsupported observation status: {self.status}")
        if self.relative_interest is None and self.status == "collected":
            raise GoogleTrendsInterestAdapterError("collected observations require relative_interest")
        if self.relative_interest is not None and self.status == "unavailable":
            raise GoogleTrendsInterestAdapterError("unavailable observations must not invent interest values")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class GoogleTrendsParseResult:
    fixture_id: str
    request_kind: str
    source_file: str
    parse_status: str
    observations: tuple[GoogleTrendsInterestObservation, ...]
    warnings: tuple[str, ...]
    sanitized: bool
    raw_payload_stored: bool

    def __post_init__(self) -> None:
        if self.raw_payload_stored or not self.sanitized:
            raise GoogleTrendsInterestAdapterError("parse result must be sanitized and raw-payload-free")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class FakeTransportResult:
    status: str
    observations: tuple[GoogleTrendsInterestObservation, ...]
    warnings: tuple[str, ...]
    network_attempted: bool
    credentials_loaded: bool

    def __post_init__(self) -> None:
        if self.network_attempted or self.credentials_loaded:
            raise GoogleTrendsInterestAdapterError("fake transport must remain offline")
        if self.status not in COLLECTION_STATUSES:
            raise GoogleTrendsInterestAdapterError(f"unsupported transport status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


class FakeTrendsTransport:
    """Deterministic fake transport — never opens sockets or loads secrets."""

    def execute(self, request: Mapping[str, Any]) -> FakeTransportResult:
        if _secret_like(request):
            raise GoogleTrendsInterestAdapterError("secret-like or raw transport request is not accepted")
        scenario = str(request.get("scenario", "fixture_parse")).strip().lower()
        if scenario == "rate_limited":
            return FakeTransportResult("rate_limited", (), ("provider_rate_limit_simulated",), False, False)
        if scenario == "quota_exhausted":
            return FakeTransportResult("quota_exhausted", (), ("provider_quota_exhausted_simulated",), False, False)
        if scenario == "unsupported_access":
            return FakeTransportResult(
                "unsupported_access",
                (),
                (
                    "alpha_access_not_granted",
                    "auth_method_and_project_allowlist_unknown_until_alpha_docs",
                ),
                False,
                False,
            )
        if scenario == "disabled_by_policy":
            return FakeTransportResult(
                "disabled_by_policy",
                (),
                ("approval_ledger_provider_call_missing", "live_transport_disabled_by_policy"),
                False,
                False,
            )
        if scenario == "malformed":
            return FakeTransportResult("malformed", (), ("unexpected_schema",), False, False)
        # Default: no network; caller parses fixtures separately.
        return FakeTransportResult("fixture_only", (), ("offline_fixture_path",), False, False)


@dataclass(frozen=True)
class GoogleTrendsRequestPlan:
    provider_id: str
    request_plan_id: str
    request_kind: str
    endpoint_placeholder: str
    terms: tuple[str, ...]
    geography: str
    language: str
    time_resolution: str
    window_start: str
    window_end: str
    max_terms: int
    max_requests: int
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
    cost_note: str
    quota_note: str

    def __post_init__(self) -> None:
        if self.provider_id != PROVIDER_ID:
            raise GoogleTrendsInterestAdapterError("request plan provider mismatch")
        if self.request_kind not in REQUEST_KINDS:
            raise GoogleTrendsInterestAdapterError(f"unsupported request kind: {self.request_kind}")
        if self.time_resolution not in TIME_RESOLUTIONS:
            raise GoogleTrendsInterestAdapterError("unsupported time resolution")
        if self.approval_request_type not in REQUEST_TYPES:
            raise GoogleTrendsInterestAdapterError("approval request type must reuse Approval Ledger vocabulary")
        if any((self.live_request_created, self.network_calls, self.sdk_used, self.raw_payload_stored, self.schedule_enabled)):
            raise GoogleTrendsInterestAdapterError("request plans are offline, unscheduled, and raw-payload-free")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class GoogleTrendsApprovalReadiness:
    alpha_access_granted: bool
    credential_reference_exists: bool
    secret_value_absent: bool
    approval_required: bool
    approval_request_type: str
    terms_review_complete: bool
    privacy_review_complete: bool
    fixture_output_contract_tested: bool
    live_mode_blocked: bool
    readiness_state: str
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.approval_request_type not in REQUEST_TYPES:
            raise GoogleTrendsInterestAdapterError("approval type must reuse Approval Ledger vocabulary")
        if self.readiness_state not in READINESS_STATES:
            raise GoogleTrendsInterestAdapterError("unsupported readiness state")
        if not self.secret_value_absent or not self.live_mode_blocked:
            raise GoogleTrendsInterestAdapterError("readiness must be secret-free and live-blocked")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class GoogleTrendsAdapterSafetySummary:
    read_only: bool
    live_request_created: bool
    network_calls: bool
    credentials_loaded: bool
    sdk_used: bool
    raw_payload_stored: bool
    scraping_performed: bool
    pytrends_used: bool
    undocumented_endpoint_used: bool
    fail_closed: bool

    def __post_init__(self) -> None:
        if not self.read_only or any(
            (
                self.live_request_created,
                self.network_calls,
                self.credentials_loaded,
                self.sdk_used,
                self.raw_payload_stored,
                self.scraping_performed,
                self.pytrends_used,
                self.undocumented_endpoint_used,
            )
        ):
            raise GoogleTrendsInterestAdapterError("adapter must remain offline and official-API-contract-only")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class GoogleTrendsInterestReport:
    report_version: str
    generated_at: str
    provider_id: str
    evidence_category: str
    access_assessment: GoogleTrendsAccessAssessment
    request_plan: GoogleTrendsRequestPlan
    parse_result: GoogleTrendsParseResult
    observations: tuple[GoogleTrendsInterestObservation, ...]
    approval_readiness: GoogleTrendsApprovalReadiness
    safety_summary: GoogleTrendsAdapterSafetySummary
    result_status: str
    evidence_boundary: dict[str, Any]
    unavailable_fields: tuple[str, ...]
    blocked_live_activation: tuple[str, ...]
    next_best_action: str
    transport_result: FakeTransportResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)

    def to_markdown(self) -> str:
        lines = [
            "# Google Trends Organic Search-Interest Adapter",
            "",
            "## Access assessment",
            "",
            f"- Official API exists: **{self.access_assessment.official_api_exists}**",
            f"- Commercially GA: **{self.access_assessment.commercially_generally_available}**",
            f"- Alpha application required: **{self.access_assessment.alpha_application_required}**",
            f"- Suitability: {self.access_assessment.suitability_summary}",
            "",
            "## Result",
            "",
            f"- Status: **{self.result_status}**",
            f"- Observations: **{len(self.observations)}**",
            f"- Readiness: **{self.approval_readiness.readiness_state}**",
            "- Mode: **offline fixture / fake-transport only**",
            "",
            "## Evidence boundary",
            "",
            "- Relative / consistently scaled search interest only — not absolute volume,",
            "  website 0–100 rescale, sales, supplier proof, or launch evidence.",
            "- Separate from marketplace price, supplier proof, and launch authority.",
            "",
            "## Next best action",
            "",
            self.next_best_action,
            "",
        ]
        return "\n".join(lines)


def _freshness(collected_at: str | None, *, reference_date: date) -> str:
    if not collected_at:
        return "unavailable"
    collected = _parse_date(collected_at)
    age = (reference_date - collected).days
    if age < 0:
        return "future_dated"
    if age > STALE_AFTER_DAYS:
        return "stale"
    return "fresh"


def normalize_interest_observation(
    row: Mapping[str, Any],
    *,
    default_geography: str = "US",
    default_language: str = "en",
    default_resolution: str = "WEEK",
    reference_date: str | date | None = None,
) -> GoogleTrendsInterestObservation:
    if not isinstance(row, Mapping) or _secret_like(row):
        raise GoogleTrendsInterestAdapterError("secret-like or raw observation is not accepted")
    if row.get("absolute_search_volume") is not None or row.get("purchase_intent") is not None:
        raise GoogleTrendsInterestAdapterError("absolute volume and purchase intent claims are rejected")
    term = str(row.get("term") or row.get("keyword") or "").strip()
    if not term:
        raise GoogleTrendsInterestAdapterError("term is required")
    geography = validate_geography(row.get("geography") or default_geography)
    language = str(row.get("language") or default_language).strip().lower() or "en"
    if len(language) < 2:
        raise GoogleTrendsInterestAdapterError("language must be a BCP-47 / ISO language tag")
    resolution = str(row.get("time_resolution") or default_resolution).strip().upper()
    if resolution not in TIME_RESOLUTIONS:
        raise GoogleTrendsInterestAdapterError("unsupported time resolution")
    start = str(row.get("observation_period_start") or "").strip()
    end = str(row.get("observation_period_end") or "").strip()
    if not start or not end:
        raise GoogleTrendsInterestAdapterError("observation period start/end are required")
    period = validate_date_window(
        start,
        end,
        reference_date=reference_date or end,
        enforce_provider_lag=False,
    )
    if not period["valid"]:
        raise GoogleTrendsInterestAdapterError(period["reason"])
    status = str(row.get("status") or "collected").strip().lower()
    if status not in OBSERVATION_STATUSES:
        raise GoogleTrendsInterestAdapterError(f"unsupported observation status: {status}")
    interest = _number(row.get("relative_interest"))
    if "relative_interest" not in row and status in {"unavailable", "incomplete"}:
        interest = None
    if interest is None and status == "collected":
        # Explicit null with collected is invalid; treat as incomplete if key missing.
        if "relative_interest" not in row:
            status = "incomplete"
        else:
            raise GoogleTrendsInterestAdapterError("collected observations require relative_interest")
    if interest is not None and status == "unavailable":
        raise GoogleTrendsInterestAdapterError("unavailable observations must not invent interest values")
    reference = _parse_date(reference_date) if reference_date else date.today()
    collected_at = str(row.get("collected_at") or "") or None
    freshness = _freshness(collected_at, reference_date=reference)
    if freshness == "stale" and status == "collected":
        status = "stale"
    provenance = str(row.get("provenance") or "fixture").strip().lower()
    if provenance not in {"fixture", "observed", "unavailable", "incomplete", "stale", "blocked", "manual_import"}:
        provenance = "fixture"
    return GoogleTrendsInterestObservation(
        source_provider=PROVIDER_ID,
        source_method="sanitized_fixture_parser",
        term=term[:160],
        geography=geography,
        language=language[:16],
        time_resolution=resolution,
        observation_period_start=start[:10],
        observation_period_end=end[:10],
        relative_interest=interest,
        metric_kind="relative_search_interest",
        absolute_search_volume=None,
        purchase_intent=None,
        status=status,
        freshness_state=freshness,
        provenance=provenance,
        method="official_trends_api_fixture",
        collected_at=collected_at,
        limitations=(
            "Relative / consistently scaled search interest only; not absolute search volume.",
            "Not the Trends website per-request 0–100 rescale; not sales or demand counts.",
            "Not purchase intent, marketplace price proof, supplier proof, or launch evidence.",
            "Synthetic fixture unless a future approved live transport is implemented.",
            "Language is adapter observation metadata; public Trends API pages do not confirm a language filter.",
        ),
        evidence_category=EVIDENCE_CATEGORY,
        can_feed_attention_reports=True,
    )


def parse_google_trends_interest_fixture(
    payload: Mapping[str, Any],
    *,
    request_kind: str = "interest_over_time",
    source_file: str = "fixture://google-trends-interest",
    reference_date: str | date | None = None,
) -> GoogleTrendsParseResult:
    if _secret_like(payload):
        raise GoogleTrendsInterestAdapterError("secret-like or raw Trends fixture is not accepted")
    if not isinstance(payload, Mapping) or payload.get("fixture_mode") is not True:
        raise GoogleTrendsInterestAdapterError("Trends fixtures must set fixture_mode=true (malformed schema)")
    if request_kind not in REQUEST_KINDS:
        raise GoogleTrendsInterestAdapterError(f"unsupported request kind: {request_kind}")
    series = payload.get("series", ())
    if not isinstance(series, Sequence) or isinstance(series, (str, bytes)):
        raise GoogleTrendsInterestAdapterError("malformed fixture: series must be a list")
    geography = validate_geography(payload.get("geography") or "US")
    language = str(payload.get("language") or "en").strip().lower() or "en"
    resolution = str(payload.get("time_resolution") or "WEEK").strip().upper()
    if resolution not in TIME_RESOLUTIONS:
        raise GoogleTrendsInterestAdapterError("unsupported time resolution")
    window_start = payload.get("window_start")
    window_end = payload.get("window_end")
    warnings: list[str] = []
    if window_start and window_end:
        window = validate_date_window(
            window_start,
            window_end,
            reference_date=reference_date or window_end,
            enforce_provider_lag=reference_date is not None,
        )
        if not window["valid"]:
            warnings.append(f"window_{window['reason']}")
    observations: list[GoogleTrendsInterestObservation] = []
    for index, entry in enumerate(series, 1):
        if not isinstance(entry, Mapping):
            warnings.append(f"series_{index}_ignored_non_mapping")
            continue
        term = str(entry.get("term") or entry.get("keyword") or "").strip()
        points = entry.get("points", ())
        if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
            raise GoogleTrendsInterestAdapterError("malformed fixture: points must be a list")
        for point_index, point in enumerate(points, 1):
            if not isinstance(point, Mapping):
                warnings.append(f"{term or 'series'}_point_{point_index}_ignored_non_mapping")
                continue
            merged = {
                "term": term,
                "geography": entry.get("geography") or geography,
                "language": entry.get("language") or language,
                "time_resolution": entry.get("time_resolution") or resolution,
                **point,
            }
            try:
                observations.append(
                    normalize_interest_observation(
                        merged,
                        default_geography=geography,
                        default_language=language,
                        default_resolution=resolution,
                        reference_date=reference_date,
                    )
                )
            except GoogleTrendsInterestAdapterError as exc:
                warnings.append(f"{term or 'series'}_point_{point_index}_{exc}")
    if not series:
        warnings.append("empty_fixture_results")
        parse_status = "empty"
    elif not observations:
        parse_status = "incomplete"
        warnings.append("no_normalized_observations")
    else:
        parse_status = "parsed"
        if any(item.status in {"unavailable", "incomplete"} for item in observations):
            warnings.append("partial_series_present")
    return GoogleTrendsParseResult(
        fixture_id=str(payload.get("fixture_id", "google-trends-interest-fixture")),
        request_kind=request_kind,
        source_file=source_file,
        parse_status=parse_status,
        observations=tuple(observations),
        warnings=tuple(warnings),
        sanitized=True,
        raw_payload_stored=False,
    )


def _default_payload(terms: Sequence[str], geography: str, language: str, resolution: str) -> dict[str, Any]:
    return {
        "fixture_id": "trends-interest-default-synthetic",
        "fixture_mode": True,
        "provider_id": PROVIDER_ID,
        "request_kind": "interest_over_time",
        "terms": list(terms),
        "geography": geography,
        "language": language,
        "time_resolution": resolution,
        "window_start": "2024-01-01",
        "window_end": "2024-03-31",
        "series": [
            {
                "term": term,
                "geography": geography,
                "language": language,
                "time_resolution": resolution,
                "points": [
                    {
                        "observation_period_start": "2024-01-01",
                        "observation_period_end": "2024-01-07",
                        "relative_interest": 30 + index,
                        "status": "collected",
                        "collected_at": "2024-04-02T00:00:00Z",
                    }
                ],
            }
            for index, term in enumerate(terms)
        ],
    }


def _access_assessment() -> GoogleTrendsAccessAssessment:
    return GoogleTrendsAccessAssessment(
        provider_id=PROVIDER_ID,
        official_api_exists=True,
        commercially_generally_available=False,
        alpha_application_required=True,
        primary_documentation=PRIMARY_DOCS,
        supported_geographies_note=(
            "Public announcement: region and sub-region breakdowns per ISO 3166-2. "
            "WORLD is an adapter convenience label only — not confirmed on public pages."
        ),
        supported_time_window_note=(
            f"Public announcement: rolling ~{MAX_LOOKBACK_DAYS}-day (~5 year) window; "
            f"data available up to about {DATA_LAG_DAYS} days ago; aggregations "
            "daily/weekly/monthly/yearly. Exact request field names remain unknown "
            "until alpha reference docs are accessible."
        ),
        supported_aggregations=TIME_RESOLUTIONS,
        quotas_published=False,
        costs_published=False,
        unavailable_fields=UNAVAILABLE_FIELDS,
        pytrends_allowed=False,
        browser_scraping_allowed=False,
        undocumented_endpoints_allowed=False,
        suitability_summary=(
            "Official Google Trends API exists as an alpha with application-gated access; "
            "detailed reference docs are gated for accepted testers. Not commercially "
            "generally available. Suitable only as an offline contract/fixture vertical "
            "for relative search-interest evidence until access, published "
            "quotas/pricing/method schema, Approval Ledger approval, and a separately "
            "reviewed transport exist."
        ),
        alternative_considered=(
            "No non-overlapping official GA alternative publishes relative organic "
            "search-interest time series. Google Ads keyword historical metrics are "
            "absolute volume estimates (different category; overlaps DataForSEO keyword "
            "demand) and were not selected. Pytrends/scraping/undocumented endpoints "
            "are forbidden here."
        ),
    )


def build_google_trends_interest_report(
    *,
    generated_at: str = "offline-deterministic",
    request_kind: str = "interest_over_time",
    terms: Sequence[str] = ("desk fan",),
    geography: str = "US",
    language: str = "en",
    time_resolution: str = "WEEK",
    window_start: str = "2024-01-01",
    window_end: str = "2024-03-31",
    payload: Mapping[str, Any] | None = None,
    source_file: str = "fixture://google-trends-interest-default",
    live_read_only: bool = False,
    transport_scenario: str | None = None,
    reference_date: str | date | None = None,
) -> GoogleTrendsInterestReport:
    if request_kind not in REQUEST_KINDS:
        raise GoogleTrendsInterestAdapterError(f"unsupported request kind: {request_kind}")
    geo = validate_geography(geography)
    resolution = str(time_resolution).strip().upper()
    if resolution not in TIME_RESOLUTIONS:
        raise GoogleTrendsInterestAdapterError("unsupported time resolution")
    clean_terms = tuple(dict.fromkeys(str(item).strip() for item in terms if str(item).strip()))[:10] or ("desk fan",)
    window = validate_date_window(
        window_start,
        window_end,
        reference_date=reference_date or window_end,
        enforce_provider_lag=reference_date is not None,
    )
    plan_status = "blocked_live_mode" if live_read_only else "dry_run_ready"
    plan = GoogleTrendsRequestPlan(
        provider_id=PROVIDER_ID,
        request_plan_id="google-trends-interest-request-plan-v1",
        request_kind=request_kind,
        endpoint_placeholder=(
            "unknown_until_alpha_reference_docs "
            "(public Trends API pages do not publish endpoint URLs or method schemas; "
            "accepted alpha testers receive gated documentation)"
        ),
        terms=clean_terms,
        geography=geo,
        language=str(language).strip().lower() or "en",
        time_resolution=resolution,
        window_start=str(window_start)[:10],
        window_end=str(window_end)[:10],
        # Fixture/dry-run caps only — official max terms/requests are unpublished.
        max_terms=10,
        max_requests=10,
        credential_reference_id="credential-google-trends-official",
        approval_request_type="provider_call",
        terms_review_required=True,
        privacy_review_required=True,
        live_request_created=False,
        network_calls=False,
        sdk_used=False,
        raw_payload_stored=False,
        schedule_enabled=False,
        status=plan_status,
        cost_note=(
            "Unit pricing is unknown on public Trends API alpha pages; treat cost as unavailable."
        ),
        quota_note=(
            "Numeric quotas are unknown on public Trends API alpha pages; treat quota as "
            "unavailable until Google documents them for an approved alpha/GA project."
        ),
    )
    parsed = parse_google_trends_interest_fixture(
        payload or _default_payload(clean_terms, geo, plan.language, resolution),
        request_kind=request_kind,
        source_file=source_file,
        reference_date=reference_date,
    )
    transport = FakeTrendsTransport()
    transport_result = transport.execute(
        {"scenario": transport_scenario or ("unsupported_access" if live_read_only else "fixture_parse"), "terms": list(clean_terms)}
    )
    blockers = [
        "alpha_access_not_granted",
        "approval_missing",
        "terms_review_missing",
        "privacy_review_missing",
        "published_quota_unavailable",
        "published_pricing_unavailable",
        "live_transport_not_implemented",
    ]
    if live_read_only:
        blockers.insert(0, "live_mode_requested")
    if not window["valid"]:
        blockers.append(window["reason"])
    readiness_state = "blocked" if live_read_only else "dry_run_ready"
    readiness = GoogleTrendsApprovalReadiness(
        alpha_access_granted=False,
        credential_reference_exists=False,
        secret_value_absent=True,
        approval_required=True,
        approval_request_type="provider_call",
        terms_review_complete=False,
        privacy_review_complete=False,
        fixture_output_contract_tested=True,
        live_mode_blocked=True,
        readiness_state=readiness_state,
        blockers=tuple(dict.fromkeys(blockers)),
    )
    if transport_result.status in {"rate_limited", "quota_exhausted", "unsupported_access", "disabled_by_policy"}:
        result_status = transport_result.status
    elif live_read_only:
        result_status = "blocked_live_mode"
    elif parsed.parse_status == "empty":
        result_status = "incomplete"
    elif any(item.status == "stale" for item in parsed.observations) and all(
        item.status in {"stale", "unavailable", "incomplete"} for item in parsed.observations
    ):
        result_status = "stale"
    elif parsed.observations and all(item.status == "collected" for item in parsed.observations):
        result_status = "collected"
    elif parsed.observations:
        result_status = "incomplete"
    else:
        result_status = "fixture_only"
    boundary = {
        "marketplace_price_authority": False,
        "supplier_proof": False,
        "launch_authority": False,
        "purchase_intent_authority": False,
        "absolute_volume_authority": False,
        "sales_or_demand_proof": False,
        "website_0_100_rescale": False,
        "relative_search_interest_evidence": True,
        "attention_evidence_only": True,
    }
    blocked_live = (
        "Google Trends API alpha access is application-gated and not commercially GA.",
        "Detailed method/endpoint/auth docs are gated; public pages leave them unknown.",
        "Credential reference is metadata-only / absent; no secret is loaded.",
        "Approval Ledger provider_call approval is missing.",
        "Terms and privacy reviews are incomplete.",
        "Published quotas and unit pricing are unavailable on the public docs.",
        "Network, SDK, Pytrends, scraping, and undocumented endpoints are disabled.",
        "Raw provider payload storage is forbidden.",
    )
    if live_read_only:
        blocked_live = ("live_mode_requested",) + blocked_live
    return GoogleTrendsInterestReport(
        report_version="google-trends-interest-adapter-v1",
        generated_at=generated_at,
        provider_id=PROVIDER_ID,
        evidence_category=EVIDENCE_CATEGORY,
        access_assessment=_access_assessment(),
        request_plan=plan,
        parse_result=parsed,
        observations=parsed.observations,
        approval_readiness=readiness,
        safety_summary=GoogleTrendsAdapterSafetySummary(
            True, False, False, False, False, False, False, False, False, True
        ),
        result_status=result_status,
        evidence_boundary=boundary,
        unavailable_fields=UNAVAILABLE_FIELDS,
        blocked_live_activation=blocked_live,
        next_best_action=(
            "Keep Google Trends interest evidence in fixture/dry-run mode as relative "
            "search-interest only. Before any transport: obtain alpha/GA access and "
            "gated reference docs; record published endpoints/methods/auth, quotas, "
            "and pricing; Approval Ledger provider_call approval; metadata-only "
            "credential reference; separately reviewed fail-closed live transport. "
            "Never treat results as volume, sales, supplier proof, or launch evidence."
        ),
        transport_result=transport_result,
    )


__all__ = [
    "PROVIDER_ID",
    "EVIDENCE_CATEGORY",
    "PRIMARY_DOCS",
    "MAX_LOOKBACK_DAYS",
    "DATA_LAG_DAYS",
    "REQUEST_KINDS",
    "TIME_RESOLUTIONS",
    "COLLECTION_STATUSES",
    "OBSERVATION_STATUSES",
    "READINESS_STATES",
    "UNAVAILABLE_FIELDS",
    "GoogleTrendsInterestAdapterError",
    "GoogleTrendsAccessAssessment",
    "GoogleTrendsInterestObservation",
    "GoogleTrendsParseResult",
    "GoogleTrendsRequestPlan",
    "GoogleTrendsApprovalReadiness",
    "GoogleTrendsAdapterSafetySummary",
    "GoogleTrendsInterestReport",
    "FakeTrendsTransport",
    "FakeTransportResult",
    "validate_geography",
    "validate_date_window",
    "normalize_interest_observation",
    "parse_google_trends_interest_fixture",
    "build_google_trends_interest_report",
]

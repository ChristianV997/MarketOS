"""Offline contracts for future read-only intelligence provider adapters.

This module deliberately stops before network or SDK behavior.  It turns the
CompanyOS provider, credential, tool, and approval vocabularies into request
plans, normalized evidence contracts, and deterministic dry-run results.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

from evaluation.companyos.approval_ledger import REQUEST_TYPES
from evaluation.companyos.credential_registry import build_credential_registry
from evaluation.companyos.provider_registry import build_provider_registry

ADAPTER_MODES = (
    "fixture_only",
    "manual_import",
    "dry_run_request_plan",
    "approved_live_read_only_later",
    "blocked",
)
READINESS_STATES = (
    "not_ready",
    "metadata_ready",
    "dry_run_ready",
    "approval_ready",
    "live_read_only_ready_later",
    "blocked",
)
EVIDENCE_CATEGORIES = (
    "MarketplaceEvidence",
    "SupplierEvidence",
    "ConsumerAttentionEvidence",
    "SearchDemandEvidence",
    "ReviewEvidence",
    "CompetitorPricingEvidence",
    "CreativeSignalEvidence",
    "ProviderRunEvidence",
)
STOP_CONDITIONS = (
    "cost_cap_reached",
    "terms_review_missing",
    "approval_missing",
    "credential_missing",
    "output_contract_failed",
    "provider_error",
    "unexpected_schema",
    "privacy_risk",
)
_SECRET_KEYS = frozenset({
    "actual_secret_value", "api_key", "raw_api_key", "raw_oauth_token",
    "oauth_token", "access_token", "refresh_token", "password",
    "private_key", "private_key_material", "authorization", "cookie",
})
_RAW_KEYS = frozenset({"raw_payload", "raw_html", "html", "body", "response_body", "javascript"})


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


# "sk-" is a credential prefix only when it starts a token; it is also the tail of words such as
# desk-clamp-lamp or risk-review-pack, so it must not follow a letter or digit.
_SK_PREFIX = re.compile(r"(?<![a-z0-9])sk-")


def _secret_like(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _SECRET_KEYS or normalized in _RAW_KEYS or _secret_like(item):
                return True
        return False
    if isinstance(value, (tuple, list, set)):
        return any(_secret_like(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return "-----begin " in lowered or "bearer " in lowered or _SK_PREFIX.search(lowered) is not None or any(marker in lowered for marker in ("ghp_", "xoxb-", "AIza"))
    return False


@dataclass(frozen=True)
class ProviderRateLimitPlan:
    provider_id: str
    requests_per_minute: int
    max_runs_per_day: int
    max_items_per_run: int
    rate_limit_notes: str
    overage_risk: str
    stop_conditions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class ProviderCostEstimate:
    provider_id: str
    estimated_cost_per_run_min: float
    estimated_cost_per_run_max: float
    estimated_monthly_budget_min: float
    estimated_monthly_budget_max: float
    currency: str
    cost_driver: str
    assumption_note: str
    stop_conditions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class ProviderOutputContract:
    contract_id: str
    evidence_category: str
    target_model: str
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    sanitized: bool
    raw_payload_allowed: bool
    provenance_required: bool
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.evidence_category not in EVIDENCE_CATEGORIES:
            raise ValueError(f"unsupported evidence category: {self.evidence_category}")
        if self.raw_payload_allowed:
            raise ValueError("raw provider payloads are never allowed")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class ProviderEvidenceMapping:
    provider_id: str
    source_method: str
    evidence_category: str
    target_model: str
    normalized_fields: tuple[str, ...]
    limitations: tuple[str, ...]
    terms_notes: str
    privacy_notes: str
    can_feed_reports: bool

    def __post_init__(self) -> None:
        if self.evidence_category not in EVIDENCE_CATEGORIES:
            raise ValueError(f"unsupported evidence category: {self.evidence_category}")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class ProviderNormalizationRule:
    rule_id: str
    provider_id: str
    field: str
    transform: str
    missing_behavior: str
    conflict_behavior: str
    provenance: str = "derived"

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class ProviderApprovalCheck:
    check_id: str
    provider_id: str
    check_type: str
    required: bool
    satisfied: bool
    status: str
    evidence_ref: str
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class ProviderCredentialCheck:
    credential_reference_id: str
    provider_id: str
    required: bool
    reference_exists: bool
    secret_value_absent: bool
    status: str
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class ProviderTermsPrivacyReview:
    provider_id: str
    terms_review_required: bool
    terms_review_complete: bool
    privacy_review_required: bool
    privacy_review_complete: bool
    data_minimization_note: str
    blocked_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class ProviderRequestPlan:
    plan_id: str
    provider_id: str
    request_kind: str
    target_data_needs: tuple[str, ...]
    parameters: dict[str, Any]
    max_items: int
    max_cost: float
    currency: str
    output_contract_id: str
    schedule_disabled: bool
    live_request_created: bool
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.live_request_created:
            raise ValueError("live request creation is disabled")
        if not self.schedule_disabled:
            raise ValueError("scheduling must remain disabled")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class ProviderRunEnvelope:
    run_id: str
    provider_id: str
    request_plan_id: str
    mode: str
    request_id_placeholder: str
    credential_reference_id: str
    approval_id_placeholder: str
    input_parameters: dict[str, Any]
    idempotency_key_placeholder: str
    created_at_placeholder: str
    network_allowed: bool
    external_action_performed: bool
    raw_payload_storage: str

    def __post_init__(self) -> None:
        if self.mode not in ADAPTER_MODES:
            raise ValueError(f"unsupported adapter mode: {self.mode}")
        if self.network_allowed or self.external_action_performed or self.raw_payload_storage != "none":
            raise ValueError("run envelopes are offline and raw-payload-free")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class ProviderActivationReadiness:
    provider_id: str
    state: str
    credential_check: ProviderCredentialCheck
    approval_checks: tuple[ProviderApprovalCheck, ...]
    terms_privacy_review: ProviderTermsPrivacyReview
    blockers: tuple[str, ...]
    future_prerequisites: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.state not in READINESS_STATES:
            raise ValueError(f"unsupported readiness state: {self.state}")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class ProviderBlockedReason:
    provider_id: str
    reason_code: str
    description: str
    blocking: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class ProviderAdapterContract:
    provider_id: str
    provider_name: str
    provider_category: str
    target_data_needs: tuple[str, ...]
    supported_modes: tuple[str, ...]
    default_mode: str
    credential_reference_id: str
    required_approval_type: tuple[str, ...]
    required_tool_category: str
    estimated_cost_per_run_min: float
    estimated_cost_per_run_max: float
    monthly_budget_cap: float
    rate_limit_policy: ProviderRateLimitPlan
    terms_review_required: bool
    privacy_review_required: bool
    output_contract: ProviderOutputContract
    evidence_mapping: tuple[ProviderEvidenceMapping, ...]
    normalization_rules: tuple[ProviderNormalizationRule, ...]
    activation_readiness: ProviderActivationReadiness
    blocked_reasons: tuple[ProviderBlockedReason, ...]

    def __post_init__(self) -> None:
        if self.default_mode not in ADAPTER_MODES or self.default_mode in {"approved_live_read_only_later"}:
            raise ValueError("default adapter mode must be offline or blocked")
        if any(item not in REQUEST_TYPES for item in self.required_approval_type if item != "none"):
            raise ValueError("approval types must reuse Approval Ledger vocabulary")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class ProviderDryRunResult:
    provider_id: str
    run_id: str
    result_status: str
    fixture_ref: str
    normalized_records: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]
    network_calls: bool
    raw_payload_stored: bool
    external_action_performed: bool

    def __post_init__(self) -> None:
        if self.network_calls or self.raw_payload_stored or self.external_action_performed:
            raise ValueError("dry-run results cannot contain live or raw data")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class NormalizedEvidenceRecord:
    source_provider: str
    source_method: str
    source_url_or_id_placeholder: str
    captured_at_placeholder: str
    raw_record_ref_placeholder: str
    normalized_fields: dict[str, Any]
    confidence: str
    limitations: tuple[str, ...]
    terms_notes: str
    privacy_notes: str
    evidence_category: str
    can_feed_reports: bool

    def __post_init__(self) -> None:
        if self.evidence_category not in EVIDENCE_CATEGORIES:
            raise ValueError(f"unsupported evidence category: {self.evidence_category}")
        if _secret_like(self.normalized_fields):
            raise ValueError("normalized evidence cannot contain secrets or raw payload keys")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


class NormalizedMarketplaceSignal(NormalizedEvidenceRecord):
    pass


class NormalizedSearchSignal(NormalizedEvidenceRecord):
    pass


class NormalizedReviewSignal(NormalizedEvidenceRecord):
    pass


class NormalizedCompetitorSignal(NormalizedEvidenceRecord):
    pass


class NormalizedCreativeSignal(NormalizedEvidenceRecord):
    pass


class NormalizedSupplierSignal(NormalizedEvidenceRecord):
    pass


class ProviderRunEvidence(NormalizedEvidenceRecord):
    pass


@dataclass(frozen=True)
class ProviderAdapterSafetySummary:
    read_only: bool
    network_calls: bool
    credentials_loaded: bool
    provider_calls: bool
    sdk_calls: bool
    scraping_performed: bool
    raw_payloads_stored: bool
    raw_html_stored: bool
    external_actions: bool
    fail_closed: bool

    def __post_init__(self) -> None:
        if not self.read_only or any((self.network_calls, self.credentials_loaded, self.provider_calls, self.sdk_calls, self.scraping_performed, self.raw_payloads_stored, self.raw_html_stored, self.external_actions)):
            raise ValueError("adapter plan safety summary must be offline and read-only")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class IntelligenceAdapterPlanReport:
    report_version: str
    generated_at: str
    provider_count: int
    adapter_contract_count: int
    request_plan_count: int
    dry_run_result_count: int
    readiness_by_provider: tuple[ProviderActivationReadiness, ...]
    credential_gaps: tuple[str, ...]
    approval_gaps: tuple[str, ...]
    terms_privacy_gaps: tuple[str, ...]
    cost_plan: tuple[ProviderCostEstimate, ...]
    rate_limit_plan: tuple[ProviderRateLimitPlan, ...]
    evidence_mappings: tuple[ProviderEvidenceMapping, ...]
    normalization_summary: tuple[ProviderNormalizationRule, ...]
    providers_blocked: tuple[str, ...]
    providers_ready_for_dry_run: tuple[str, ...]
    providers_ready_for_future_approval: tuple[str, ...]
    contracts: tuple[ProviderAdapterContract, ...]
    request_plans: tuple[ProviderRequestPlan, ...]
    run_envelopes: tuple[ProviderRunEnvelope, ...]
    dry_run_results: tuple[ProviderDryRunResult, ...]
    blocked_reasons: tuple[ProviderBlockedReason, ...]
    safety_summary: ProviderAdapterSafetySummary
    next_best_action: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)

    def to_markdown(self) -> str:
        lines = [
            "# Intelligence Live Read-Only Adapter Plan", "", "## Executive Summary", "",
            f"- Providers: **{self.provider_count}**", f"- Adapter contracts: **{self.adapter_contract_count}**",
            f"- Request plans: **{self.request_plan_count}**", f"- Dry runs: **{self.dry_run_result_count}**",
            "- Mode: **offline, deterministic, fixture-backed; live mode blocked**", "",
            "## Provider Adapter Contracts", "", "| Provider | Default mode | Readiness | Cost/run |", "|---|---|---|---|",
        ]
        lines.extend(f"| {item.provider_name} | {item.default_mode} | {item.activation_readiness.state} | ${item.estimated_cost_per_run_min:.2f}-${item.estimated_cost_per_run_max:.2f} |" for item in self.contracts)
        lines += ["", "## Request Plans", ""]
        lines.extend(f"- **{item.provider_id}** `{item.request_kind}`: max {item.max_items} items, max ${item.max_cost:.2f}, schedule disabled." for item in self.request_plans)
        lines += ["", "## Approval and Credential Checks", ""]
        lines.extend(f"- {item.provider_id}: {item.state}; {len(item.blockers)} blocker(s)." for item in self.readiness_by_provider)
        lines += ["", "## Cost and Rate Limits", ""]
        rate_by_provider = {item.provider_id: item for item in self.rate_limit_plan}
        lines.extend(f"- {item.provider_id}: ${item.estimated_cost_per_run_min:.2f}-${item.estimated_cost_per_run_max:.2f}/run; {rate_by_provider[item.provider_id].max_runs_per_day} run(s)/day; {rate_by_provider[item.provider_id].max_items_per_run} item(s)/run." for item in self.cost_plan)
        lines += ["", "## Terms and Privacy Review", ""]
        lines.extend(f"- {item}" for item in self.terms_privacy_gaps)
        lines += ["", "## Evidence Mapping", ""]
        lines.extend(f"- {item.provider_id} / {item.source_method} -> `{item.evidence_category}` (`{item.target_model}`)." for item in self.evidence_mappings)
        lines += ["", "## Normalization Rules", ""]
        lines.extend(f"- `{item.field}`: {item.transform}; missing -> {item.missing_behavior}; conflicts -> {item.conflict_behavior}." for item in self.normalization_summary[:16])
        lines += ["", "## Dry-Run Results", ""]
        lines.extend(f"- {item.provider_id}: `{item.result_status}` from `{item.fixture_ref}`; {len(item.normalized_records)} normalized record(s)." for item in self.dry_run_results)
        lines += ["", "## Blocked Providers", ""]
        lines.extend(f"- {item}" for item in self.providers_blocked)
        lines += ["", "## Next Best Action", "", self.next_best_action, "", "## Safety Boundaries", "", "No credentials are loaded, no SDKs or network calls are used, no raw payloads or HTML are stored, and no provider action occurs.", ""]
        return "\n".join(lines)


_PROVIDER_SPECS: tuple[dict[str, Any], ...] = (
    {"id": "apify", "name": "Apify", "category": "intelligence_data", "needs": ("marketplace_demand", "competitor_pricing", "review_extraction", "consumer_attention", "social_public_snapshots", "scheduled_monitoring"), "mode": "dry_run_request_plan", "credential": "credential-apify", "approval": ("provider_call", "web_data_acquisition"), "tool": "search_web", "cost": (0.05, 5.0, 50.0, 500.0), "items": 100, "runs": 10, "rpm": 2, "method": "actor_dataset_snapshot", "evidence": ("MarketplaceEvidence", "ReviewEvidence", "ConsumerAttentionEvidence"), "fixture": "apify_marketplace_snapshot_dry_run.json"},
    {"id": "dataforseo", "name": "DataForSEO", "category": "search_serp_data", "needs": ("search_serp_keyword_demand", "competitor_pricing", "official_api_validation"), "mode": "dry_run_request_plan", "credential": "credential-dataforseo", "approval": ("provider_call", "web_data_acquisition"), "tool": "search_web", "cost": (0.05, 2.0, 50.0, 500.0), "items": 100, "runs": 20, "rpm": 10, "method": "serp_keyword_snapshot", "evidence": ("SearchDemandEvidence", "CompetitorPricingEvidence"), "fixture": "dataforseo_serp_snapshot_dry_run.json"},
    {"id": "serpapi", "name": "SerpApi", "category": "search_serp_data", "needs": ("search_serp_keyword_demand", "competitor_pricing"), "mode": "dry_run_request_plan", "credential": "credential-serpapi", "approval": ("provider_call", "web_data_acquisition"), "tool": "search_web", "cost": (0.05, 3.0, 50.0, 600.0), "items": 100, "runs": 20, "rpm": 10, "method": "search_shopping_snapshot", "evidence": ("SearchDemandEvidence", "CompetitorPricingEvidence"), "fixture": "serpapi_shopping_snapshot_dry_run.json"},
    {"id": "official-marketplace-apis", "name": "Official Marketplace APIs", "category": "marketplace_api", "needs": ("marketplace_api_validation", "supplier_api_validation"), "mode": "dry_run_request_plan", "credential": "credential-official-marketplace-apis-planned", "approval": ("provider_call",), "tool": "search_web", "cost": (0.0, 2.0, 0.0, 200.0), "items": 50, "runs": 10, "rpm": 5, "method": "official_read_only_snapshot", "evidence": ("MarketplaceEvidence", "SupplierEvidence"), "fixture": "manual_import_marketplace_snapshot.json"},
    {"id": "official-social-search-apis", "name": "Official Social/Search APIs", "category": "intelligence_data", "needs": ("consumer_attention", "social_public_snapshots", "official_api_validation"), "mode": "dry_run_request_plan", "credential": "credential-official-social-search-apis-planned", "approval": ("provider_call",), "tool": "search_web", "cost": (0.0, 5.0, 0.0, 300.0), "items": 50, "runs": 10, "rpm": 5, "method": "official_public_snapshot", "evidence": ("ConsumerAttentionEvidence", "SearchDemandEvidence"), "fixture": "manual_import_marketplace_snapshot.json"},
    {"id": "bright-data", "name": "Bright Data", "category": "scraping_proxy", "needs": ("hard_target_extraction", "enterprise_scale"), "mode": "blocked", "credential": "credential-bright-data-planned", "approval": ("provider_call", "web_data_acquisition"), "tool": "search_web", "cost": (0.0, 100.0, 0.0, 2000.0), "items": 10, "runs": 1, "rpm": 1, "method": "proxy_acquisition_blocked", "evidence": ("ProviderRunEvidence",), "fixture": "manual_import_marketplace_snapshot.json"},
    {"id": "oxylabs", "name": "Oxylabs", "category": "scraping_proxy", "needs": ("hard_target_extraction", "enterprise_scale"), "mode": "blocked", "credential": "credential-oxylabs-planned", "approval": ("provider_call", "web_data_acquisition"), "tool": "search_web", "cost": (0.0, 150.0, 0.0, 3000.0), "items": 10, "runs": 1, "rpm": 1, "method": "proxy_acquisition_blocked", "evidence": ("ProviderRunEvidence",), "fixture": "manual_import_marketplace_snapshot.json"},
    {"id": "manual-import", "name": "Manual Imports", "category": "intelligence_data", "needs": ("marketplace_demand", "competitor_pricing", "supplier_feasibility", "consumer_attention"), "mode": "manual_import", "credential": "none", "approval": ("none",), "tool": "read_file", "cost": (0.0, 0.0, 0.0, 0.0), "items": 500, "runs": 1, "rpm": 0, "method": "sanitized_manual_import", "evidence": ("MarketplaceEvidence", "SupplierEvidence", "ConsumerAttentionEvidence"), "fixture": "manual_import_marketplace_snapshot.json"},
)


def _output_contract(provider_id: str, category: str, model: str, fields: tuple[str, ...]) -> ProviderOutputContract:
    return ProviderOutputContract(f"output-{provider_id}-{category.lower()}", category, model, fields, ("source_url_or_id", "captured_at", "limitations"), True, False, True, ("fixture/manual values are not live proof", "provider payloads are discarded after normalization"))


def _mappings(spec: Mapping[str, Any]) -> tuple[ProviderEvidenceMapping, ...]:
    return tuple(ProviderEvidenceMapping(spec["id"], spec["method"], category, {"MarketplaceEvidence": "MarketplaceTrendEvidence", "SupplierEvidence": "SupplierFeasibilityEvidence", "ConsumerAttentionEvidence": "ConsumerAttentionEvidence", "SearchDemandEvidence": "SearchTrendEvidence", "ReviewEvidence": "ReviewMiningEvidence", "CompetitorPricingEvidence": "MarketplaceTrendEvidence", "ProviderRunEvidence": "ProviderRunEvidence"}[category], ("candidate_id", "query", "source_provider", "source_method", "confidence", "limitations"), ("fixture/manual evidence is not live proof",), "Terms/TOS review is a prerequisite for live activation.", "Use data minimization and omit personal data; privacy review is required.", True) for category in spec["evidence"])


def _normalization_rules(spec: Mapping[str, Any]) -> tuple[ProviderNormalizationRule, ...]:
    fields = ("candidate_id", "query", "title", "price", "currency", "rank", "review_count", "rating", "trend_label", "source_url")
    return tuple(ProviderNormalizationRule(f"normalize-{spec['id']}-{field}", spec["id"], field, {"price": "parse numeric price and retain currency", "currency": "normalize ISO-like currency code", "rank": "coerce positive integer", "review_count": "coerce non-negative integer", "rating": "bound to provider scale", "source_url": "retain placeholder or public URL only"}.get(field, "trim text and normalize whitespace"), "mark unavailable with provenance", "prefer observed value, otherwise mark conflicting", "derived") for field in fields)


def _cost(spec: Mapping[str, Any]) -> ProviderCostEstimate:
    low, high, monthly_low, monthly_high = spec["cost"]
    return ProviderCostEstimate(spec["id"], low, high, monthly_low, monthly_high, "USD", "items, requests, actor/runtime, or provider plan usage", "Offline planning band; verify current pricing before activation.", STOP_CONDITIONS)


def _rate(spec: Mapping[str, Any]) -> ProviderRateLimitPlan:
    return ProviderRateLimitPlan(spec["id"], spec["rpm"], spec["runs"], spec["items"], "Use bounded requests with backoff in a future adapter; no request is made now.", "Unexpected pagination, actor runtime, or overage can exceed the planning band.", STOP_CONDITIONS)


def _request_plan(spec: Mapping[str, Any], output: ProviderOutputContract) -> ProviderRequestPlan:
    parameters: dict[str, Any]
    if spec["id"] == "apify":
        parameters = {"actor_id_placeholder": "actor-marketos-public-intelligence", "input_schema_placeholder": {"query": "candidate query", "maxItems": spec["items"]}, "dataset_output_contract": output.contract_id, "schedule_disabled": True}
    elif spec["id"] == "dataforseo":
        parameters = {"endpoint_placeholder": "/serp/google/organic/task_post", "keyword_batch": ["candidate query"], "location_code_placeholder": "TBD", "language_code": "en", "max_requests": spec["runs"], "max_cost": spec["cost"][1], "output_contract": output.contract_id}
    elif spec["id"] == "serpapi":
        parameters = {"endpoint_placeholder": "search.json", "engine_placeholder": "google_shopping", "q": "candidate query", "location_placeholder": "TBD", "max_requests": spec["runs"], "max_cost": spec["cost"][1], "output_contract": output.contract_id}
    elif spec["id"] == "manual-import":
        parameters = {"input_path_placeholder": "tests/fixtures/intelligence_adapter_plan/manual_import_marketplace_snapshot.json", "format": "sanitized_json_or_csv", "raw_payload_passthrough": False}
    else:
        parameters = {"endpoint_placeholder": "official_read_only_endpoint_TBD", "request_schema_placeholder": "TBD", "output_contract": output.contract_id}
    return ProviderRequestPlan(f"request-plan-{spec['id']}", spec["id"], spec["method"], spec["needs"], parameters, spec["items"], spec["cost"][1], "USD", output.contract_id, True, False, ("No live request is created.", "Approval and credential checks must pass before a future adapter can be implemented."))


def _readiness(spec: Mapping[str, Any], credentials: Any, output: ProviderOutputContract) -> ProviderActivationReadiness:
    credential_id = spec["credential"]
    reference_exists = credential_id == "none" or any(item.credential_id == credential_id for item in credentials.credentials)
    credential = ProviderCredentialCheck(credential_id, spec["id"], credential_id != "none", reference_exists, True, "metadata_ready" if reference_exists else "blocked", "Reference-only metadata; no secret value is loaded.")
    approval_checks = tuple(ProviderApprovalCheck(f"check-{spec['id']}-{name}", spec["id"], name, name != "manual_import", False, "pending" if name != "manual_import" else "not_required", "future-policy-placeholder", "Approval Ledger review is required before live use.") for name in ("approval_required", "budget_cap_set", "terms_review_complete", "privacy_review_complete", "output_contract_tested", "dry_run_fixture_available", "live_mode_blocked"))
    review = ProviderTermsPrivacyReview(spec["id"], spec["id"] != "manual-import", False, spec["id"] != "manual-import", False, "Minimize fields, exclude personal data, and store normalized evidence only.", () if spec["id"] == "manual-import" else ("terms_review_missing", "privacy_review_missing"))
    blockers = []
    if not reference_exists and credential_id != "none":
        blockers.append("credential_reference_missing")
    if spec["id"] != "manual-import":
        blockers.extend(("approval_missing", "terms_review_missing", "privacy_review_missing"))
    if spec["mode"] == "blocked":
        blockers.append("provider_class_blocked_in_current_mode")
    state = "blocked" if spec["mode"] == "blocked" else "dry_run_ready"
    return ProviderActivationReadiness(spec["id"], state, credential, approval_checks, review, tuple(dict.fromkeys(blockers)), ("owner assigned", "secret-manager reference configured", "budget cap approved", "terms/privacy review complete", "normalized output contract test passes", "Approval Ledger decision recorded"))


def _contract(spec: Mapping[str, Any], credentials: Any) -> ProviderAdapterContract:
    category = spec["evidence"][0]
    model = {"MarketplaceEvidence": "MarketplaceTrendEvidence", "SearchDemandEvidence": "SearchTrendEvidence", "ConsumerAttentionEvidence": "ConsumerAttentionEvidence", "SupplierEvidence": "SupplierFeasibilityEvidence", "ProviderRunEvidence": "ProviderRunEvidence"}[category]
    output = _output_contract(spec["id"], category, model, ("candidate_id", "query", "source_provider", "source_method", "normalized_fields", "confidence", "limitations"))
    readiness = _readiness(spec, credentials, output)
    blocked = tuple(ProviderBlockedReason(spec["id"], reason, {"approval_missing": "Approval Ledger request is not approved.", "terms_review_missing": "Provider terms review is not complete.", "privacy_review_missing": "Privacy review is not complete.", "credential_reference_missing": "No safe credential reference is registered.", "provider_class_blocked_in_current_mode": "Enterprise proxy acquisition is explicitly blocked in offline mode."}.get(reason, "Live adapter prerequisite is not satisfied.")) for reason in readiness.blockers)
    return ProviderAdapterContract(spec["id"], spec["name"], spec["category"], spec["needs"], ADAPTER_MODES, spec["mode"], spec["credential"], spec["approval"], spec["tool"], spec["cost"][0], spec["cost"][1], spec["cost"][3], _rate(spec), spec["id"] != "manual-import", spec["id"] != "manual-import", output, _mappings(spec), _normalization_rules(spec), readiness, blocked)


def _envelope(spec: Mapping[str, Any]) -> ProviderRunEnvelope:
    mode = spec["mode"]
    return ProviderRunEnvelope(f"dry-run-{spec['id']}", spec["id"], f"request-plan-{spec['id']}", mode, f"request-{spec['id']}-placeholder", spec["credential"], f"approval-{spec['id']}-placeholder", {"query": "candidate query", "max_items": spec["items"]}, f"idempotency-{spec['id']}-placeholder", "offline-deterministic", False, False, "none")


def _dry_run(spec: Mapping[str, Any]) -> ProviderDryRunResult:
    category = spec["evidence"][0]
    normalized = {"candidate_id": "mini-thermal-printer", "query": "mini thermal printer", "source_provider": spec["id"], "source_method": spec["method"], "title": "Synthetic normalized marketplace signal", "price": 29.99, "currency": "USD", "confidence": "fixture", "evidence_category": category, "limitations": ["synthetic fixture", "not live supplier or market proof"]}
    return ProviderDryRunResult(spec["id"], f"dry-run-{spec['id']}", "normalized_fixture", f"tests/fixtures/intelligence_adapter_plan/{spec['fixture']}", (normalized,), ("Synthetic fixture; no provider response was received.",), False, False, False)


def normalize_provider_record(provider_id: str, evidence_category: str, record: Mapping[str, Any], *, method: str = "fixture_snapshot") -> NormalizedEvidenceRecord:
    """Normalize one sanitized provider-shaped record without retaining its payload."""
    if _secret_like(record):
        raise ValueError("secret-like or raw provider fields are not accepted")
    fields = {key: record[key] for key in ("candidate_id", "query", "title", "price", "currency", "rank", "review_count", "rating", "trend_label") if key in record}
    fields = {"candidate_id": str(fields.get("candidate_id", "unknown")), "query": str(fields.get("query", "unknown")), **{key: value for key, value in fields.items() if key not in {"candidate_id", "query"}}}
    return NormalizedEvidenceRecord(provider_id, method, "public-source-placeholder", "offline-deterministic", f"normalized-{provider_id}-record", fields, "fixture", ("input is sanitized and synthetic",), "Terms/privacy review required before live use.", "No personal data retained.", evidence_category, True)


def parse_dry_run_fixture(provider_id: str, payload: Mapping[str, Any], *, evidence_category: str = "ProviderRunEvidence") -> tuple[NormalizedEvidenceRecord, ...]:
    """Parse a synthetic fixture and return only normalized records."""
    if _secret_like(payload):
        raise ValueError("secret-like or raw provider output is not accepted")
    records = payload.get("records", payload.get("results", payload.get("items", ())))
    if isinstance(records, Mapping):
        records = (records,)
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ValueError("dry-run fixture records must be a list")
    return tuple(normalize_provider_record(provider_id, evidence_category, item) for item in records if isinstance(item, Mapping))


def build_intelligence_adapter_plan(*, generated_at: str = "offline-deterministic", provider: str | None = None, data_need: str | None = None, fixture_payloads: Mapping[str, Mapping[str, Any]] | None = None) -> IntelligenceAdapterPlanReport:
    credentials = build_credential_registry(generated_at=generated_at)
    specs = list(_PROVIDER_SPECS)
    if provider:
        normalized = provider.lower().replace(" ", "-")
        specs = [item for item in specs if item["id"] == normalized]
        if not specs:
            raise ValueError(f"unknown adapter provider: {normalized}")
    if data_need:
        specs = [item for item in specs if data_need in item["needs"]]
        if not specs:
            raise ValueError(f"unknown or unsupported data need: {data_need}")
    contracts = tuple(_contract(spec, credentials) for spec in specs)
    outputs = {item.provider_id: item.output_contract for item in contracts}
    requests = tuple(_request_plan(spec, outputs[spec["id"]]) for spec in specs)
    envelopes = tuple(_envelope(spec) for spec in specs)
    payloads = fixture_payloads or {}
    results: list[ProviderDryRunResult] = []
    for spec in specs:
        if spec["id"] in payloads:
            parse_dry_run_fixture(spec["id"], payloads[spec["id"]], evidence_category=spec["evidence"][0])
        results.append(_dry_run(spec))
    readiness = tuple(item.activation_readiness for item in contracts)
    costs = tuple(_cost(spec) for spec in specs)
    rates = tuple(_rate(spec) for spec in specs)
    mappings = tuple(mapping for item in contracts for mapping in item.evidence_mapping)
    rules = tuple(rule for item in contracts for rule in item.normalization_rules)
    credential_gaps = tuple(f"{item.provider_id}: credential reference or secret-manager value remains metadata-only" for item in contracts if item.activation_readiness.credential_check.required)
    approval_gaps = tuple(f"{item.provider_id}: Approval Ledger request type {', '.join(item.required_approval_type)} is not approved" for item in contracts if item.required_approval_type != ("none",))
    terms_gaps = tuple(f"{item.provider_id}: terms/privacy review is incomplete" for item in contracts if item.terms_review_required or item.privacy_review_required)
    blocked = tuple(item.provider_id for item in contracts if item.activation_readiness.state == "blocked")
    dry_ready = tuple(item.provider_id for item in contracts if item.activation_readiness.state == "dry_run_ready")
    future_approval = tuple(item.provider_id for item in contracts if item.provider_id in {"apify", "dataforseo", "serpapi", "official-marketplace-apis", "official-social-search-apis"})
    safety = ProviderAdapterSafetySummary(True, False, False, False, False, False, False, False, False, True)
    return IntelligenceAdapterPlanReport("intelligence-live-readonly-adapter-plan-v1", generated_at, len(contracts), len(contracts), len(requests), len(results), readiness, credential_gaps, approval_gaps, terms_gaps, costs, rates, mappings, rules, blocked, dry_ready, future_approval, contracts, requests, envelopes, tuple(results), tuple(reason for item in contracts for reason in item.blocked_reasons), safety, "Run and review the deterministic dry-run contracts; then choose one provider, owner, budget, terms/privacy review, and Approval Ledger request before any future live read-only implementation.")


__all__ = [
    "ADAPTER_MODES", "READINESS_STATES", "EVIDENCE_CATEGORIES", "STOP_CONDITIONS",
    "IntelligenceAdapterPlanReport", "ProviderAdapterContract", "ProviderRequestPlan", "ProviderRunEnvelope",
    "ProviderActivationReadiness", "ProviderApprovalCheck", "ProviderCredentialCheck", "ProviderCostEstimate",
    "ProviderRateLimitPlan", "ProviderTermsPrivacyReview", "ProviderOutputContract", "ProviderEvidenceMapping",
    "ProviderNormalizationRule", "ProviderDryRunResult", "ProviderBlockedReason", "ProviderAdapterSafetySummary",
    "NormalizedEvidenceRecord", "NormalizedMarketplaceSignal", "NormalizedSearchSignal", "NormalizedReviewSignal",
    "NormalizedCompetitorSignal", "NormalizedCreativeSignal", "NormalizedSupplierSignal", "ProviderRunEvidence",
    "IntelligenceAdapterPlanReport", "normalize_provider_record", "parse_dry_run_fixture", "build_intelligence_adapter_plan",
]

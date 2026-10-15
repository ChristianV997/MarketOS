"""evaluation.commerce.tiktok_research_evidence — TikTok official research evidence contract.

Offline / fixture / fake-transport only. Live TikTok Research Tools calls are
default-off and blocked for MarketOS commercial use.

Surfaces are evaluated separately from primary docs (rechecked 2026-10-15):

- Research API / Research Tools FAQ: creators, advertisers, and commercial
  users are not eligible (answer: No.). Applicant regions on the products page
  do not include Mexico.
- Commercial Content API: products page frames public/researchers access with
  EU-phase ad data; Getting Started uses an approved research client. Do **not**
  assume CCL shares the Research API eligibility rule verbatim—no dedicated CCL
  FAQ was found. Supported Countries list EU/EEA/UK/CH; Mexico is not listed.
- Creative Center: public website/inspiration hub ≠ ingest/scrape license.
- Marketing API: advertiser own-account analytics/mutation ≠ market-wide demand.

Academic Research API eligibility therefore does not authorize MarketOS
commercial product research, and absence of an authorized Mexico source is a
precise blocked/unavailable capability—not a generic “MarketOS offline” claim.

This module does not replace ``backend.adapters.tiktok_organic`` (signal mock /
Creative Center attempt path) and does not duplicate the generic consumer-
attention importer. Fixture rows are normalized through
``backend.adapters.research.consumer_attention.normalize_record`` into
``ConsumerAttentionEvidence`` and scored only via
``evaluation.commerce.consumer_attention.build_report``.
"""
from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from backend.adapters.research.consumer_attention import (
    ConsumerAttentionImportError,
    contains_raw_payload,
    contains_secret,
    import_json,
    normalize_record,
    validate_input_path,
)
from evaluation.commerce.consumer_attention import ConsumerAttentionEvidence, build_report
from evaluation.companyos.resource_execution_governor import (
    ExecutionDecisionRequest,
    evaluate_execution_request,
)

REPORT_VERSION = "tiktok-research-evidence-v3"
SOURCE = "tiktok_research_tools"
ACCESS_DATE = "2026-10-15"
DOC_RECHECK_DATE = "2026-10-15"

# Distinct TikTok surfaces evaluated for commercial consumer-attention research.
EVALUATED_SURFACES = (
    "research_api",
    "commercial_content_api",
    "creative_center",
    "marketing_api",
)
# Backward-compatible alias for Research Tools pair.
RESEARCH_TOOL_SURFACES = ("research_api", "commercial_content_api")

CAPABILITY_STATUSES = frozenset(
    {
        "fixture_demo",
        "manual_import",
        "not_configured",
        "blocked_ineligible_commercial_use",
        "blocked_no_supported_commercial_attention_source",
        "blocked_offline_demo_disabled",
        "blocked_live_mode",
        "blocked_by_policy",
        "fake_transport_ok",
        "fake_transport_error",
        "malformed_input",
        "partial",
    }
)

OFFLINE_DEMO_MODES = frozenset({"fixture_demo", "manual_import", "fake_transport"})

# Documented blockers for MarketOS commercial operation (not academic research).
COMMERCIAL_INELIGIBILITY = (
    "tiktok_research_tools_require_approved_research_project",
    "tiktok_faq_commercial_users_ineligible_for_research_tools",
    "academic_research_api_eligibility_does_not_authorize_marketos_commercial_use",
    "research_api_applicant_regions_exclude_mexico_per_products_page",
    "commercial_content_api_eligibility_not_assumed_identical_to_research_api",
    "commercial_content_api_ad_geography_eu_eea_uk_ch_mexico_not_listed",
    "mexico_commercial_product_attention_has_no_eligible_live_source",
    "creative_center_website_visibility_is_not_scrape_or_api_permission",
    "marketing_api_is_advertiser_own_account_not_market_wide_attention",
    "no_eligible_official_live_source_for_marketos_commercial_attention",
    "no_live_transport_in_this_module",
    "approval_ledger_provider_call_not_granted_by_this_layer",
)

_AUTHORITY_FALSE = {
    "publish": False,
    "spend": False,
    "launch": False,
    "supplier_proof": False,
    "product_demand": False,
    "purchase_evidence": False,
    "decision_scoring": False,
    "ad_creation": False,
    "messaging": False,
    "targeting_activated": False,
    "campaign_authority": False,
    "authenticated_observation": False,
    "live_provider_calls": False,
}


class TikTokResearchTransport(Protocol):
    """Injected transport. Production code never ships a live implementation here."""

    def fetch(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class FakeTikTokResearchTransport:
    """Deterministic fake for tests. Never opens a socket."""

    status: str = "ok"
    rows: tuple[Mapping[str, Any], ...] = ()
    error_code: str = "fake_upstream_error"

    def fetch(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if self.status == "ok":
            return {"http_status": 200, "body": {"data": list(self.rows)}, "request": dict(request)}
        if self.status == "rate_limited":
            return {"http_status": 429, "body": {"error": {"code": "rate_limited"}}, "request": dict(request)}
        if self.status == "unauthorized":
            return {"http_status": 401, "body": {"error": {"code": "unauthorized"}}, "request": dict(request)}
        return {"http_status": 500, "body": {"error": {"code": self.error_code}}, "request": dict(request)}


@dataclass(frozen=True)
class TikTokResearchCapability:
    surface: str
    status: str
    eligible_for_marketos_commercial_use: bool
    live_transport_implemented: bool
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TikTokResearchEvidenceReport:
    report_version: str
    source: str
    capability_status: str
    surfaces: tuple[TikTokResearchCapability, ...]
    evidence_mode: str
    attention_report: Mapping[str, Any] | None
    evidence_count: int
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    official_citations: tuple[Mapping[str, str], ...]
    authority: Mapping[str, bool] = field(default_factory=lambda: dict(_AUTHORITY_FALSE))
    client_visibility: str = "internal_only"
    sanitizer_status: str = "best_effort_reuses_consumer_attention_importer"
    execution_authorized: bool = False
    network_calls: bool = False
    live_provider_calls: bool = False
    read_only: bool = True
    mutated: bool = False
    next_best_action: str = ""
    fingerprint: str = ""
    observed_at: float = 0.0
    operational_capability: bool = False
    offline_demo_allowed: bool = False
    eligible_live_source: str | None = None
    no_supported_commercial_attention_source: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "source": self.source,
            "capability_status": self.capability_status,
            "surfaces": [item.to_dict() for item in self.surfaces],
            "evidence_mode": self.evidence_mode,
            "attention_report": dict(self.attention_report) if isinstance(self.attention_report, Mapping) else None,
            "evidence_count": self.evidence_count,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "official_citations": [dict(item) for item in self.official_citations],
            "authority": dict(self.authority),
            "client_visibility": self.client_visibility,
            "sanitizer_status": self.sanitizer_status,
            "execution_authorized": False,
            "network_calls": False,
            "live_provider_calls": False,
            "read_only": True,
            "mutated": False,
            "operational_capability": False,
            "offline_demo_allowed": bool(self.offline_demo_allowed),
            "eligible_live_source": None,
            "no_supported_commercial_attention_source": True,
            "next_best_action": self.next_best_action,
            "fingerprint": self.fingerprint,
            "observed_at": self.observed_at,
            "requires_future_approval_or_credentials": [
                "Eligibility change on TikTok Research Tools FAQ (commercial users currently No)",
                "Approval Ledger provider_call approval before any future live transport",
                "Credential references only (never secret values) if a permitted surface ever exists",
                "Terms/privacy and output-contract review for that surface",
                "Do not invent approval booleans or a second credential system in this module",
            ],
            "canonical_dependency_gaps": [
                "no_eligible_tiktok_commercial_attention_api_under_current_official_terms",
                "live_secret_resolution_not_invoked_because_live_transport_absent",
                "approval_ledger_provider_call_remains_blocked_in_offline_ledger",
            ],
        }


def official_citations() -> tuple[dict[str, str], ...]:
    return (
        {
            "title": "Research Tools product page",
            "url": "https://developers.tiktok.com/products/research-api/",
            "access_date": DOC_RECHECK_DATE,
            "supports": (
                "Qualified researchers in the U.S., Europe, Canada, and Brazil; "
                "independent of commercial interests; Mexico not listed among applicant regions"
            ),
        },
        {
            "title": "Getting Started - Research API",
            "url": "https://developers.tiktok.com/doc/research-api-get-started",
            "access_date": DOC_RECHECK_DATE,
            "supports": "Research API query flow; approved research client; bearer token; video/account query examples",
        },
        {
            "title": "Research API FAQ (Research Tools)",
            "url": "https://developers.tiktok.com/doc/research-api-faq",
            "access_date": DOC_RECHECK_DATE,
            "supports": (
                "Research Tools FAQ: creator/advertiser/commercial user eligibility answer No.; "
                "approved research project required; country eligibility deferred to products page; "
                "quotas for approved research only"
            ),
        },
        {
            "title": "Query Videos (Research API)",
            "url": "https://developers.tiktok.com/doc/research-api-specs-query-videos",
            "access_date": DOC_RECHECK_DATE,
            "supports": (
                "region_code field enum includes MX as creator-account registration country; "
                "this is not documented MarketOS applicant eligibility or Mexico commercial coverage"
            ),
        },
        {
            "title": "Commercial Content API product page",
            "url": "https://developers.tiktok.com/products/commercial-content-api",
            "access_date": DOC_RECHECK_DATE,
            "supports": (
                "Public and researchers framing; ads data from EU to begin with; "
                "requester may be located in any country while data phase is EU-only; "
                "application + client key; distinct from Research API academic criteria text"
            ),
        },
        {
            "title": "Getting Started - Commercial Content API",
            "url": "https://developers.tiktok.com/doc/commercial-content-api-getting-started",
            "access_date": DOC_RECHECK_DATE,
            "supports": (
                "Research & Insights Commercial Content API path; approved research client + "
                "client key/secret; does not publish a separate commercial-eligibility FAQ"
            ),
        },
        {
            "title": "Commercial Content API Supported Countries",
            "url": "https://developers.tiktok.com/doc/commercial-content-api-supported-countries",
            "access_date": DOC_RECHECK_DATE,
            "supports": "Documented ad-data countries: EU, EEA, UK, CH; Mexico (MX) not listed",
        },
        {
            "title": "TikTok Developer Docs Overview",
            "url": "https://developers.tiktok.com/doc/overview",
            "access_date": DOC_RECHECK_DATE,
            "supports": "Research API and Commercial Content API under Research & Insights; Creative Center listed separately",
        },
        {
            "title": "Introduction to Creative Center",
            "url": "https://ads.tiktok.com/help/article/creative-center",
            "access_date": DOC_RECHECK_DATE,
            "supports": "Creative Center is a public website/inspiration hub; login optional for more features; not an official MarketOS research ingest API",
        },
        {
            "title": "TikTok API for Business (Marketing API portal)",
            "url": "https://business-api.tiktok.com/portal/docs",
            "access_date": DOC_RECHECK_DATE,
            "supports": "Advertiser-account Marketing API surface; own-account campaign/reporting, not market-wide competitor attention research",
        },
    )


def research_tool_capabilities() -> tuple[TikTokResearchCapability, ...]:
    """Capability matrix for evaluated TikTok surfaces (all non-operational today)."""
    specs = (
        (
            "research_api",
            "blocked_ineligible_commercial_use",
            (
                "requires_approved_research_project",
                "faq_commercial_creator_advertiser_users_not_eligible",
                "products_page_applicant_regions_us_europe_canada_brazil_not_mexico",
                "mx_in_video_region_code_enum_is_not_applicant_or_market_coverage",
                "live_transport_absent",
            ),
        ),
        (
            "commercial_content_api",
            "blocked_ineligible_commercial_use",
            (
                "products_page_public_and_researchers_eu_ads_phase",
                "getting_started_uses_approved_research_client",
                "no_dedicated_ccl_commercial_eligibility_faq_found",
                "do_not_assume_identical_research_api_eligibility_rule",
                "supported_countries_eu_eea_uk_ch_mexico_not_listed",
                "not_marketos_mexico_commercial_product_attention_source",
                "live_transport_absent",
            ),
        ),
        (
            "creative_center",
            "blocked_no_supported_commercial_attention_source",
            (
                "public_website_inspiration_hub",
                "website_visibility_is_not_scrape_permission",
                "no_official_readonly_ingest_contract_for_marketos",
            ),
        ),
        (
            "marketing_api",
            "blocked_no_supported_commercial_attention_source",
            (
                "advertiser_own_account_analytics_and_mutation_surface",
                "not_market_wide_competitor_or_public_attention_evidence",
                "must_not_be_labeled_as_demand_or_competitor_proof",
            ),
        ),
    )
    return tuple(
        TikTokResearchCapability(
            surface=surface,
            status=status,
            eligible_for_marketos_commercial_use=False,
            live_transport_implemented=False,
            notes=notes,
        )
        for surface, status, notes in specs
    )


def _reject_unsafe_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[list[Mapping[str, Any]], list[str]]:
    kept: list[Mapping[str, Any]] = []
    warnings: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            warnings.append(f"row_{index}_not_mapping")
            continue
        if contains_secret(row):
            warnings.append(f"row_{index}_rejected_secret_shaped")
            continue
        if contains_raw_payload(row):
            warnings.append(f"row_{index}_rejected_raw_payload")
            continue
        kept.append(row)
    return kept, warnings


def _normalize_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    default_source_type: str,
    mode: str,
) -> tuple[list[ConsumerAttentionEvidence], list[str]]:
    evidence: list[ConsumerAttentionEvidence] = []
    warnings: list[str] = []
    for index, row in enumerate(rows):
        item = normalize_record(
            row,
            default_platform="tiktok",
            default_source_type=default_source_type,
            mode=mode,
        )
        if item is None:
            warnings.append(f"row_{index}_normalize_rejected")
            continue
        # Refuse evidence-class promotion: creative/ad attention stays non-purchase / non-supplier.
        if item.platform != "tiktok":
            warnings.append(f"row_{index}_platform_not_tiktok")
            continue
        evidence.append(item)
    return evidence, warnings


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(repr(sorted(payload.items())).encode("utf-8")).hexdigest()[:24]


def build_tiktok_research_evidence(
    *,
    mode: str = "blocked_ineligible_commercial_use",
    fixture_path: str | Path | None = None,
    rows: Sequence[Mapping[str, Any]] | None = None,
    transport: TikTokResearchTransport | None = None,
    transport_request: Mapping[str, Any] | None = None,
    allow_live: bool = False,
    allow_offline_demo: bool = False,
    workspace_id: str = "offline-tiktok-research",
    observed_at: float | None = None,
) -> TikTokResearchEvidenceReport:
    """Build a TikTok research-evidence capability report.

    Ordinary runtime defaults to ``blocked_ineligible_commercial_use`` with
    zero evidence rows and ``operational_capability=false``. Fixture / manual /
    fake-transport paths require explicit ``allow_offline_demo=True`` and are
    never an operational live capability.
    """
    now = time.time() if observed_at is None else float(observed_at)
    surfaces = research_tool_capabilities()
    citations = official_citations()
    assumptions = (
        "tiktok_creative_or_ad_activity_is_not_purchase_intent",
        "tiktok_attention_is_not_supplier_proof",
        "tiktok_attention_is_not_product_fact",
        "aggregate_metrics_only_when_supplied",
        "unknown_fields_remain_unknown",
        "fixture_or_manual_evidence_is_not_live_validation",
        "offline_demo_is_not_operational_capability",
        "marketing_api_own_account_metrics_are_not_market_attention",
    )
    limitations = (
        "no_live_tiktok_provider_calls_in_this_module",
        "no_credentials_read",
        "no_unofficial_scrape_or_proxy",
        "research_tools_ineligible_for_marketos_commercial_use_per_official_faq",
        "ccl_eligibility_not_copied_from_research_api_without_primary_evidence",
        "mexico_not_documented_as_ccl_supported_ad_country",
        "no_supported_official_commercial_attention_source",
        "does_not_duplicate_generic_consumer_attention_importer_cli",
        "does_not_authorize_ad_creation_spend_messaging_or_publishing",
    )

    provider = evaluate_execution_request(
        ExecutionDecisionRequest(
            "tiktok-research-provider-pull",
            "run_provider_data_pull",
            "provider",
            "intelligence",
            workspace_id or "offline-tiktok-research",
            1,
            "data_provider_budget",
            provider_id="tiktok_research_tools",
            terms_privacy_complete=False,
            approval_state="not_requested",
        )
    )
    blockers = list(COMMERCIAL_INELIGIBILITY) + [f"provider_pull_outcome:{provider.outcome}"]

    def _blocked(
        *,
        status: str,
        evidence_mode: str,
        extra_blockers: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
        next_best_action: str,
        fingerprint_payload: Mapping[str, Any],
        offline_demo_allowed: bool = False,
    ) -> TikTokResearchEvidenceReport:
        return TikTokResearchEvidenceReport(
            report_version=REPORT_VERSION,
            source=SOURCE,
            capability_status=status,
            surfaces=surfaces,
            evidence_mode=evidence_mode,
            attention_report=None,
            evidence_count=0,
            blockers=tuple(blockers) + extra_blockers,
            warnings=warnings,
            assumptions=assumptions,
            limitations=limitations,
            official_citations=citations,
            next_best_action=next_best_action,
            fingerprint=_fingerprint(dict(fingerprint_payload)),
            observed_at=now,
            operational_capability=False,
            offline_demo_allowed=offline_demo_allowed,
            eligible_live_source=None,
            no_supported_commercial_attention_source=True,
        )

    if allow_live:
        return _blocked(
            status="blocked_live_mode",
            evidence_mode="blocked",
            extra_blockers=("live_mode_requested", "live_transport_not_implemented", "no_eligible_live_source"),
            warnings=("live_tiktok_commercial_attention_calls_are_disabled",),
            next_best_action="no_eligible_tiktok_commercial_attention_source_do_not_scrape_or_bypass_policy",
            fingerprint_payload={"mode": "blocked_live", "at": now},
        )

    if mode in {
        "not_configured",
        "blocked_ineligible_commercial_use",
        "blocked_no_supported_commercial_attention_source",
    }:
        status = mode
        return _blocked(
            status=status,
            evidence_mode=status,
            warnings=(
                "no_supported_official_tiktok_source_for_marketos_commercial_attention",
                "ordinary_runtime_returns_zero_evidence_rows",
            ),
            next_best_action="use_non_tiktok_attention_sources_or_generic_manual_importer_not_research_tools_live",
            fingerprint_payload={"mode": status, "at": now},
        )

    if mode in OFFLINE_DEMO_MODES and not allow_offline_demo:
        return _blocked(
            status="blocked_offline_demo_disabled",
            evidence_mode="blocked",
            extra_blockers=("offline_demo_not_enabled", "fixture_rows_are_not_operational_capability"),
            warnings=("offline_demo_requires_explicit_allow_offline_demo",),
            next_best_action="keep_blocked_or_pass_allow_offline_demo_only_for_explicit_tests",
            fingerprint_payload={"mode": mode, "demo": False, "at": now},
        )

    warnings: list[str] = []
    evidence_mode = mode
    source_type = "tiktok_creative_center_snapshot"
    normalize_mode = "fixture"

    if mode == "manual_import":
        source_type = "tiktok_ad_snapshot"
        normalize_mode = "manual_import"
    elif mode == "fixture_demo":
        source_type = "tiktok_creative_center_snapshot"
        normalize_mode = "fixture"
    elif mode == "fake_transport":
        source_type = "tiktok_creative_center_snapshot"
        normalize_mode = "fixture"
    else:
        return TikTokResearchEvidenceReport(
            report_version=REPORT_VERSION,
            source=SOURCE,
            capability_status="malformed_input",
            surfaces=surfaces,
            evidence_mode="malformed",
            attention_report=None,
            evidence_count=0,
            blockers=tuple(blockers) + ("unsupported_mode",),
            warnings=("unsupported_mode",),
            assumptions=assumptions,
            limitations=limitations,
            official_citations=citations,
            next_best_action="use_not_configured_fixture_demo_manual_import_or_fake_transport",
            fingerprint=_fingerprint({"mode": mode, "at": now}),
            observed_at=now,
        )

    collected_rows: list[Mapping[str, Any]] = []
    capability_status = mode

    if transport is not None:
        response = transport.fetch(dict(transport_request or {"surface": "research_api", "dry_run": True}))
        http_status = response.get("http_status")
        body = response.get("body") if isinstance(response.get("body"), Mapping) else {}
        if http_status == 200 and isinstance(body, Mapping) and isinstance(body.get("data"), list):
            collected_rows = [item for item in body["data"] if isinstance(item, Mapping)]
            capability_status = "fake_transport_ok"
            warnings.append("fake_transport_used_not_live")
        else:
            return TikTokResearchEvidenceReport(
                report_version=REPORT_VERSION,
                source=SOURCE,
                capability_status="fake_transport_error",
                surfaces=surfaces,
                evidence_mode="fake_transport",
                attention_report=None,
                evidence_count=0,
                blockers=tuple(blockers) + ("fake_transport_non_success", f"http_status:{http_status}"),
                warnings=("fake_transport_failed",),
                assumptions=assumptions,
                limitations=limitations,
                official_citations=citations,
                next_best_action="inspect_fake_transport_fixture_or_remain_blocked",
                fingerprint=_fingerprint({"mode": "fake_error", "status": http_status, "at": now}),
                observed_at=now,
            )
    elif rows is not None:
        collected_rows = [item for item in rows if isinstance(item, Mapping)]
    elif fixture_path is not None:
        try:
            path = validate_input_path(fixture_path)
            imported = import_json(path, platform="tiktok", source_type=source_type)
            # import_json already returns ConsumerAttentionEvidence; rebuild via dicts for one path.
            # Prefer raw JSON rows so secret/raw checks run again explicitly in this layer.
            import json

            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                collected_rows = [item for item in raw if isinstance(item, Mapping)]
            elif isinstance(raw, Mapping) and isinstance(raw.get("data"), list):
                collected_rows = [item for item in raw["data"] if isinstance(item, Mapping)]
            else:
                collected_rows = []
            if not collected_rows and imported:
                # Fall back: serialize already-normalized evidence is not raw; keep empty and warn.
                warnings.append("fixture_normalized_via_importer_without_raw_rows")
                evidence = list(imported)
                attention = build_report(evidence, evidence_mode=evidence_mode).to_dict()
                return TikTokResearchEvidenceReport(
                    report_version=REPORT_VERSION,
                    source=SOURCE,
                    capability_status="partial" if warnings else mode,
                    surfaces=surfaces,
                    evidence_mode=evidence_mode,
                    attention_report=attention,
                    evidence_count=len(evidence),
                    blockers=tuple(blockers),
                    warnings=tuple(dict.fromkeys(warnings + ["research_tools_still_blocked_for_live"])),
                    assumptions=assumptions + ("fixture_not_live_research_api_observation",),
                    limitations=limitations,
                    official_citations=citations,
                    next_best_action=str(attention.get("next_best_action") or "review_tiktok_attention_offline"),
                    fingerprint=_fingerprint({"mode": mode, "count": len(evidence), "at": now}),
                    observed_at=now,
                    offline_demo_allowed=True,
                )
        except (ConsumerAttentionImportError, OSError, ValueError) as exc:
            return TikTokResearchEvidenceReport(
                report_version=REPORT_VERSION,
                source=SOURCE,
                capability_status="malformed_input",
                surfaces=surfaces,
                evidence_mode="malformed",
                attention_report=None,
                evidence_count=0,
                blockers=tuple(blockers) + (f"fixture_error:{type(exc).__name__}",),
                warnings=("fixture_load_failed",),
                assumptions=assumptions,
                limitations=limitations,
                official_citations=citations,
                next_best_action="repair_sanitized_fixture_path",
                fingerprint=_fingerprint({"mode": "malformed", "at": now}),
                observed_at=now,
            )
    else:
        return TikTokResearchEvidenceReport(
            report_version=REPORT_VERSION,
            source=SOURCE,
            capability_status="not_configured",
            surfaces=surfaces,
            evidence_mode="not_configured",
            attention_report=None,
            evidence_count=0,
            blockers=tuple(blockers) + ("no_fixture_rows_or_transport",),
            warnings=("no_offline_evidence_supplied",),
            assumptions=assumptions,
            limitations=limitations,
            official_citations=citations,
            next_best_action="supply_sanitized_tiktok_fixture_or_manual_snapshot",
            fingerprint=_fingerprint({"mode": "empty", "at": now}),
            observed_at=now,
        )

    safe_rows, reject_warnings = _reject_unsafe_rows(collected_rows)
    warnings.extend(reject_warnings)
    evidence, normalize_warnings = _normalize_rows(safe_rows, default_source_type=source_type, mode=normalize_mode)
    warnings.extend(normalize_warnings)

    if not evidence:
        return TikTokResearchEvidenceReport(
            report_version=REPORT_VERSION,
            source=SOURCE,
            capability_status="malformed_input" if collected_rows else "not_configured",
            surfaces=surfaces,
            evidence_mode=evidence_mode,
            attention_report=None,
            evidence_count=0,
            blockers=tuple(blockers) + (("no_usable_tiktok_attention_rows",) if collected_rows else ()),
            warnings=tuple(dict.fromkeys(warnings + ["missing_evidence_not_treated_as_positive"])),
            assumptions=assumptions,
            limitations=limitations,
            official_citations=citations,
            next_best_action="supply_aggregate_only_sanitized_tiktok_rows",
            fingerprint=_fingerprint({"mode": mode, "count": 0, "at": now}),
            observed_at=now,
        )

    attention = build_report(evidence, evidence_mode=evidence_mode).to_dict()
    # Guard: never promote to purchase/supplier classes via this layer.
    if attention.get("network_calls") or attention.get("mutated"):
        warnings.append("attention_report_unexpected_side_effect_flags")

    if reject_warnings or normalize_warnings:
        capability_status = "partial"

    return TikTokResearchEvidenceReport(
        report_version=REPORT_VERSION,
        source=SOURCE,
        capability_status=capability_status,
        surfaces=surfaces,
        evidence_mode=evidence_mode,
        attention_report=attention,
        evidence_count=len(evidence),
        blockers=tuple(blockers),
        warnings=tuple(dict.fromkeys(warnings + ["research_tools_live_path_remains_blocked"])),
        assumptions=assumptions + ("fixture_or_fake_transport_not_authenticated_observation",),
        limitations=limitations,
        official_citations=citations,
        next_best_action=str(attention.get("next_best_action") or "review_tiktok_attention_offline"),
        fingerprint=_fingerprint({"mode": capability_status, "count": len(evidence), "at": now}),
        observed_at=now,
        offline_demo_allowed=True,
    )


def render_markdown(report: TikTokResearchEvidenceReport | Mapping[str, Any]) -> str:
    data = report.to_dict() if isinstance(report, TikTokResearchEvidenceReport) else dict(report)
    lines = [
        "# TikTok Research Evidence (official Research Tools contract)",
        "",
        f"Report version: `{data.get('report_version')}`",
        f"Capability status: `{data.get('capability_status')}`",
        f"Evidence mode: `{data.get('evidence_mode')}`",
        f"Client visibility: `{data.get('client_visibility')}`",
        f"Execution authorized: `{bool(data.get('execution_authorized'))}`",
        f"Live provider calls: `{bool(data.get('live_provider_calls'))}`",
        f"Evidence rows: {data.get('evidence_count', 0)}",
        f"Next action: {_text(data.get('next_best_action'), 240)}",
        "",
        "## Surfaces",
        "",
        "| Surface | Status | Commercial eligible | Live transport |",
        "| --- | --- | --- | --- |",
    ]
    for surface in data.get("surfaces") or []:
        lines.append(
            f"| {surface.get('surface')} | `{surface.get('status')}` | "
            f"{surface.get('eligible_for_marketos_commercial_use')} | "
            f"{surface.get('live_transport_implemented')} |"
        )
    lines += ["", "## Blockers", ""]
    lines.extend(f"- {item}" for item in data.get("blockers") or [])
    lines += ["", "## Citations", ""]
    for cite in data.get("official_citations") or []:
        lines.append(f"- [{cite.get('title')}]({cite.get('url')}) (accessed {cite.get('access_date')})")
    lines += [
        "",
        "Ad/creative attention is not purchase intent, sales, supplier proof, or product fact. "
        "No ad creation, spend, messaging, or publishing authority.",
        "",
    ]
    return "\n".join(lines)


def _text(value: Any, limit: int = 160) -> str:
    return str(value or "").strip()[:limit]


__all__ = [
    "REPORT_VERSION",
    "ACCESS_DATE",
    "DOC_RECHECK_DATE",
    "EVALUATED_SURFACES",
    "OFFLINE_DEMO_MODES",
    "RESEARCH_TOOL_SURFACES",
    "FakeTikTokResearchTransport",
    "TikTokResearchCapability",
    "TikTokResearchEvidenceReport",
    "build_tiktok_research_evidence",
    "official_citations",
    "research_tool_capabilities",
    "render_markdown",
]

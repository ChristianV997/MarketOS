"""evaluation.commerce.serpapi_commerce_projection -- a thin, deterministic,
offline downstream consumer of the existing SerpApi runtime adapter
(backend.adapters.research.serpapi).

This module does not call SerpApi, does not read credentials, and does not
duplicate the adapter's own parsing/normalization logic. It only reshapes
the adapter's already-normalized, already-sanitized evidence into a
commerce-facing projection report -- read-only, fixture/dry-run only.

Deliberate non-goals, matching this repository's own established pillar
boundaries:

- This is **not** a fourth Product Opportunity Synthesis pillar.
  `evaluation.commerce.opportunity_synthesis` fuses exactly three offline
  evidence pillars (marketplace, supplier, consumer); this module is not
  wired into it and does not add a parameter there.
- This does **not** convert SERP titles into Consumer Attention evidence.
  `evaluation.commerce.consumer_attention`'s evidence model is untouched
  and unimported here.
- This does **not** infer a marketplace identity (Amazon, eBay, ...) from
  generic Google-Shopping-shaped SerpApi results. A `MarketplaceTrendEvidence`
  projection (`evaluation.commerce.marketplace_trends`, an existing,
  unmodified module) is only ever constructed when the **caller** names a
  marketplace explicitly, and only when that name is a member of that
  module's own existing `SUPPORTED` set. No SerpApi field is inspected to
  guess a marketplace name.
- SerpApi and DataForSEO remain independent, non-summed evidence sources.
  This module never imports `backend.adapters.research.dataforseo` or
  `evaluation.commerce.dataforseo_adapter` -- there is no code path here
  that could combine or double-count the two.

Safety, by construction:

- The adapter is always invoked with a `SidecarContext(dry_run=True)`
  constructed internally -- this module exposes no way to request a live
  call. `backend.adapters.research.serpapi.fetch_search_evidence` remains
  the sole owner of live/dry-run behavior; nothing here duplicates or
  overrides it.
- Any adapter status other than `"dry_run_ready"` (i.e. `"error"`,
  `"blocked"`, `"blocked_live_mode"`) yields zero projected records --
  the adapter's own blockers/warnings are passed through unchanged, never
  reinterpreted as a partial success.
- A caller-supplied `fixture_payload` is scanned for secret-shaped content
  by this module's own guard *before* it ever reaches the adapter --
  defense in depth on top of the adapter's own equivalent guard.
- `query` length is bounded; an oversized query is rejected rather than
  passed through unbounded.
- Every projected record carries `fixture_identity_label` (always
  `"synthetic_fixture_example"` in this release -- no live search proof
  exists) and `evidence_tier="supplemental_non_live"`.
- No network, credential, model, provider, SDK, or plugin call occurs
  anywhere in this file. No artifact is written unless the caller
  explicitly asks the CLI for one via `--output`.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from backend.adapters.research.serpapi import SOURCE as SERPAPI_SOURCE, fetch_search_evidence
from backend.contracts.adapters import SidecarContext
from evaluation.commerce.marketplace_trends import SUPPORTED as SUPPORTED_MARKETPLACES

REPORT_VERSION = "serpapi-commerce-projection-v1"
FIXTURE_IDENTITY_LABEL = "synthetic_fixture_example"
EVIDENCE_TIER = "supplemental_non_live"
MAX_QUERY_LENGTH = 200

_SECRET_KEY_NAMES = frozenset({
    "api_key", "apikey", "access_token", "authorization", "auth_token",
    "password", "private_key", "secret", "secret_key", "token", "credential",
    "cookie", "cookies", "raw_payload", "raw_html", "html", "body",
    "response_body", "javascript",
})
_SECRET_SHAPED_VALUE = re.compile(
    r"(?is)("
    r"-----begin (?:rsa |ec |dsa |openssh )?private key-----"
    r"|ghp_[A-Za-z0-9_]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-(?:live|test)?-?[A-Za-z0-9]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|bearer [A-Za-z0-9._-]{10,}"
    r"|<html\b"
    r"|<script\b"
    r")"
)


def _secret_like(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(str(key).lower().replace("-", "_") in _SECRET_KEY_NAMES or _secret_like(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_secret_like(item) for item in value)
    if isinstance(value, str):
        return bool(_SECRET_SHAPED_VALUE.search(value))
    return False


@dataclass(frozen=True)
class SerpApiCommerceProjectionRecord:
    """One projected view of a single SerpApi normalized record. Never
    carries a raw provider payload -- only the whitelisted fields the
    adapter itself already normalized."""

    candidate_id: str
    query: str
    title: str
    fixture_identity_label: str
    evidence_tier: str
    source_provider: str
    marketplace: str | None
    marketplace_evidence: dict[str, Any] | None
    normalized_fields: dict[str, Any]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "query": self.query,
            "title": self.title,
            "fixture_identity_label": self.fixture_identity_label,
            "evidence_tier": self.evidence_tier,
            "source_provider": self.source_provider,
            "marketplace": self.marketplace,
            "marketplace_evidence": self.marketplace_evidence,
            "normalized_fields": self.normalized_fields,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class SerpApiCommerceProjectionSafetySummary:
    read_only: bool
    network_calls: bool
    credentials_loaded: bool
    provider_calls: bool
    sdk_used: bool
    raw_payload_stored: bool
    raw_html_stored: bool
    external_actions: bool
    launch_authority: bool
    fail_closed: bool

    def __post_init__(self) -> None:
        if not self.read_only or not self.fail_closed:
            raise ValueError("projection safety summary must be read_only and fail_closed")
        if any((
            self.network_calls, self.credentials_loaded, self.provider_calls, self.sdk_used,
            self.raw_payload_stored, self.raw_html_stored, self.external_actions, self.launch_authority,
        )):
            raise ValueError("projection must not report any live/mutating/launch behavior")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _default_safety_summary() -> SerpApiCommerceProjectionSafetySummary:
    return SerpApiCommerceProjectionSafetySummary(
        read_only=True, network_calls=False, credentials_loaded=False, provider_calls=False,
        sdk_used=False, raw_payload_stored=False, raw_html_stored=False, external_actions=False,
        launch_authority=False, fail_closed=True,
    )


@dataclass(frozen=True)
class SerpApiCommerceProjectionReport:
    report_version: str
    generated_at: str
    query: str
    adapter_source: str
    adapter_status: str
    adapter_readiness_state: str
    adapter_blockers: tuple[str, ...]
    marketplace_requested: str | None
    marketplace_projection_applied: bool
    records: tuple[SerpApiCommerceProjectionRecord, ...]
    record_count: int
    warnings: tuple[str, ...]
    safety_summary: SerpApiCommerceProjectionSafetySummary
    non_double_counting_note: str
    next_best_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "generated_at": self.generated_at,
            "query": self.query,
            "adapter_source": self.adapter_source,
            "adapter_status": self.adapter_status,
            "adapter_readiness_state": self.adapter_readiness_state,
            "adapter_blockers": list(self.adapter_blockers),
            "marketplace_requested": self.marketplace_requested,
            "marketplace_projection_applied": self.marketplace_projection_applied,
            "records": [item.to_dict() for item in self.records],
            "record_count": self.record_count,
            "warnings": list(self.warnings),
            "safety_summary": self.safety_summary.to_dict(),
            "non_double_counting_note": self.non_double_counting_note,
            "next_best_action": self.next_best_action,
        }

    def to_markdown(self) -> str:
        lines = [
            "# SerpApi Commerce Projection", "", "## Executive Summary", "",
            f"- Query: **{self.query}**", f"- Adapter status: **{self.adapter_status}**",
            f"- Readiness: **{self.adapter_readiness_state}**", f"- Records projected: **{self.record_count}**",
            f"- Marketplace requested: **{self.marketplace_requested or 'none'}**",
            f"- Marketplace projection applied: **{self.marketplace_projection_applied}**", "",
            "## Records", "", "| Candidate | Title | Marketplace |", "|---|---|---|",
        ]
        lines.extend(f"| {r.candidate_id} | {r.title} | {r.marketplace or '-'} |" for r in self.records)
        lines += ["", "## Adapter Blockers", ""]
        lines.extend(f"- {item}" for item in self.adapter_blockers)
        lines += ["", "## Non-Double-Counting Note", "", self.non_double_counting_note, ""]
        lines += ["## Next Best Action", "", self.next_best_action, ""]
        lines += ["## Safety Boundaries", "", "No credentials, network calls, SDKs, provider calls, raw payloads, raw HTML, or launch/advertising/publishing/ordering/payment authority occur in this module.", ""]
        return "\n".join(lines)


def _validate_marketplace(marketplace: str | None) -> str | None:
    """Never guess. A marketplace projection is only ever attempted when
    the caller names one explicitly, and only when it is a member of
    `evaluation.commerce.marketplace_trends`'s own existing SUPPORTED set
    -- reused, not duplicated."""
    if not marketplace:
        return None
    normalized = marketplace.strip().lower()
    return normalized if normalized in SUPPORTED_MARKETPLACES else None


def _project_marketplace_evidence(record: Mapping[str, Any], *, marketplace: str, query: str) -> dict[str, Any] | None:
    """Build a MarketplaceTrendEvidence dict from a normalized SerpApi
    record, reusing the existing dataclass and its own validation --
    never a new marketplace evidence shape. `source_type="fixture_demo"`
    is used deliberately: this is fixture/dry-run SerpApi data, never a
    live retailer snapshot, and "fixture_demo" is the one existing
    SOURCE_TYPES value that says so honestly without fabricating a new
    SerpApi-specific source type in a module this PR does not modify."""
    from evaluation.commerce.marketplace_trends import MarketplaceTrendEvidence

    try:
        evidence = MarketplaceTrendEvidence(
            candidate_id=str(record.get("candidate_id", "unknown")),
            query=query,
            marketplace=marketplace,
            source_type="fixture_demo",
            rank_position=record.get("rank"),
            price=record.get("price"),
            currency=str(record.get("currency", "USD")),
            review_count=record.get("review_count"),
            rating=record.get("rating"),
            trend_label=str(record.get("trend_label", "")),
            evidence_mode="fixture",
            source_confidence=0.0,
            warnings=("synthetic SerpApi fixture; not a live marketplace snapshot",),
        )
    except (ValueError, TypeError):
        return None
    return evidence.to_dict()


def _project_record(record: Mapping[str, Any], *, marketplace: str | None, query: str) -> SerpApiCommerceProjectionRecord:
    fields = dict(record.get("normalized_fields", {}))
    marketplace_evidence = _project_marketplace_evidence(fields, marketplace=marketplace, query=query) if marketplace else None
    return SerpApiCommerceProjectionRecord(
        candidate_id=str(fields.get("candidate_id", "unknown")),
        query=str(fields.get("query", query)),
        title=str(fields.get("title", "")),
        fixture_identity_label=FIXTURE_IDENTITY_LABEL,
        evidence_tier=EVIDENCE_TIER,
        source_provider="serpapi",
        marketplace=marketplace,
        marketplace_evidence=marketplace_evidence,
        normalized_fields=fields,
        limitations=tuple(record.get("limitations", ())),
    )


def build_serpapi_commerce_projection(
    *,
    query: str = "portable espresso maker",
    fixture_payload: Mapping[str, Any] | None = None,
    marketplace: str | None = None,
    generated_at: str = "offline-deterministic",
) -> SerpApiCommerceProjectionReport:
    """Never executes a live SerpApi call -- `fetch_search_evidence` is
    always invoked with a `SidecarContext(dry_run=True)` constructed
    internally. Rejects an oversized query and a secret-shaped
    `fixture_payload` before either ever reaches the adapter.

    `generated_at` defaults to the deterministic sentinel string this
    repository's other offline harnesses already use (e.g.
    `build_dataforseo_adapter_report`, `build_intelligence_adapter_plan`)
    -- never a real wall-clock timestamp, so two calls with identical
    inputs always produce byte-identical output."""
    clean_query = (query or "").strip()
    if len(clean_query) > MAX_QUERY_LENGTH:
        raise ValueError(f"query exceeds the {MAX_QUERY_LENGTH}-character bound")
    if not clean_query:
        clean_query = "unspecified query"

    if fixture_payload is not None and _secret_like(fixture_payload):
        raise ValueError("secret-like or raw fixture_payload is not accepted")

    validated_marketplace = _validate_marketplace(marketplace)
    context = SidecarContext(workspace_id="serpapi-commerce-projection", run_id="offline-deterministic", dry_run=True)
    evidence = fetch_search_evidence(clean_query, context=context, payload=dict(fixture_payload) if fixture_payload is not None else None)
    evidence_dict = evidence.to_dict()

    records: tuple[SerpApiCommerceProjectionRecord, ...] = ()
    if evidence_dict.get("status") == "dry_run_ready":
        raw_records = evidence_dict.get("report", {}).get("records", [])
        records = tuple(
            _project_record(item, marketplace=validated_marketplace, query=clean_query)
            for item in raw_records if isinstance(item, Mapping)
        )

    marketplace_applied = bool(validated_marketplace) and any(item.marketplace_evidence for item in records)
    non_double_counting_note = (
        "SerpApi and DataForSEO are consolidation-choice alternatives for the same "
        "search_serp_data capability (see evaluation/companyos/subscription_registry.py's "
        "own consolidate-search recommendation), not independent confirmations. This "
        "projection consumes only SerpApi evidence and does not import or combine "
        "DataForSEO evidence anywhere."
    )
    next_best_action = (
        "Review this projection alongside, not summed with, any DataForSEO projection "
        "for the same query before choosing one search provider after a bounded benchmark."
    )
    return SerpApiCommerceProjectionReport(
        report_version=REPORT_VERSION,
        generated_at=generated_at,
        query=clean_query,
        adapter_source=SERPAPI_SOURCE,
        adapter_status=evidence_dict.get("status", "unknown"),
        adapter_readiness_state=evidence_dict.get("readiness_state", "unknown"),
        adapter_blockers=tuple(evidence_dict.get("blockers", ())),
        marketplace_requested=marketplace,
        marketplace_projection_applied=marketplace_applied,
        records=records,
        record_count=len(records),
        warnings=tuple(evidence_dict.get("warnings", ())),
        safety_summary=_default_safety_summary(),
        non_double_counting_note=non_double_counting_note,
        next_best_action=next_best_action,
    )


__all__ = [
    "REPORT_VERSION",
    "FIXTURE_IDENTITY_LABEL",
    "EVIDENCE_TIER",
    "MAX_QUERY_LENGTH",
    "SerpApiCommerceProjectionRecord",
    "SerpApiCommerceProjectionSafetySummary",
    "SerpApiCommerceProjectionReport",
    "build_serpapi_commerce_projection",
]

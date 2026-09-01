"""backend.adapters.research.serpapi -- thin runtime bridge from the
existing generic Intelligence Adapter Plan
(evaluation.commerce.intelligence_adapter_plan) into MarketOS's Product
Research seam, for the "serpapi" provider entry specifically.

Unlike DataForSEO (which has its own dedicated offline module,
evaluation.commerce.dataforseo_adapter, and its own runtime bridge,
backend.adapters.research.dataforseo), SerpApi's offline plan already
lives entirely inside the generic, provider-agnostic
evaluation.commerce.intelligence_adapter_plan module: its own
`_PROVIDER_SPECS` entry, `build_intelligence_adapter_plan()`, and
`parse_dry_run_fixture()`. This file delegates to that existing generic
machinery rather than building a second, SerpApi-specific offline parser
module -- adding one would duplicate a capability the generic module
already provides. No new provider registry, adapter framework, or parser
is introduced here.

This module has no verified knowledge of SerpApi's actual API surface --
`evaluation.commerce.intelligence_adapter_plan`'s own SerpApi request-plan
parameters (endpoint_placeholder="search.json",
engine_placeholder="google_shopping") are explicitly documented there as
planning placeholders, not a confirmed live contract, and nothing here
changes that.

Two bounded request kinds are supported (`REQUEST_KINDS`):
`"organic_search_snapshot"` (default -- organic SERP/keyword-demand,
`SearchDemandEvidence`, its own sanitized fixture added by this PR) and
`"shopping_snapshot"` (optional secondary -- competitor pricing,
`CompetitorPricingEvidence`, the one fixture that already existed before
this PR). Each maps to its own sanitized fixture and evidence category;
neither is a new parser or evidence type -- both are parsed by the same
existing `parse_dry_run_fixture()`.

Provider Registry membership is checked explicitly via
`evaluation.companyos.provider_registry.build_provider_registry()` --
`evaluation.commerce.intelligence_adapter_plan` itself imports that
function but never calls it (a pre-existing gap in that shared module,
out of this file's scope to fix); this adapter does not silently assume
registration.

SerpApi and DataForSEO are **consolidation-choice alternatives for the
same search_serp_data capability, not two independent confirmations**
(see `evaluation/companyos/subscription_registry.py`'s own
"consolidate-search" recommendation: "choose one search provider after a
bounded benchmark"). A caller attaching both
`to_additional_evidence()`/`signals_to_additional_evidence()` results to
the same `ResearchCandidate` must not sum, average, or otherwise treat
them as independent corroborating signals -- they are two candidate
sources for one data need, evaluated so one can eventually be selected.

Safety, by construction (mirrors backend.adapters.research.dataforseo):

- `mode="plan_only"` is the default via `SidecarContext.dry_run=True`;
  constructing configuration and importing this module never execute
  anything.
- A `context.dry_run=False` (live) request never reaches the offline
  plan/parser -- it returns a structured `blocked_live_mode` result
  naming every unmet prerequisite.
- No network, credential, model, provider, SDK, or plugin call occurs
  anywhere in this file.
- Any unexpected failure from the offline plan/parser is caught and
  converted to a safe, generic `status="error"` result -- the raw
  exception message is never included in the returned evidence.
- Every result is explicitly labelled `evidence_tier="supplemental_non_live"`
  and carries `retry_attempts_allowed=0` (no live transport exists, so no
  retry logic exists either -- an explicit, testable zero).
- Output attaches to
  `backend.mvp_commerce.product_research.ResearchCandidate
  .additional_evidence` via `to_additional_evidence()`/
  `signals_to_additional_evidence()`, the existing, documented extension
  point -- nothing here constructs a `ResearchCandidate` directly.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.contracts.adapters import AdapterHealth, SidecarContext
from evaluation.commerce.intelligence_adapter_plan import (
    IntelligenceAdapterPlanReport,
    NormalizedEvidenceRecord,
    build_intelligence_adapter_plan,
    parse_dry_run_fixture,
)
from evaluation.companyos.provider_registry import build_provider_registry

_log = logging.getLogger(__name__)

SOURCE = "serpapi_readonly_search"
PROVIDER_ID = "serpapi"

# Two bounded request kinds, matching the mission split: organic SERP/
# keyword-demand snapshots are the primary, required capability;
# shopping/competitor-pricing snapshots are the optional secondary one
# (the only fixture that existed before this PR). Naming mirrors
# backend.adapters.research.dataforseo's request_kind concept.
REQUEST_KINDS = ("organic_search_snapshot", "shopping_snapshot")
DEFAULT_REQUEST_KIND = "organic_search_snapshot"

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURES_DIR = _REPO_ROOT / "tests/fixtures/intelligence_adapter_plan"
_REQUEST_KIND_TO_EVIDENCE_CATEGORY = {
    "organic_search_snapshot": "SearchDemandEvidence",
    "shopping_snapshot": "CompetitorPricingEvidence",
}
_REQUEST_KIND_TO_FIXTURE_PATH = {
    "organic_search_snapshot": _FIXTURES_DIR / "serpapi_organic_snapshot_dry_run.json",
    "shopping_snapshot": _FIXTURES_DIR / "serpapi_shopping_snapshot_dry_run.json",
}
DEFAULT_EVIDENCE_CATEGORY = _REQUEST_KIND_TO_EVIDENCE_CATEGORY[DEFAULT_REQUEST_KIND]

# No live transport exists in this release, so no retry logic exists either
# -- this is an explicit, testable zero, not merely an absence. A future
# transport PR must define and justify any non-zero value.
MAX_RETRY_ATTEMPTS = 0

# Every result from this module is offline/fixture-sourced and must never be
# mistaken for a live-validated signal.
EVIDENCE_TIER = "supplemental_non_live"

_LIVE_PREREQUISITES = (
    "approved Approval Ledger request (provider_call + web_data_acquisition)",
    "credential reference configured (credential-serpapi, secret value absent)",
    "monthly/per-run budget cap approved",
    "terms review complete",
    "privacy review complete",
    "output contract tests passing",
    "timeout/retry policy defined for a real transport",
    "workspace and client-isolation checks passed",
    "a separately reviewed live transport implementation",
)


@dataclass(frozen=True)
class SerpApiSearchEvidence:
    """One SerpApi offline evidence observation -- always fixture/dry-run
    sourced in this release. Field shape mirrors
    `backend.adapters.research.dataforseo.DataForSEOSearchEvidence` so
    mvp_commerce callers can treat every research-adapter evidence type
    consistently."""

    source: str
    provider_id: str
    request_kind: str
    evidence_category: str
    observed_at: float
    query: str
    status: str
    readiness_state: str
    provider_registered: bool
    blockers: tuple[str, ...]
    signal_count: int
    confidence: str
    warnings: tuple[str, ...]
    report: dict[str, Any] = dataclass_field(default_factory=dict)
    evidence_tier: str = EVIDENCE_TIER
    retry_attempts_allowed: int = MAX_RETRY_ATTEMPTS

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "provider_id": self.provider_id,
            "request_kind": self.request_kind,
            "evidence_category": self.evidence_category,
            "observed_at": self.observed_at,
            "query": self.query,
            "status": self.status,
            "readiness_state": self.readiness_state,
            "provider_registered": self.provider_registered,
            "blockers": list(self.blockers),
            "signal_count": self.signal_count,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
            "report": self.report,
            "evidence_tier": self.evidence_tier,
            "retry_attempts_allowed": self.retry_attempts_allowed,
        }


def _is_provider_registered() -> bool:
    """Check Provider Registry membership without reading any credential
    or secret -- evaluation.commerce.intelligence_adapter_plan imports
    build_provider_registry but never actually calls it (a pre-existing
    gap in that shared module, out of this adapter's file scope to fix);
    this adapter checks registration itself instead of silently assuming
    it.

    Fails closed: if the registry lookup itself fails unexpectedly, this
    returns False (not registered) rather than propagating the raw
    exception or assuming registration -- the caller sees a `blocked`
    result with `provider_not_registered`, never a crash."""
    try:
        registry = build_provider_registry()
        return any(item.provider_id == PROVIDER_ID for item in registry.providers)
    except Exception:
        _log.warning("serpapi_provider_registry_check_failed")
        return False


def _slugify(query: str) -> str:
    return "-".join((query or "").lower().split()) or "unknown-query"


def _blocked_live_result(query: str, *, request_kind: str, evidence_category: str, provider_registered: bool) -> SerpApiSearchEvidence:
    """Structured, honest 'blocked' result for a requested live call --
    never an exception, never a silent no-op; every missing prerequisite
    is named explicitly."""
    return SerpApiSearchEvidence(
        source=SOURCE,
        provider_id=PROVIDER_ID,
        request_kind=request_kind,
        evidence_category=evidence_category,
        observed_at=time.time(),
        query=query,
        status="blocked_live_mode",
        readiness_state="blocked",
        provider_registered=provider_registered,
        blockers=("live_mode_requested",) + _LIVE_PREREQUISITES,
        signal_count=0,
        confidence="none",
        warnings=("SerpApi live transport is not implemented in this release.",),
        report={},
    )


def _default_fixture_payload(query: str, *, request_kind: str) -> dict[str, Any]:
    """Load the bundled sanitized fixture for this request kind and
    substitute the caller's own query into its records.

    Regression fix: overlaying only `query` while leaving `candidate_id`
    and `title` at the fixture's own hardcoded example (e.g.
    candidate_id="neck-massager") produced a self-contradictory record --
    a caller querying "portable espresso maker" would see
    candidate_id="neck-massager" beside query="portable espresso maker",
    misrepresenting an unrelated candidate as if it were that query's
    result. `candidate_id` and `title` are now both derived from the
    same query, mirroring
    `evaluation.commerce.dataforseo_adapter._default_payload`'s existing
    precedent (candidate_id/title are both keyword-derived there too) --
    every other sanitized field (rank, trend_label, price, currency,
    review_count, rating) stays exactly as the fixture defines it."""
    fixture_path = _REQUEST_KIND_TO_FIXTURE_PATH[request_kind]
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    records = raw.get("records", [])
    candidate_id = _slugify(query)
    patched = []
    for item in records:
        if not isinstance(item, Mapping):
            continue
        base_title = str(item.get("title", "Synthetic result"))
        patched.append({**item, "candidate_id": candidate_id, "query": query, "title": f"{base_title} for {query}"})
    return {**raw, "records": patched}


def fetch_search_evidence(
    query: str,
    *,
    context: SidecarContext,
    request_kind: str = DEFAULT_REQUEST_KIND,
    payload: Mapping[str, Any] | None = None,
) -> SerpApiSearchEvidence:
    """Fail-closed bridge into the existing generic Intelligence Adapter
    Plan for the `serpapi` provider entry.

    `request_kind="organic_search_snapshot"` (default) is the bounded,
    required organic SERP/keyword-demand path;
    `request_kind="shopping_snapshot"` is the optional secondary
    competitor-pricing path, reusing the one fixture that existed before
    this PR.

    `context.dry_run=False` (a live request) never reaches the offline
    plan/parser -- it always returns a structured blocked result naming
    every unmet prerequisite. Any unexpected failure from the offline
    module is caught and converted to a safe, generic degraded result;
    the raw exception message is never included in the returned evidence.
    """
    kind = request_kind if request_kind in REQUEST_KINDS else DEFAULT_REQUEST_KIND
    category = _REQUEST_KIND_TO_EVIDENCE_CATEGORY[kind]
    provider_registered = _is_provider_registered()

    if not context.dry_run:
        return _blocked_live_result(query, request_kind=kind, evidence_category=category, provider_registered=provider_registered)

    try:
        plan: IntelligenceAdapterPlanReport = build_intelligence_adapter_plan(provider=PROVIDER_ID)
        contract = plan.contracts[0]
        readiness = contract.activation_readiness
        fixture_payload = dict(payload) if payload is not None else _default_fixture_payload(query, request_kind=kind)
        records: tuple[NormalizedEvidenceRecord, ...] = parse_dry_run_fixture(
            PROVIDER_ID, fixture_payload, evidence_category=category,
        )
    except Exception:
        # Fail closed on any unexpected failure -- never propagate the raw
        # exception (its message could embed a value derived from caller
        # input) and never fabricate signals.
        _log.warning("serpapi_offline_plan_failed request_kind=%s", kind)
        return SerpApiSearchEvidence(
            source=SOURCE,
            provider_id=PROVIDER_ID,
            request_kind=kind,
            evidence_category=category,
            observed_at=time.time(),
            query=query,
            status="error",
            readiness_state="unavailable",
            provider_registered=provider_registered,
            blockers=("offline_plan_failed",),
            signal_count=0,
            confidence="none",
            warnings=("SerpApi offline plan/parser failed unexpectedly; details withheld.",),
            report={},
        )

    blockers = readiness.blockers if provider_registered else readiness.blockers + ("provider_not_registered",)
    readiness_state = "blocked" if (readiness.state == "blocked" or not provider_registered) else readiness.state
    status = "blocked" if readiness_state == "blocked" else "dry_run_ready"
    return SerpApiSearchEvidence(
        source=SOURCE,
        provider_id=PROVIDER_ID,
        request_kind=kind,
        evidence_category=category,
        observed_at=time.time(),
        query=query,
        status=status,
        readiness_state=readiness_state,
        provider_registered=provider_registered,
        blockers=tuple(dict.fromkeys(blockers)),
        signal_count=len(records),
        confidence="fixture",
        warnings=tuple(dict.fromkeys(limitation for record in records for limitation in record.limitations)),
        report={
            "contract": contract.to_dict(),
            "request_plan": plan.request_plans[0].to_dict(),
            "records": [record.to_dict() for record in records],
        },
    )


def discover_search_queries(query: str, *, context: SidecarContext, max_results: int = 5) -> list[str]:
    """Deterministic query-normalization placeholder -- returns the
    cleaned input query only. No live keyword-suggestion call is made.
    `context` and `max_results` are accepted for signature parity with
    the DataForSEO/CJ adapters and are unused in this offline-only
    implementation."""
    del context, max_results
    cleaned = " ".join((query or "").split())
    return [cleaned] if cleaned else []


async def discover(
    query: str,
    *,
    context: SidecarContext,
    request_kind: str = DEFAULT_REQUEST_KIND,
) -> Sequence[Mapping[str, Any]]:
    """Structurally satisfies
    `backend.contracts.adapters.ProductResearchProvider.discover` (same
    `async def discover(query, *, context) -> Sequence[Mapping[str, Any]]`
    signature) without introducing a second Protocol, registry, or parser.
    Entirely offline and instantaneous -- `async` only for Protocol
    conformance, no actual I/O occurs.

    Dry-run: returns each normalized record already produced by the
    existing generic parser (via `fetch_search_evidence`), as plain
    mappings, each enriched with `evidence_category` and
    `readiness_state`. Live: returns a single-element sequence containing
    the structured `blocked_live_mode`/`error` result -- the network is
    never called.
    """
    evidence = fetch_search_evidence(query, context=context, request_kind=request_kind)
    if evidence.status in ("blocked_live_mode", "error"):
        return (evidence.to_dict(),)

    records = evidence.report.get("records", [])
    enriched: list[dict[str, Any]] = []
    for record in records:
        item = dict(record)
        item["evidence_category"] = evidence.evidence_category
        item["readiness_state"] = evidence.readiness_state
        enriched.append(item)
    return tuple(enriched)


class SerpApiResearchAdapter:
    """Thin class wrapper structurally satisfying
    `backend.contracts.adapters.ProductResearchProvider` for callers that
    prefer an instance over free functions. Holds no state and no
    registry entry of its own -- it delegates every call to the
    module-level functions above."""

    name = SOURCE

    def health(self) -> AdapterHealth:
        return health()

    async def discover(self, query: str, *, context: SidecarContext) -> Sequence[Mapping[str, Any]]:
        return await discover(query, context=context)


def to_additional_evidence(evidence: SerpApiSearchEvidence) -> dict[str, Any]:
    """Shape this evidence for
    `backend.mvp_commerce.product_research.ResearchCandidate
    .additional_evidence` -- the existing, documented extension point.
    Never constructs a `ResearchCandidate` here; the caller decides which
    `candidate_id` this attaches to."""
    return {"serpapi": evidence.to_dict()}


def signals_to_additional_evidence(signals: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Per-signal counterpart to `to_additional_evidence`, for
    `ResearchCandidate.additional_evidence`. Uses a distinct key so it can
    coexist with `to_additional_evidence`'s output on the same candidate."""
    return {"serpapi_signals": list(signals)}


def health() -> AdapterHealth:
    return AdapterHealth(
        name=SOURCE,
        configured=True,
        reachable=False,
        capabilities=("search_serp_keyword", "fixture_only", "dry_run_only"),
        detail="Offline fixture/dry-run only in this release; no live transport implemented.",
    )


__all__ = [
    "SOURCE",
    "PROVIDER_ID",
    "REQUEST_KINDS",
    "DEFAULT_REQUEST_KIND",
    "DEFAULT_EVIDENCE_CATEGORY",
    "MAX_RETRY_ATTEMPTS",
    "EVIDENCE_TIER",
    "SerpApiSearchEvidence",
    "SerpApiResearchAdapter",
    "fetch_search_evidence",
    "discover_search_queries",
    "discover",
    "to_additional_evidence",
    "signals_to_additional_evidence",
    "health",
]

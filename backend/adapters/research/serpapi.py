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
    EVIDENCE_CATEGORIES,
    IntelligenceAdapterPlanReport,
    NormalizedEvidenceRecord,
    build_intelligence_adapter_plan,
    parse_dry_run_fixture,
)

_log = logging.getLogger(__name__)

SOURCE = "serpapi_readonly_search"
PROVIDER_ID = "serpapi"
DEFAULT_EVIDENCE_CATEGORY = "CompetitorPricingEvidence"

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_FIXTURE_PATH = _REPO_ROOT / "tests/fixtures/intelligence_adapter_plan/serpapi_shopping_snapshot_dry_run.json"

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
    evidence_category: str
    observed_at: float
    query: str
    status: str
    readiness_state: str
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
            "evidence_category": self.evidence_category,
            "observed_at": self.observed_at,
            "query": self.query,
            "status": self.status,
            "readiness_state": self.readiness_state,
            "blockers": list(self.blockers),
            "signal_count": self.signal_count,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
            "report": self.report,
            "evidence_tier": self.evidence_tier,
            "retry_attempts_allowed": self.retry_attempts_allowed,
        }


def _blocked_live_result(query: str, *, evidence_category: str) -> SerpApiSearchEvidence:
    """Structured, honest 'blocked' result for a requested live call --
    never an exception, never a silent no-op; every missing prerequisite
    is named explicitly."""
    return SerpApiSearchEvidence(
        source=SOURCE,
        provider_id=PROVIDER_ID,
        evidence_category=evidence_category,
        observed_at=time.time(),
        query=query,
        status="blocked_live_mode",
        readiness_state="blocked",
        blockers=("live_mode_requested",) + _LIVE_PREREQUISITES,
        signal_count=0,
        confidence="none",
        warnings=("SerpApi live transport is not implemented in this release.",),
        report={},
    )


def _default_fixture_payload(query: str) -> dict[str, Any]:
    """Load the bundled sanitized fixture and substitute the caller's own
    query into its single synthetic record, so returned evidence reflects
    the actual query rather than the fixture's hardcoded example -- every
    other field stays exactly as the sanitized fixture defines it."""
    raw = json.loads(_DEFAULT_FIXTURE_PATH.read_text(encoding="utf-8"))
    records = raw.get("records", [])
    patched = [{**item, "query": query} for item in records if isinstance(item, Mapping)]
    return {**raw, "records": patched}


def fetch_search_evidence(
    query: str,
    *,
    context: SidecarContext,
    evidence_category: str = DEFAULT_EVIDENCE_CATEGORY,
    payload: Mapping[str, Any] | None = None,
) -> SerpApiSearchEvidence:
    """Fail-closed bridge into the existing generic Intelligence Adapter
    Plan for the `serpapi` provider entry.

    `context.dry_run=False` (a live request) never reaches the offline
    plan/parser -- it always returns a structured blocked result naming
    every unmet prerequisite. Any unexpected failure from the offline
    module is caught and converted to a safe, generic degraded result;
    the raw exception message is never included in the returned evidence.
    """
    category = evidence_category if evidence_category in EVIDENCE_CATEGORIES else DEFAULT_EVIDENCE_CATEGORY
    if not context.dry_run:
        return _blocked_live_result(query, evidence_category=category)

    try:
        plan: IntelligenceAdapterPlanReport = build_intelligence_adapter_plan(provider=PROVIDER_ID)
        contract = plan.contracts[0]
        readiness = contract.activation_readiness
        fixture_payload = dict(payload) if payload is not None else _default_fixture_payload(query)
        records: tuple[NormalizedEvidenceRecord, ...] = parse_dry_run_fixture(
            PROVIDER_ID, fixture_payload, evidence_category=category,
        )
    except Exception:
        # Fail closed on any unexpected failure -- never propagate the raw
        # exception (its message could embed a value derived from caller
        # input) and never fabricate signals.
        _log.warning("serpapi_offline_plan_failed evidence_category=%s", category)
        return SerpApiSearchEvidence(
            source=SOURCE,
            provider_id=PROVIDER_ID,
            evidence_category=category,
            observed_at=time.time(),
            query=query,
            status="error",
            readiness_state="unavailable",
            blockers=("offline_plan_failed",),
            signal_count=0,
            confidence="none",
            warnings=("SerpApi offline plan/parser failed unexpectedly; details withheld.",),
            report={},
        )

    status = "blocked" if readiness.state == "blocked" else "dry_run_ready"
    return SerpApiSearchEvidence(
        source=SOURCE,
        provider_id=PROVIDER_ID,
        evidence_category=category,
        observed_at=time.time(),
        query=query,
        status=status,
        readiness_state=readiness.state,
        blockers=readiness.blockers,
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
    evidence_category: str = DEFAULT_EVIDENCE_CATEGORY,
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
    evidence = fetch_search_evidence(query, context=context, evidence_category=evidence_category)
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

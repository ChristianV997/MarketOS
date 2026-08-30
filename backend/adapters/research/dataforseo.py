"""backend.adapters.research.dataforseo -- thin runtime bridge from the
existing offline DataForSEO adapter (evaluation.commerce.dataforseo_adapter)
into MarketOS's existing Product Research seam.

This module introduces no new evidence dataclass hierarchy, no new event
type, no new provider registry, and no live transport. It is deliberately
the narrowest possible seam, mirroring the one existing precedent for a
concrete research-evidence source in this directory,
`backend.adapters.research.cj_public_evidence`: plain sync free functions
(`health()`, `fetch_*`, `discover_*`), not a class instantiated against
`backend.adapters.research.registry.ResearchAdapterRegistry` (that registry
is scoped to the simpler no-arg `fetch() -> list[dict]` trend-source
adapters in `backend.jobs.research_trend_v1` -- CJ public evidence does not
register there either, and DataForSEO evidence is not a trend source).

Every parse/normalize/evidence decision is delegated to the already-tested
`evaluation.commerce.dataforseo_adapter` module (merged in PR #178, 157
deterministic tests) -- this file adds no parsing logic of its own.

Fail-closed by construction. `SidecarContext.dry_run` defaults to `True`
(`backend.contracts.adapters.SidecarContext`); this adapter refuses any
network/SDK call regardless of that flag's value in this release --
implementing a live transport is explicitly out of scope for this PR (see
`docs/DATAFORSEO_RUNTIME_ADAPTER.md`'s "Future activation" section). A
`context.dry_run=False` request never reaches the offline builder; it
returns a structured, honest `blocked_live_mode` result naming every unmet
prerequisite instead of attempting a call or raising.

Output attaches to `backend.mvp_commerce.product_research.ResearchCandidate
.additional_evidence` -- the existing, documented extension point for "a
future source... attached without changing [ResearchCandidate's] shape."
Nothing here constructs a `ResearchCandidate` directly; the caller decides
which candidate a result attaches to.

`discover()` (module function) and `DataForSEOResearchAdapter` (a thin,
stateless class wrapper around it) structurally satisfy
`backend.contracts.adapters.ProductResearchProvider`'s
`async def discover(query, *, context) -> Sequence[Mapping[str, Any]]`
signature -- no second Protocol, no second registry. Both are `async` only
for Protocol conformance; no I/O occurs, since everything is delegated to
the same offline, instantaneous builder `fetch_search_evidence` already
uses.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Mapping, Sequence

from backend.contracts.adapters import AdapterHealth, SidecarContext
from evaluation.commerce.dataforseo_adapter import (
    REQUEST_KINDS,
    DataForSEOAdapterReport,
    build_dataforseo_adapter_report,
)

SOURCE = "dataforseo_readonly_search"
DEFAULT_REQUEST_KIND = "serp_google_organic_snapshot"

# Every prerequisite a live request is missing today -- named explicitly so
# a blocked result is never a bare "no", matching
# evaluation/commerce/dataforseo_adapter.py's own DataForSEOApprovalReadiness
# vocabulary rather than inventing a second one.
_LIVE_PREREQUISITES = (
    "approved Approval Ledger request (approval_request_type=provider_call)",
    "credential reference configured (credential-dataforseo, secret value absent)",
    "monthly/per-run budget cap approved",
    "terms review complete",
    "privacy review complete",
    "output contract tests passing",
    "timeout/retry policy defined for a real transport",
    "workspace and client-isolation checks passed",
    "a separately reviewed live transport implementation",
)


@dataclass(frozen=True)
class DataForSEOSearchEvidence:
    """One DataForSEO offline evidence observation -- always fixture/dry-run
    sourced in this release. Field shape mirrors
    `cj_public_evidence.CJProductEvidence` (source, confidence, warnings)
    so mvp_commerce callers can treat every research-adapter evidence type
    consistently, without sharing CJ's supplier-specific fields."""

    source: str
    request_kind: str
    observed_at: float
    query: str
    status: str
    readiness_state: str
    blockers: tuple[str, ...]
    search_signal_count: int
    shopping_signal_count: int
    competitor_signal_count: int
    confidence: str
    warnings: tuple[str, ...]
    report: dict[str, Any] = dataclass_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "request_kind": self.request_kind,
            "observed_at": self.observed_at,
            "query": self.query,
            "status": self.status,
            "readiness_state": self.readiness_state,
            "blockers": list(self.blockers),
            "search_signal_count": self.search_signal_count,
            "shopping_signal_count": self.shopping_signal_count,
            "competitor_signal_count": self.competitor_signal_count,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
            "report": self.report,
        }


def _blocked_live_result(query: str, *, request_kind: str) -> DataForSEOSearchEvidence:
    """Structured, honest 'blocked' result for a requested live call --
    never an exception, never a silent no-op; every missing prerequisite
    is named explicitly."""
    return DataForSEOSearchEvidence(
        source=SOURCE,
        request_kind=request_kind,
        observed_at=time.time(),
        query=query,
        status="blocked_live_mode",
        readiness_state="blocked",
        blockers=("live_mode_requested",) + _LIVE_PREREQUISITES,
        search_signal_count=0,
        shopping_signal_count=0,
        competitor_signal_count=0,
        confidence="none",
        warnings=("DataForSEO live transport is not implemented in this release.",),
        report={},
    )


def fetch_search_evidence(
    query: str,
    *,
    context: SidecarContext,
    request_kind: str = DEFAULT_REQUEST_KIND,
) -> DataForSEOSearchEvidence:
    """Fail-closed bridge into the existing offline DataForSEO adapter.

    `context.dry_run=False` (a live request) never reaches the offline
    builder -- it always returns a structured blocked result naming every
    unmet prerequisite, matching this adapter family's fail-closed idiom
    (`SidecarContext.require_live_idempotency`) elsewhere in this repo.
    """
    kind = request_kind if request_kind in REQUEST_KINDS else DEFAULT_REQUEST_KIND
    if not context.dry_run:
        return _blocked_live_result(query, request_kind=kind)

    report: DataForSEOAdapterReport = build_dataforseo_adapter_report(
        request_kind=kind,
        keywords=(query,),
        live_read_only=False,
    )
    return DataForSEOSearchEvidence(
        source=SOURCE,
        request_kind=kind,
        observed_at=time.time(),
        query=query,
        status=report.request_plan.status,
        readiness_state=report.approval_readiness.readiness_state,
        blockers=report.approval_readiness.blockers,
        search_signal_count=len(report.parse_result.search_signals),
        shopping_signal_count=len(report.parse_result.shopping_signals),
        competitor_signal_count=len(report.parse_result.competitor_signals),
        confidence="fixture",
        warnings=report.parse_result.warnings,
        report=report.to_dict(),
    )


def discover_search_queries(query: str, *, context: SidecarContext, max_results: int = 5) -> list[str]:
    """Deterministic query-normalization placeholder -- returns the
    cleaned input query only. No live keyword-suggestion call is made:
    DataForSEO's keyword-expansion endpoints are themselves live-only and
    out of scope for this release. `context` and `max_results` are
    accepted for signature parity with
    `cj_public_evidence.discover_candidate_urls` and are unused in this
    offline-only implementation."""
    del context, max_results
    cleaned = " ".join((query or "").split())
    return [cleaned] if cleaned else []


def to_additional_evidence(evidence: DataForSEOSearchEvidence) -> dict[str, Any]:
    """Shape this evidence for
    `backend.mvp_commerce.product_research.ResearchCandidate
    .additional_evidence` -- the existing, documented extension point for
    "a future source... attached without changing [ResearchCandidate's]
    shape." Never constructs a `ResearchCandidate` here; the caller decides
    which `candidate_id` this attaches to."""
    return {"dataforseo": evidence.to_dict()}


def signals_to_additional_evidence(signals: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Shape a `discover()` result sequence for
    `ResearchCandidate.additional_evidence` -- the per-signal counterpart to
    `to_additional_evidence`, which wraps a single aggregate
    `DataForSEOSearchEvidence` instead. Additive only: does not replace or
    change `to_additional_evidence`'s existing "dataforseo" key."""
    return {"dataforseo_signals": list(signals)}


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

    Dry-run (`context.dry_run=True`, the default): returns each normalized
    search/shopping/competitor signal already produced by the existing
    offline builder (via `fetch_search_evidence`), as plain mappings, each
    enriched with `request_kind` and `readiness_state` so a caller sees
    query lineage, source method, confidence, limitations, and readiness
    state without re-deriving them. No raw provider-shaped payload is ever
    included -- every mapping here is already the sanitized, normalized
    signal shape `evaluation.commerce.dataforseo_adapter` produces.

    Live (`context.dry_run=False`): returns a single-element sequence
    containing the structured `blocked_live_mode` result -- the network is
    never called, matching `fetch_search_evidence`'s fail-closed behavior.
    """
    evidence = fetch_search_evidence(query, context=context, request_kind=request_kind)
    if evidence.status == "blocked_live_mode":
        return (evidence.to_dict(),)

    parsed = evidence.report.get("parse_result", {})
    records: list[dict[str, Any]] = []
    for key in ("search_signals", "shopping_signals", "competitor_signals"):
        for signal in parsed.get(key, ()):
            record = dict(signal)
            record["request_kind"] = evidence.request_kind
            record["readiness_state"] = evidence.readiness_state
            records.append(record)
    return tuple(records)


class DataForSEOResearchAdapter:
    """Thin class wrapper structurally satisfying
    `backend.contracts.adapters.ProductResearchProvider` for callers that
    prefer an instance over free functions (e.g. a future caller iterating
    over several `ProductResearchProvider`-shaped sources uniformly). Holds
    no state and no registry entry of its own -- it delegates every call to
    the module-level functions above, which remain independently usable."""

    name = SOURCE

    def health(self) -> AdapterHealth:
        return health()

    async def discover(self, query: str, *, context: SidecarContext) -> Sequence[Mapping[str, Any]]:
        return await discover(query, context=context)


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
    "DEFAULT_REQUEST_KIND",
    "DataForSEOSearchEvidence",
    "DataForSEOResearchAdapter",
    "fetch_search_evidence",
    "discover_search_queries",
    "discover",
    "to_additional_evidence",
    "signals_to_additional_evidence",
    "health",
]

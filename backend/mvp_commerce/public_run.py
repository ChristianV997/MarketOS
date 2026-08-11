"""Operator-gated public Google News RSS Commerce MVP composition.

This module composes existing public-signal ingestion with the existing
Commerce MVP packet builder. It does not add a second source adapter or a
second commerce decision path.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from backend.contracts.adapters import SidecarContext
from backend.contracts.events import Event
from backend.events.repository import EventRepository
from backend.signals.public_signal_cache import PublicSignalCache
from backend.signals.public_signal_models import PublicSignalIngestionResult
from backend.signals.public_sources import ingest_public_rss, public_signal_event

from .competition_intelligence import build_market_opportunity_report, compute_margin_intelligence, competition_intelligence_events, gather_market_intelligence
from .events import commerce_mvp_events
from .models import CommerceMvpRun
from .opportunity import build_opportunity_candidates_from_signals, select_candidate
from .opportunity_scoring import opportunity_scoring_events, rank_opportunities
from .runner import run_commerce_mvp_slice
from .supplier_evidence import gather_authenticated_supplier_evidence, gather_supplier_evidence, supplier_evidence_events


@dataclass(frozen=True)
class PublicCommerceRunResult:
    run: CommerceMvpRun
    ingestion: PublicSignalIngestionResult
    events: tuple[Event, ...]
    write_targets: tuple[str, ...] = ()
    operator_note: str = ""

    @property
    def status(self) -> str:
        return self.ingestion.status

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.ingestion.status,
            "public_source_status": self.ingestion.status,
            "network_used": self.ingestion.network_used,
            "cache_status": self.ingestion.cache_status,
            "signal_count": len(self.ingestion.signals),
            "candidate_count": len(self.run.opportunity_candidates),
            "selected_candidate": self.run.selected_candidate.product_name if self.run.selected_candidate else None,
            "event_count": len(self.events),
            "event_type_counts": _event_type_counts(self.events),
            "write_targets": list(self.write_targets),
            "dashboard_next_step": "Inspect /operator/events after an explicit event write." if self.write_targets else "Choose an explicit JSONL or Supabase staging target to populate read views.",
            "warnings": _unique([*self.ingestion.warnings, *self.run.warnings]),
            "blockers": _unique([*self.ingestion.errors, *self.run.blockers]),
            "source_url": self.ingestion.source_url,
            "run": self.run.to_dict(),
            "ingestion": self.ingestion.to_dict(),
            "operator_note": self.operator_note,
            "read_only": True,
            "advisory": True,
            "mutated": False,
        }


def _event_type_counts(events: list[Event] | tuple[Event, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        counts[event.event_type] = counts.get(event.event_type, 0) + 1
    return dict(sorted(counts.items()))


def _unique(values: list[str] | tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(values))


def explain_public_network_run_readiness(
    *,
    query: str = "",
    allow_network: bool = False,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Return readiness without performing a network request."""
    cache = PublicSignalCache(cache_dir) if cache_dir else None
    cache_info = cache.readiness("google_news_rss", query) if cache else {
        "cache_available": False,
        "last_success": None,
        "cached_signal_count": 0,
    }
    return {
        "source": "google_news_rss",
        "configured": True,
        "allow_network": allow_network,
        "network_required": True,
        "requires_credentials": False,
        "status": "ready" if allow_network else "blocked",
        "reason": "explicit_operator_network_gate_required" if not allow_network else "bounded_public_get_ready",
        "cache": cache_info,
        "allowed_actions": ["read_public_only", "cache_local_observation", "append_advisory_canonical_event"],
        "forbidden_actions": ["login", "credentialed_fetch", "write", "publish", "spend", "mutate"],
        "network_calls": False,
        "read_only": True,
    }


def load_public_signals_for_commerce_query(
    query: str,
    *,
    max_signals: int = 10,
    allow_network: bool = False,
    cache_dir: str | Path | None = None,
    fetcher: Callable[[str, int], str] | None = None,
) -> PublicSignalIngestionResult:
    """Load one bounded Google News RSS result through the existing adapter."""
    cache = PublicSignalCache(cache_dir) if cache_dir else None
    return ingest_public_rss(query, limit=max_signals, allow_network=allow_network, cache=cache, fetcher=fetcher)


def run_commerce_mvp_from_public_rss(
    *,
    workspace_id: str = "commerce-mvp-public",
    query: str,
    max_signals: int = 10,
    max_candidates: int = 5,
    allow_network: bool = False,
    cache_dir: str | Path | None = None,
    shopify_store_context: Any | None = None,
    event_repository: EventRepository | None = None,
    fetcher: Callable[[str, int], str] | None = None,
    operator_note: str = "",
    attempt_supplier_evidence: bool = False,
    supplier_source: str = "public_page_static",
    allow_authenticated_supplier: bool = False,
    supplier_candidate_urls: list[str] | None = None,
    use_opportunity_ranking: bool = False,
    attempt_competition_evidence: bool = False,
    competitor_urls: list[str] | None = None,
    research_portfolio: Any | None = None,
    **economics: float,
) -> PublicCommerceRunResult:
    """Run an advisory Commerce MVP packet from one public RSS query.

    The public fetch is the only network-capable operation. Event persistence
    occurs only through the explicitly injected repository.

    attempt_supplier_evidence=True additionally tries to ground unit
    economics in a real, observed CJ public-page supplier cost (see
    backend.mvp_commerce.supplier_evidence) for whichever candidate the
    existing selection logic picks — never a second, independent candidate
    decision. It never performs live network I/O unless allow_network is
    also True (the same gate the RSS fetch itself uses); with
    allow_network=False the evidence attempt is dry-run/simulated and never
    changes economics, matching every other public-network capability in
    this module.

    use_opportunity_ranking=True additionally scores and ranks every
    candidate this ingestion produced (see
    backend.mvp_commerce.opportunity_scoring) instead of taking the single
    highest-source-score candidate. Pure computation, no network I/O of its
    own; the ranking result is recomputed here (deterministic, same
    candidates/evidence as run_commerce_mvp_slice used internally) purely to
    surface its canonical events — the ranking decision itself is made once,
    inside run_commerce_mvp_slice.

    attempt_competition_evidence=True additionally gathers public
    competitor-listing evidence (see
    backend.mvp_commerce.competition_intelligence) for the same peeked
    candidate, feeding it into opportunity scoring and unit-economics margin
    computation alongside supplier evidence — only takes effect together
    with use_opportunity_ranking=True (competition evidence composes
    through the ranking path only, never the single-candidate default
    path). Same allow_network gate as supplier evidence: dry-run/simulated
    with allow_network=False.

    research_portfolio, when supplied, takes priority over both the
    default pick and use_opportunity_ranking (see
    backend.mvp_commerce.product_research and
    run_commerce_mvp_slice's own docstring) — this module never builds a
    portfolio itself (no multi-candidate evidence-gathering orchestration
    here yet; see docs/PRODUCT_RESEARCH.md's stated limitations), it only
    forwards an already-built one.
    """
    ingestion = load_public_signals_for_commerce_query(
        query,
        max_signals=max_signals,
        allow_network=allow_network,
        cache_dir=cache_dir,
        fetcher=fetcher,
    )

    supplier_evidence_result = None
    competition_evidence_result = None
    if attempt_supplier_evidence or attempt_competition_evidence:
        # Peek the same deterministic candidate selection run_commerce_mvp_slice
        # will make, so evidence is gathered for the actual selected product —
        # never a second, independent candidate decision. Cheap and pure.
        peeked_candidates = build_opportunity_candidates_from_signals(ingestion.signals, workspace_id, query, max_candidates)
        peeked_selected = select_candidate(peeked_candidates)
        if peeked_selected is not None:
            if attempt_supplier_evidence:
                supplier_context = SidecarContext(workspace_id=workspace_id, dry_run=not allow_network)
                if supplier_source == "authenticated_readonly":
                    supplier_evidence_result = gather_authenticated_supplier_evidence(
                        peeked_selected.product_name, context=supplier_context, max_candidates=max_candidates,
                        allow_network=allow_network and allow_authenticated_supplier,
                    )
                else:
                    supplier_evidence_result = gather_supplier_evidence(
                        peeked_selected.product_name, context=supplier_context,
                        candidate_urls=supplier_candidate_urls,
                    )
            if attempt_competition_evidence:
                competition_evidence_result = gather_market_intelligence(
                    peeked_selected.product_name,
                    context=SidecarContext(workspace_id=workspace_id, dry_run=not allow_network),
                    competitor_urls=competitor_urls,
                )

    run = run_commerce_mvp_slice(
        workspace_id=workspace_id,
        query=query,
        signals=ingestion.signals,
        mode="public-network",
        max_signals=max_signals,
        max_candidates=max_candidates,
        shopify_store_context=shopify_store_context,
        write_repository=None,
        supplier_evidence=supplier_evidence_result,
        use_opportunity_ranking=use_opportunity_ranking,
        competition_evidence=competition_evidence_result,
        research_portfolio=research_portfolio,
        **economics,
    )
    metadata = {
        **run.metadata,
        "run_mode": "public-network",
        "public_source": ingestion.source,
        "public_source_status": ingestion.status,
        "network_used": ingestion.network_used,
        "cache_status": ingestion.cache_status,
        "source_url": ingestion.source_url,
        "operator_note": operator_note,
        "supplier_source": supplier_source,
        "authenticated_supplier_allowed": bool(allow_authenticated_supplier),
        "provider_calls": bool(
            supplier_evidence_result is not None
            and supplier_evidence_result.attempted
            and supplier_evidence_result.source_type == "authenticated_readonly_api"
        ),
        "read_only": True,
        "advisory": True,
        "non_authoritative": True,
    }
    warnings = tuple(dict.fromkeys((*run.warnings, *ingestion.warnings)))
    blockers = tuple(dict.fromkeys((*run.blockers, *ingestion.errors)))
    run = replace(run, metadata=metadata, warnings=warnings, blockers=blockers)
    public_events = [public_signal_event(signal, workspace_id, cache_status=ingestion.cache_status) for signal in ingestion.signals]
    commerce_events = commerce_mvp_events(run)
    evidence_events = (
        supplier_evidence_events(supplier_evidence_result, workspace_id=workspace_id, run_id=run.run_id, occurred_at=run.started_at)
        if supplier_evidence_result is not None else []
    )
    ranking_events: list[Event] = []
    competition_events: list[Event] = []
    if use_opportunity_ranking and run.opportunity_candidates:
        provisional = select_candidate(list(run.opportunity_candidates))
        evidence_map = (
            {provisional.candidate_id: supplier_evidence_result}
            if provisional is not None and supplier_evidence_result is not None else {}
        )
        competition_map = (
            {provisional.candidate_id: competition_evidence_result}
            if provisional is not None and competition_evidence_result is not None else {}
        )
        margin_map = (
            {provisional.candidate_id: compute_margin_intelligence(provisional.candidate_id, supplier_evidence=supplier_evidence_result, market_report=competition_evidence_result)}
            if provisional is not None else {}
        )
        assessment = rank_opportunities(
            list(run.opportunity_candidates), workspace_id=workspace_id, query=query,
            supplier_evidence_by_candidate=evidence_map, competition_evidence_by_candidate=competition_map,
            margin_by_candidate=margin_map, generated_at=run.started_at,
        )
        ranking_events = opportunity_scoring_events(assessment, run_id=run.run_id)
        if competition_evidence_result is not None:
            top_id = assessment.top_candidate_id
            top_candidate = next((c for c in run.opportunity_candidates if c.candidate_id == top_id), None)
            top_score = next((s for s in assessment.scores if s.candidate_id == top_id), None)
            market_opportunity_report = (
                build_market_opportunity_report(
                    top_id, top_candidate.product_name, opportunity_score=top_score,
                    supplier_evidence=evidence_map.get(top_id), market_report=competition_map.get(top_id),
                    margin=margin_map.get(top_id), generated_at=run.started_at,
                )
                if top_candidate is not None else None
            )
            competition_events = competition_intelligence_events(
                competition_evidence_result, margin_map.get(top_id), market_opportunity_report,
                workspace_id=workspace_id, run_id=run.run_id,
            )
    events = tuple(public_events + commerce_events + evidence_events + ranking_events + competition_events)
    run = replace(run, canonical_event_ids=tuple(event.event_id for event in events), completed_at=run.started_at + len(events) / 1000)
    if event_repository is not None:
        event_repository.append_many(events)
    return PublicCommerceRunResult(run, ingestion, events, ("injected_repository",) if event_repository else (), operator_note)


__all__ = [
    "PublicCommerceRunResult",
    "explain_public_network_run_readiness",
    "load_public_signals_for_commerce_query",
    "run_commerce_mvp_from_public_rss",
]

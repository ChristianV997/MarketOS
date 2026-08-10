"""Operator-gated public Google News RSS Commerce MVP composition.

This module composes existing public-signal ingestion with the existing
Commerce MVP packet builder. It does not add a second source adapter or a
second commerce decision path.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from backend.contracts.events import Event
from backend.events.repository import EventRepository
from backend.signals.public_signal_cache import PublicSignalCache
from backend.signals.public_signal_models import PublicSignalIngestionResult
from backend.signals.public_sources import ingest_public_rss, public_signal_event

from .events import commerce_mvp_events
from .models import CommerceMvpRun
from .runner import run_commerce_mvp_slice


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
    **economics: float,
) -> PublicCommerceRunResult:
    """Run an advisory Commerce MVP packet from one public RSS query.

    The public fetch is the only network-capable operation. Event persistence
    occurs only through the explicitly injected repository.
    """
    ingestion = load_public_signals_for_commerce_query(
        query,
        max_signals=max_signals,
        allow_network=allow_network,
        cache_dir=cache_dir,
        fetcher=fetcher,
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
        "provider_calls": False,
        "read_only": True,
        "advisory": True,
        "non_authoritative": True,
    }
    warnings = tuple(dict.fromkeys((*run.warnings, *ingestion.warnings)))
    blockers = tuple(dict.fromkeys((*run.blockers, *ingestion.errors)))
    run = replace(run, metadata=metadata, warnings=warnings, blockers=blockers)
    public_events = [public_signal_event(signal, workspace_id, cache_status=ingestion.cache_status) for signal in ingestion.signals]
    commerce_events = commerce_mvp_events(run)
    events = tuple(public_events + commerce_events)
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

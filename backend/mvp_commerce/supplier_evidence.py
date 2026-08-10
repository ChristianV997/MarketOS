"""backend.mvp_commerce.supplier_evidence — bridges CJ public-page supplier
evidence (backend.adapters.research.cj_public_evidence) into one Commerce
MVP run's unit economics, with observed-over-assumed precedence and
canonical event emission.

This module does not add a second commerce loop or a second economics
engine: it decides *which numbers* ``backend.mvp_commerce.runner``'s
existing economics math receives, and records provenance for the ones it
overrides. `_economics()` itself stays byte-for-byte unchanged; the
evidence-aware path is purely additive (see `_economics_with_evidence` in
runner.py, used only when a caller explicitly supplies
``SupplierEvidenceResult``).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from backend.adapters.research.cj_public_evidence import (
    CJProductEvidence, discover_candidate_urls, fetch_product_evidence, score_candidates,
)
from backend.contracts.adapters import SidecarContext
from backend.contracts.events import Event

SOURCE = "backend.mvp_commerce.supplier_evidence"


@dataclass(frozen=True)
class SupplierEvidenceResult:
    """What Commerce MVP economics needs from a supplier-evidence attempt —
    deliberately narrow (only the fields `_economics_with_evidence` can
    actually use); the full `CJProductEvidence` record travels separately
    for the canonical event payload."""

    attempted: bool
    unit_cost: float | None
    shipping_cost: float | None
    source_url: str
    supplier: str = "cj_public_page"
    candidates_considered: int = 0
    evidence: CJProductEvidence | None = None
    ranking: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = ()


def gather_supplier_evidence(
    query: str,
    *,
    context: SidecarContext,
    candidate_urls: list[str] | None = None,
    max_candidates: int = 5,
) -> SupplierEvidenceResult:
    """Never raises. Fetches evidence for operator-supplied CJ product URLs
    (the reliable Phase 1 path — see docs/CJ_PUBLIC_SUPPLIER_EVIDENCE.md),
    falling back to best-effort discovery only when none are supplied.
    Ranks whatever evidence comes back and selects the strongest candidate
    that actually has an observed price; returns attempted=False with no
    numbers when nothing usable was found, rather than inventing a cost.
    """
    urls = list(candidate_urls or [])
    if not urls:
        urls = discover_candidate_urls(query, context=context, max_results=max_candidates)
    if not urls:
        return SupplierEvidenceResult(
            attempted=True, unit_cost=None, shipping_cost=None, source_url="",
            warnings=("no_candidate_urls: supply candidate_urls or rely on discovery",),
        )

    evidences = [fetch_product_evidence(url, context=context) for url in urls[:max_candidates]]
    ranking = score_candidates(evidences, query)
    priced_ids = {e.external_product_id for e in evidences if e.price is not None and e.field_status.get("price") == "observed"}
    # ranking is already sorted best-first; keep that order, just restrict
    # to candidates with an actual observed price.
    priced_ranking = [item for item in ranking if item["product_id"] in priced_ids]
    if not priced_ranking:
        return SupplierEvidenceResult(
            attempted=True, unit_cost=None, shipping_cost=None, source_url="",
            candidates_considered=len(evidences), ranking=tuple(ranking),
            warnings=tuple(sorted({warning for evidence in evidences for warning in evidence.warnings})),
        )
    best_id = priced_ranking[0]["product_id"]
    best = next(e for e in evidences if e.external_product_id == best_id)
    return SupplierEvidenceResult(
        attempted=True, unit_cost=best.price, shipping_cost=best.shipping_cost,
        source_url=best.source_url, candidates_considered=len(evidences),
        evidence=best, ranking=tuple(ranking),
        warnings=best.warnings if best.shipping_cost is None else best.warnings + ("shipping_cost: unavailable_publicly",),
    )


def supplier_evidence_events(result: SupplierEvidenceResult, *, workspace_id: str, run_id: str, occurred_at: float) -> list[Event]:
    """Canonical events for one supplier-evidence attempt, following the
    exact shape of backend.signals.public_sources.public_signal_event and
    backend.mvp_commerce.events.commerce_mvp_events: dry-run/advisory/
    non-authoritative metadata, correlation to the owning run."""
    events: list[Event] = []

    def _event_id(suffix: str) -> str:
        return "supplier-evidence-" + hashlib.sha256(f"{run_id}:{suffix}".encode()).hexdigest()[:20]

    metadata = {
        "dry_run": True, "advisory": True, "no_credentials": True, "public_source": True,
        "non_authoritative": True, "no_launch_authority": True, "no_spend_authority": True,
        "no_order_authority": True,
    }
    events.append(Event(
        _event_id("requested"), workspace_id, "commerce_mvp_run", run_id,
        "supplier_evidence_requested", 1, occurred_at, correlation_id=run_id, source=SOURCE,
        payload={"candidates_considered": result.candidates_considered}, metadata=metadata,
    ))
    if result.evidence is not None:
        events.append(Event(
            _event_id(f"observed:{result.evidence.external_product_id}"), workspace_id, "supplier_product",
            result.evidence.external_product_id, "supplier_product_observed", 1, occurred_at + 0.001,
            correlation_id=run_id, source=SOURCE, payload=result.evidence.to_dict(),
            metadata={**metadata, "source_url": result.evidence.source_url, "extraction_method": result.evidence.extraction_method},
        ))
        events.append(Event(
            _event_id(f"enriched:{result.evidence.external_product_id}"), workspace_id, "commerce_mvp_run", run_id,
            "commerce_economics_enriched", 1, occurred_at + 0.002, correlation_id=run_id, source=SOURCE,
            payload={
                "unit_cost_source": "observed_cj_public_page", "unit_cost": result.unit_cost,
                "shipping_source": "observed_cj_public_page" if result.shipping_cost is not None else "assumption_unchanged",
                "shipping_cost": result.shipping_cost, "source_url": result.evidence.source_url,
            },
            metadata=metadata,
        ))
    else:
        events.append(Event(
            _event_id("degraded"), workspace_id, "commerce_mvp_run", run_id,
            "supplier_evidence_degraded", 1, occurred_at + 0.001, correlation_id=run_id, source=SOURCE,
            payload={"warnings": list(result.warnings), "candidates_considered": result.candidates_considered},
            metadata=metadata,
        ))
    return events


__all__ = ["SupplierEvidenceResult", "gather_supplier_evidence", "supplier_evidence_events"]

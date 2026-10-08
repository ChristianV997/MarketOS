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
import math
from dataclasses import dataclass, field
from typing import Any

from backend.adapters.research.cj_public_evidence import (
    CJProductEvidence, discover_candidate_urls, fetch_product_evidence, score_candidates,
)
from backend.contracts.adapters import SidecarContext
from backend.contracts.events import Event

SOURCE = "backend.mvp_commerce.supplier_evidence"


def _public_page_source_type(evidence: CJProductEvidence | None) -> str:
    if evidence is not None and evidence.extraction_method.startswith("crawl4ai_js_rendered"):
        return "public_page_js"
    return "public_page_static"


def _finite_amount(value: Any, *, positive: bool) -> float | None:
    if value is None:
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(amount) or (amount <= 0 if positive else amount < 0):
        return None
    return amount


def _currency_code(value: Any) -> str | None:
    return str(value).strip().upper() if isinstance(value, str) and value.strip() else None


def _fetch_timestamp(evidence: Any) -> float | None:
    value = getattr(evidence, "fetched_at", None)
    if value is None:
        value = getattr(evidence, "observed_at", None)
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    return timestamp if math.isfinite(timestamp) and timestamp >= 0 else None


def _economics_components(evidence: CJProductEvidence) -> tuple[float | None, float | None, tuple[str, ...]]:
    """Return only USD-compatible inputs; raw source amounts remain on evidence."""
    warnings = list(evidence.warnings)
    observed_price = (
        _finite_amount(evidence.price, positive=True)
        if evidence.field_status.get("price") == "observed" else None
    )
    currency = _currency_code(evidence.currency)
    unit_cost = None
    if evidence.field_status.get("price") == "observed":
        if observed_price is None:
            if "price_not_usable_as_supplier_cost" not in warnings:
                warnings.append("price_not_usable_as_supplier_cost")
        elif currency is None:
            warnings.append("unit_cost_currency_unavailable: economics require USD")
        elif currency != "USD":
            warnings.append(f"unit_cost_currency_mismatch: observed {currency}; economics require USD")
        else:
            unit_cost = observed_price

    observed_shipping = (
        _finite_amount(evidence.shipping_cost, positive=False)
        if evidence.field_status.get("shipping_cost") == "observed" else None
    )
    shipping_currency = _currency_code(evidence.shipping_currency)
    shipping_cost = None
    shipping_status = evidence.field_status.get("shipping_cost", "unavailable")
    if shipping_status == "unavailable":
        warnings.append("shipping_cost: unavailable_publicly")
    elif shipping_status != "observed":
        warnings.append("shipping_cost_not_usable")
    elif observed_shipping is None:
        warnings.append("shipping_cost_not_usable")
    elif shipping_currency is None:
        warnings.append("shipping_currency_unavailable: economics require USD")
    elif shipping_currency != "USD":
        warnings.append(f"shipping_currency_mismatch: observed {shipping_currency}; economics require USD")
    else:
        shipping_cost = observed_shipping
    return unit_cost, shipping_cost, tuple(dict.fromkeys(warnings))


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
    source_type: str = "public_page_static"
    status: str = "unavailable"
    currency: str | None = None
    shipping_currency: str | None = None
    fetched_at: float | None = None
    fetch_provenance: str = "unknown"

    def __post_init__(self) -> None:
        warnings = list(self.warnings)
        cost = _finite_amount(self.unit_cost, positive=True)
        if self.unit_cost is not None and cost is None:
            object.__setattr__(self, "unit_cost", None)
            if "price_not_usable_as_supplier_cost" not in warnings:
                warnings.append("price_not_usable_as_supplier_cost")
        elif cost is not None:
            object.__setattr__(self, "unit_cost", cost)
        shipping = _finite_amount(self.shipping_cost, positive=False)
        if self.shipping_cost is not None and shipping is None:
            object.__setattr__(self, "shipping_cost", None)
            if "shipping_cost_not_usable" not in warnings:
                warnings.append("shipping_cost_not_usable")
        elif shipping is not None:
            object.__setattr__(self, "shipping_cost", shipping)
        object.__setattr__(self, "warnings", tuple(warnings))
        currency = _currency_code(self.currency)
        if currency is None and self.evidence is not None:
            currency = _currency_code(self.evidence.currency)
        shipping_currency = _currency_code(self.shipping_currency)
        if shipping_currency is None and self.evidence is not None:
            shipping_currency = _currency_code(self.evidence.shipping_currency)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "shipping_currency", shipping_currency)
        fetched_at = self.fetched_at if self.fetched_at is not None else _fetch_timestamp(self.evidence)
        timestamp = _finite_amount(fetched_at, positive=False)
        object.__setattr__(self, "fetched_at", timestamp)
        if self.fetch_provenance == "unknown" and self.evidence is not None:
            object.__setattr__(self, "fetch_provenance", self.evidence.fetch_provenance)


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
    priced_ids = {
        e.external_product_id for e in evidences
        if _finite_amount(e.price, positive=True) is not None
        and e.field_status.get("price") == "observed"
        and _fetch_timestamp(e) is not None and e.fetch_provenance in {"fresh_fetch", "cache_hit"}
    }
    # ranking is already sorted best-first; keep that order, just restrict
    # to candidates with an actual observed price.
    priced_ranking = [item for item in ranking if item["product_id"] in priced_ids]
    usd_priced_ids = {
        e.external_product_id for e in evidences
        if e.external_product_id in priced_ids and _currency_code(e.currency) == "USD"
    }
    usd_priced_ranking = [item for item in ranking if item["product_id"] in usd_priced_ids]
    selected_ranking = usd_priced_ranking or priced_ranking
    best_id = selected_ranking[0]["product_id"] if selected_ranking else (ranking[0]["product_id"] if ranking else None)
    if best_id is None:
        return SupplierEvidenceResult(
            attempted=True, unit_cost=None, shipping_cost=None, source_url="",
            candidates_considered=len(evidences), ranking=tuple(ranking),
            warnings=tuple(sorted({warning for evidence in evidences for warning in evidence.warnings})),
        )
    best = next(e for e in evidences if e.external_product_id == best_id)
    unit_cost, observed_shipping, warnings = _economics_components(best)
    fetched_at = _fetch_timestamp(best)
    return SupplierEvidenceResult(
        attempted=True,
        unit_cost=unit_cost,
        shipping_cost=observed_shipping,
        source_url=best.source_url, candidates_considered=len(evidences),
        evidence=best if best.title else None, ranking=tuple(ranking),
        warnings=warnings,
        source_type=_public_page_source_type(best),
        status="observed" if unit_cost is not None else "unavailable",
        currency=best.currency, shipping_currency=best.shipping_currency,
        fetched_at=fetched_at, fetch_provenance=best.fetch_provenance,
    )


def gather_authenticated_supplier_evidence(
    query: str,
    *,
    context: SidecarContext,
    max_candidates: int = 5,
    allow_network: bool = False,
    adapter: Any | None = None,
) -> SupplierEvidenceResult:
    """Use the explicitly gated CJ catalog read path, never a mutation path."""
    from backend.adapters.research.cj_readonly_api import CjReadOnlySupplierAdapter

    result = (adapter or CjReadOnlySupplierAdapter()).search(
        query, limit=max_candidates, allow_network=bool(allow_network and not context.dry_run)
    )
    best = result.best
    if best is None:
        return SupplierEvidenceResult(
            attempted=result.attempted, unit_cost=None, shipping_cost=None, source_url="",
            supplier="cj_dropshipping", warnings=result.warnings,
            source_type="authenticated_readonly_api", status=result.status,
        )
    return SupplierEvidenceResult(
        attempted=True,
        unit_cost=(
            _finite_amount(best.price, positive=True)
            if best.field_status.get("price") == "observed" and _currency_code(best.currency) == "USD" else None
        ),
        shipping_cost=(
            _finite_amount(best.shipping_cost, positive=False)
            if best.field_status.get("shipping_cost") == "observed"
            and _currency_code(getattr(best, "shipping_currency", None)) == "USD" else None
        ),
        source_url=best.source_url, supplier="cj_dropshipping", candidates_considered=len(result.products),
        evidence=best, warnings=result.warnings + best.warnings,
        source_type="authenticated_readonly_api", status=result.status,
        currency=getattr(best, "currency", None),
        shipping_currency=getattr(best, "shipping_currency", None),
        fetched_at=_fetch_timestamp(best), fetch_provenance=getattr(best, "fetch_provenance", "unknown"),
    )


def supplier_evidence_events(result: SupplierEvidenceResult, *, workspace_id: str, run_id: str, occurred_at: float) -> list[Event]:
    """Canonical events for one supplier-evidence attempt, following the
    exact shape of backend.signals.public_sources.public_signal_event and
    backend.mvp_commerce.events.commerce_mvp_events: dry-run/advisory/
    non-authoritative metadata, correlation to the owning run."""
    events: list[Event] = []

    def _event_id(suffix: str) -> str:
        return "supplier-evidence-" + hashlib.sha256(f"{run_id}:{suffix}".encode()).hexdigest()[:20]

    authenticated = result.source_type == "authenticated_readonly_api"
    metadata = {
        "dry_run": True, "advisory": True, "no_credentials": not authenticated, "public_source": not authenticated,
        "authenticated_readonly": authenticated, "supplier_source": result.source_type,
        "non_authoritative": True, "no_launch_authority": True, "no_ad_authority": True,
        "no_spend_authority": True,
        "no_order_authority": True, "no_supplier_mutation_authority": True,
        "no_inventory_mutation_authority": True, "no_fulfillment_authority": True,
        "no_payment_authority": True, "no_outreach_authority": True,
        "no_customer_message_authority": True,
        "no_external_action_authority": True,
    }
    events.append(Event(
        _event_id("requested"), workspace_id, "commerce_mvp_run", run_id,
        "supplier_evidence_requested", 1, occurred_at, correlation_id=run_id, source=SOURCE,
        payload={"candidates_considered": result.candidates_considered, "source_type": result.source_type,
                 "status": result.status}, metadata=metadata,
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
                "unit_cost_source": f"observed_{result.source_type}" if result.unit_cost is not None else "assumption_unchanged",
                "unit_cost": result.unit_cost,
                "shipping_source": f"observed_{result.source_type}" if result.shipping_cost is not None else "assumption_unchanged",
                "shipping_cost": result.shipping_cost, "source_url": result.evidence.source_url,
                "observed_price": result.evidence.price,
                "currency": result.currency,
                "observed_shipping_cost": result.evidence.shipping_cost,
                "shipping_currency": result.shipping_currency,
                "warnings": list(result.warnings),
                "fetched_at": result.fetched_at,
                "observed_at": result.evidence.observed_at,
                "fetch_provenance": result.fetch_provenance,
            },
            metadata=metadata,
        ))
    else:
        events.append(Event(
            _event_id("degraded"), workspace_id, "commerce_mvp_run", run_id,
            "supplier_evidence_degraded", 1, occurred_at + 0.001, correlation_id=run_id, source=SOURCE,
            payload={"warnings": list(result.warnings), "candidates_considered": result.candidates_considered,
                     "status": result.status, "source_type": result.source_type},
            metadata=metadata,
        ))
    return events


__all__ = ["SupplierEvidenceResult", "gather_supplier_evidence", "gather_authenticated_supplier_evidence", "supplier_evidence_events"]

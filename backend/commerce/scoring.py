"""Opportunity scoring for the canonical commerce loop."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from backend.vector.semantic_search import (
    find_similar_campaigns,
    find_similar_products,
    search_all,
)
from evaluation import LaunchReadiness, ProductCandidate, SupplierOffer, evaluate_product

from .contracts import (
    CommerceSignal,
    RankedOpportunity,
    build_product_candidate,
    build_supplier_offer,
)


def _clamp(value: float, *, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _quality_score(signal: CommerceSignal) -> tuple[float, list[str]]:
    q = signal.quality
    score = 0.0
    reasons: list[str] = []

    if q.is_live_attributed:
        score += 1.0
        reasons.append("live_attributed_signal")
    elif q.provenance == "live":
        score += 0.8
        reasons.append("live_signal")
    elif q.is_synthetic:
        score += 0.2
        reasons.append("synthetic_signal")
    else:
        score += 0.4
        reasons.append("unclassified_signal")

    if q.attribution == "partial":
        score -= 0.1
        reasons.append("partial_attribution")
    elif q.attribution in {"unknown", "unattributed"}:
        score -= 0.2
        reasons.append("weak_attribution")

    if q.completeness != "complete":
        score -= 0.15
        reasons.append("incomplete_signal")

    return _clamp(score), reasons


def _semantic_score(query: str) -> tuple[float, list[str], list[str]]:
    hits: list[str] = []
    score = 0.0

    try:
        grouped_hits = search_all(query, top_k=3, collections=["products", "campaigns", "patterns"])
        for hit in [
            *grouped_hits.get("products", []),
            *grouped_hits.get("campaigns", []),
            *grouped_hits.get("patterns", []),
        ]:
            payload = hit.payload or {}
            roas = float(payload.get("roas", 0.0) or 0.0)
            candidate = _clamp(hit.score)
            if roas >= 1.5:
                candidate = min(1.0, candidate + min(roas / 10.0, 0.25))
                hits.append(f"winner_match:{hit.collection or 'vector'}")
            elif roas > 0:
                hits.append(f"historical_match:{hit.collection or 'vector'}")
            score = max(score, candidate)
    except Exception:
        return 0.0, ["semantic_search_unavailable"], []

    if score > 0:
        hits.append("semantic_support")
    return score, sorted(set(hits)), []


def _economics_score(readiness: LaunchReadiness | None) -> tuple[float, list[str]]:
    if readiness is None:
        return 0.0, ["missing_readiness"]

    reasons = list(readiness.reasons)
    economics = readiness.economics
    if economics is None:
        reasons.append("missing_economics")
        return 0.0, sorted(set(reasons))

    if not economics.eligible:
        reasons.extend(economics.reasons)
        return 0.0, sorted(set(reasons))

    margin = _clamp(economics.margin_rate, low=0.0, high=1.0)
    roas = economics.break_even_roas or 0.0
    return _clamp(0.55 * margin + 0.45 * min(roas / 5.0, 1.0)), sorted(set([*reasons, *economics.reasons]))


@dataclass
class OpportunityScorer:
    """Score and rank commerce opportunities with truth-aware signals."""

    signal_weight: float = 0.35
    semantic_weight: float = 0.25
    economics_weight: float = 0.25
    quality_weight: float = 0.15
    competition_penalty_weight: float = 0.20
    default_currency: str = "USD"
    _last_ranked: list[RankedOpportunity] = field(default_factory=list, init=False, repr=False)

    def build_candidates(
        self,
        signals: Iterable[dict[str, Any] | CommerceSignal],
        *,
        product_overrides: Mapping[str, ProductCandidate] | None = None,
        offer_overrides: Mapping[str, SupplierOffer] | None = None,
    ) -> list[tuple[CommerceSignal, ProductCandidate, SupplierOffer | None]]:
        candidates: list[tuple[CommerceSignal, ProductCandidate, SupplierOffer | None]] = []
        products = product_overrides or {}
        offers = offer_overrides or {}
        for raw in signals:
            signal = raw if isinstance(raw, CommerceSignal) else CommerceSignal.from_signal(raw)
            product = products.get(signal.product_id) or products.get(signal.product_name)
            if product is None:
                product = build_product_candidate(signal, selling_price=float((raw.get("selling_price") if isinstance(raw, dict) else 0.0) or (raw.get("price") if isinstance(raw, dict) else 0.0) or 0.0))
            offer = offers.get(product.product_id) or offers.get(product.name)
            if offer is None and isinstance(raw, dict):
                unit_cost = float(raw.get("unit_cost", 0.0) or 0.0)
                shipping_cost = float(raw.get("shipping_cost", 0.0) or 0.0)
                if unit_cost > 0 or shipping_cost > 0:
                    offer = build_supplier_offer(signal, unit_cost=unit_cost, shipping_cost=shipping_cost, source_ref=signal.signal_id)
            candidates.append((signal, product, offer))
        return candidates

    def score_candidate(
        self,
        signal: CommerceSignal,
        product: ProductCandidate,
        offer: SupplierOffer | None,
    ) -> RankedOpportunity:
        signal_score = _clamp(
            0.5 * _clamp(signal.score) +
            0.25 * _clamp(signal.engagement) +
            0.25 * _clamp(signal.velocity)
        )
        quality_score, quality_reasons = _quality_score(signal)
        query = " ".join(part for part in [signal.product_name, signal.raw_text, signal.source, signal.platform] if part).strip()
        semantic_score, semantic_reasons, _ = _semantic_score(query or product.name)

        readiness = evaluate_product(product, offer)
        economics_score, economics_reasons = _economics_score(readiness)

        competition_penalty = _clamp(float(signal.metadata.get("competition", signal.metadata.get("density", 0.0))) if signal.metadata else 0.0)

        reasons = sorted(
            set(
                [
                    *quality_reasons,
                    *semantic_reasons,
                    *economics_reasons,
                    *(readiness.reasons if readiness else ()),
                ]
            )
        )

        score = (
            self.signal_weight * signal_score
            + self.semantic_weight * semantic_score
            + self.economics_weight * economics_score
            + self.quality_weight * quality_score
            - self.competition_penalty_weight * competition_penalty
        )

        if not readiness.launchable:
            reasons.append("not_launchable")

        return RankedOpportunity(
            artifact_id=f"{signal.signal_id}:{product.product_id}",
            workspace=signal.workspace,
            parent_ids=[signal.artifact_id],
            signal_id=signal.signal_id,
            product_id=product.product_id,
            product_name=product.name,
            source_signal_ids=tuple(product.source_signal_ids or (signal.signal_id,)),
            score=round(score * 100.0, 4),
            signal_score=round(signal_score, 4),
            semantic_score=round(semantic_score, 4),
            economics_score=round(economics_score, 4),
            quality_score=round(quality_score, 4),
            competition_penalty=round(competition_penalty, 4),
            reasons=tuple(sorted(set(reasons))),
            quality=signal.quality,
            readiness=readiness,
            economics=readiness.economics.to_dict() if readiness.economics else {},
        )

    def rank(
        self,
        signals: Iterable[dict[str, Any] | CommerceSignal],
        *,
        products: Mapping[str, ProductCandidate] | None = None,
        offers: Mapping[str, SupplierOffer] | None = None,
        product_overrides: Mapping[str, ProductCandidate] | None = None,
        offer_overrides: Mapping[str, SupplierOffer] | None = None,
        top_k: int = 10,
    ) -> list[RankedOpportunity]:
        product_map = product_overrides or products
        offer_map = offer_overrides or offers
        candidates = self.build_candidates(
            signals,
            product_overrides=product_map,
            offer_overrides=offer_map,
        )
        ranked = [self.score_candidate(signal, product, offer) for signal, product, offer in candidates]
        ranked.sort(key=lambda item: (item.score, item.semantic_score, item.signal_score), reverse=True)
        self._last_ranked = ranked[:top_k]
        return self._last_ranked

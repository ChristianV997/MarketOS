"""backend.mvp_commerce.opportunity_scoring — deterministic, explainable
opportunity ranking sitting between supplier evidence and Commerce MVP
economics.

Naming note (read before renaming anything): this is deliberately **not**
called "Product Intelligence" despite that being the task's working name.
`backend/commercial_intelligence/product_analyzer.py` already owns that
exact term — it titles its own output "Product Intelligence: {product}"
and writes `opportunity.metadata["product_intelligence_report_id"/
"product_intelligence_confidence"/"product_intelligence_advisory_only"]`,
consumed by `backend/intelligence/knowledge_graph_builder.py`,
`backend/optimization/action_generator.py`,
`backend/obsidian/sync.py::sync_product_intelligence_note`, and
`backend/workflows/stage_executor.py`. That system scores evidence from
`backend.discovery.discovery_registry`/`opportunity_registry` — the
broader, heavier discovery stack the MVP Island profile deliberately
excludes ("OFF in the MVP Island: ... experimental modules not named by
the profile", see docs/MVP_ISLAND.md). Reusing it here would mean pulling
that stack into the narrow, deployable Commerce MVP slice; reusing its
*name* while scoring a different evidence source would silently conflate
two unrelated systems. This module scores `mvp_commerce`'s own
`OpportunityCandidate`/CJ-public-evidence pipeline only, under its own
name, and never touches `backend/commercial_intelligence/`.

Composes through existing architecture only:
- Consumes `backend.mvp_commerce.opportunity.OpportunityCandidate` (no new
  candidate model) and `backend.mvp_commerce.supplier_evidence.SupplierEvidenceResult`
  (no new evidence model).
- Does not replace `backend.mvp_commerce.opportunity.select_candidate` —
  that function, and the byte-identical default Commerce MVP path built on
  it, are untouched. `rank_opportunities()` is a separate, opt-in
  alternative selection path (see `runner.py::_select_with_ranking`).
- Emits events through the existing `backend.contracts.events.Event`/
  `backend.events.repository.EventRepository` system — no second event
  store (see `opportunity_scoring_events()`).

Scoring philosophy: every dimension below is computed *only* when a real
data source backs it. A dimension with no backing data is still reported
(never hidden) with `provenance="unavailable"`, `is_unknown=True`,
`raw_value=None`, and zero weight/contribution — it lowers the opportunity's
*confidence*, never fabricates a score. This mirrors exactly the
field-level provenance discipline already established in
`backend.adapters.research.cj_public_evidence.CJProductEvidence`.

Competition Intelligence integration (Phase 1 follow-on): `competition`/
`margin` are additive, `None`-default parameters on `score_opportunity()`/
`rank_opportunities()`, following the exact same pattern already
established for `supplier_evidence` — six market-evidence dimensions
(`market_saturation`, `price_competitiveness`, `supplier_advantage`,
`market_confidence`, `review_strength`, `offer_diversity`) are always
present in `_all_dimensions()`, resolving to `provenance="unavailable"`
when no `MarketIntelligenceReport`/`MarginIntelligence` is supplied — the
same "always computed, resolves to unavailable" pattern the supplier-
evidence dimensions (`supplier_evidence_quality`, `product_simplicity`,
etc.) already use. This replaces the old permanently-unavailable
`competition_estimate` placeholder (see `docs/OPPORTUNITY_SCORING.md` for
the full before/after). `category_stability` remains permanently
unavailable — Competition Intelligence observes pricing/saturation, not
category-level stability, and no data source for that exists.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from backend.contracts.events import Event

from .competition_intelligence import MarginIntelligence, MarketIntelligenceReport
from .opportunity import OpportunityCandidate
from .supplier_evidence import SupplierEvidenceResult

# Base weights among dimensions that ARE computed for a given candidate;
# renormalized to the subset actually available (see _composite). Unwritten
# rationale for each weight lives next to its compute function below.
_WEIGHTS: dict[str, float] = {
    "trend_strength": 30.0,
    "freshness": 15.0,
    "historical_evidence_quality": 15.0,
    "observed_information_completeness": 10.0,
    "supplier_evidence_quality": 20.0,
    "observed_supplier_cost": 5.0,
    "assumption_count": 5.0,
    "missing_data_penalty": 5.0,
    "category_stability": 10.0,
    "market_saturation": 10.0,
    "price_competitiveness": 10.0,
    "supplier_advantage": 10.0,
    "market_confidence": 5.0,
    "review_strength": 5.0,
    "offer_diversity": 5.0,
    "product_simplicity": 5.0,
    "shipping_complexity": 5.0,
    "weight_volume": 5.0,
    "variant_complexity": 5.0,
}

# Provenance -> confidence-tier weight (see _confidence). Assumed evidence
# is worth something but far less than observed; unknown is worth nothing.
_PROVENANCE_CONFIDENCE_WEIGHT = {"observed": 1.0, "derived": 0.7, "assumed": 0.35, "unavailable": 0.0}


@dataclass(frozen=True)
class ScoreDimension:
    name: str
    raw_value: float | None
    normalized_value: float | None  # 0-100, None when not computed
    weight: float                    # 0 when not computed
    contribution: float              # normalized_value * (renormalized weight), 0 when not computed
    reason: str
    provenance: str                  # "observed" | "derived" | "assumed" | "unavailable"
    is_unknown: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "raw_value": self.raw_value, "normalized_value": self.normalized_value,
            "weight": self.weight, "contribution": self.contribution, "reason": self.reason,
            "provenance": self.provenance, "is_unknown": self.is_unknown,
        }


@dataclass(frozen=True)
class OpportunityScore:
    candidate_id: str
    product_name: str
    dimensions: tuple[ScoreDimension, ...]
    composite_score: float           # 0-100, weighted mean of *available* dimensions only
    confidence: float                # 0-1
    observed_pct: float
    derived_pct: float
    assumed_pct: float
    unknown_pct: float
    reasons: tuple[str, ...]
    risks: tuple[str, ...]
    unknowns: tuple[str, ...]
    blockers: tuple[str, ...]
    recommended_action: str
    operator_override: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id, "product_name": self.product_name,
            "dimensions": [dimension.to_dict() for dimension in self.dimensions],
            "composite_score": self.composite_score, "confidence": self.confidence,
            "observed_pct": self.observed_pct, "derived_pct": self.derived_pct,
            "assumed_pct": self.assumed_pct, "unknown_pct": self.unknown_pct,
            "reasons": list(self.reasons), "risks": list(self.risks), "unknowns": list(self.unknowns),
            "blockers": list(self.blockers), "recommended_action": self.recommended_action,
            "operator_override": self.operator_override,
        }

    @property
    def effective_score(self) -> float:
        """The score ranking actually sorts on: an operator override, when
        present, replaces the computed composite outright — but the
        computed composite/dimensions are always preserved on the object
        for audit, never overwritten. See 'Operator Overrides' in
        docs/OPPORTUNITY_SCORING.md."""
        if self.operator_override and "score" in self.operator_override:
            return float(self.operator_override["score"])
        return self.composite_score


@dataclass(frozen=True)
class OpportunityAssessment:
    workspace_id: str
    query: str
    scores: tuple[OpportunityScore, ...]  # sorted best-first (effective_score desc, candidate_id asc)
    top_candidate_id: str | None
    generated_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id, "query": self.query,
            "scores": [score.to_dict() for score in self.scores],
            "top_candidate_id": self.top_candidate_id, "generated_at": self.generated_at,
        }


def _dim(name: str, raw: float | None, normalized: float | None, reason: str, provenance: str) -> ScoreDimension:
    is_unknown = provenance == "unavailable"
    return ScoreDimension(name, raw, normalized, 0.0, 0.0, reason, provenance, is_unknown)


def _trend_strength(candidate: OpportunityCandidate) -> ScoreDimension:
    # source_local_score is already 0-100 (backend/mvp_commerce/opportunity.py);
    # reused directly, never recomputed — this dimension IS that field.
    value = candidate.source_local_score
    return _dim("trend_strength", value, value,
                f"{candidate.source_count} attributed public signal(s), local score {value}", "derived")


def _freshness(candidate: OpportunityCandidate) -> ScoreDimension:
    value = candidate.recency_score
    reason = "signals observed at more than one distinct time" if value >= 100 else "signals cluster at a single observation time"
    return _dim("freshness", value, value, reason, "derived")


def _historical_evidence_quality(candidate: OpportunityCandidate) -> ScoreDimension:
    # source_count is a real, observed count of attributed public signals —
    # not a derived score. Capped at 100 via a bounded linear scale.
    normalized = min(100.0, candidate.source_count * 25.0)
    return _dim("historical_evidence_quality", float(candidate.source_count), normalized,
                f"{candidate.source_count} independently attributed source(s)", "observed")


def _observed_information_completeness(candidate: OpportunityCandidate) -> ScoreDimension:
    total = len(candidate.assumptions) + len(candidate.unknowns) + 1  # +1 avoids div-by-zero, keeps scale stable
    normalized = max(0.0, 100.0 - (len(candidate.assumptions) * 15.0 + len(candidate.unknowns) * 10.0))
    return _dim("observed_information_completeness", float(total), round(normalized, 2),
                f"{len(candidate.assumptions)} assumption(s), {len(candidate.unknowns)} unknown(s) on this candidate",
                "derived")


def _supplier_evidence_quality(evidence: SupplierEvidenceResult | None) -> ScoreDimension:
    if evidence is None or not evidence.ranking:
        return _dim("supplier_evidence_quality", None, None,
                     "no supplier evidence was gathered for this candidate", "unavailable")
    best = evidence.ranking[0]
    normalized = round(float(best["composite_score"]) * 100.0, 2)
    provenance = "observed" if evidence.evidence is not None else "assumed"
    return _dim("supplier_evidence_quality", float(best["composite_score"]), normalized,
                f"best CJ public-page candidate composite score {best['composite_score']}", provenance)


def _observed_supplier_cost(evidence: SupplierEvidenceResult | None) -> ScoreDimension:
    # This is a completeness dimension, not a "cheaper is better" judgment:
    # no competitor-pricing data source exists anywhere in this repository
    # to say what counts as a *good* price, so this only rewards having a
    # real observed cost at all (vs. an assumption) rather than guessing at
    # price attractiveness.
    if evidence is None or evidence.unit_cost is None:
        return _dim("observed_supplier_cost", None, None,
                     "no observed CJ supplier cost for this candidate", "unavailable")
    return _dim("observed_supplier_cost", evidence.unit_cost, 100.0,
                f"supplier unit cost observed: {evidence.unit_cost} (source={evidence.source_url})", "observed")


def _assumption_count(candidate: OpportunityCandidate) -> ScoreDimension:
    count = len(candidate.assumptions)
    normalized = max(0.0, 100.0 - count * 20.0)
    return _dim("assumption_count", float(count), normalized, f"{count} disclosed assumption(s)", "derived")


def _missing_data_penalty(candidate: OpportunityCandidate) -> ScoreDimension:
    count = len(candidate.unknowns)
    normalized = max(0.0, 100.0 - count * 20.0)
    return _dim("missing_data_penalty", float(count), normalized, f"{count} unresolved unknown(s)", "derived")


def _unavailable(name: str, reason: str) -> ScoreDimension:
    return _dim(name, None, None, reason, "unavailable")


def _product_simplicity(evidence: SupplierEvidenceResult | None) -> ScoreDimension:
    if evidence is None or evidence.evidence is None or evidence.evidence.field_status.get("variants") != "observed":
        return _unavailable("product_simplicity", "no observed variant data for this candidate's supplier evidence")
    variant_count = len(evidence.evidence.variants)
    normalized = max(0.0, 100.0 - variant_count * 10.0)
    return _dim("product_simplicity", float(variant_count), normalized, f"{variant_count} observed variant(s)", "observed")


def _shipping_complexity(evidence: SupplierEvidenceResult | None) -> ScoreDimension:
    if evidence is None or evidence.evidence is None:
        return _unavailable("shipping_complexity", "no supplier evidence gathered for this candidate")
    ev = evidence.evidence
    if ev.field_status.get("shipping_cost") != "observed" and ev.field_status.get("estimated_delivery_days") != "observed":
        return _unavailable("shipping_complexity", "shipping cost/delivery estimate not exposed by the supplier page")
    penalty = 0.0
    parts = []
    if ev.shipping_cost is not None:
        penalty += min(50.0, ev.shipping_cost * 5.0)
        parts.append(f"shipping cost {ev.shipping_cost}")
    if ev.estimated_delivery_days is not None:
        penalty += min(50.0, max(0.0, ev.estimated_delivery_days - 7) * 3.0)
        parts.append(f"{ev.estimated_delivery_days}-day estimated delivery")
    normalized = max(0.0, 100.0 - penalty)
    return _dim("shipping_complexity", penalty, round(normalized, 2), "; ".join(parts) or "observed shipping data", "observed")


def _weight_volume(evidence: SupplierEvidenceResult | None) -> ScoreDimension:
    if evidence is None or evidence.evidence is None or evidence.evidence.field_status.get("weight_kg") != "observed":
        return _unavailable("weight_volume", "no observed weight/dimension data for this candidate's supplier evidence")
    weight = evidence.evidence.weight_kg or 0.0
    normalized = max(0.0, 100.0 - weight * 10.0)
    return _dim("weight_volume", weight, round(normalized, 2), f"observed weight {weight}kg", "observed")


def _variant_complexity(evidence: SupplierEvidenceResult | None) -> ScoreDimension:
    if evidence is None or evidence.evidence is None or evidence.evidence.field_status.get("variants") != "observed":
        return _unavailable("variant_complexity", "no observed variant data for this candidate's supplier evidence")
    count = len(evidence.evidence.variants)
    normalized = max(0.0, 100.0 - count * 8.0)
    return _dim("variant_complexity", float(count), normalized, f"{count} observed variant option(s)", "observed")


def _market_saturation(competition: MarketIntelligenceReport | None) -> ScoreDimension:
    if competition is None or competition.market_saturation is None:
        return _unavailable("market_saturation", "no competition evidence gathered for this candidate")
    normalized = round(max(0.0, 100.0 - competition.market_saturation * 100.0), 2)
    provenance = "observed" if competition.observed_competitor_count > 0 else "derived"
    return _dim("market_saturation", competition.market_saturation, normalized,
                f"{competition.observed_competitor_count} observed competitor listing(s), saturation {competition.market_saturation}", provenance)


def _price_competitiveness(competition: MarketIntelligenceReport | None) -> ScoreDimension:
    # Room to price competitively, inferred from observed price dispersion
    # across competitors — not a judgment on any specific assumed price
    # (score_opportunity doesn't receive one), so this measures market
    # headroom, not "our price is good."
    if competition is None or not competition.observed_median_price or competition.observed_pricing_variance is None:
        return _unavailable("price_competitiveness", "no observed competitor pricing dispersion for this candidate")
    variance_ratio = competition.observed_pricing_variance / competition.observed_median_price
    normalized = round(min(100.0, variance_ratio * 200.0), 2)
    return _dim("price_competitiveness", round(variance_ratio, 4), normalized,
                f"observed price dispersion across {competition.observed_competitor_count} competitor(s): "
                f"variance={competition.observed_pricing_variance}, median={competition.observed_median_price}", "observed")


def _supplier_advantage(margin: MarginIntelligence | None) -> ScoreDimension:
    if margin is None or margin.observed_supplier_advantage is None:
        return _unavailable("supplier_advantage", "no observed margin/supplier-cost comparison for this candidate")
    normalized = round(max(0.0, min(100.0, margin.observed_supplier_advantage * 100.0)), 2)
    return _dim("supplier_advantage", margin.observed_supplier_advantage, normalized,
                f"observed supplier cost advantage vs cheapest observed competitor: {margin.observed_supplier_advantage}", "observed")


def _market_confidence(competition: MarketIntelligenceReport | None) -> ScoreDimension:
    if competition is None:
        return _unavailable("market_confidence", "no competition evidence gathered for this candidate")
    normalized = round(competition.confidence * 100.0, 2)
    return _dim("market_confidence", competition.confidence, normalized,
                f"market intelligence confidence {competition.confidence} from {len(competition.offers)} observed listing(s)", "derived")


def _review_strength(competition: MarketIntelligenceReport | None) -> ScoreDimension:
    if competition is None or (competition.observed_review_density is None and competition.observed_rating_mean is None):
        return _unavailable("review_strength", "no observed competitor rating/review data for this candidate")
    rating_component = (competition.observed_rating_mean / 5.0 * 100.0) if competition.observed_rating_mean is not None else 50.0
    density_component = min(100.0, (competition.observed_review_density or 0.0) / 2.0)
    normalized = round((rating_component + density_component) / 2, 2)
    return _dim("review_strength", competition.observed_rating_mean, normalized,
                f"observed competitor rating mean {competition.observed_rating_mean}, review density {competition.observed_review_density}", "observed")


def _offer_diversity(competition: MarketIntelligenceReport | None) -> ScoreDimension:
    # Consolidates the brief's separate "Offer Diversity"/"Brand
    # Concentration"/"Seller Concentration" dimensions into one — the
    # underlying brand/seller diversity ratios remain individually visible
    # on MarketIntelligenceReport for drill-down, avoiding near-duplicate
    # dimensions here.
    if competition is None or (competition.observed_brand_diversity is None and competition.observed_seller_diversity is None):
        return _unavailable("offer_diversity", "no observed brand/seller diversity data for this candidate")
    brand = competition.observed_brand_diversity or 0.0
    seller = competition.observed_seller_diversity or 0.0
    normalized = round(((brand + seller) / 2) * 100.0, 2)
    return _dim("offer_diversity", round((brand + seller) / 2, 4), normalized,
                f"observed brand diversity {competition.observed_brand_diversity}, seller diversity {competition.observed_seller_diversity}", "observed")


def _all_dimensions(
    candidate: OpportunityCandidate, evidence: SupplierEvidenceResult | None,
    competition: MarketIntelligenceReport | None = None, margin: MarginIntelligence | None = None,
) -> tuple[ScoreDimension, ...]:
    return (
        _trend_strength(candidate),
        _freshness(candidate),
        _historical_evidence_quality(candidate),
        _observed_information_completeness(candidate),
        _supplier_evidence_quality(evidence),
        _observed_supplier_cost(evidence),
        _assumption_count(candidate),
        _missing_data_penalty(candidate),
        _unavailable("category_stability", "no category-stability data source exists in this repository"),
        _market_saturation(competition),
        _price_competitiveness(competition),
        _supplier_advantage(margin),
        _market_confidence(competition),
        _review_strength(competition),
        _offer_diversity(competition),
        _product_simplicity(evidence),
        _shipping_complexity(evidence),
        _weight_volume(evidence),
        _variant_complexity(evidence),
    )


def _composite(dimensions: tuple[ScoreDimension, ...]) -> tuple[ScoreDimension, ...]:
    """Attach weight/contribution to each dimension, renormalizing base
    weights across only the dimensions that were actually computed (raw
    weight redistribution, not a silent zero-fill) — an unavailable
    dimension never drags the composite down or props it up."""
    available = [d for d in dimensions if not d.is_unknown]
    total_base_weight = sum(_WEIGHTS[d.name] for d in available) or 1.0
    updated = []
    for dimension in dimensions:
        if dimension.is_unknown:
            updated.append(dimension)
            continue
        weight = round(_WEIGHTS[dimension.name] / total_base_weight * 100.0, 4)
        contribution = round((dimension.normalized_value or 0.0) * weight / 100.0, 4)
        updated.append(ScoreDimension(dimension.name, dimension.raw_value, dimension.normalized_value,
                                       weight, contribution, dimension.reason, dimension.provenance, False))
    return tuple(updated)


def _confidence(dimensions: tuple[ScoreDimension, ...]) -> tuple[float, float, float, float, float]:
    """Returns (confidence, observed_pct, derived_pct, assumed_pct, unknown_pct).
    Tiered by provenance so an "unavailable" dimension reduces confidence
    without ever touching the composite score."""
    total = len(dimensions) or 1
    counts = {"observed": 0, "derived": 0, "assumed": 0, "unavailable": 0}
    for dimension in dimensions:
        counts[dimension.provenance] += 1
    observed_pct = round(counts["observed"] / total * 100.0, 2)
    derived_pct = round(counts["derived"] / total * 100.0, 2)
    assumed_pct = round(counts["assumed"] / total * 100.0, 2)
    unknown_pct = round(counts["unavailable"] / total * 100.0, 2)
    confidence = round(sum(_PROVENANCE_CONFIDENCE_WEIGHT[d.provenance] for d in dimensions) / total, 4)
    return confidence, observed_pct, derived_pct, assumed_pct, unknown_pct


def score_opportunity(
    candidate: OpportunityCandidate, *, supplier_evidence: SupplierEvidenceResult | None = None,
    competition_evidence: MarketIntelligenceReport | None = None, margin: MarginIntelligence | None = None,
    operator_override: dict[str, Any] | None = None,
) -> OpportunityScore:
    """Never raises. Deterministic given identical inputs."""
    dimensions = _composite(_all_dimensions(candidate, supplier_evidence, competition_evidence, margin))
    composite = round(sum(d.contribution for d in dimensions), 2)
    confidence, observed_pct, derived_pct, assumed_pct, unknown_pct = _confidence(dimensions)

    reasons = tuple(f"{d.name}: {d.reason}" for d in sorted(
        (d for d in dimensions if not d.is_unknown), key=lambda d: -d.contribution)[:3])
    risks = tuple(f"{d.name} is low ({d.normalized_value})" for d in dimensions
                  if not d.is_unknown and d.normalized_value is not None and d.normalized_value < 40.0)
    unknowns = tuple(f"{d.name}: {d.reason}" for d in dimensions if d.is_unknown)
    blockers = tuple(candidate.cannot_claim)

    if confidence >= 0.6 and composite >= 60.0:
        action = "advance_to_economics_review"
    elif confidence < 0.3:
        action = "gather_more_evidence_before_any_decision"
    else:
        action = "corroborate_before_advancing"

    return OpportunityScore(
        candidate.candidate_id, candidate.product_name, dimensions, composite, confidence,
        observed_pct, derived_pct, assumed_pct, unknown_pct, reasons, risks, unknowns, blockers, action,
        operator_override,
    )


def rank_opportunities(
    candidates: list[OpportunityCandidate], *, workspace_id: str, query: str,
    supplier_evidence_by_candidate: dict[str, SupplierEvidenceResult] | None = None,
    competition_evidence_by_candidate: dict[str, MarketIntelligenceReport] | None = None,
    margin_by_candidate: dict[str, MarginIntelligence] | None = None,
    operator_overrides: dict[str, dict[str, Any]] | None = None, generated_at: float | None = None,
) -> OpportunityAssessment:
    """Never raises. Deterministic given identical inputs: ties in
    effective_score break on candidate_id ascending, matching the existing
    tie-break convention in backend.mvp_commerce.opportunity.select_candidate."""
    evidence_map = supplier_evidence_by_candidate or {}
    competition_map = competition_evidence_by_candidate or {}
    margin_map = margin_by_candidate or {}
    override_map = operator_overrides or {}
    scores = [
        score_opportunity(
            candidate, supplier_evidence=evidence_map.get(candidate.candidate_id),
            competition_evidence=competition_map.get(candidate.candidate_id), margin=margin_map.get(candidate.candidate_id),
            operator_override=override_map.get(candidate.candidate_id),
        )
        for candidate in candidates
    ]
    scores.sort(key=lambda score: (-score.effective_score, score.candidate_id))
    top = scores[0].candidate_id if scores else None
    return OpportunityAssessment(workspace_id, query, tuple(scores), top, generated_at if generated_at is not None else time.time())


# -- canonical events ---------------------------------------------------

_EVENT_METADATA = {
    "dry_run": True, "advisory": True, "non_authoritative": True,
    "no_launch_authority": True, "no_spend_authority": True, "no_order_authority": True,
}


def opportunity_scoring_events(assessment: OpportunityAssessment, *, run_id: str) -> list[Event]:
    """Follows the exact shape established by
    backend.signals.public_sources.public_signal_event and
    backend.mvp_commerce.supplier_evidence.supplier_evidence_events — its
    own event-type set, not an extension of commerce_mvp_events()'s
    _EVENTS tuple (same precedent that module's own events already set)."""
    import hashlib

    def _event_id(suffix: str) -> str:
        return "opportunity-scoring-" + hashlib.sha256(f"{run_id}:{suffix}".encode()).hexdigest()[:20]

    events = [Event(
        _event_id("started"), assessment.workspace_id, "commerce_mvp_run", run_id,
        "opportunity_scoring_started", 1, assessment.generated_at, correlation_id=run_id,
        source="backend.mvp_commerce.opportunity_scoring",
        payload={"candidate_count": len(assessment.scores), "query": assessment.query}, metadata=_EVENT_METADATA,
    )]
    for index, score in enumerate(assessment.scores):
        events.append(Event(
            _event_id(f"scored:{score.candidate_id}"), assessment.workspace_id, "opportunity_candidate",
            score.candidate_id, "candidate_scored", 1, assessment.generated_at + (index + 1) / 1000,
            correlation_id=run_id, source="backend.mvp_commerce.opportunity_scoring",
            payload=score.to_dict(), metadata=_EVENT_METADATA,
        ))
    events.append(Event(
        _event_id("ranked"), assessment.workspace_id, "commerce_mvp_run", run_id,
        "opportunity_ranked", 1, assessment.generated_at + (len(assessment.scores) + 1) / 1000,
        correlation_id=run_id, source="backend.mvp_commerce.opportunity_scoring",
        payload={"top_candidate_id": assessment.top_candidate_id,
                 "ranking": [score.candidate_id for score in assessment.scores]},
        metadata=_EVENT_METADATA,
    ))
    events.append(Event(
        _event_id("completed"), assessment.workspace_id, "commerce_mvp_run", run_id,
        "opportunity_scoring_completed", 1, assessment.generated_at + (len(assessment.scores) + 2) / 1000,
        correlation_id=run_id, source="backend.mvp_commerce.opportunity_scoring",
        payload={"top_candidate_id": assessment.top_candidate_id}, metadata=_EVENT_METADATA,
    ))
    return events


__all__ = [
    "OpportunityAssessment", "OpportunityScore", "ScoreDimension",
    "opportunity_scoring_events", "rank_opportunities", "score_opportunity",
]

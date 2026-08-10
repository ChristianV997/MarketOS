"""backend.mvp_commerce.product_research — the Product Research
Intelligence Engine: candidate aggregation, deterministic identity
resolution, clustering, and portfolio construction sitting above
Opportunity Scoring.

Pipeline this module fills in — large-scale candidate discovery and
prioritization, the capability the existing single-candidate pipeline
never had:

    Public Signals -> Supplier Evidence -> Competition Intelligence ->
    Opportunity Scoring -> Product Research (this module) -> Commerce MVP

Composes through existing architecture only:

- `ResearchCandidate` *wraps* (never duplicates)
  `backend.mvp_commerce.opportunity.OpportunityCandidate`,
  `backend.mvp_commerce.opportunity_scoring.OpportunityScore`,
  `backend.mvp_commerce.supplier_evidence.SupplierEvidenceResult`, and
  `backend.mvp_commerce.competition_intelligence.MarketIntelligenceReport`
  — no new candidate/scoring/evidence model. Scoring itself is never
  recomputed here; this module only aggregates, groups, and buckets
  scores `opportunity_scoring.py` already produced.
- Emits events through the existing `backend.contracts.events.Event`/
  `backend.events.repository.EventRepository` system — its own event-type
  set, following the exact precedent `supplier_evidence_events()`/
  `opportunity_scoring_events()`/`competition_intelligence_events()`
  already set.
- `run_commerce_mvp_slice(..., research_portfolio=None)` only *consumes* an
  already-built `ResearchPortfolio` (see runner.py) — this module never
  orchestrates evidence-gathering itself; the caller (CLI, or a future
  API path) builds candidates/evidence/portfolio and hands the finished
  portfolio to the runner, exactly the same "additive, None-default"
  pattern `supplier_evidence`/`competition_evidence` already established.

Not the same thing as `backend.commercial.product_research.run_product_research()`:
that is a small, separate, explicitly-unconnected placeholder scaffold
("status: not_connected" on every evidence field) in an unrelated package
(`backend/commercial/`, not `backend/mvp_commerce/`) with no dataclasses,
events, or evidence aggregation of its own — a different, older, disused
surface. This module is the actually-wired Product Research Intelligence
Engine for the Commerce MVP pipeline and never touches that file.

Identity resolution philosophy: deterministic, stdlib-plus-scikit-learn
(already a pinned dependency — see docs/PRODUCT_RESEARCH.md's OSS research
section for what was evaluated and why nothing new was installed), never
merges two products below an explicit similarity threshold. An uncertain
match stays two separate candidates, never a silent merge.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any

from backend.contracts.events import Event

from .competition_intelligence import MarketIntelligenceReport
from .opportunity import OpportunityCandidate
from .opportunity_scoring import OpportunityScore
from .supplier_evidence import SupplierEvidenceResult

_STOPWORDS = frozenset({"the", "a", "an", "for", "with", "of", "and", "to", "in", "on", "by"})
_BRAND_SUFFIXES = ("inc", "llc", "co", "ltd", "corp", "company", "group")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalize_title(title: str) -> str:
    """Lowercase, strip punctuation, drop stopwords, collapse whitespace.
    Deterministic and reversible-in-spirit only for comparison — never
    used as a display value."""
    tokens = [token for token in _TOKEN_RE.findall((title or "").lower()) if token not in _STOPWORDS]
    return " ".join(tokens)


def normalize_brand(brand: str) -> str:
    tokens = [token for token in _TOKEN_RE.findall((brand or "").lower()) if token not in _BRAND_SUFFIXES]
    return " ".join(tokens)


def normalize_category(category: str) -> str:
    value = (category or "").strip().lower()
    value = re.sub(r"[^a-z0-9\s]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _similarity_matrix(titles: list[str]) -> list[list[float]]:
    """Deterministic pairwise title similarity via scikit-learn's
    char-n-gram TF-IDF + cosine similarity — see docs/PRODUCT_RESEARCH.md
    for why this was chosen over adding a new fuzzy-matching dependency
    (scikit-learn is already pinned in requirements.txt for other
    subsystems in this repository). No randomness: identical inputs always
    produce an identical matrix."""
    count = len(titles)
    if count == 0:
        return []
    if count == 1:
        return [[1.0]]
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    non_empty = [title if title.strip() else "unnamed" for title in titles]
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
    matrix = vectorizer.fit_transform(non_empty)
    similarity = cosine_similarity(matrix)
    return [[round(float(similarity[i][j]), 4) for j in range(count)] for i in range(count)]


@dataclass(frozen=True)
class ProductIdentity:
    candidate_id: str
    normalized_title: str
    normalized_brand: str
    normalized_category: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id, "normalized_title": self.normalized_title,
            "normalized_brand": self.normalized_brand, "normalized_category": self.normalized_category,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ResearchCandidate:
    """One aggregated research candidate: composes evidence from as many
    or as few sources as have actually been gathered, without coupling to
    any one provider. `additional_evidence` is a deliberately generic bag
    (e.g. a Shopify read-only context snippet) so a future source can be
    attached without changing this dataclass's shape."""

    candidate_id: str
    opportunity_candidate: OpportunityCandidate
    opportunity_score: OpportunityScore | None = None
    supplier_evidence: SupplierEvidenceResult | None = None
    competition_evidence: MarketIntelligenceReport | None = None
    additional_evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "opportunity_candidate": self.opportunity_candidate.to_dict(),
            "opportunity_score": self.opportunity_score.to_dict() if self.opportunity_score else None,
            "has_supplier_evidence": self.supplier_evidence is not None,
            "has_competition_evidence": self.competition_evidence is not None,
            "additional_evidence_keys": sorted(self.additional_evidence),
        }


def build_research_candidates(
    candidates: list[OpportunityCandidate], *,
    scores_by_id: dict[str, OpportunityScore] | None = None,
    supplier_evidence_by_id: dict[str, SupplierEvidenceResult] | None = None,
    competition_evidence_by_id: dict[str, MarketIntelligenceReport] | None = None,
    additional_evidence_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[ResearchCandidate]:
    """Never raises. Pure aggregation — no fetching, no scoring; every
    input map defaults to empty so a candidate with no gathered evidence
    yet is still a valid, honestly-thin ResearchCandidate."""
    scores = scores_by_id or {}
    supplier = supplier_evidence_by_id or {}
    competition = competition_evidence_by_id or {}
    additional = additional_evidence_by_id or {}
    return [
        ResearchCandidate(
            candidate.candidate_id, candidate, scores.get(candidate.candidate_id),
            supplier.get(candidate.candidate_id), competition.get(candidate.candidate_id),
            dict(additional.get(candidate.candidate_id, {})),
        )
        for candidate in candidates
    ]


def resolve_identity(candidate: ResearchCandidate) -> ProductIdentity:
    """Never raises. Deterministic. Confidence reflects how much of the
    identity actually came from real fields (title/brand/category) versus
    being empty — never a guess at similarity itself."""
    title = normalize_title(candidate.opportunity_candidate.product_name)
    brand = ""
    if candidate.competition_evidence is not None and candidate.competition_evidence.offers:
        brand = normalize_brand(candidate.competition_evidence.offers[0].brand)
    category = normalize_category(candidate.opportunity_candidate.category_name)
    fields_present = sum(1 for value in (title, brand, category) if value)
    confidence = round(fields_present / 3, 4)
    return ProductIdentity(candidate.candidate_id, title, brand, category, confidence)


@dataclass(frozen=True)
class DuplicateGroup:
    group_id: str
    member_ids: tuple[str, ...]
    representative_id: str
    similarity_score: float
    confidence: float
    kind: str  # "duplicate" | "variant" | "unique"
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id, "member_ids": list(self.member_ids),
            "representative_id": self.representative_id, "similarity_score": self.similarity_score,
            "confidence": self.confidence, "kind": self.kind, "reason": self.reason,
        }


def _connected_components(count: int, edges: list[tuple[int, int]]) -> list[list[int]]:
    parent = list(range(count))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[max(root_a, root_b)] = min(root_a, root_b)

    for a, b in edges:
        union(a, b)
    groups: dict[int, list[int]] = {}
    for index in range(count):
        groups.setdefault(find(index), []).append(index)
    return [sorted(members) for members in sorted(groups.values(), key=lambda members: members[0])]


def group_duplicates(candidates: list[ResearchCandidate], *, duplicate_threshold: float = 0.85, variant_threshold: float = 0.55) -> list[DuplicateGroup]:
    """Deterministic, threshold-gated grouping. Never merges two products
    below `variant_threshold` — anything below stays its own singleton
    "unique" group. `duplicate_threshold` gates "duplicate" (near-identical
    listings of the same product) versus "variant" (same family, distinct
    product — e.g. a battery vs. manual espresso maker)."""
    if not candidates:
        return []
    identities = [resolve_identity(candidate) for candidate in candidates]
    titles = [identity.normalized_title for identity in identities]
    matrix = _similarity_matrix(titles)
    edges = [
        (i, j) for i in range(len(candidates)) for j in range(i + 1, len(candidates))
        if matrix[i][j] >= variant_threshold and (
            identities[i].normalized_brand == identities[j].normalized_brand or not identities[i].normalized_brand or not identities[j].normalized_brand
        )
    ]
    components = _connected_components(len(candidates), edges)
    groups: list[DuplicateGroup] = []
    for members in components:
        member_ids = tuple(candidates[index].candidate_id for index in members)
        if len(members) == 1:
            groups.append(DuplicateGroup(
                f"dup-{hashlib.sha256('|'.join(member_ids).encode()).hexdigest()[:12]}",
                member_ids, member_ids[0], 1.0, identities[members[0]].confidence, "unique",
                "no similar candidate found above the variant threshold",
            ))
            continue
        pair_scores = [matrix[a][b] for a in members for b in members if a < b]
        avg_similarity = round(sum(pair_scores) / len(pair_scores), 4) if pair_scores else 0.0
        kind = "duplicate" if avg_similarity >= duplicate_threshold else "variant"
        representative = min(member_ids)
        confidence = round(min(identities[index].confidence for index in members) * avg_similarity, 4)
        groups.append(DuplicateGroup(
            f"dup-{hashlib.sha256('|'.join(sorted(member_ids)).encode()).hexdigest()[:12]}",
            member_ids, representative, avg_similarity, confidence, kind,
            f"{len(member_ids)} candidates with average title similarity {avg_similarity}",
        ))
    return groups


@dataclass(frozen=True)
class ProductCluster:
    cluster_id: str
    name: str
    member_ids: tuple[str, ...]
    representative_id: str
    confidence: float
    common_attributes: dict[str, Any]
    price_range: dict[str, float | None]
    supplier_diversity: int
    competition_diversity: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id, "name": self.name, "member_ids": list(self.member_ids),
            "representative_id": self.representative_id, "confidence": self.confidence,
            "common_attributes": dict(self.common_attributes), "price_range": dict(self.price_range),
            "supplier_diversity": self.supplier_diversity, "competition_diversity": self.competition_diversity,
        }


def _observed_prices(candidate: ResearchCandidate) -> list[float]:
    prices: list[float] = []
    if candidate.supplier_evidence is not None and candidate.supplier_evidence.unit_cost is not None:
        prices.append(candidate.supplier_evidence.unit_cost)
    if candidate.competition_evidence is not None and candidate.competition_evidence.observed_median_price is not None:
        prices.append(candidate.competition_evidence.observed_median_price)
    return prices


def build_clusters(candidates: list[ResearchCandidate], *, threshold: float = 0.55) -> list[ProductCluster]:
    """Never raises. Connected-component clustering by title similarity —
    deterministic, sorted output.

    Deliberately does NOT partition by `OpportunityCandidate.category_name`
    first: in this pipeline that field is always the constant
    `"public_signal_hypothesis"` (a source-type tag from
    `backend.mvp_commerce.opportunity.build_opportunity_candidates_from_signals`,
    not a real product taxonomy) — partitioning on it would put every
    candidate in one meaningless bucket and silently mask the real
    grouping signal. `normalize_category()` still processes whatever value
    is present (so a future evidence source with a real category
    populates `common_attributes` correctly), but clustering itself relies
    on title similarity alone until a real category signal exists — see
    docs/PRODUCT_RESEARCH.md."""
    if not candidates:
        return []
    identities = {candidate.candidate_id: resolve_identity(candidate) for candidate in candidates}
    titles = [identities[candidate.candidate_id].normalized_title for candidate in candidates]
    matrix = _similarity_matrix(titles)
    edges = [(i, j) for i in range(len(candidates)) for j in range(i + 1, len(candidates)) if matrix[i][j] >= threshold]

    clusters: list[ProductCluster] = []
    for component in _connected_components(len(candidates), edges):
        member_candidates = [candidates[index] for index in component]
        member_ids = tuple(sorted(item.candidate_id for item in member_candidates))
        representative = min(member_ids)
        brands = {identities[item.candidate_id].normalized_brand for item in member_candidates if identities[item.candidate_id].normalized_brand}
        categories = {identities[item.candidate_id].normalized_category for item in member_candidates if identities[item.candidate_id].normalized_category}
        prices = [price for item in member_candidates for price in _observed_prices(item)]
        suppliers = {item.supplier_evidence.supplier for item in member_candidates if item.supplier_evidence is not None}
        competitors = {offer.source for item in member_candidates if item.competition_evidence is not None for offer in item.competition_evidence.offers}
        pair_scores = [matrix[a][b] for a in component for b in component if a < b] or [1.0]
        confidence = round(sum(pair_scores) / len(pair_scores), 4)
        representative_title = identities[representative].normalized_title
        name = " ".join(representative_title.split(" ")[:3]) if representative_title else "unnamed cluster"
        clusters.append(ProductCluster(
            f"cluster-{hashlib.sha256('|'.join(member_ids).encode()).hexdigest()[:12]}", name, member_ids,
            representative, confidence, {"category_tags": sorted(categories), "brands": sorted(brands)},
            {"min": round(min(prices), 2) if prices else None, "max": round(max(prices), 2) if prices else None,
             "median": round(sorted(prices)[len(prices) // 2], 2) if prices else None},
            len(suppliers), len(competitors),
        ))
    return sorted(clusters, key=lambda cluster: cluster.cluster_id)


@dataclass(frozen=True)
class ResearchQuality:
    evidence_coverage: float
    supplier_coverage: float
    competition_coverage: float
    observed_pricing_coverage: float
    market_confidence: float
    research_completeness: float
    unknown_ratio: float
    research_freshness: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_coverage": self.evidence_coverage, "supplier_coverage": self.supplier_coverage,
            "competition_coverage": self.competition_coverage, "observed_pricing_coverage": self.observed_pricing_coverage,
            "market_confidence": self.market_confidence, "research_completeness": self.research_completeness,
            "unknown_ratio": self.unknown_ratio, "research_freshness": self.research_freshness,
        }


def compute_research_quality(candidates: list[ResearchCandidate], *, now: float | None = None, freshness_window_s: float = 3600.0) -> ResearchQuality:
    """Never raises; every field computed from real counts. Empty input
    yields all-zero coverage (never a fabricated default)."""
    total = len(candidates)
    if total == 0:
        return ResearchQuality(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    has_supplier = sum(1 for item in candidates if item.supplier_evidence is not None and item.supplier_evidence.unit_cost is not None)
    has_competition = sum(1 for item in candidates if item.competition_evidence is not None and item.competition_evidence.offers)
    has_any_evidence = sum(1 for item in candidates if (item.supplier_evidence is not None and item.supplier_evidence.unit_cost is not None) or (item.competition_evidence is not None and item.competition_evidence.offers))
    has_pricing = sum(1 for item in candidates if _observed_prices(item))
    market_confidences = [item.competition_evidence.confidence for item in candidates if item.competition_evidence is not None]
    unknown_pcts = [item.opportunity_score.unknown_pct for item in candidates if item.opportunity_score is not None]
    when = now if now is not None else time.time()
    timestamps = [item.competition_evidence.generated_at for item in candidates if item.competition_evidence is not None]
    fresh = sum(1 for ts in timestamps if when - ts <= freshness_window_s)

    supplier_coverage = round(has_supplier / total, 4)
    competition_coverage = round(has_competition / total, 4)
    evidence_coverage = round(has_any_evidence / total, 4)
    pricing_coverage = round(has_pricing / total, 4)
    market_confidence = round(sum(market_confidences) / len(market_confidences), 4) if market_confidences else 0.0
    unknown_ratio = round(sum(unknown_pcts) / len(unknown_pcts) / 100.0, 4) if unknown_pcts else 1.0
    completeness = round((evidence_coverage + supplier_coverage + competition_coverage + pricing_coverage) / 4, 4)
    freshness = round(fresh / len(timestamps), 4) if timestamps else 0.0
    return ResearchQuality(evidence_coverage, supplier_coverage, competition_coverage, pricing_coverage, market_confidence, completeness, unknown_ratio, freshness)


@dataclass(frozen=True)
class PortfolioBucketEntry:
    candidate_id: str
    product_name: str
    composite_score: float | None
    confidence: float | None
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id, "product_name": self.product_name,
            "composite_score": self.composite_score, "confidence": self.confidence, "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class ResearchPortfolio:
    workspace_id: str
    query: str
    generated_at: float
    candidate_ids: tuple[str, ...]
    clusters: tuple[ProductCluster, ...]
    duplicate_groups: tuple[DuplicateGroup, ...]
    quality: ResearchQuality
    top_opportunities: tuple[PortfolioBucketEntry, ...]
    emerging_opportunities: tuple[PortfolioBucketEntry, ...]
    undervalued_opportunities: tuple[PortfolioBucketEntry, ...]
    high_risk_opportunities: tuple[PortfolioBucketEntry, ...]
    high_uncertainty_opportunities: tuple[PortfolioBucketEntry, ...]
    rejected_candidates: tuple[PortfolioBucketEntry, ...]
    top_candidate_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id, "query": self.query, "generated_at": self.generated_at,
            "candidate_ids": list(self.candidate_ids),
            "clusters": [item.to_dict() for item in self.clusters],
            "duplicate_groups": [item.to_dict() for item in self.duplicate_groups],
            "quality": self.quality.to_dict(),
            "top_opportunities": [item.to_dict() for item in self.top_opportunities],
            "emerging_opportunities": [item.to_dict() for item in self.emerging_opportunities],
            "undervalued_opportunities": [item.to_dict() for item in self.undervalued_opportunities],
            "high_risk_opportunities": [item.to_dict() for item in self.high_risk_opportunities],
            "high_uncertainty_opportunities": [item.to_dict() for item in self.high_uncertainty_opportunities],
            "rejected_candidates": [item.to_dict() for item in self.rejected_candidates],
            "top_candidate_id": self.top_candidate_id,
        }


def _entry(candidate: ResearchCandidate) -> PortfolioBucketEntry:
    score = candidate.opportunity_score
    reasons = score.reasons if score else (candidate.opportunity_candidate.cannot_claim or ("not yet scored",))
    return PortfolioBucketEntry(
        candidate.candidate_id, candidate.opportunity_candidate.product_name,
        score.composite_score if score else None, score.confidence if score else None, tuple(reasons),
    )


def build_research_portfolio(candidates: list[ResearchCandidate], *, workspace_id: str, query: str, generated_at: float | None = None) -> ResearchPortfolio:
    """Never raises. Buckets are mutually exclusive per candidate — every
    candidate lands in exactly one bucket, evaluated in this priority
    order: high_uncertainty (confidence < 0.3 or unscored) -> top
    (score>=60, confidence>=0.6) -> undervalued (strong observed margin,
    not yet top) -> high_risk (real risks flagged) -> emerging (score>=50)
    -> rejected (everything else, including blocked candidates)."""
    when = generated_at if generated_at is not None else time.time()
    clusters = build_clusters(candidates)
    duplicate_groups = group_duplicates(candidates)
    quality = compute_research_quality(candidates, now=when)

    top: list[PortfolioBucketEntry] = []
    emerging: list[PortfolioBucketEntry] = []
    undervalued: list[PortfolioBucketEntry] = []
    high_risk: list[PortfolioBucketEntry] = []
    high_uncertainty: list[PortfolioBucketEntry] = []
    rejected: list[PortfolioBucketEntry] = []

    for candidate in candidates:
        score = candidate.opportunity_score
        entry = _entry(candidate)
        margin_dims = {d.name: d for d in score.dimensions} if score else {}
        supplier_advantage = margin_dims.get("supplier_advantage")
        has_strong_advantage = supplier_advantage is not None and not supplier_advantage.is_unknown and (supplier_advantage.raw_value or 0.0) >= 0.4
        if score is None or score.confidence < 0.3:
            high_uncertainty.append(entry)
        elif score.composite_score >= 60.0 and score.confidence >= 0.6:
            top.append(entry)
        elif has_strong_advantage and score.composite_score < 60.0:
            undervalued.append(entry)
        elif score.risks:
            high_risk.append(entry)
        elif score.composite_score >= 50.0:
            emerging.append(entry)
        else:
            rejected.append(entry)

    def _sorted(entries: list[PortfolioBucketEntry]) -> tuple[PortfolioBucketEntry, ...]:
        return tuple(sorted(entries, key=lambda item: (-(item.composite_score or 0.0), item.candidate_id)))

    top_sorted, emerging_sorted, undervalued_sorted, high_risk_sorted = _sorted(top), _sorted(emerging), _sorted(undervalued), _sorted(high_risk)
    # top_candidate_id prefers a genuine top_opportunities pick, but falls
    # back through the other still-advanceable buckets (never
    # high_uncertainty/rejected, which are explicitly "do not advance yet")
    # so a portfolio without a confidently-top candidate can still hand
    # Commerce MVP a usable, honestly-reasoned selection.
    for bucket in (top_sorted, undervalued_sorted, high_risk_sorted, emerging_sorted):
        if bucket:
            top_candidate_id = bucket[0].candidate_id
            break
    else:
        top_candidate_id = None
    return ResearchPortfolio(
        workspace_id, query, when, tuple(candidate.candidate_id for candidate in candidates),
        tuple(clusters), tuple(duplicate_groups), quality,
        top_sorted, emerging_sorted, undervalued_sorted, high_risk_sorted, _sorted(high_uncertainty), _sorted(rejected),
        top_candidate_id,
    )


@dataclass(frozen=True)
class PortfolioMovement:
    candidate_id: str
    score_delta: float | None
    confidence_delta: float | None
    rank_delta: int | None
    change_kind: str  # "new" | "removed" | "improved" | "declined" | "unchanged"

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id, "score_delta": self.score_delta,
            "confidence_delta": self.confidence_delta, "rank_delta": self.rank_delta, "change_kind": self.change_kind,
        }


@dataclass(frozen=True)
class PortfolioComparison:
    workspace_id: str
    query: str
    previous_generated_at: float
    current_generated_at: float
    movements: tuple[PortfolioMovement, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id, "query": self.query,
            "previous_generated_at": self.previous_generated_at, "current_generated_at": self.current_generated_at,
            "movements": [item.to_dict() for item in self.movements],
        }


def _bucket_index(portfolio: ResearchPortfolio, candidate_id: str) -> int | None:
    for index, entry in enumerate(portfolio.top_opportunities):
        if entry.candidate_id == candidate_id:
            return index
    return None


def _bucket_entry(portfolio: ResearchPortfolio, candidate_id: str) -> PortfolioBucketEntry | None:
    for bucket in (portfolio.top_opportunities, portfolio.emerging_opportunities, portfolio.undervalued_opportunities,
                   portfolio.high_risk_opportunities, portfolio.high_uncertainty_opportunities, portfolio.rejected_candidates):
        for entry in bucket:
            if entry.candidate_id == candidate_id:
                return entry
    return None


def compare_portfolios(previous: ResearchPortfolio, current: ResearchPortfolio) -> PortfolioComparison:
    """Never raises. Deterministic diff over the union of candidate IDs —
    this is stateless: the caller supplies two already-built portfolios
    (e.g. replayed from two JSONL research_portfolio_updated events); no
    database or hidden persistence is introduced."""
    all_ids = sorted(set(previous.candidate_ids) | set(current.candidate_ids))
    movements: list[PortfolioMovement] = []
    for candidate_id in all_ids:
        prev_entry = _bucket_entry(previous, candidate_id)
        curr_entry = _bucket_entry(current, candidate_id)
        if prev_entry is None and curr_entry is not None:
            movements.append(PortfolioMovement(candidate_id, None, None, None, "new"))
            continue
        if prev_entry is not None and curr_entry is None:
            movements.append(PortfolioMovement(candidate_id, None, None, None, "removed"))
            continue
        assert prev_entry is not None and curr_entry is not None
        score_delta = None
        if prev_entry.composite_score is not None and curr_entry.composite_score is not None:
            score_delta = round(curr_entry.composite_score - prev_entry.composite_score, 2)
        confidence_delta = None
        if prev_entry.confidence is not None and curr_entry.confidence is not None:
            confidence_delta = round(curr_entry.confidence - prev_entry.confidence, 4)
        prev_rank, curr_rank = _bucket_index(previous, candidate_id), _bucket_index(current, candidate_id)
        rank_delta = (prev_rank - curr_rank) if prev_rank is not None and curr_rank is not None else None
        if score_delta is not None and score_delta > 0:
            kind = "improved"
        elif score_delta is not None and score_delta < 0:
            kind = "declined"
        else:
            kind = "unchanged"
        movements.append(PortfolioMovement(candidate_id, score_delta, confidence_delta, rank_delta, kind))
    return PortfolioComparison(previous.workspace_id, previous.query, previous.generated_at, current.generated_at, tuple(movements))


# -- canonical events ---------------------------------------------------

_EVENT_METADATA = {
    "dry_run": True, "advisory": True, "non_authoritative": True,
    "no_launch_authority": True, "no_spend_authority": True, "no_order_authority": True,
}


def product_research_events(
    portfolio: ResearchPortfolio, candidates: list[ResearchCandidate], *, run_id: str, comparison: PortfolioComparison | None = None,
) -> list[Event]:
    """Follows the exact shape established by opportunity_scoring_events()/
    competition_intelligence_events(): its own event-type set. Emitted by
    whoever *built* the portfolio (see module docstring) — run_commerce_mvp_slice
    only consumes an already-built portfolio and does not re-emit these."""

    def _event_id(suffix: str) -> str:
        return "product-research-" + hashlib.sha256(f"{run_id}:{suffix}".encode()).hexdigest()[:20]

    events: list[Event] = [Event(
        _event_id(f"discovered:{candidate.candidate_id}"), portfolio.workspace_id, "opportunity_candidate",
        candidate.candidate_id, "candidate_discovered", 1, portfolio.generated_at, correlation_id=run_id,
        source="backend.mvp_commerce.product_research", payload=candidate.to_dict(), metadata=_EVENT_METADATA,
    ) for candidate in candidates]
    events.extend(Event(
        _event_id(f"clustered:{cluster.cluster_id}"), portfolio.workspace_id, "product_cluster", cluster.cluster_id,
        "candidate_clustered", 1, portfolio.generated_at + 0.001, correlation_id=run_id,
        source="backend.mvp_commerce.product_research", payload=cluster.to_dict(), metadata=_EVENT_METADATA,
    ) for cluster in portfolio.clusters)
    events.append(Event(
        _event_id("portfolio"), portfolio.workspace_id, "commerce_mvp_run", run_id, "research_portfolio_updated", 1,
        portfolio.generated_at + 0.002, correlation_id=run_id, source="backend.mvp_commerce.product_research",
        payload={
            "candidate_count": len(portfolio.candidate_ids), "cluster_count": len(portfolio.clusters),
            "top_candidate_id": portfolio.top_candidate_id, "quality": portfolio.quality.to_dict(),
            "bucket_counts": {
                "top_opportunities": len(portfolio.top_opportunities), "emerging_opportunities": len(portfolio.emerging_opportunities),
                "undervalued_opportunities": len(portfolio.undervalued_opportunities), "high_risk_opportunities": len(portfolio.high_risk_opportunities),
                "high_uncertainty_opportunities": len(portfolio.high_uncertainty_opportunities), "rejected_candidates": len(portfolio.rejected_candidates),
            },
        }, metadata=_EVENT_METADATA,
    ))
    if comparison is not None:
        events.extend(Event(
            _event_id(f"ranked:{movement.candidate_id}"), portfolio.workspace_id, "opportunity_candidate",
            movement.candidate_id, "ranking_changed", 1, portfolio.generated_at + 0.003, correlation_id=run_id,
            source="backend.mvp_commerce.product_research", payload=movement.to_dict(), metadata=_EVENT_METADATA,
        ) for movement in comparison.movements if movement.change_kind != "unchanged")
    events.append(Event(
        _event_id("completed"), portfolio.workspace_id, "commerce_mvp_run", run_id, "research_completed", 1,
        portfolio.generated_at + 0.004, correlation_id=run_id, source="backend.mvp_commerce.product_research",
        payload={"top_candidate_id": portfolio.top_candidate_id, "candidate_count": len(portfolio.candidate_ids)},
        metadata=_EVENT_METADATA,
    ))
    return events


__all__ = [
    "DuplicateGroup", "PortfolioBucketEntry", "PortfolioComparison", "PortfolioMovement", "ProductCluster",
    "ProductIdentity", "ResearchCandidate", "ResearchPortfolio", "ResearchQuality",
    "build_clusters", "build_research_candidates", "build_research_portfolio", "compare_portfolios",
    "compute_research_quality", "group_duplicates", "normalize_brand", "normalize_category", "normalize_title",
    "product_research_events", "resolve_identity",
]

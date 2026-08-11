"""Offline marketplace-native demand and pricing evidence.

This module deliberately models marketplace signals as a separate evidence class.
They can improve a consulting report's demand and competition view, but they never
become supplier proof, inventory proof, or authorization to take a commerce action.
"""
from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

PROVENANCE = frozenset(
    {
        "observed",
        "derived",
        "assumed",
        "unavailable",
        "malformed",
        "blocked",
        "manual_import",
        "fixture",
    }
)
SUPPORTED = frozenset(
    {
        "amazon",
        "ebay",
        "mercadolibre",
        "alibaba",
        "aliexpress",
        "etsy",
        "walmart",
        "shopify",
        "woocommerce",
    }
)
SOURCE_TYPES = frozenset(
    {
        "amazon_best_sellers_snapshot",
        "amazon_product_snapshot",
        "ebay_terapeak_manual_import",
        "ebay_public_listing_snapshot",
        "mercadolibre_trends_snapshot",
        "mercadolibre_highlights_snapshot",
        "mercadolibre_best_sellers_snapshot",
        "alibaba_market_trending_snapshot",
        "alibaba_high_profit_snapshot",
        "aliexpress_trending_snapshot",
        "etsy_public_listing_snapshot",
        "walmart_public_listing_snapshot",
        "shopify_storefront_snapshot",
        "woocommerce_storefront_snapshot",
        "manual_csv_import",
        "fixture_demo",
    }
)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "")
    for marker in ("$", "USD", "MXN", "EUR", "GBP"):
        text = text.replace(marker, "")
    try:
        return float(text.strip().split(" ")[0])
    except (TypeError, ValueError):
        return None


def _bounded(value: Any) -> float:
    number = _number(value) or 0.0
    return round(max(0.0, min(1.0, number)), 4)


def _int(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


@dataclass(frozen=True)
class MarketplaceSignalProvenance:
    """Field-level provenance vocabulary used in client reports."""

    value: str
    source: str = "marketplace"
    note: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class MarketplaceTrendEvidence:
    candidate_id: str
    query: str
    marketplace: str
    source_type: str
    site_id: str = ""
    category_id: str = ""
    source_url: str = ""
    evidence_mode: str = "fixture"
    rank_position: int | None = None
    best_seller_badge: bool = False
    trend_label: str = ""
    search_growth_signal: float | None = None
    sold_count_text: str = ""
    review_count: int | None = None
    rating: float | None = None
    price: float | None = None
    currency: str = "USD"
    price_band_min: float | None = None
    price_band_max: float | None = None
    offer_count: int | None = None
    seller_count: int | None = None
    availability: str = ""
    shipping_signal: str = ""
    fulfillment_signal: str = ""
    source_confidence: float = 0.0
    field_provenance: Mapping[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    observed_at: str = "deterministic"
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False

    def __post_init__(self) -> None:
        if self.marketplace not in SUPPORTED:
            raise ValueError(f"unsupported marketplace: {self.marketplace}")
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"unsupported source_type: {self.source_type}")
        invalid = set(self.field_provenance.values()) - PROVENANCE
        if invalid:
            raise ValueError(f"invalid provenance: {sorted(invalid)}")
        if not self.read_only or self.network_calls or self.mutated:
            raise ValueError("marketplace trend evidence must remain offline and read-only")

    @property
    def has_price(self) -> bool:
        return self.price is not None or self.price_band_min is not None

    @property
    def provenance_mode(self) -> str:
        if self.evidence_mode == "manual_import":
            return "manual_import"
        if any(value == "observed" for value in self.field_provenance.values()):
            return "observed"
        return self.evidence_mode

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["field_provenance"] = dict(self.field_provenance)
        result["warnings"] = list(self.warnings)
        return result


@dataclass(frozen=True)
class MarketplaceTrendScore:
    candidate_id: str
    marketplace_signal_score: float
    demand_proxy_score: float
    saturation_score: float
    price_confidence: float
    source_diversity_score: float
    overall_marketplace_opportunity: float
    recommendation: str
    dimensions: Mapping[str, float]
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["dimensions"] = dict(self.dimensions)
        result["reasons"] = list(self.reasons)
        return result


@dataclass(frozen=True)
class MarketplaceTrendCandidateResult:
    candidate_id: str
    query: str
    evidence: tuple[MarketplaceTrendEvidence, ...]
    score: MarketplaceTrendScore
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "query": self.query,
            "evidence": [item.to_dict() for item in self.evidence],
            "score": self.score.to_dict(),
            "marketplaces": sorted({item.marketplace for item in self.evidence}),
            "source_types": sorted({item.source_type for item in self.evidence}),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class MarketplaceTrendReport:
    report_version: str
    evidence_mode: str
    candidate_count: int
    source_count: int
    marketplaces_observed: tuple[str, ...]
    best_seller_evidence_count: int
    top_candidate_id: str | None
    next_best_action: str
    candidates: tuple[MarketplaceTrendCandidateResult, ...]
    warnings: tuple[str, ...] = ()
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "evidence_mode": self.evidence_mode,
            "candidate_count": self.candidate_count,
            "source_count": self.source_count,
            "marketplaces_observed": list(self.marketplaces_observed),
            "best_seller_evidence_count": self.best_seller_evidence_count,
            "top_candidate_id": self.top_candidate_id,
            "next_best_action": self.next_best_action,
            "candidates": [item.to_dict() for item in self.candidates],
            "warnings": list(self.warnings),
            "read_only": self.read_only,
            "network_calls": self.network_calls,
            "mutated": self.mutated,
        }


def evidence_field_status(evidence: MarketplaceTrendEvidence, field_name: str) -> str:
    """Return explicit status for a field without inventing missing values."""
    if field_name in evidence.field_provenance:
        return evidence.field_provenance[field_name]
    return "observed" if getattr(evidence, field_name, None) not in (None, "", []) else "unavailable"


def collapse_duplicates(records: Iterable[MarketplaceTrendEvidence]) -> list[MarketplaceTrendEvidence]:
    """Collapse the same candidate/source deterministically, keeping best evidence."""
    selected: dict[tuple[str, str, str, str], MarketplaceTrendEvidence] = {}
    for record in records:
        key = (record.candidate_id, record.marketplace, record.source_type, record.source_url)
        old = selected.get(key)
        if old is None or (record.source_confidence, record.has_price, len(record.field_provenance)) > (
            old.source_confidence,
            old.has_price,
            len(old.field_provenance),
        ):
            selected[key] = record
    return sorted(selected.values(), key=lambda item: (item.candidate_id, item.marketplace, item.source_type, item.source_url))


def _average(values: Iterable[float]) -> float:
    values = list(values)
    return _bounded(sum(values) / len(values)) if values else 0.0


def score_candidate(candidate_id: str, evidence: list[MarketplaceTrendEvidence], *, supplier_proof: bool = False) -> MarketplaceTrendScore:
    """Score demand/competition evidence; supplier proof is an explicit input."""
    evidence = collapse_duplicates(evidence)
    if not evidence:
        return MarketplaceTrendScore(
            candidate_id,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            "reject_low_signal",
            {},
            ("no_marketplace_evidence", "supplier_proof_not_evaluated"),
        )

    markets = {item.marketplace for item in evidence}
    priced = [item for item in evidence if item.has_price]
    growth = [_bounded(item.search_growth_signal) for item in evidence if item.search_growth_signal is not None]
    ratings = [_bounded((item.rating or 0) / 5) for item in evidence if item.rating is not None]
    reviews = [_bounded((item.review_count or 0) / 10000) for item in evidence if item.review_count is not None]
    sellers = [item.seller_count for item in evidence if item.seller_count is not None]
    offers = [item.offer_count for item in evidence if item.offer_count is not None]
    confidence = _average(item.source_confidence for item in evidence)

    dimensions = {
        "cross_marketplace_presence": _bounded(len(markets) / 3),
        "best_seller_presence": _bounded(sum(item.best_seller_badge for item in evidence) / len(evidence)),
        "trend_growth_signal": _average(growth),
        "review_density": _average(reviews),
        "rating_quality": _average(ratings),
        "price_band_quality": _bounded(len(priced) / len(evidence)),
        "seller_competition": _bounded((statistics.mean(sellers) if sellers else 0) / 100),
        "marketplace_saturation": _bounded((statistics.mean(sellers) if sellers else len(markets) * 12) / 100),
        "shipping_fulfillment_signal": _bounded(
            sum(bool(item.shipping_signal or item.fulfillment_signal) for item in evidence) / len(evidence)
        ),
        "manual_import_confidence": _average(
            item.source_confidence for item in evidence if item.evidence_mode == "manual_import"
        )
        if any(item.evidence_mode == "manual_import" for item in evidence)
        else 0.0,
        "source_diversity": _bounded(len({item.source_type for item in evidence}) / 4),
    }
    demand = _average(
        dimensions[name]
        for name in ("cross_marketplace_presence", "best_seller_presence", "trend_growth_signal", "review_density", "rating_quality")
    )
    base = _average(
        dimensions[name]
        for name in (
            "cross_marketplace_presence",
            "best_seller_presence",
            "trend_growth_signal",
            "review_density",
            "rating_quality",
            "price_band_quality",
            "shipping_fulfillment_signal",
            "source_diversity",
        )
    )
    saturation = dimensions["marketplace_saturation"]
    opportunity = _bounded(base * (1.0 - saturation * 0.45) * (0.65 + confidence * 0.35))
    if saturation >= 0.8:
        recommendation = "reject_oversaturated"
    elif opportunity < 0.25:
        recommendation = "reject_low_signal"
    elif not supplier_proof:
        recommendation = "validate_supplier_first"
    elif opportunity >= 0.68:
        recommendation = "advance_to_launch_draft"
    elif dimensions["price_band_quality"] < 0.5:
        recommendation = "expand_competitor_research"
    else:
        recommendation = "hold_for_manual_review"
    reasons = [
        "marketplace_evidence_is_not_supplier_proof",
        "supplier_proof_observed" if supplier_proof else "supplier_proof_not_observed",
    ]
    if not priced:
        reasons.append("price_missing")
    if dimensions["source_diversity"] < 0.34:
        reasons.append("source_diversity_limited")
    return MarketplaceTrendScore(
        candidate_id=candidate_id,
        marketplace_signal_score=round(base, 4),
        demand_proxy_score=round(demand, 4),
        saturation_score=round(saturation, 4),
        price_confidence=round(_bounded(dimensions["price_band_quality"] * confidence), 4),
        source_diversity_score=round(dimensions["source_diversity"], 4),
        overall_marketplace_opportunity=round(opportunity, 4),
        recommendation=recommendation,
        dimensions={key: round(value, 4) for key, value in dimensions.items()},
        reasons=tuple(reasons),
    )


def build_report(records: list[MarketplaceTrendEvidence], *, evidence_mode: str = "fixture") -> MarketplaceTrendReport:
    records = collapse_duplicates(records)
    grouped: dict[str, list[MarketplaceTrendEvidence]] = {}
    for record in records:
        if record.candidate_id:
            grouped.setdefault(record.candidate_id, []).append(record)
    results = tuple(
        MarketplaceTrendCandidateResult(
            candidate_id,
            tuple(rows)[0].query,
            tuple(sorted(rows, key=lambda item: (item.marketplace, item.source_type, item.source_url))),
            score_candidate(candidate_id, rows),
            tuple(sorted({warning for row in rows for warning in row.warnings})),
        )
        for candidate_id, rows in sorted(grouped.items())
    )
    results = tuple(sorted(results, key=lambda item: (-item.score.overall_marketplace_opportunity, item.candidate_id)))
    top = results[0] if results else None
    warnings = ("marketplace_evidence_is_not_supplier_proof",) if records else ("marketplace_trends_not_supplied",)
    return MarketplaceTrendReport(
        report_version="marketplace-trend-v2",
        evidence_mode=evidence_mode,
        candidate_count=len(results),
        source_count=len({item.source_type for item in records}),
        marketplaces_observed=tuple(sorted({item.marketplace for item in records})),
        best_seller_evidence_count=sum(item.best_seller_badge for item in records),
        top_candidate_id=top.candidate_id if top else None,
        next_best_action=(f"{top.score.recommendation}:{top.candidate_id}" if top else "hold_for_manual_review"),
        candidates=results,
        warnings=warnings,
    )

"""backend.mvp_commerce.competition_intelligence — market pricing/
saturation intelligence sitting between Supplier Evidence and Opportunity
Scoring.

Pipeline this module fills in:

    Public Signals -> Supplier Evidence -> Competition Intelligence ->
    Opportunity Scoring -> Commerce MVP -> Dashboard

Composes through existing architecture only:

- Consumes ``backend.adapters.research.competition_evidence.CompetitorOffer``
  (no new HTML/JSON-LD extraction here) and
  ``backend.mvp_commerce.supplier_evidence.SupplierEvidenceResult`` (no new
  supplier-cost model).
- Does not replace or duplicate ``backend.mvp_commerce.opportunity_scoring``
  — this module produces evidence that becomes one additional scoring
  dimension there (see ``_market_saturation``/``_price_competitiveness``/
  etc. in opportunity_scoring.py), not a second scoring engine.
- Emits events through the existing ``backend.contracts.events.Event`` /
  ``backend.events.repository.EventRepository`` system.

Deliberately NOT wired into ``backend/commercial_intelligence/`` (which
already owns "competition_score"/"saturation_score" fields computed from
*locally recorded* ``discovery_registry`` evidence — see
``backend/commercial_intelligence/scoring.py``). That stack is one of the
heavier, "OFF in the MVP Island" experimental modules
(``docs/MVP_ISLAND.md``: "experimental modules not named by the profile")
that the Commerce MVP vertical slice deliberately does not depend on — the
same reasoning that kept ``opportunity_scoring.py`` from being named
"Product Intelligence" (see that module's own docstring). Pulling live
competitor-listing evidence into ``discovery_registry`` would widen the MVP
Island's dependency surface; this module stays narrow and only feeds the
Commerce MVP / Opportunity Scoring pipeline it was built for. This is an
explicit, documented exception to "reuse a canonical owner"
(``ARCHITECTURE_CONTRACT.md``), not an oversight.

Every observed-vs-computed value is provenance-tagged; unknown evidence
reduces confidence, never invents certainty (same discipline as
``cj_public_evidence``/``opportunity_scoring``).
"""
from __future__ import annotations

import hashlib
import statistics
import time
from dataclasses import dataclass, field as dataclass_field
from typing import Any

from backend.adapters.research.competition_evidence import CompetitorOffer, fetch_competitor_offer
from backend.contracts.adapters import SidecarContext
from backend.contracts.events import Event
from backend.mvp_commerce.supplier_evidence import SupplierEvidenceResult

SOURCE = "backend.mvp_commerce.competition_intelligence"

# Saturation ceiling: an independent constant from
# backend.discovery.ad_intelligence's ADLIB_SATURATION_CEILING (ad-count
# based) — this one is listing-count based, a different signal.
SATURATION_CEILING = 20


@dataclass(frozen=True)
class MarketIntelligenceReport:
    """Aggregated, observed-only market intelligence for one query."""

    query: str
    generated_at: float
    offers: tuple[CompetitorOffer, ...]
    observed_competitor_count: int
    observed_median_price: float | None
    observed_mean_price: float | None
    observed_min_price: float | None
    observed_max_price: float | None
    observed_pricing_variance: float | None
    observed_shipping_min: float | None
    observed_shipping_max: float | None
    observed_review_density: float | None
    observed_rating_mean: float | None
    observed_brand_diversity: float | None
    observed_seller_diversity: float | None
    observed_availability_ratio: float | None
    market_maturity: str
    market_saturation: float | None
    confidence: float
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query, "generated_at": self.generated_at,
            "offers": [offer.to_dict() for offer in self.offers],
            "observed_competitor_count": self.observed_competitor_count,
            "observed_median_price": self.observed_median_price, "observed_mean_price": self.observed_mean_price,
            "observed_min_price": self.observed_min_price, "observed_max_price": self.observed_max_price,
            "observed_pricing_variance": self.observed_pricing_variance,
            "observed_shipping_min": self.observed_shipping_min, "observed_shipping_max": self.observed_shipping_max,
            "observed_review_density": self.observed_review_density, "observed_rating_mean": self.observed_rating_mean,
            "observed_brand_diversity": self.observed_brand_diversity, "observed_seller_diversity": self.observed_seller_diversity,
            "observed_availability_ratio": self.observed_availability_ratio,
            "market_maturity": self.market_maturity, "market_saturation": self.market_saturation,
            "confidence": self.confidence, "warnings": list(self.warnings),
        }


def _priced_offers(offers: list[CompetitorOffer]) -> list[CompetitorOffer]:
    return [offer for offer in offers if offer.price is not None and offer.field_status.get("price") == "observed"]


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def gather_market_intelligence(
    query: str, *, context: SidecarContext, competitor_urls: list[str] | None = None,
    source_hints: dict[str, str] | None = None, max_competitors: int = 10, generated_at: float | None = None,
) -> MarketIntelligenceReport:
    """Never raises. Fetches evidence for operator-supplied competitor URLs
    (public storefronts, no discovery/search automation this round — see
    docs/COMPETITION_INTELLIGENCE.md) and aggregates only what was actually
    observed."""
    urls = list(competitor_urls or [])[:max(0, max_competitors)]
    hints = source_hints or {}
    when = generated_at if generated_at is not None else time.time()
    offers = tuple(fetch_competitor_offer(url, source=hints.get(url, ""), context=context) for url in urls)
    warnings: list[str] = []
    if not urls:
        warnings.append("no_competitor_urls: supply competitor_urls to gather market intelligence")
    priced = _priced_offers(list(offers))
    prices = [offer.price for offer in priced if offer.price is not None]
    shipping = [offer.shipping_cost for offer in offers if offer.shipping_cost is not None]
    reviews = [offer.review_count for offer in offers if offer.review_count is not None]
    ratings = [offer.rating for offer in offers if offer.rating is not None]
    brands = {offer.brand for offer in offers if offer.brand}
    sellers = {offer.seller for offer in offers if offer.seller}
    availability_reported = [offer for offer in offers if offer.availability]
    in_stock = [offer for offer in availability_reported if "instock" in offer.availability.lower().replace(" ", "")]

    median_price = round(statistics.median(prices), 2) if prices else None
    mean_price = round(statistics.fmean(prices), 2) if prices else None
    variance = round(statistics.pstdev(prices), 4) if len(prices) > 1 else None
    review_density = round(statistics.fmean(reviews), 2) if reviews else None
    rating_mean = round(statistics.fmean(ratings), 2) if ratings else None

    saturation = min(1.0, round(len(priced) / SATURATION_CEILING, 4)) if offers else None
    if review_density is None and rating_mean is None:
        maturity = "unknown"
    elif (review_density or 0) > 50 or (rating_mean or 0) >= 4.0:
        maturity = "established"
    else:
        maturity = "emerging"

    total_dimensions = 8  # price, shipping, review, rating, brand, seller, availability, saturation
    observed_dimensions = sum(1 for value in (
        median_price, shipping, review_density, rating_mean, brands, sellers, availability_reported, saturation,
    ) if value)
    confidence = round(observed_dimensions / total_dimensions, 4) if offers else 0.0

    return MarketIntelligenceReport(
        query=query, generated_at=when, offers=offers, observed_competitor_count=len(priced),
        observed_median_price=median_price, observed_mean_price=mean_price,
        observed_min_price=round(min(prices), 2) if prices else None,
        observed_max_price=round(max(prices), 2) if prices else None,
        observed_pricing_variance=variance,
        observed_shipping_min=round(min(shipping), 2) if shipping else None,
        observed_shipping_max=round(max(shipping), 2) if shipping else None,
        observed_review_density=review_density, observed_rating_mean=rating_mean,
        observed_brand_diversity=_ratio(len(brands), len(offers)), observed_seller_diversity=_ratio(len(sellers), len(offers)),
        observed_availability_ratio=_ratio(len(in_stock), len(availability_reported)),
        market_maturity=maturity, market_saturation=saturation, confidence=confidence, warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class MarginIntelligence:
    """Observed-over-assumed margin computed from Supplier Evidence x
    Competition Intelligence. Never fabricated: unavailable inputs make the
    corresponding output None, not a guessed number."""

    candidate_id: str
    observed_gross_margin: float | None
    observed_margin_low: float | None
    observed_margin_high: float | None
    observed_supplier_advantage: float | None
    observed_pricing_confidence: float
    observed_margin_confidence: float
    provenance: dict[str, str]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id, "observed_gross_margin": self.observed_gross_margin,
            "observed_margin_low": self.observed_margin_low, "observed_margin_high": self.observed_margin_high,
            "observed_supplier_advantage": self.observed_supplier_advantage,
            "observed_pricing_confidence": self.observed_pricing_confidence,
            "observed_margin_confidence": self.observed_margin_confidence,
            "provenance": dict(self.provenance), "warnings": list(self.warnings),
        }


def compute_margin_intelligence(
    candidate_id: str, *, supplier_evidence: SupplierEvidenceResult | None, market_report: MarketIntelligenceReport | None,
) -> MarginIntelligence:
    """Never raises. Combines an observed supplier cost with observed market
    prices; any missing input degrades to None outputs with an explicit
    provenance/warning, never a filled-in assumption."""
    unit_cost = supplier_evidence.unit_cost if supplier_evidence is not None else None
    has_cost = unit_cost is not None
    median_price = market_report.observed_median_price if market_report is not None else None
    min_price = market_report.observed_min_price if market_report is not None else None
    max_price = market_report.observed_max_price if market_report is not None else None
    has_market = median_price is not None

    provenance = {
        "supplier_cost": "observed" if has_cost else "missing",
        "market_price": "observed" if has_market else "missing",
    }
    warnings: list[str] = []
    if not has_cost:
        warnings.append("no_observed_supplier_cost: gather supplier evidence before trusting this margin")
    if not has_market:
        warnings.append("no_observed_market_price: gather competitor evidence before trusting this margin")

    if not (has_cost and has_market):
        return MarginIntelligence(
            candidate_id=candidate_id, observed_gross_margin=None, observed_margin_low=None, observed_margin_high=None,
            observed_supplier_advantage=None, observed_pricing_confidence=0.0 if not has_market else market_report.confidence,
            observed_margin_confidence=0.0, provenance=provenance, warnings=tuple(warnings),
        )

    gross_margin = round((median_price - unit_cost) / median_price, 4) if median_price else None
    margin_low = round((min_price - unit_cost) / min_price, 4) if min_price else None
    margin_high = round((max_price - unit_cost) / max_price, 4) if max_price else None
    supplier_advantage = round((min_price - unit_cost) / min_price, 4) if min_price else None
    margin_confidence = round((market_report.confidence + (1.0 if has_cost else 0.0)) / 2, 4)

    return MarginIntelligence(
        candidate_id=candidate_id, observed_gross_margin=gross_margin, observed_margin_low=margin_low,
        observed_margin_high=margin_high, observed_supplier_advantage=supplier_advantage,
        observed_pricing_confidence=market_report.confidence, observed_margin_confidence=margin_confidence,
        provenance=provenance, warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class MarketOpportunityReport:
    """The operator-facing commercial decision artifact: one candidate's
    opportunity score, supplier evidence, competition evidence, and margin,
    combined with explicit risks/strengths/weaknesses/missing-evidence and a
    recommended next step. Composes existing artifacts; computes nothing an
    operator couldn't already see split across three separate objects."""

    candidate_id: str
    product_name: str
    generated_at: float
    opportunity_score: float | None
    opportunity_confidence: float | None
    supplier_summary: dict[str, Any]
    competition_summary: dict[str, Any]
    observed_pricing: dict[str, Any]
    observed_supplier_cost: float | None
    observed_margin: dict[str, Any]
    market_risks: tuple[str, ...]
    strengths: tuple[str, ...]
    weaknesses: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    operator_actions: tuple[str, ...]
    recommended_next_step: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id, "product_name": self.product_name, "generated_at": self.generated_at,
            "opportunity_score": self.opportunity_score, "opportunity_confidence": self.opportunity_confidence,
            "supplier_summary": self.supplier_summary, "competition_summary": self.competition_summary,
            "observed_pricing": self.observed_pricing, "observed_supplier_cost": self.observed_supplier_cost,
            "observed_margin": self.observed_margin, "market_risks": list(self.market_risks),
            "strengths": list(self.strengths), "weaknesses": list(self.weaknesses),
            "missing_evidence": list(self.missing_evidence), "operator_actions": list(self.operator_actions),
            "recommended_next_step": self.recommended_next_step,
        }


def build_market_opportunity_report(
    candidate_id: str, product_name: str, *, opportunity_score: Any | None = None,
    supplier_evidence: SupplierEvidenceResult | None = None, market_report: MarketIntelligenceReport | None = None,
    margin: MarginIntelligence | None = None, generated_at: float | None = None,
) -> MarketOpportunityReport:
    """Never raises. Pure combination of already-computed artifacts — this
    function does not fetch evidence or compute new numbers itself."""
    when = generated_at if generated_at is not None else time.time()
    supplier_summary = {
        "attempted": supplier_evidence.attempted if supplier_evidence else False,
        "unit_cost": supplier_evidence.unit_cost if supplier_evidence else None,
        "shipping_cost": supplier_evidence.shipping_cost if supplier_evidence else None,
        "supplier": supplier_evidence.supplier if supplier_evidence else None,
        "source_url": supplier_evidence.source_url if supplier_evidence else "",
    }
    competition_summary = {
        "observed_competitor_count": market_report.observed_competitor_count if market_report else 0,
        "market_saturation": market_report.market_saturation if market_report else None,
        "market_maturity": market_report.market_maturity if market_report else "unknown",
        "confidence": market_report.confidence if market_report else 0.0,
    }
    observed_pricing = {
        "median": market_report.observed_median_price if market_report else None,
        "mean": market_report.observed_mean_price if market_report else None,
        "min": market_report.observed_min_price if market_report else None,
        "max": market_report.observed_max_price if market_report else None,
    }
    margin_dict = margin.to_dict() if margin else {}

    risks: list[str] = []
    strengths: list[str] = []
    weaknesses: list[str] = []
    missing: list[str] = []

    if market_report and market_report.market_saturation is not None and market_report.market_saturation >= 0.75:
        risks.append(f"market_saturation is high ({market_report.market_saturation})")
    if margin and margin.observed_gross_margin is not None and margin.observed_gross_margin < 0.2:
        risks.append(f"observed_gross_margin is thin ({margin.observed_gross_margin})")
    if market_report and market_report.observed_pricing_variance and market_report.observed_median_price and \
            market_report.observed_pricing_variance > market_report.observed_median_price * 0.3:
        risks.append("observed pricing variance is high across competitors")

    if margin and margin.observed_gross_margin is not None and margin.observed_gross_margin >= 0.4:
        strengths.append(f"observed_gross_margin is strong ({margin.observed_gross_margin})")
    if market_report and market_report.market_saturation is not None and market_report.market_saturation < 0.25:
        strengths.append(f"market_saturation is low ({market_report.market_saturation})")

    if not supplier_evidence or supplier_evidence.unit_cost is None:
        weaknesses.append("no observed supplier cost")
        missing.append("supplier_cost")
    if not market_report or not market_report.offers:
        weaknesses.append("no observed competitor listings")
        missing.append("competitor_evidence")
    if market_report and market_report.observed_rating_mean is None:
        missing.append("competitor_ratings")

    actions: list[str] = []
    if missing:
        actions.append(f"Gather missing evidence: {', '.join(missing)}")
    if margin and margin.observed_margin_confidence < 0.5:
        actions.append("Corroborate margin with additional supplier/competitor evidence before advancing")
    if not actions:
        actions.append("Review this report with an operator before any external action")

    if missing:
        next_step = "gather_more_evidence_before_any_decision"
    elif risks:
        next_step = "corroborate_before_advancing"
    else:
        next_step = "advance_to_manual_review"

    return MarketOpportunityReport(
        candidate_id=candidate_id, product_name=product_name, generated_at=when,
        opportunity_score=getattr(opportunity_score, "composite_score", None),
        opportunity_confidence=getattr(opportunity_score, "confidence", None),
        supplier_summary=supplier_summary, competition_summary=competition_summary,
        observed_pricing=observed_pricing, observed_supplier_cost=supplier_summary["unit_cost"],
        observed_margin=margin_dict, market_risks=tuple(risks), strengths=tuple(strengths),
        weaknesses=tuple(weaknesses), missing_evidence=tuple(missing), operator_actions=tuple(actions),
        recommended_next_step=next_step,
    )


# -- canonical events ---------------------------------------------------

_EVENT_METADATA = {
    "dry_run": True, "advisory": True, "non_authoritative": True, "public_source": True,
    "no_launch_authority": True, "no_spend_authority": True, "no_order_authority": True,
}


def competition_intelligence_events(
    market_report: MarketIntelligenceReport, margin: MarginIntelligence | None,
    opportunity_report: MarketOpportunityReport | None, *, workspace_id: str, run_id: str,
) -> list[Event]:
    """Follows the exact shape established by supplier_evidence_events()/
    opportunity_scoring_events(): its own event-type set, not an extension
    of commerce_mvp_events()'s _EVENTS tuple."""

    def _event_id(suffix: str) -> str:
        return "competition-intelligence-" + hashlib.sha256(f"{run_id}:{suffix}".encode()).hexdigest()[:20]

    events: list[Event] = []
    for offer in market_report.offers:
        events.append(Event(
            _event_id(f"observed:{offer.external_listing_id}"), workspace_id, "competitor_listing",
            offer.external_listing_id, "competition_observed", 1, market_report.generated_at,
            correlation_id=run_id, source=SOURCE, payload=offer.to_dict(), metadata=_EVENT_METADATA,
        ))
    events.append(Event(
        _event_id("summary"), workspace_id, "commerce_mvp_run", run_id, "competition_summary_created", 1,
        market_report.generated_at + 0.001, correlation_id=run_id, source=SOURCE,
        payload=market_report.to_dict(), metadata=_EVENT_METADATA,
    ))
    if margin is not None:
        events.append(Event(
            _event_id(f"pricing:{margin.candidate_id}"), workspace_id, "opportunity_candidate", margin.candidate_id,
            "market_pricing_computed", 1, market_report.generated_at + 0.002, correlation_id=run_id, source=SOURCE,
            payload=margin.to_dict(), metadata=_EVENT_METADATA,
        ))
    if opportunity_report is not None:
        events.append(Event(
            _event_id(f"completed:{opportunity_report.candidate_id}"), workspace_id, "opportunity_candidate",
            opportunity_report.candidate_id, "market_intelligence_completed", 1,
            market_report.generated_at + 0.003, correlation_id=run_id, source=SOURCE,
            payload=opportunity_report.to_dict(), metadata=_EVENT_METADATA,
        ))
    return events


__all__ = [
    "MarginIntelligence", "MarketIntelligenceReport", "MarketOpportunityReport",
    "build_market_opportunity_report", "compute_margin_intelligence",
    "competition_intelligence_events", "gather_market_intelligence",
]

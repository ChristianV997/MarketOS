"""Bounded, sanitized public-market evidence benchmark for Phase 1.

This module orchestrates existing competitor evidence records and the existing
benchmark matrix.  It deliberately does not fetch by default, retain HTML, or
turn public prices into supplier costs.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from backend.adapters.research.competition_evidence import CompetitorOffer, fetch_competitor_offer
from backend.contracts.adapters import SidecarContext
from .benchmark_matrix import BenchmarkCandidate, BenchmarkMatrixReport, build_benchmark_matrix, normalize_candidate
from .marketplace_trends import MarketplaceTrendEvidence, MarketplaceTrendReport, build_report as build_marketplace_trend_report
from .opportunity_synthesis import ProductOpportunitySynthesisReport, build_product_opportunity_synthesis

VERSION = "phase1-public-market-benchmark-v1"
MAX_CANDIDATES = 10
MAX_COMPETITORS_PER_CANDIDATE = 4

_MARKETPLACE_ALIASES = (
    "amazon",
    "ebay",
    "mercadolibre",
    "alibaba",
    "aliexpress",
    "etsy",
    "walmart",
    "woocommerce",
)
_SOURCE_BY_MARKETPLACE = {
    "amazon": "amazon_product_snapshot",
    "ebay": "ebay_public_listing_snapshot",
    "mercadolibre": "mercadolibre_highlights_snapshot",
    "alibaba": "alibaba_market_trending_snapshot",
    "aliexpress": "aliexpress_trending_snapshot",
    "etsy": "etsy_public_listing_snapshot",
    "walmart": "walmart_public_listing_snapshot",
    "shopify": "shopify_storefront_snapshot",
    "woocommerce": "woocommerce_storefront_snapshot",
}


def _bounded(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 4)
    except (TypeError, ValueError):
        return 0.0


_URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def _safe_url(value: Any) -> str:
    """Keep scheme, host[:port] and path; userinfo, query and fragment may hold operator secrets."""
    try:
        parsed = urlparse(str(value or ""))
    except ValueError:
        return ""
    host_port = parsed.netloc.rpartition("@")[2]
    if parsed.scheme not in {"http", "https"} or not host_port:
        return ""
    return f"{parsed.scheme}://{host_port}{parsed.path}"


def _redact_urls(text: str) -> str:
    """Sanitize URLs embedded in free text, e.g. adapter warnings that echo the requested URL."""
    return _URL_IN_TEXT.sub(lambda match: _safe_url(match.group(0)) or "[redacted-url]", text)


def _safe_text(value: Any, limit: int = 180) -> str:
    # Redact before truncating so a cut-off URL can never leave partial userinfo behind.
    return _redact_urls(str(value or "")).replace("\n", " ").replace("\r", " ")[:limit]


def _safe_domain(value: Any) -> str:
    """Hostname only: userinfo, scheme, path, query and fragment never survive."""
    text = str(value or "").strip()
    try:
        return (urlparse(text if "://" in text else f"//{text}").hostname or "").lower()
    except ValueError:
        return ""


def _has_userinfo(value: str) -> bool:
    """True for URLs such as ``https://user:pw@host/``; ``requests`` would forward them as Basic auth."""
    try:
        return "@" in urlparse(value).netloc
    except ValueError:
        return False


def redact_report_urls(value: Any) -> Any:
    """Re-apply URL sanitization to a stored report; artifacts written by older runs may predate it."""
    if isinstance(value, str):
        return _redact_urls(value) if "://" in value else value
    if isinstance(value, Mapping):
        return {key: redact_report_urls(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_report_urls(item) for item in value]
    return value


@dataclass(frozen=True)
class PublicMarketEvidence:
    candidate_id: str
    query: str
    competitor_url: str
    source_domain: str
    extraction_mode: str
    product_title: str = ""
    brand: str = ""
    price: float | None = None
    currency: str = ""
    availability: str = ""
    rating: float | None = None
    review_count: int | None = None
    shipping_cost: float | None = None
    source_confidence: float = 0.0
    field_provenance: Mapping[str, str] | None = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["competitor_url"] = _safe_url(value["competitor_url"])
        value["product_title"] = _safe_text(value["product_title"])
        value["brand"] = _safe_text(value["brand"])
        value["field_provenance"] = dict(self.field_provenance or {})
        value["warnings"] = [_safe_text(item) for item in self.warnings]
        return value


@dataclass(frozen=True)
class PublicMarketCandidateResult:
    candidate_id: str
    query: str
    pages_attempted: int
    offers_observed: int
    pricing_coverage: float
    public_evidence_confidence: float
    evidence: tuple[PublicMarketEvidence, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "evidence": [item.to_dict() for item in self.evidence], "warnings": list(self.warnings)}


@dataclass(frozen=True)
class PublicMarketBenchmarkReport:
    report_version: str
    evidence_mode: str
    network_used: bool
    candidates_tested: int
    competitor_pages_attempted: int
    competitor_offers_observed: int
    pricing_coverage: float
    top_candidate_from_public_market: str | None
    public_evidence_confidence: float
    remaining_supplier_blocker: str
    next_best_action: str
    candidate_results: tuple[PublicMarketCandidateResult, ...]
    benchmark_matrix: BenchmarkMatrixReport
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "candidate_results": [item.to_dict() for item in self.candidate_results],
            "benchmark_matrix": self.benchmark_matrix.to_dict(),
            "warnings": list(self.warnings),
            "mutated": False, "read_only": True, "credentials_required": False,
        }


def evidence_from_offer(candidate_id: str, query: str, offer: CompetitorOffer, *, mode: str) -> PublicMarketEvidence:
    return PublicMarketEvidence(
        candidate_id=candidate_id, query=query, competitor_url=offer.source_url,
        source_domain=(urlparse(offer.source_url).hostname or "").lower(), extraction_mode=mode,
        product_title=offer.title, brand=offer.brand, price=offer.price, currency=offer.currency,
        availability=offer.availability, rating=offer.rating, review_count=offer.review_count,
        shipping_cost=offer.shipping_cost, source_confidence=offer.confidence,
        field_provenance=offer.field_status, warnings=offer.warnings,
    )


def _fixture_evidence(candidate: Mapping[str, Any]) -> list[PublicMarketEvidence]:
    result: list[PublicMarketEvidence] = []
    for raw in candidate.get("fixture_offers", []) if isinstance(candidate.get("fixture_offers"), list) else []:
        if not isinstance(raw, Mapping):
            continue
        status = raw.get("field_provenance") if isinstance(raw.get("field_provenance"), Mapping) else {}
        result.append(PublicMarketEvidence(
            candidate_id=str(candidate.get("candidate_id", "")), query=str(candidate.get("query", "")),
            competitor_url=str(raw.get("competitor_url", "")), source_domain=_safe_domain(raw.get("source_domain")),
            extraction_mode="fixture", product_title=str(raw.get("product_title", "")), brand=str(raw.get("brand", "")),
            price=raw.get("price") if isinstance(raw.get("price"), (int, float)) else None,
            currency=str(raw.get("currency", "")), availability=str(raw.get("availability", "")),
            rating=raw.get("rating") if isinstance(raw.get("rating"), (int, float)) else None,
            review_count=raw.get("review_count") if isinstance(raw.get("review_count"), int) else None,
            shipping_cost=raw.get("shipping_cost") if isinstance(raw.get("shipping_cost"), (int, float)) else None,
            source_confidence=_bounded(raw.get("source_confidence", 0.0)), field_provenance=dict(status),
            warnings=tuple(str(item) for item in raw.get("warnings", []) if isinstance(item, str)),
        ))
    return result


def _candidate_for_matrix(raw: Mapping[str, Any], evidence: list[PublicMarketEvidence]) -> BenchmarkCandidate:
    candidate = normalize_candidate(raw)
    priced = [item for item in evidence if item.price is not None]
    sources = sorted({item.source_domain for item in evidence if item.source_domain})
    competition = dict(candidate.competition_evidence)
    competition.update({
        "observed_offers": len([item for item in evidence if item.product_title or item.price is not None]),
        "pricing_coverage": _bounded(len(priced) / max(1, len(evidence))),
        "sources": sources,
        "availability_observed": any(bool(item.availability) for item in evidence),
        "reviews_observed": any(item.rating is not None or item.review_count is not None for item in evidence),
        "confidence": _bounded(sum(item.source_confidence for item in evidence) / max(1, len(evidence))),
        "js_rendered": any(item.extraction_mode == "js_rendered" for item in evidence),
    })
    return BenchmarkCandidate(**{**candidate.to_dict(), "competition_evidence": competition})


def load_public_market_seed(path: str | Path | None) -> tuple[list[dict[str, Any]], list[str]]:
    if path is None:
        return [], ["candidate_seed_not_provided"]
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], [f"candidate_seed_unavailable:{type(exc).__name__}"]
    values = raw.get("candidates", []) if isinstance(raw, Mapping) else []
    if not isinstance(values, list):
        return [], ["candidate_seed_candidates_not_a_list"]
    warnings: list[str] = []
    seen: set[str] = set(); candidates: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, Mapping):
            warnings.append("candidate_seed_item_ignored"); continue
        candidate_id = str(value.get("candidate_id", "")).strip()
        if not candidate_id or candidate_id in seen:
            warnings.append("candidate_seed_duplicate_or_missing_id"); continue
        seen.add(candidate_id); candidates.append(dict(value))
    return candidates, warnings


def build_public_market_benchmark(
    candidates: list[Mapping[str, Any]], *, allow_network: bool = False, max_candidates: int = 3,
    max_competitors_per_candidate: int = 3, fetcher: Callable[..., CompetitorOffer] = fetch_competitor_offer,
) -> PublicMarketBenchmarkReport:
    """Build a bounded report; live fetching is opt-in and delegates to the adapter."""
    maximum = max(1, min(int(max_candidates), MAX_CANDIDATES))
    per_candidate = max(1, min(int(max_competitors_per_candidate), MAX_COMPETITORS_PER_CANDIDATE))
    selected = list(candidates)[:maximum]
    results: list[PublicMarketCandidateResult] = []; matrix_candidates: list[BenchmarkCandidate] = []
    warnings: list[str] = []
    for raw in selected:
        evidence = _fixture_evidence(raw) if not allow_network else []
        urls = [str(item) for item in raw.get("competitor_urls", []) if isinstance(item, str)][:per_candidate]
        if allow_network:
            if any(_has_userinfo(url) for url in urls):
                # The fetcher would transmit embedded credentials; never hand such a URL over.
                warnings.append("competitor_url_with_userinfo_rejected")
                urls = [url for url in urls if not _has_userinfo(url)]
            context = SidecarContext(dry_run=False, approval_state="not_required")
            for url in urls:
                offer = fetcher(url, context=context)
                mode = "js_rendered" if "js_rendered" in offer.extraction_method else "static"
                evidence.append(evidence_from_offer(str(raw.get("candidate_id", "")), str(raw.get("query", "")), offer, mode=mode))
        observed = [item for item in evidence if item.product_title or item.price is not None]
        priced = [item for item in evidence if item.price is not None]
        confidence = _bounded(sum(item.source_confidence for item in evidence) / max(1, len(evidence)))
        result = PublicMarketCandidateResult(str(raw.get("candidate_id", "")), str(raw.get("query", "")), len(urls) if allow_network else len(evidence), len(observed), _bounded(len(priced) / max(1, len(evidence))), confidence, tuple(evidence), ())
        results.append(result); matrix_candidates.append(_candidate_for_matrix(raw, evidence))
    matrix = build_benchmark_matrix(candidates=matrix_candidates)
    pages = sum(item.pages_attempted for item in results); offers = sum(item.offers_observed for item in results)
    coverage = _bounded(sum(item.pricing_coverage * max(1, item.pages_attempted) for item in results) / max(1, pages))
    top = matrix.top_candidate_id
    next_action = f"set_cj_credentials_and_validate_candidate:{top}" if top else "set_cj_credentials_and_run_validation_pack"
    if not allow_network: warnings.append("fixture_demo_evidence_only_not_live_proof")
    return PublicMarketBenchmarkReport(VERSION, "public_live" if allow_network else "fixture_demo", allow_network, len(results), pages, offers, coverage, top, _bounded(sum(item.public_evidence_confidence for item in results) / max(1, len(results))), "authenticated_supplier_evidence_not_live_observed", next_action, tuple(results), matrix, tuple(sorted(set(warnings))))


def _infer_marketplace(domain: str) -> str:
    text = str(domain or "").lower()
    for name in _MARKETPLACE_ALIASES:
        if name in text:
            return name
    # Generic public storefront pages map to the Shopify storefront bucket.
    return "shopify"


def _as_report_dict(report: Mapping[str, Any] | PublicMarketBenchmarkReport) -> dict[str, Any]:
    if isinstance(report, PublicMarketBenchmarkReport):
        return report.to_dict()
    return dict(report)


def to_marketplace_trend_report(
    report: Mapping[str, Any] | PublicMarketBenchmarkReport,
) -> MarketplaceTrendReport:
    """Project public-market offers into the marketplace pillar for synthesis.

    Reuses ``marketplace_trends.build_report`` scoring. Public competitor prices
    remain market context: demand proxies and saturation are derived/assumed from
    observed offer coverage and never authorize supplier proof, spend, or launch.
    """
    data = _as_report_dict(report)
    mode = str(data.get("evidence_mode") or "fixture_demo")
    records: list[MarketplaceTrendEvidence] = []
    for candidate in data.get("candidate_results") or []:
        if not isinstance(candidate, Mapping):
            continue
        candidate_id = str(candidate.get("candidate_id") or "").strip()
        query = str(candidate.get("query") or candidate_id)
        offers = [item for item in candidate.get("evidence") or [] if isinstance(item, Mapping)]
        domains = sorted({str(item.get("source_domain") or "") for item in offers if item.get("source_domain")})
        seller_proxy = max(1, len(domains)) if offers else None
        for offer in offers:
            if not (offer.get("product_title") or offer.get("price") is not None):
                continue
            marketplace = _infer_marketplace(str(offer.get("source_domain") or ""))
            source_type = "fixture_demo" if mode == "fixture_demo" else _SOURCE_BY_MARKETPLACE.get(marketplace, "shopify_storefront_snapshot")
            provenance = {
                str(key): str(value)
                for key, value in dict(offer.get("field_provenance") or {}).items()
                if str(value) in {"observed", "derived", "assumed", "unavailable", "malformed", "blocked", "manual_import", "fixture"}
            }
            if seller_proxy is not None:
                provenance.setdefault("seller_count", "derived")
            provenance.setdefault("offer_count", "derived")
            records.append(
                MarketplaceTrendEvidence(
                    candidate_id=candidate_id,
                    query=query,
                    marketplace=marketplace,
                    source_type=source_type,
                    source_url=_safe_url(offer.get("competitor_url")),
                    evidence_mode="fixture" if mode == "fixture_demo" else mode,
                    review_count=offer.get("review_count") if isinstance(offer.get("review_count"), int) else None,
                    rating=offer.get("rating") if isinstance(offer.get("rating"), (int, float)) else None,
                    price=offer.get("price") if isinstance(offer.get("price"), (int, float)) else None,
                    currency=str(offer.get("currency") or "USD") or "USD",
                    offer_count=len(offers),
                    seller_count=seller_proxy,
                    availability=str(offer.get("availability") or ""),
                    shipping_signal="observed" if offer.get("shipping_cost") is not None else "",
                    source_confidence=_bounded(offer.get("source_confidence", 0.0)),
                    field_provenance=provenance,
                    warnings=(
                        "public_competitor_price_is_market_context_not_supplier_cost",
                        "demand_proxies_assumed_from_public_offer_coverage",
                    ),
                    # MarketplaceTrendEvidence is offline-shaped even when the
                    # parent public-market report used bounded public GETs.
                    network_calls=False,
                    mutated=False,
                    read_only=True,
                )
            )
    marketplace_report = build_marketplace_trend_report(records, evidence_mode=mode)
    extra = [
        "projected_from_public_market_benchmark",
        "marketplace_pillar_from_public_offers_not_native_marketplace_import",
        "price_cpa_ctr_budget_thresholds_remain_planning_assumptions",
    ]
    if mode == "fixture_demo":
        extra.append("fixture_demo_evidence_only_not_live_proof")
    return MarketplaceTrendReport(
        report_version=marketplace_report.report_version,
        evidence_mode=marketplace_report.evidence_mode,
        candidate_count=marketplace_report.candidate_count,
        source_count=marketplace_report.source_count,
        marketplaces_observed=marketplace_report.marketplaces_observed,
        best_seller_evidence_count=marketplace_report.best_seller_evidence_count,
        top_candidate_id=marketplace_report.top_candidate_id,
        next_best_action=marketplace_report.next_best_action,
        candidates=marketplace_report.candidates,
        warnings=tuple(sorted(set([*marketplace_report.warnings, *extra]))),
        read_only=True,
        network_calls=False,
        mutated=False,
    )


def synthesize_from_public_market(
    report: Mapping[str, Any] | PublicMarketBenchmarkReport,
    *,
    supplier_report: Mapping[str, Any] | None = None,
    consumer_report: Mapping[str, Any] | None = None,
) -> ProductOpportunitySynthesisReport:
    """Fuse the projected marketplace pillar through Product Opportunity Synthesis.

    Missing supplier/consumer pillars stay missing so the canonical synthesizer
    can recommend ``validate_supplier_first`` without inventing supplier proof.
    """
    marketplace = to_marketplace_trend_report(report).to_dict()
    return build_product_opportunity_synthesis(marketplace, supplier_report, consumer_report)


def markdown_report(report: Mapping[str, Any]) -> str:
    lines = ["# Phase 1 Public Market Evidence Benchmark", "", f"- Mode: `{report.get('evidence_mode')}`", f"- Candidates: {report.get('candidates_tested', 0)}", f"- Competitor pages: {report.get('competitor_pages_attempted', 0)}", f"- Offers observed: {report.get('competitor_offers_observed', 0)}", f"- Pricing coverage: {float(report.get('pricing_coverage', 0)):.0%}", f"- Top candidate: `{report.get('top_candidate_from_public_market') or 'none'}`", f"- Next action: `{report.get('next_best_action')}`", "", "## Candidate results", "", "| Candidate | Offers | Pricing coverage | Confidence |", "| --- | ---: | ---: | ---: |"]
    for item in report.get("candidate_results", []): lines.append(f"| {item['candidate_id']} | {item['offers_observed']} | {float(item['pricing_coverage']):.0%} | {float(item['public_evidence_confidence']):.0%} |")
    marketplace = report.get("marketplace_trend_report") if isinstance(report.get("marketplace_trend_report"), Mapping) else None
    synthesis = report.get("opportunity_synthesis") if isinstance(report.get("opportunity_synthesis"), Mapping) else None
    if marketplace:
        lines.extend(["", "## Marketplace pillar projection", "", f"- Top marketplace candidate: `{marketplace.get('top_candidate_id') or 'none'}`", f"- Marketplaces observed: {', '.join(marketplace.get('marketplaces_observed') or []) or 'none'}", f"- Next marketplace action: `{marketplace.get('next_best_action')}`", "- Projection feeds Product Opportunity Synthesis only; it is not supplier proof."])
    if synthesis:
        lines.extend(["", "## Opportunity synthesis (marketplace pillar)", "", f"- Recommendation: `{synthesis.get('overall_recommendation')}`", f"- Combined opportunity: {float(synthesis.get('combined_opportunity_score', 0) or 0):.0%}", f"- Next action: `{synthesis.get('next_best_action')}`", "- CPA/CTR/budget/scale thresholds in the synthesis layer remain planning assumptions."])
    lines.extend(["", "Public-market evidence is read-only market context, not supplier proof. No provider actions were performed."])
    return "\n".join(lines) + "\n"

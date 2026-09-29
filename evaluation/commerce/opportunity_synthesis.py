"""Deterministic fusion of MarketOS' three offline evidence pillars.

This module is deliberately a thin decision layer over the existing marketplace,
supplier-feasibility, and consumer-attention reports.  It does not rescore raw
evidence, call providers, or grant launch authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from .market_access_report import build_market_access_section

RECOMMENDATIONS = frozenset(
    {
        "advance_to_launch_draft",
        "validate_supplier_first",
        "expand_supplier_research",
        "expand_consumer_research",
        "expand_marketplace_research",
        "reject_poor_margin",
        "reject_low_attention",
        "reject_oversaturated",
        "hold_for_manual_review",
    }
)
CONFIDENCE_GRADES = frozenset({"A_live_validated", "B_multi_source_manual", "C_fixture_or_partial", "D_low_confidence", "F_reject_or_missing"})


def _bounded(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value or 0))), 4)
    except (TypeError, ValueError):
        return 0.0


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def _identity_key(candidate: Mapping[str, Any]) -> str:
    """SYN-ALIAS-NO-COLLAPSE: a conservative correlated-alias signal built
    only from fields the existing evidence/offers contract already
    carries -- `source_family` provenance plus the candidate's own
    `query` -- not a new identity registry or source-family authority.

    Requires an explicit `source_family` on at least one evidence/offer
    item before two candidates can ever be considered aliases: `query`
    text alone is too weak and generic to safely collapse two
    candidates (many genuinely distinct products share a plain search
    query), so query-only matches are left as separate, distinct
    candidates.
    """
    source_families = sorted({str(item.get("source_family")) for item in _evidence(candidate, "evidence") + _evidence(candidate, "offers") if item.get("source_family")})
    if not source_families:
        return ""
    query = _text(candidate.get("query") or "", 160).lower()
    return f"{query}|{','.join(source_families)}"


def _candidate_map(report: Mapping[str, Any] | None) -> tuple[dict[str, Mapping[str, Any]], tuple[str, ...]]:
    """Builds the candidate_id -> candidate map for one pillar report,
    collapsing correlated aliases (same query + source_family, different
    candidate_id) so the same product/source family is never scored and
    ranked twice. A literal duplicate candidate_id still collapses via
    plain dict-key overwrite, as before. Ambiguity is never silently
    dropped: every collapse is recorded in the returned notes tuple, and
    a score mismatch between the kept candidate and its alias is called
    out explicitly rather than picked arbitrarily."""
    result: dict[str, Mapping[str, Any]] = {}
    seen_identity: dict[str, tuple[str, Mapping[str, Any]]] = {}
    notes: list[str] = []
    for item in (report or {}).get("candidates", []):
        if not item.get("candidate_id"):
            continue
        candidate_id = str(item.get("candidate_id"))
        identity = _identity_key(item)
        if identity and identity in seen_identity:
            kept_id, kept_item = seen_identity[identity]
            if _score(item) != _score(kept_item):
                notes.append(f"correlated alias '{candidate_id}' of '{kept_id}' shares query/source_family but reported conflicting scores; kept '{kept_id}' and excluded '{candidate_id}' from ranking")
            else:
                notes.append(f"correlated alias '{candidate_id}' collapsed into '{kept_id}' (same query and source_family)")
            continue
        if identity:
            seen_identity[identity] = (candidate_id, item)
        result[candidate_id] = item
    return result, tuple(notes)


def _score(candidate: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return (candidate or {}).get("score", {}) if isinstance((candidate or {}).get("score", {}), Mapping) else {}


def _evidence(candidate: Mapping[str, Any] | None, key: str) -> list[Mapping[str, Any]]:
    values = (candidate or {}).get(key, [])
    return [item for item in values if isinstance(item, Mapping)]


def _mode(report: Mapping[str, Any] | None, candidate: Mapping[str, Any] | None) -> str:
    modes = [str((report or {}).get("evidence_mode", ""))]
    for item in _evidence(candidate, "evidence") + _evidence(candidate, "offers"):
        modes.append(str(item.get("evidence_mode", "")))
    return next((item for item in modes if item in {"live_readonly", "public_live", "authenticated_live"}), next((item for item in modes if item in {"manual_import", "fixture_demo", "fixture"}), "missing"))


LIVE_EVIDENCE_MODES = frozenset({"live_readonly", "public_live", "authenticated_live"})


def _grade(market: Mapping[str, Any] | None, supplier: Mapping[str, Any] | None, consumer: Mapping[str, Any] | None, scores: tuple[float, float, float], recommendation: str, market_report: Mapping[str, Any] | None = None, supplier_report: Mapping[str, Any] | None = None, consumer_report: Mapping[str, Any] | None = None) -> str:
    """SYN-GRADE-LIVE-LABEL fix: `A_live_validated` used to require only
    that *any one* of the three supplied pillars carry a live-looking
    evidence_mode -- so one live-labeled pillar mixed with two fixture/
    manual ones still graded as professionally live-validated. It now
    requires an explicit live attestation on *every* supplied pillar
    (`all(...)`, not `any(...)`): three populated pillars alone is never
    sufficient, and a single fixture/manual pillar caps the grade at
    C_fixture_or_partial even when another pillar claims live evidence.

    Evidence-label consistency: `market`/`supplier`/`consumer` are the
    per-candidate evidence entries, which never carry the pillar
    *report's own* top-level `evidence_mode`. A candidate whose embedded
    evidence/offer items claim `live_readonly` while the pillar report
    that contained it is itself labeled `fixture_demo` (or the reverse)
    is an internally inconsistent label, not a live attestation --
    `market_report`/`supplier_report`/`consumer_report` (the original
    top-level report dicts, optional for backward compatibility) are
    checked too, and a live grade requires the top-level label to agree.
    """
    if recommendation.startswith("reject") or not any(scores):
        return "F_reject_or_missing"
    pillars = [(candidate, report) for candidate, report in ((market, market_report), (supplier, supplier_report), (consumer, consumer_report)) if candidate]
    supplied = len(pillars)
    modes = [_mode(None, candidate) for candidate, _ in pillars]
    top_level_modes = [str((report or {}).get("evidence_mode", "")) for _, report in pillars]
    if supplied == 3 and all(mode in LIVE_EVIDENCE_MODES for mode in modes) and all(mode in LIVE_EVIDENCE_MODES for mode in top_level_modes):
        return "A_live_validated"
    if supplied == 3 and set(modes) <= {"manual_import"}:
        return "B_multi_source_manual"
    if supplied >= 2:
        return "C_fixture_or_partial"
    return "D_low_confidence"


def _price_band(market_candidate: Mapping[str, Any] | None) -> tuple[float | None, float | None]:
    prices: list[float] = []
    for item in _evidence(market_candidate, "evidence"):
        for key in ("price", "price_band_min", "price_band_max"):
            value = _number(item.get(key))
            if value is not None and value > 0:
                prices.append(value)
    if not prices:
        return None, None
    return round(min(prices), 2), round(max(prices), 2)


def _economics(supplier_candidate: Mapping[str, Any] | None) -> dict[str, Any]:
    economics = _score(supplier_candidate).get("economics")
    return dict(economics) if isinstance(economics, Mapping) else {}


def _risks(market: Mapping[str, Any] | None, supplier: Mapping[str, Any] | None, consumer: Mapping[str, Any] | None) -> "ProductOpportunityRiskProfile":
    market_score, supplier_score, consumer_score = _score(market), _score(supplier), _score(consumer)
    marketplace_risks: list[str] = []
    supplier_risks: list[str] = []
    consumer_risks: list[str] = []
    if not market:
        marketplace_risks.append("marketplace_evidence_missing")
    if _bounded(market_score.get("saturation_score")) >= 0.7:
        marketplace_risks.append("marketplace_saturation_high")
    if not supplier:
        supplier_risks.append("supplier_proof_missing")
    for flag in supplier_score.get("risk_flags", []):
        if isinstance(flag, Mapping) and flag.get("code"):
            supplier_risks.append(str(flag["code"]))
    if not consumer:
        consumer_risks.append("consumer_attention_missing")
    if _bounded(consumer_score.get("objection_density")) >= 0.6:
        consumer_risks.append("objection_density_high")
    if _bounded(consumer_score.get("attention_saturation_risk")) >= 0.7:
        consumer_risks.append("creative_saturation_high")
    blockers = sorted(set(supplier_risks + marketplace_risks + consumer_risks))
    level = "high" if any(item in blockers for item in ("supplier_proof_missing", "low_margin_proxy", "marketplace_saturation_high", "objection_density_high")) else "medium" if blockers else "low"
    return ProductOpportunityRiskProfile(level, tuple(sorted(set(supplier_risks))), tuple(sorted(set(marketplace_risks))), tuple(sorted(set(consumer_risks))), tuple(blockers))


@dataclass(frozen=True)
class ProductOpportunityDecisionThresholds:
    target_sell_price: float | None
    recommended_price_band_min: float | None
    recommended_price_band_max: float | None
    estimated_landed_cost: float | None
    gross_margin_percent: float | None
    profit_per_order_before_ads: float | None
    break_even_cpa: float | None
    break_even_roas: float | None
    max_test_budget_recommendation: float | None
    minimum_validation_sample_size: int
    kill_if_cpa_above: float | None
    kill_if_ctr_below: float
    kill_if_add_to_cart_below: float
    scale_if_cpa_below: float | None
    scale_if_margin_above: float
    supplier_validation_required: bool
    assumptions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["assumptions"] = list(self.assumptions)
        return result


@dataclass(frozen=True)
class ProductOpportunityRiskProfile:
    risk_level: str
    supplier_risks: tuple[str, ...] = ()
    marketplace_risks: tuple[str, ...] = ()
    consumer_risks: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("supplier_risks", "marketplace_risks", "consumer_risks", "blockers"):
            result[key] = list(result[key])
        return result


@dataclass(frozen=True)
class ProductOpportunityRecommendation:
    code: str
    rationale: str
    next_action: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ProductOpportunityScore:
    candidate_id: str
    marketplace_opportunity: float
    supplier_feasibility: float
    consumer_attention: float
    combined_opportunity_score: float
    evidence_confidence: float
    confidence_grade: str
    recommendation: ProductOpportunityRecommendation
    risk_profile: ProductOpportunityRiskProfile
    contributions: Mapping[str, float]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["recommendation"] = self.recommendation.to_dict()
        result["risk_profile"] = self.risk_profile.to_dict()
        result["contributions"] = dict(self.contributions)
        return result


@dataclass(frozen=True)
class ProductOpportunityEvidenceMatrix:
    marketplace: Mapping[str, Any]
    supplier: Mapping[str, Any]
    consumer: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"marketplace": dict(self.marketplace), "supplier": dict(self.supplier), "consumer": dict(self.consumer)}


@dataclass(frozen=True)
class ProductOpportunityActionPlan:
    candidate_id: str
    recommendation: str
    days: tuple[Mapping[str, Any], ...]
    client_checklist: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"candidate_id": self.candidate_id, "recommendation": self.recommendation, "days": [dict(item) for item in self.days], "client_checklist": list(self.client_checklist)}


@dataclass(frozen=True)
class ProductOpportunityCandidate:
    candidate_id: str
    title: str
    query: str
    score: ProductOpportunityScore
    decision_thresholds: ProductOpportunityDecisionThresholds
    unit_economics_summary: Mapping[str, Any]
    evidence_matrix: ProductOpportunityEvidenceMatrix
    top_hooks: tuple[str, ...] = ()
    top_pain_points: tuple[str, ...] = ()
    top_objections: tuple[str, ...] = ()
    top_ad_angles: tuple[str, ...] = ()
    top_supplier_risks: tuple[str, ...] = ()
    top_marketplace_risks: tuple[str, ...] = ()
    top_consumer_risks: tuple[str, ...] = ()
    market_access: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["score"] = self.score.to_dict()
        result["decision_thresholds"] = self.decision_thresholds.to_dict()
        result["evidence_matrix"] = self.evidence_matrix.to_dict()
        for key in ("top_hooks", "top_pain_points", "top_objections", "top_ad_angles", "top_supplier_risks", "top_marketplace_risks", "top_consumer_risks"):
            result[key] = list(getattr(self, key))
        # Preserve the compact v1 keys consumed by existing reports/tests.
        result.update(
            {
                "marketplace_opportunity": self.score.marketplace_opportunity,
                "supplier_feasibility": self.score.supplier_feasibility,
                "consumer_attention": self.score.consumer_attention,
                "combined_opportunity": self.score.combined_opportunity_score,
                "combined_risk": self.score.risk_profile.risk_level,
                "combined_recommendation": self.score.recommendation.code,
                "next_best_action": self.score.recommendation.next_action,
            }
        )
        return result


@dataclass(frozen=True)
class ProductOpportunitySynthesisReport:
    report_version: str
    generated_at: str
    evidence_mode: str
    candidate_count: int
    top_candidate_id: str | None
    top_candidate_title: str | None
    overall_recommendation: str
    combined_opportunity_score: float
    marketplace_opportunity: float
    supplier_feasibility: float
    consumer_attention: float
    unit_economics_summary: Mapping[str, Any]
    evidence_confidence: float
    confidence_grade: str
    risk_profile: Mapping[str, Any]
    decision_thresholds: Mapping[str, Any]
    kill_scale_rules: Mapping[str, Any]
    recommended_price_band: Mapping[str, Any]
    break_even_cpa: float | None
    break_even_roas: float | None
    top_hooks: tuple[str, ...]
    top_pain_points: tuple[str, ...]
    top_objections: tuple[str, ...]
    top_ad_angles: tuple[str, ...]
    top_supplier_risks: tuple[str, ...]
    top_marketplace_risks: tuple[str, ...]
    top_consumer_risks: tuple[str, ...]
    next_best_action: str
    fourteen_day_validation_plan: tuple[Mapping[str, Any], ...]
    client_summary: str
    operator_summary: str
    candidates: tuple[ProductOpportunityCandidate, ...]
    source_reports: Mapping[str, str]
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False
    alias_notes: tuple[str, ...] = ()
    market_access: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("top_hooks", "top_pain_points", "top_objections", "top_ad_angles", "top_supplier_risks", "top_marketplace_risks", "top_consumer_risks", "alias_notes"):
            result[key] = list(getattr(self, key))
        result["fourteen_day_validation_plan"] = [dict(item) for item in self.fourteen_day_validation_plan]
        result["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        result["read_only"] = True
        result["network_calls"] = False
        result["mutated"] = False
        return result


def _recommendation(market: Mapping[str, Any] | None, supplier: Mapping[str, Any] | None, consumer: Mapping[str, Any] | None, combined: float, risk: ProductOpportunityRiskProfile) -> ProductOpportunityRecommendation:
    ms, ss, cs = _score(market), _score(supplier), _score(consumer)
    margin = _economics(supplier).get("gross_margin_percent")
    if str(ss.get("recommendation", "")).startswith("reject"):
        code = str(ss["recommendation"])
        return ProductOpportunityRecommendation(code, "The supplier feasibility layer has already identified a blocking risk.", "review_supplier_risk")
    if margin is not None and _number(margin) < 0.15:
        return ProductOpportunityRecommendation("reject_poor_margin", "The current landed-cost scenario is below the 15% margin floor.", "review_supplier_cost_or_price_band")
    if _bounded(ms.get("saturation_score")) >= 0.7:
        return ProductOpportunityRecommendation("reject_oversaturated", "Marketplace saturation is high relative to the available demand signal.", "expand_marketplace_research_before_testing")
    if cs.get("recommendation") in {"reject_low_attention", "reject_high_objection_risk"}:
        code = str(cs["recommendation"])
        return ProductOpportunityRecommendation(code, "Consumer evidence is too weak or objection-heavy for a responsible launch draft.", "expand_consumer_research")
    if not supplier:
        return ProductOpportunityRecommendation("validate_supplier_first", "Demand and/or creative evidence exists, but supplier feasibility is not supplied.", "run_readonly_supplier_validation")
    if not market:
        return ProductOpportunityRecommendation("expand_marketplace_research", "Supplier evidence exists, but market price and demand coverage is incomplete.", "expand_marketplace_research")
    if not consumer:
        return ProductOpportunityRecommendation("expand_consumer_research", "Market and supplier evidence exist, but customer language and creative evidence are missing.", "expand_consumer_research")
    if ss.get("recommendation") == "expand_supplier_research":
        return ProductOpportunityRecommendation("expand_supplier_research", "The supplier scenario is partial on logistics, inventory, or cost.", "expand_supplier_research")
    if combined >= 0.68 and risk.risk_level == "low":
        return ProductOpportunityRecommendation("advance_to_launch_draft", "All three evidence pillars are present and the deterministic score clears the draft threshold.", "prepare_launch_draft_for_human_review")
    if _bounded(cs.get("overall_consumer_attention")) < 0.35:
        return ProductOpportunityRecommendation("expand_consumer_research", "Attention evidence is below the creative-testing threshold.", "expand_consumer_research")
    return ProductOpportunityRecommendation("hold_for_manual_review", "Evidence is useful but the combined score or risk profile is not decisive.", "operator_review_evidence_matrix")


def _thresholds(market: Mapping[str, Any] | None, supplier: Mapping[str, Any] | None) -> ProductOpportunityDecisionThresholds:
    economics = _economics(supplier)
    low, high = _price_band(market)
    target = _number(economics.get("target_sell_price"))
    landed = _number(economics.get("estimated_landed_cost"))
    margin = _number(economics.get("gross_margin_percent"))
    profit = _number(economics.get("profit_per_order_before_ad_spend"))
    cpa = _number(economics.get("break_even_cpa"))
    roas = _number(economics.get("break_even_roas"))
    assumptions = ["ctr_and_add_to_cart_thresholds_are_planning_assumptions", "test_budget_is_a_rule_of_thumb_not_a_spend_authorization"]
    if target is None:
        assumptions.append("target_sell_price_missing")
    if landed is None:
        assumptions.append("estimated_landed_cost_missing")
    max_budget = round(min(500.0, max(0.0, profit * 20)), 2) if profit is not None else None
    kill_cpa = round(max(0.0, profit * 0.8), 2) if profit is not None else None
    scale_cpa = round(max(0.0, profit * 0.5), 2) if profit is not None else None
    live_supplier = any(item.get("evidence_mode") in {"live_readonly", "authenticated_live"} for item in _evidence(supplier, "offers"))
    if not live_supplier:
        assumptions.append("supplier_readonly_proof_missing")
    return ProductOpportunityDecisionThresholds(target, low, high, landed, margin, profit, cpa, roas, max_budget, 20, kill_cpa, 0.008, 0.02, scale_cpa, 0.35, not live_supplier, tuple(assumptions))


def _plan(candidate_id: str, recommendation: str) -> ProductOpportunityActionPlan:
    if recommendation == "validate_supplier_first":
        focus = "supplier-first"
        days = (("1-2", "Run one bounded read-only supplier validation and confirm cost, SKU, inventory, shipping, and delivery."), ("3-4", "Compare supplier cost against observed marketplace price bands."), ("5-6", "Draft a provisional offer and landing-page brief using only observed fields."), ("7-8", "Write creative scripts from existing hooks; do not publish."), ("9-10", "Prepare a bounded test design with no spend or posting action."), ("11-12", "Review evidence gaps and sensitivity scenarios."), ("13", "Kill, iterate, or advance only if thresholds are met."), ("14", "Update the client report with provenance and next gate."))
    elif recommendation in {"expand_consumer_research", "reject_low_attention"}:
        focus = "consumer-research"
        days = (("1-2", "Collect sanitized search, review, comment, and creative imports."), ("3-4", "Cluster pain points, objections, and desired outcomes."), ("5-6", "Draft three hook and UGC hypotheses for review."), ("7-8", "Compare creative angles against competitor evidence."), ("9-10", "Define a no-spend creative test design."), ("11-12", "Review attention confidence and saturation risk."), ("13", "Kill weak angles or retain the strongest hypothesis."), ("14", "Update the client report and supplier gate."))
    elif recommendation == "reject_poor_margin":
        focus = "economics-research"
        days = (("1-2", "Recheck landed-cost and fee assumptions."), ("3-4", "Test alternative supplier and price-band scenarios."), ("5-6", "Identify whether shipping or MOQ is the margin blocker."), ("7-8", "Remove unsupported profit claims from the offer draft."), ("9-10", "Compare substitute candidates."), ("11-12", "Review margin sensitivity."), ("13", "Reject or revise the candidate."), ("14", "Update the client report."))
    elif recommendation == "advance_to_launch_draft":
        focus = "launch-draft"
        days = (("1-2", "Freeze the evidence matrix and confirm remaining assumptions."), ("3-4", "Draft the offer and landing-page brief."), ("5-6", "Prepare creative scripts and asset requirements."), ("7-8", "Complete human review of claims and compliance risks."), ("9-10", "Prepare a bounded test design; no launch occurs here."), ("11-12", "Review thresholds and kill rules."), ("13", "Approve, iterate, or stop the draft."), ("14", "Deliver the updated client report."))
    else:
        focus = "manual-review"
        days = (("1-2", "Review the evidence matrix and missing fields."), ("3-4", "Resolve the highest-confidence source gap."), ("5-6", "Recalculate economics and risk."), ("7-8", "Review hooks and objections."), ("9-10", "Compare one alternative candidate."), ("11-12", "Document the decision threshold."), ("13", "Kill or select the next validation."), ("14", "Update the client report."))
    return ProductOpportunityActionPlan(candidate_id, recommendation, tuple({"window": window, "focus": focus, "task": task, "read_only": True} for window, task in days), ("Confirm evidence provenance.", "Confirm supplier proof status.", "Review assumptions and thresholds.", "Approve the next bounded validation step."))


def _candidate(candidate_id: str, market: Mapping[str, Any] | None, supplier: Mapping[str, Any] | None, consumer: Mapping[str, Any] | None, *, use_consumer_weight: bool = True, market_report: Mapping[str, Any] | None = None, supplier_report: Mapping[str, Any] | None = None, consumer_report: Mapping[str, Any] | None = None, market_access_evidence: Mapping[str, Any] | None = None) -> tuple[ProductOpportunityCandidate, ProductOpportunityActionPlan]:
    market_score, supplier_score, consumer_score = _score(market), _score(supplier), _score(consumer)
    m, s, c = _bounded(market_score.get("overall_marketplace_opportunity")), _bounded(supplier_score.get("overall_supplier_feasibility")), _bounded(consumer_score.get("overall_consumer_attention"))
    combined = round(m * 0.4 + s * 0.35 + c * 0.25, 4) if use_consumer_weight else round(m * 0.55 + s * 0.45, 4)
    risk = _risks(market, supplier, consumer)
    recommendation = _recommendation(market, supplier, consumer, combined, risk)
    confidence = round((m + s + c) / 3, 4)
    grade = _grade(market, supplier, consumer, (m, s, c), recommendation.code, market_report, supplier_report, consumer_report)
    thresholds = _thresholds(market, supplier)
    economics = _economics(supplier)
    consumer_voc = consumer_score.get("voice_of_customer", {}) if isinstance(consumer_score.get("voice_of_customer", {}), Mapping) else {}
    title = _text((market or supplier or consumer or {}).get("query") or candidate_id, 120)
    query = _text((market or supplier or consumer or {}).get("query") or candidate_id, 160)
    matrix = ProductOpportunityEvidenceMatrix(
        {"status": "supplied" if market else "missing", "mode": _mode(None, market), "score": m},
        {"status": "supplied" if supplier else "missing", "mode": _mode(None, supplier), "score": s},
        {"status": "supplied" if consumer else "missing", "mode": _mode(None, consumer), "score": c},
    )
    score = ProductOpportunityScore(candidate_id, m, s, c, combined, confidence, grade, recommendation, risk, {"marketplace_weight": 0.4 if use_consumer_weight else 0.55, "supplier_weight": 0.35 if use_consumer_weight else 0.45, "consumer_weight": 0.25 if use_consumer_weight else 0.0, "raw_marketplace": m, "raw_supplier": s, "raw_consumer": c})
    action = _plan(candidate_id, recommendation.code)
    hooks = tuple(item.get("hook", "") for item in consumer_score.get("creative_hooks", []) if isinstance(item, Mapping) and item.get("hook"))
    offering_kind = (market or {}).get("offering_kind") or (supplier or {}).get("offering_kind") or (consumer or {}).get("offering_kind")
    market_access = build_market_access_section({"id": candidate_id, "offering_kind": offering_kind}, market_access_evidence)
    result = ProductOpportunityCandidate(candidate_id, title, query, score, thresholds, economics, matrix, hooks, tuple(consumer_voc.get("pain_points", [])), tuple(consumer_voc.get("objections", [])), tuple(consumer_score.get("recommended_ad_angles", [])), tuple(risk.supplier_risks), tuple(risk.marketplace_risks), tuple(risk.consumer_risks), market_access)
    return result, action


def build_product_opportunity_synthesis(
    marketplace_report: Mapping[str, Any] | None,
    supplier_report: Mapping[str, Any] | None,
    consumer_report: Mapping[str, Any] | None,
    *,
    product_validation_report: Mapping[str, Any] | None = None,
    client_context: Mapping[str, Any] | None = None,
    market_access_evidence: Mapping[str, Any] | None = None,
) -> ProductOpportunitySynthesisReport:
    (market, market_alias_notes), (supplier, supplier_alias_notes), (consumer, consumer_alias_notes) = _candidate_map(marketplace_report), _candidate_map(supplier_report), _candidate_map(consumer_report)
    alias_notes = tuple(market_alias_notes + supplier_alias_notes + consumer_alias_notes)
    market_access_evidence = dict(market_access_evidence or {})
    candidates: list[ProductOpportunityCandidate] = []
    plans: dict[str, ProductOpportunityActionPlan] = {}
    for candidate_id in sorted(set(market) | set(supplier) | set(consumer)):
        item, plan = _candidate(candidate_id, market.get(candidate_id), supplier.get(candidate_id), consumer.get(candidate_id), use_consumer_weight=consumer_report is not None, market_report=marketplace_report, supplier_report=supplier_report, consumer_report=consumer_report, market_access_evidence=market_access_evidence.get(candidate_id))
        candidates.append(item)
        plans[candidate_id] = plan
    candidates.sort(key=lambda item: (-item.score.combined_opportunity_score, item.candidate_id))
    top = candidates[0] if candidates else None
    plan = plans[top.candidate_id] if top else _plan("", "hold_for_manual_review")
    source_reports = {"marketplace": "supplied" if marketplace_report else "missing", "supplier": "supplied" if supplier_report else "missing", "consumer_attention": "supplied" if consumer_report else "missing", "product_validation": "supplied" if product_validation_report else "missing"}
    report_modes = [str(report.get("evidence_mode", "")) for report in (marketplace_report, supplier_report, consumer_report) if report]
    mode = "fixture_demo" if "fixture_demo" in report_modes else "manual_import" if "manual_import" in report_modes else "sanitized_report"
    if top:
        rec = top.score.recommendation
        client = f"{top.title} is the leading candidate at {top.score.combined_opportunity_score:.0%} combined opportunity. Recommendation: {rec.code}. This is validation guidance, not a profit guarantee or launch authorization."
        operator = f"Next action: {rec.next_action}. Confidence: {top.score.confidence_grade}. Risks: {', '.join(top.score.risk_profile.blockers) or 'none recorded'}."
        band = {"min": top.decision_thresholds.recommended_price_band_min, "max": top.decision_thresholds.recommended_price_band_max, "currency": "USD", "status": "observed_or_derived" if top.decision_thresholds.recommended_price_band_min is not None else "unavailable"}
        return ProductOpportunitySynthesisReport("product-opportunity-synthesis-v1", "deterministic", mode, len(candidates), top.candidate_id, top.title, rec.code, top.score.combined_opportunity_score, top.score.marketplace_opportunity, top.score.supplier_feasibility, top.score.consumer_attention, top.unit_economics_summary, top.score.evidence_confidence, top.score.confidence_grade, top.score.risk_profile.to_dict(), top.decision_thresholds.to_dict(), {"kill_if_cpa_above": top.decision_thresholds.kill_if_cpa_above, "scale_if_cpa_below": top.decision_thresholds.scale_if_cpa_below, "kill_if_ctr_below": top.decision_thresholds.kill_if_ctr_below, "kill_if_add_to_cart_below": top.decision_thresholds.kill_if_add_to_cart_below, "scale_if_margin_above": top.decision_thresholds.scale_if_margin_above}, band, top.decision_thresholds.break_even_cpa, top.decision_thresholds.break_even_roas, top.top_hooks, top.top_pain_points, top.top_objections, top.top_ad_angles, top.top_supplier_risks, top.top_marketplace_risks, top.top_consumer_risks, rec.next_action, plan.days, client, operator, tuple(candidates), source_reports, alias_notes=alias_notes, market_access=top.market_access)
    return ProductOpportunitySynthesisReport(
        report_version="product-opportunity-synthesis-v1",
        generated_at="deterministic",
        evidence_mode="fixture_demo",
        candidate_count=0,
        top_candidate_id=None,
        top_candidate_title=None,
        overall_recommendation="hold_for_manual_review",
        combined_opportunity_score=0.0,
        marketplace_opportunity=0.0,
        supplier_feasibility=0.0,
        consumer_attention=0.0,
        unit_economics_summary={},
        evidence_confidence=0.0,
        confidence_grade="F_reject_or_missing",
        risk_profile={},
        decision_thresholds={},
        kill_scale_rules={},
        recommended_price_band={},
        break_even_cpa=None,
        break_even_roas=None,
        top_hooks=(),
        top_pain_points=(),
        top_objections=(),
        top_ad_angles=(),
        top_supplier_risks=(),
        top_marketplace_risks=(),
        top_consumer_risks=(),
        next_best_action="hold_for_manual_review",
        fourteen_day_validation_plan=plan.days,
        client_summary="No candidate evidence was supplied.",
        operator_summary="Supply at least one sanitized evidence report.",
        candidates=(),
        source_reports=source_reports,
        alias_notes=alias_notes,
        market_access=build_market_access_section({"id": ""}),
    )


def synthesize_opportunities(marketplace_report: Mapping[str, Any] | None, supplier_report: Mapping[str, Any] | None, consumer_report: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Backward-compatible compact view used by existing callers."""
    report = build_product_opportunity_synthesis(marketplace_report, supplier_report, consumer_report)
    return [candidate.to_dict() for candidate in report.candidates]


def build_synthesis_report(marketplace_report: Mapping[str, Any] | None, supplier_report: Mapping[str, Any] | None, consumer_report: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result = build_product_opportunity_synthesis(marketplace_report, supplier_report, consumer_report).to_dict()
    if result.get("candidates") and result["candidates"][0]["combined_recommendation"] == "validate_supplier_first":
        result["next_best_action"] = f"validate_live_supplier_first:{result['top_candidate_id']}"
    return result

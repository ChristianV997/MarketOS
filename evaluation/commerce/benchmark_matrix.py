"""Deterministic Phase 1 candidate comparison and validation-priority matrix.

The matrix consumes normalized/sanitized evidence summaries.  It is a
commercial decision workbench, not a new commerce runner, provider adapter,
or event system.  It never fetches, writes, or promotes a candidate.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from .readiness import _safe, load_sanitized_artifact

VERSION = "phase1-benchmark-matrix-v1"
DECISIONS = (
    "advance_to_live_supplier_validation", "advance_to_competitor_expansion", "hold_for_credentials",
    "reject_insufficient_margin", "reject_insufficient_evidence", "reject_high_risk",
    "ready_for_readonly_deployment", "needs_mapping_hardening", "needs_operator_review",
)


def _number(value: Any, default: float = 0.0) -> float:
    try: return float(value)
    except (TypeError, ValueError): return default


def _bounded(value: Any) -> float:
    return round(max(0.0, min(1.0, _number(value))), 4)


@dataclass(frozen=True)
class SupplierEvidenceScore:
    score: float; confidence: float; observed_fields: tuple[str, ...]; source_type: str; credential_status: str; reasons: tuple[str, ...]
    def to_dict(self) -> dict[str, Any]: return {**asdict(self), "observed_fields": list(self.observed_fields), "reasons": list(self.reasons)}

@dataclass(frozen=True)
class CompetitionEvidenceScore:
    score: float; confidence: float; observed_offers: int; pricing_coverage: float; source_diversity: int; reasons: tuple[str, ...]
    def to_dict(self) -> dict[str, Any]: return {**asdict(self), "reasons": list(self.reasons)}

@dataclass(frozen=True)
class EconomicsScore:
    score: float; margin_quality: str; gross_margin: float | None; assumption_ratio: float; reasons: tuple[str, ...]
    def to_dict(self) -> dict[str, Any]: return {**asdict(self), "reasons": list(self.reasons)}

@dataclass(frozen=True)
class ValidationPriorityScore:
    score: float; priority: str; target: str; reasons: tuple[str, ...]
    def to_dict(self) -> dict[str, Any]: return {**asdict(self), "reasons": list(self.reasons)}

@dataclass(frozen=True)
class BenchmarkCandidate:
    candidate_id: str; title: str; query: str; category: str; source: str; supplier_evidence: dict[str, Any] = field(default_factory=dict); competition_evidence: dict[str, Any] = field(default_factory=dict); opportunity_score: float = 0.0; research_cluster: str = ""; commerce_run: dict[str, Any] = field(default_factory=dict); evaluation_summary: dict[str, Any] = field(default_factory=dict); readiness_summary: dict[str, Any] = field(default_factory=dict); assumptions: tuple[str, ...] = (); warnings: tuple[str, ...] = ()
    def to_dict(self) -> dict[str, Any]:
        value = asdict(self); value["assumptions"] = list(self.assumptions); value["warnings"] = list(self.warnings); return value

@dataclass(frozen=True)
class CandidateEvidenceSnapshot:
    candidate: BenchmarkCandidate; supplier: SupplierEvidenceScore; competition: CompetitionEvidenceScore; economics: EconomicsScore; validation: ValidationPriorityScore; evidence_completeness: float; assumption_ratio: float; risk_level: str; commercial_decision: str; next_best_action: str
    def to_dict(self) -> dict[str, Any]:
        return {"candidate": self.candidate.to_dict(), "supplier_evidence": self.supplier.to_dict(), "competition_evidence": self.competition.to_dict(), "economics": self.economics.to_dict(), "validation_priority": self.validation.to_dict(), "evidence_completeness": self.evidence_completeness, "assumption_ratio": self.assumption_ratio, "risk_level": self.risk_level, "commercial_decision": self.commercial_decision, "next_best_action": self.next_best_action}

@dataclass(frozen=True)
class CommercialDecision:
    candidate_id: str; decision: str; reasons: tuple[str, ...]; blocking_reason: str | None = None
    def to_dict(self) -> dict[str, Any]: return {**asdict(self), "reasons": list(self.reasons)}

@dataclass(frozen=True)
class BenchmarkMatrixReport:
    report_version: str; generated_at: str; status: str; evidence_mode: str; candidates: tuple[CandidateEvidenceSnapshot, ...]; top_candidate_id: str | None; highest_validation_priority: dict[str, Any]; next_best_action: str; warnings: tuple[str, ...]; source_artifacts: dict[str, str]; read_only: bool = True; mutated: bool = False; network_calls: bool = False
    def to_dict(self) -> dict[str, Any]:
        return {"report_version": self.report_version, "generated_at": self.generated_at, "status": self.status, "evidence_mode": self.evidence_mode, "candidate_count": len(self.candidates), "candidates": [item.to_dict() for item in self.candidates], "top_candidate_id": self.top_candidate_id, "highest_validation_priority": self.highest_validation_priority, "next_best_action": self.next_best_action, "warnings": list(self.warnings), "source_artifacts": dict(self.source_artifacts), "read_only": self.read_only, "mutated": self.mutated, "network_calls": self.network_calls}

@dataclass(frozen=True)
class BenchmarkMatrixComparison:
    baseline_top_candidate_id: str | None; current_top_candidate_id: str | None; candidate_score_deltas: dict[str, float | None]; notes: tuple[str, ...] = ()
    def to_dict(self) -> dict[str, Any]: return {**asdict(self), "notes": list(self.notes)}


def supplier_score(value: Mapping[str, Any]) -> SupplierEvidenceScore:
    fields = tuple(sorted(str(item) for item in value.get("observed_fields", []) if item))
    source = str(value.get("source_type", value.get("source", "unavailable")))
    credential = str(value.get("credential_status", "not_configured"))
    field_weights = {"price": .32, "sku": .12, "inventory": .16, "variant": .12, "shipping": .16, "delivery": .12}
    score = sum(weight for field, weight in field_weights.items() if field in fields)
    if "authenticated" in source: score += .08
    if source == "fixture": score *= .55
    reasons = [f"{field}_observed" for field in fields]
    if credential == "credential_missing": reasons.append("credential_missing")
    return SupplierEvidenceScore(round(min(1.0, score), 4), _bounded(value.get("confidence", score)), fields, source, credential, tuple(reasons or ["supplier_evidence_unavailable"]))


def competition_score(value: Mapping[str, Any]) -> CompetitionEvidenceScore:
    offers = int(_number(value.get("observed_offers", value.get("offer_count", 0))))
    coverage = _bounded(value.get("pricing_coverage"))
    sources = value.get("sources", [])
    diversity = len(set(sources)) if isinstance(sources, list) else int(_number(value.get("source_diversity", 0)))
    availability = bool(value.get("availability_observed")); reviews = bool(value.get("reviews_observed"))
    score = min(1.0, .35 * min(offers / 3, 1) + .4 * coverage + .1 * min(diversity / 3, 1) + .1 * availability + .05 * reviews)
    reasons = [f"{offers}_offers", f"pricing_coverage_{coverage}"]
    if value.get("js_rendered"): reasons.append("js_rendered_public_evidence")
    return CompetitionEvidenceScore(round(score, 4), _bounded(value.get("confidence", score)), offers, coverage, diversity, tuple(reasons))


def economics_score(value: Mapping[str, Any], supplier: SupplierEvidenceScore, competition: CompetitionEvidenceScore, assumptions: tuple[str, ...]) -> EconomicsScore:
    margin = value.get("gross_margin")
    margin_number = _number(margin, -1) if margin is not None else None
    assumption_ratio = _bounded(value.get("assumption_ratio", len(assumptions) / 6 if assumptions else 0))
    shipping = "shipping" in supplier.observed_fields; delivery = "delivery" in supplier.observed_fields
    score = .35 * supplier.score + .3 * competition.score + .15 * (max(0, min(1, margin_number)) if margin_number is not None else 0) + .1 * shipping + .1 * delivery - .25 * assumption_ratio
    quality = "high" if score >= .7 else "medium" if score >= .45 else "low"
    reasons = ["supplier_cost_observed" if "price" in supplier.observed_fields else "supplier_cost_unknown", "market_price_observed" if competition.pricing_coverage else "market_price_unknown"]
    if not shipping: reasons.append("shipping_unknown")
    if not delivery: reasons.append("delivery_unknown")
    return EconomicsScore(round(max(0, min(1, score)), 4), quality, margin_number, assumption_ratio, tuple(reasons))


def validation_priority(candidate: BenchmarkCandidate, supplier: SupplierEvidenceScore, competition: CompetitionEvidenceScore, economics: EconomicsScore) -> ValidationPriorityScore:
    opportunity = _bounded(candidate.opportunity_score)
    if economics.gross_margin is not None and economics.gross_margin < .15: return ValidationPriorityScore(.05, "low", "none", ("insufficient_margin",))
    if supplier.score < .5 and opportunity >= .55:
        return ValidationPriorityScore(round(.5 * opportunity + .5 * (1 - supplier.score), 4), "high", "supplier", ("high_opportunity_missing_supplier_proof",))
    if competition.score < .5 and supplier.score >= .45:
        return ValidationPriorityScore(round(.45 * opportunity + .55 * (1 - competition.score), 4), "high", "competition", ("supplier_evidence_exists_pricing_missing",))
    if supplier.score >= .65 and competition.score >= .65:
        return ValidationPriorityScore(round(.4 * opportunity + .6 * economics.score, 4), "medium", "deployment", ("evidence_ready_for_readonly_deployment_review",))
    return ValidationPriorityScore(round(.4 * opportunity + .3 * (1 - supplier.score) + .3 * (1 - competition.score), 4), "medium", "operator_review", ("mixed_evidence_requires_review",))


def _decision(candidate: BenchmarkCandidate, supplier: SupplierEvidenceScore, competition: CompetitionEvidenceScore, economics: EconomicsScore, priority: ValidationPriorityScore) -> tuple[str, str, str]:
    if economics.gross_margin is not None and economics.gross_margin < .15: return "reject_insufficient_margin", "reject_low_margin", "gross_margin_below_15_percent"
    if economics.assumption_ratio >= .75 and candidate.opportunity_score < .55: return "reject_high_risk", "reject_high_assumption_ratio", "assumptions_dominate_evidence"
    if supplier.credential_status == "credential_missing" and priority.target == "supplier": return "hold_for_credentials", "set_cj_credentials_and_run_validation_pack", "supplier_validation_requires_credentials"
    if priority.target == "supplier": return "advance_to_live_supplier_validation", "run_live_cj_readonly_probe", "supplier_evidence_incomplete"
    if priority.target == "competition": return "advance_to_competitor_expansion", "expand_js_competitor_benchmark", "competitor_pricing_incomplete"
    if priority.target == "deployment": return "ready_for_readonly_deployment", "deploy_readonly_validation_stack", "read_only_evidence_threshold_met"
    if supplier.score == 0 and competition.score == 0: return "reject_insufficient_evidence", "collect_fixture_or_public_evidence", "no_supplier_or_competition_evidence"
    return "needs_operator_review", "review_mixed_evidence", "mixed_evidence"


def normalize_candidate(value: Mapping[str, Any]) -> BenchmarkCandidate:
    return BenchmarkCandidate(str(value.get("candidate_id", "unknown")), str(value.get("title", "Untitled candidate")), str(value.get("query", "")), str(value.get("category", "unknown")), str(value.get("source", "fixture")), dict(_safe(value.get("supplier_evidence", {}))), dict(_safe(value.get("competition_evidence", {}))), _bounded(value.get("opportunity_score")), str(value.get("research_cluster", "")), dict(_safe(value.get("commerce_run", {}))), dict(_safe(value.get("evaluation_summary", {}))), dict(_safe(value.get("readiness_summary", {}))), tuple(str(item) for item in value.get("assumptions", []) if item), tuple(str(item) for item in value.get("warnings", []) if item))


def evaluate_candidate(candidate: BenchmarkCandidate) -> CandidateEvidenceSnapshot:
    supplier = supplier_score(candidate.supplier_evidence); competition = competition_score(candidate.competition_evidence)
    economics = economics_score(candidate.commerce_run, supplier, competition, candidate.assumptions)
    priority = validation_priority(candidate, supplier, competition, economics)
    completeness = round((supplier.score + competition.score + economics.score) / 3, 4)
    risk = "high" if economics.assumption_ratio >= .7 or (supplier.score == 0 and competition.score == 0) else "medium" if completeness < .55 else "low"
    decision, action, _ = _decision(candidate, supplier, competition, economics, priority)
    return CandidateEvidenceSnapshot(candidate, supplier, competition, economics, priority, completeness, economics.assumption_ratio, risk, decision, action)


def default_candidates() -> list[BenchmarkCandidate]:
    return [
        normalize_candidate({"candidate_id": "portable-espresso-maker", "title": "Portable espresso maker", "query": "portable espresso maker", "category": "coffee", "source": "fixture", "supplier_evidence": {"source_type": "fixture", "observed_fields": ["price", "sku"], "confidence": .5, "credential_status": "credential_missing"}, "competition_evidence": {"observed_offers": 1, "pricing_coverage": .25, "sources": ["manufacturer"], "js_rendered": True, "confidence": .45}, "opportunity_score": .78, "research_cluster": "portable-coffee", "commerce_run": {"gross_margin": .42, "assumption_ratio": .5}, "assumptions": ["shipping", "delivery", "inventory"]}),
        normalize_candidate({"candidate_id": "travel-coffee-grinder", "title": "Travel coffee grinder", "query": "travel coffee grinder", "category": "coffee", "source": "fixture", "supplier_evidence": {"source_type": "fixture", "observed_fields": ["price", "inventory", "variant"], "confidence": .6}, "competition_evidence": {"observed_offers": 0, "pricing_coverage": 0}, "opportunity_score": .7, "research_cluster": "portable-coffee", "commerce_run": {"gross_margin": .36, "assumption_ratio": .48}, "assumptions": ["shipping", "delivery"]}),
        normalize_candidate({"candidate_id": "portable-blender", "title": "Portable blender", "query": "portable blender", "category": "kitchen", "source": "fixture", "supplier_evidence": {"source_type": "unavailable", "observed_fields": [], "credential_status": "credential_missing"}, "competition_evidence": {"observed_offers": 2, "pricing_coverage": .8, "sources": ["shopify", "manufacturer"], "availability_observed": True}, "opportunity_score": .62, "commerce_run": {"gross_margin": .28, "assumption_ratio": .65}, "assumptions": ["supplier_cost", "shipping", "delivery", "inventory"]}),
        normalize_candidate({"candidate_id": "mini-thermal-printer", "title": "Mini thermal printer", "query": "mini thermal printer", "category": "electronics", "source": "fixture", "supplier_evidence": {"source_type": "fixture", "observed_fields": ["price", "sku", "inventory", "variant"], "confidence": .75}, "competition_evidence": {"observed_offers": 3, "pricing_coverage": 1, "sources": ["shopify", "manufacturer", "independent"], "availability_observed": True, "reviews_observed": True}, "opportunity_score": .68, "commerce_run": {"gross_margin": .31, "assumption_ratio": .22}, "assumptions": ["delivery"]}),
        normalize_candidate({"candidate_id": "led-therapy-mask", "title": "LED therapy mask", "query": "LED therapy mask", "category": "beauty", "source": "fixture", "supplier_evidence": {"source_type": "fixture", "observed_fields": ["price"], "confidence": .35}, "competition_evidence": {"observed_offers": 1, "pricing_coverage": .5}, "opportunity_score": .43, "commerce_run": {"gross_margin": .1, "assumption_ratio": .82}, "assumptions": ["shipping", "delivery", "inventory", "variants", "quality"]}),
        normalize_candidate({"candidate_id": "resistance-band-kit", "title": "Resistance band kit", "query": "resistance band kit", "category": "fitness", "source": "fixture", "supplier_evidence": {"source_type": "fixture", "observed_fields": ["price", "sku", "inventory", "variant", "shipping"], "confidence": .8}, "competition_evidence": {"observed_offers": 2, "pricing_coverage": .9, "sources": ["shopify", "manufacturer"], "availability_observed": True}, "opportunity_score": .58, "commerce_run": {"gross_margin": .38, "assumption_ratio": .2}, "assumptions": ["delivery"]}),
    ]


def load_candidate_seed(path: str | Path | None) -> tuple[list[BenchmarkCandidate], list[str], str | None]:
    if not path: return default_candidates(), ["fixture_demo_candidates_used"], None
    value, warnings, source = load_sanitized_artifact(path)
    rows = value.get("candidates", value if isinstance(value, list) else [])
    if not isinstance(rows, list): return [], warnings + ["candidate_seed_requires_candidates_list"], source
    return [normalize_candidate(row) for row in rows if isinstance(row, Mapping)], warnings, source


def build_benchmark_matrix(*, candidates: list[BenchmarkCandidate] | None = None, readiness_report: Mapping[str, Any] | None = None, evaluation_report: Mapping[str, Any] | None = None, source_artifacts: Mapping[str, str] | None = None) -> BenchmarkMatrixReport:
    snapshots = sorted((evaluate_candidate(item) for item in (candidates if candidates is not None else default_candidates())), key=lambda item: (-item.evidence_completeness, -item.candidate.opportunity_score, item.candidate.candidate_id))
    top = snapshots[0] if snapshots else None
    highest = max(snapshots, key=lambda item: (item.validation.score, item.candidate.candidate_id), default=None)
    readiness_action = str((readiness_report or {}).get("next_best_action", ""))
    action = top.next_best_action if top else "collect_fixture_or_public_evidence"
    credential_hold = next((item for item in snapshots if item.commercial_decision == "hold_for_credentials" and item.validation.priority == "high"), None)
    if credential_hold is not None:
        action = "set_cj_credentials_and_run_validation_pack"
    if readiness_action.startswith("set_cj_credentials") and top and top.validation.target == "supplier": action = readiness_action
    evidence_mode = "fixture_demo" if all(item.candidate.source == "fixture" for item in snapshots) else "mixed_sanitized_artifacts"
    warnings = ["fixture_or_demo_evidence_is_not_live_proof"] if evidence_mode == "fixture_demo" else []
    return BenchmarkMatrixReport(VERSION, "deterministic", "ready" if snapshots else "degraded", evidence_mode, tuple(snapshots), top.candidate.candidate_id if top else None, highest.validation.to_dict() | {"candidate_id": highest.candidate.candidate_id} if highest else {}, action, tuple(warnings), dict(source_artifacts or {}))


def build_benchmark_from_paths(*, candidate_seed: str | Path | None = None, readiness_report: str | Path | None = None, evaluation_report: str | Path | None = None) -> BenchmarkMatrixReport:
    candidates, warnings, seed_path = load_candidate_seed(candidate_seed)
    readiness, readiness_warnings, readiness_path = load_sanitized_artifact(readiness_report)
    evaluation, evaluation_warnings, evaluation_path = load_sanitized_artifact(evaluation_report)
    report = build_benchmark_matrix(candidates=candidates, readiness_report=readiness, evaluation_report=evaluation, source_artifacts={key: value for key, value in {"candidate_seed": seed_path, "readiness_report": readiness_path, "evaluation_report": evaluation_path}.items() if value})
    if warnings or readiness_warnings or evaluation_warnings:
        return replace(report, warnings=tuple(sorted(set(report.warnings + tuple(warnings + readiness_warnings + evaluation_warnings)))))
    return report


__all__ = ["BenchmarkCandidate", "BenchmarkMatrixComparison", "BenchmarkMatrixReport", "CandidateEvidenceSnapshot", "CommercialDecision", "CompetitionEvidenceScore", "EconomicsScore", "SupplierEvidenceScore", "ValidationPriorityScore", "build_benchmark_from_paths", "build_benchmark_matrix", "competition_score", "default_candidates", "economics_score", "evaluate_candidate", "load_candidate_seed", "normalize_candidate", "supplier_score", "validation_priority"]

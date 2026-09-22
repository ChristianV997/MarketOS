"""services.market_research_evidence.report — build_evidence_integrity_report.

A disjoint, additive audit layer over the market-research evidence pillars.
It reuses `evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis`
for its existing alias-collapse notes (never recomputed here) and
`evaluation.trustos.client_workspace_isolation.check_workspace_leakage` as
the TrustOS client-safety boundary for its own output payload. It adds no
scorer, ranker, economics kernel, provider, scraper, or network call, and it
never resolves a detected conflict — only reports it.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis
from evaluation.trustos.client_workspace_isolation import check_workspace_leakage
from services.reporting.render import json_safe, render_markdown_report

from .conflict import detect_field_conflicts
from .freshness import classify_freshness
from .identity import build_observation_identity, build_source_identity, validate_binding
from .schemas import (
    MISSING,
    EvidenceIntegrityResult,
    EvidenceProvenance,
    FieldObservation,
    NegativeControls,
)

REPORT_VERSION = "market-research-evidence-integrity-v1"
TITLE = "MarketOS Market Research Evidence Integrity Report"

_PILLAR_CANDIDATE_KEYS = {
    "marketplace": "candidates",
    "supplier": "candidates",
    "consumer_attention": "candidates",
    "public_market_benchmark": "candidate_results",
}
_SCORE_FIELDS = {
    "marketplace": ("overall_marketplace_opportunity", "saturation_score"),
    "supplier": ("overall_supplier_feasibility",),
    "consumer_attention": ("overall_consumer_attention",),
}
_EXPECTED_FIELDS = {
    "marketplace": ("overall_marketplace_opportunity", "saturation_score"),
    "supplier": ("overall_supplier_feasibility", "shipping_cost"),
    "consumer_attention": ("overall_consumer_attention",),
    "public_market_benchmark": ("price", "shipping_cost"),
}


def _matched_candidate(report: Mapping[str, Any] | None, key: str, candidate_id: str) -> Mapping[str, Any] | None:
    if not report:
        return None
    for item in report.get(key, []) or []:
        if str(item.get("candidate_id")) == candidate_id:
            return item
    return None


def _observed_at(candidate: Mapping[str, Any] | None) -> str:
    if not candidate:
        return ""
    for key in ("observed_at", "as_of"):
        if candidate.get(key):
            return str(candidate[key])
    return ""


def _provenance(pillar: str, source_family: str, source_ref: str, candidate_id: str, workspace_id: str, field: str, evidence_mode: str, observed_at: str, as_of: str) -> EvidenceProvenance:
    return EvidenceProvenance(
        pillar=pillar,
        source=build_source_identity(source_family, source_ref),
        observation=build_observation_identity(candidate_id, workspace_id, field),
        evidence_mode=evidence_mode or MISSING,
        observed_at=observed_at or MISSING,
        freshness_status=classify_freshness(observed_at, as_of),
        capture_method="offline_report",
    )


def _score_field_observations(pillar: str, report: Mapping[str, Any], candidate: Mapping[str, Any], *, candidate_id: str, workspace_id: str, as_of: str, missing_fields: list[str]) -> list[FieldObservation]:
    observations: list[FieldObservation] = []
    evidence_mode = str(report.get("evidence_mode") or MISSING)
    observed_at = _observed_at(candidate)
    source_ref = str(candidate.get("query") or candidate_id)
    for field_name in _SCORE_FIELDS.get(pillar, ()):
        score = candidate.get("score", {})
        value = score.get(field_name) if isinstance(score, Mapping) else None
        if value is None:
            missing_fields.append(f"{pillar}.{field_name}")
            value = MISSING
        observations.append(
            FieldObservation(
                field=f"{pillar}.{field_name}",
                value=value,
                provenance=_provenance(pillar, pillar, source_ref, candidate_id, workspace_id, f"{pillar}.{field_name}", evidence_mode, observed_at, as_of),
            )
        )
    return observations


def _supplier_shipping_observations(report: Mapping[str, Any], candidate: Mapping[str, Any], *, candidate_id: str, workspace_id: str, as_of: str, missing_fields: list[str]) -> list[FieldObservation]:
    evidence_mode = str(report.get("evidence_mode") or MISSING)
    offers = [item for item in candidate.get("offers", []) or [] if isinstance(item, Mapping)]
    priced = [item for item in offers if item.get("shipping_cost") is not None]
    if not priced:
        missing_fields.append("supplier.shipping_cost")
        return []
    observations = []
    for offer in priced:
        source_ref = str(offer.get("supplier") or offer.get("source_type") or "supplier_offer")
        observations.append(
            FieldObservation(
                field="shipping_cost",
                value=offer["shipping_cost"],
                provenance=_provenance("supplier", "supplier", source_ref, candidate_id, workspace_id, "shipping_cost", evidence_mode, "", as_of),
            )
        )
    return observations


def _public_market_observations(report: Mapping[str, Any], candidate: Mapping[str, Any], *, candidate_id: str, workspace_id: str, as_of: str, missing_fields: list[str]) -> list[FieldObservation]:
    evidence_mode = str(report.get("evidence_mode") or MISSING)
    evidence_items = [item for item in candidate.get("evidence", []) or [] if isinstance(item, Mapping)]
    observations: list[FieldObservation] = []
    priced_any = False
    shipped_any = False
    for item in evidence_items:
        source_ref = str(item.get("source_domain") or item.get("competitor_url") or "public_market_evidence")
        if item.get("price") is not None:
            priced_any = True
            observations.append(FieldObservation("price", item["price"], _provenance("public_market_benchmark", "public_market_benchmark", source_ref, candidate_id, workspace_id, "price", evidence_mode, "", as_of)))
        if item.get("shipping_cost") is not None:
            shipped_any = True
            observations.append(FieldObservation("shipping_cost", item["shipping_cost"], _provenance("public_market_benchmark", "public_market_benchmark", source_ref, candidate_id, workspace_id, "shipping_cost", evidence_mode, "", as_of)))
    if not priced_any:
        missing_fields.append("public_market_benchmark.price")
    if not shipped_any:
        missing_fields.append("public_market_benchmark.shipping_cost")
    return observations


def build_evidence_integrity_report(
    *,
    candidate_id: str,
    workspace_id: str,
    as_of: str = "",
    marketplace_report: Mapping[str, Any] | None = None,
    supplier_report: Mapping[str, Any] | None = None,
    consumer_report: Mapping[str, Any] | None = None,
    public_market_benchmark_report: Mapping[str, Any] | None = None,
    product_validation_report: Mapping[str, Any] | None = None,
) -> EvidenceIntegrityResult:
    validate_binding(candidate_id, workspace_id)

    synthesis = build_product_opportunity_synthesis(
        marketplace_report,
        supplier_report,
        consumer_report,
        product_validation_report=product_validation_report,
    ).to_dict()
    alias_collapse_notes = tuple(synthesis.get("alias_notes", ()))

    missing_fields: list[str] = []
    unknown_freshness_fields: list[str] = []
    field_observations: list[FieldObservation] = []

    reports = {
        "marketplace": marketplace_report,
        "supplier": supplier_report,
        "consumer_attention": consumer_report,
        "public_market_benchmark": public_market_benchmark_report,
    }
    for pillar, report in reports.items():
        if not report:
            for field_name in _EXPECTED_FIELDS.get(pillar, ()):
                missing_fields.append(f"{pillar}.{field_name}")
            continue
        candidate = _matched_candidate(report, _PILLAR_CANDIDATE_KEYS[pillar], candidate_id)
        if candidate is None:
            missing_fields.append(f"{pillar}.candidate_not_matched")
            continue
        if pillar in _SCORE_FIELDS:
            field_observations.extend(_score_field_observations(pillar, report, candidate, candidate_id=candidate_id, workspace_id=workspace_id, as_of=as_of, missing_fields=missing_fields))
        if pillar == "supplier":
            field_observations.extend(_supplier_shipping_observations(report, candidate, candidate_id=candidate_id, workspace_id=workspace_id, as_of=as_of, missing_fields=missing_fields))
        if pillar == "public_market_benchmark":
            field_observations.extend(_public_market_observations(report, candidate, candidate_id=candidate_id, workspace_id=workspace_id, as_of=as_of, missing_fields=missing_fields))

    for item in field_observations:
        if item.provenance.freshness_status == "unknown":
            unknown_freshness_fields.append(item.field)

    deterministic_conflicts = detect_field_conflicts(candidate_id, tuple(field_observations))

    provenance_records = tuple(item.provenance for item in field_observations)

    negative_controls = NegativeControls()
    limitations = (
        "market_research_evidence_is_not_supplier_proof",
        "market_research_evidence_is_not_legal_clearance",
        "market_research_evidence_is_not_promotion_approval",
        "market_research_evidence_is_not_a_launch_approval",
        "deterministic_conflicts_are_reported_not_resolved_or_averaged",
        "alias_collapse_notes_are_opportunity_synthesis_existing_output_not_recomputed_here",
    )

    draft = EvidenceIntegrityResult(
        report_version=REPORT_VERSION,
        candidate_id=candidate_id,
        workspace_id=workspace_id,
        as_of=as_of or MISSING,
        provenance_records=provenance_records,
        field_observations=tuple(field_observations),
        missing_fields=tuple(dict.fromkeys(missing_fields)),
        unknown_freshness_fields=tuple(dict.fromkeys(unknown_freshness_fields)),
        deterministic_conflicts=deterministic_conflicts,
        alias_collapse_notes=alias_collapse_notes,
        deterministic_conflict_detected=bool(deterministic_conflicts),
        leakage_findings=(),
        client_export_safe=True,
        negative_controls=negative_controls,
        limitations=limitations,
        fingerprint="",
    )

    payload = json_safe(draft.to_dict())
    payload.pop("generated_at", None)
    leakage = check_workspace_leakage(payload, client_safe=True)
    leakage_findings = tuple(item.to_dict() for item in leakage)

    fingerprint_payload = dict(payload)
    fingerprint_payload.pop("fingerprint", None)
    fingerprint_payload.pop("leakage_findings", None)
    fingerprint_payload.pop("client_export_safe", None)
    fingerprint = hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    draft.leakage_findings = leakage_findings
    draft.client_export_safe = not leakage_findings
    draft.fingerprint = fingerprint
    return draft


def render_evidence_integrity_markdown(result: EvidenceIntegrityResult) -> str:
    data = result.to_dict()
    sections = [
        {"heading": "Candidate & Workspace Binding", "body": {"candidate_id": data["candidate_id"], "workspace_id": data["workspace_id"], "as_of": data["as_of"]}},
        {"heading": "Evidence Provenance", "body": data["provenance_records"] or ["none recorded"]},
        {"heading": "Field Observations", "body": data["field_observations"] or ["none recorded"]},
        {"heading": "Missing Fields (never coerced to zero)", "body": data["missing_fields"] or ["none recorded"]},
        {"heading": "Unknown-Freshness Fields", "body": data["unknown_freshness_fields"] or ["none recorded"]},
        {"heading": "Deterministic Conflicts (field-level, cross-source)", "body": data["deterministic_conflicts"] or ["none detected"]},
        {"heading": "Existing Alias-Collapse Notes (opportunity_synthesis, pass-through)", "body": list(data["alias_collapse_notes"]) or ["none detected"]},
        {"heading": "TrustOS Client-Safety Boundary", "body": {"client_export_safe": data["client_export_safe"], "leakage_findings": data["leakage_findings"] or ["none"]}},
        {"heading": "Negative Controls", "body": data["negative_controls"]},
        {"heading": "Limitations", "body": list(data["limitations"])},
        {"heading": "Report Fingerprint", "body": data["fingerprint"]},
        {"heading": "Disclaimer", "body": data["disclaimer"]},
    ]
    return render_markdown_report(TITLE, sections, dry_run=data["dry_run"], generated_at=data["generated_at"])


__all__ = ["REPORT_VERSION", "TITLE", "build_evidence_integrity_report", "render_evidence_integrity_markdown"]

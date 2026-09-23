"""services.geographic_opportunity.export -- client-safe projection of a
``GeographicOpportunityReport``.

This service has no TrustOS/workspace dependency of its own (unlike
``services.supplier_logistics_research``'s later consulting-integration
layer); "client-safe" here means: no raw free-text note is included
unless it has first passed ``controls.reject_unsafe_input``, and no
regulatory status is exported unless it is one of
``schemas.REGULATORY_STATUSES`` (never an affirmative clearance this
service has no authority to grant).
"""
from __future__ import annotations

from typing import Any

from . import controls
from .schemas import GeographicOpportunityReport


def collect_evidence_notes(report: GeographicOpportunityReport) -> tuple[str, ...]:
    """Every ``FieldEvidence.note`` reachable from the report's offer.

    These are reporter- or supplier-authored free text.
    ``schemas.FieldEvidence.__post_init__`` only validates that a note
    contains no control characters -- it does not screen for secrets or
    HTML. A caller that wants these in a client-safe export must run them
    through ``controls.reject_unsafe_input`` first, exactly as
    ``build_client_safe_export``'s ``include_notes`` path does below.
    """
    offer = report.offer
    candidates = [offer.origin_supplier_cost_evidence, offer.marketplace_fee_evidence]
    for optional in (offer.destination_price, offer.source_price, offer.trade_flow, offer.freight_duty, offer.returns_lead_time, offer.service_capacity, offer.regulatory):
        if optional is not None:
            candidates.append(optional.evidence)
    return tuple(dict.fromkeys(item.note for item in candidates if item.note))


def build_client_safe_export(report: GeographicOpportunityReport, *, include_notes: bool = False) -> dict[str, Any]:
    """A client-safe projection: structured, already-curated content
    (categories, severities, our own generated descriptions, and
    landed-cost scenario totals) plus, only when explicitly requested,
    evidence notes that have passed ``controls.reject_unsafe_input``.

    Every regulatory status included is re-verified against
    ``controls.reject_unsupported_regulatory_claim`` before export --
    defense in depth alongside the dataclass's own structural guarantee.
    """
    payload: dict[str, Any] = {
        "schema": report.schema,
        "candidate_id": report.candidate_id,
        "offering_kind": report.offer.offering_kind,
        "geography_kind": report.offer.geography_kind,
        "status": report.status,
        "blockers": list(report.blockers),
        "evidence_gaps": list(report.evidence_gaps),
        "risk_matrix": [
            {"category": entry.category, "severity": entry.severity, "description": entry.description} for entry in report.risk_matrix
        ],
        "next_actions": [{"description": action.description, "blocking": action.blocking} for action in report.next_actions],
        "landed_cost_scenarios": [
            {"scenario_id": scenario.scenario_id, "assumptions_note": scenario.assumptions_note} for scenario in report.landed_cost_scenarios
        ],
        "comparison": (
            {
                "price_gap": report.comparison.price_gap.to_dict() if report.comparison.price_gap is not None else None,
                "unit_value_conflicts_with_supplier_cost": report.comparison.unit_value_conflicts_with_supplier_cost,
                "notes": list(report.comparison.notes),
            }
            if report.comparison is not None
            else None
        ),
        "evidence_quality_summary": dict(report.evidence_quality_summary),
        "fingerprint": report.fingerprint,
        "read_only": report.read_only,
        "network_calls": report.network_calls,
        "mutated": report.mutated,
    }
    if report.offer.regulatory is not None:
        controls.reject_unsupported_regulatory_claim(report.offer.regulatory.status, field_name="offer.regulatory.status")
        payload["regulatory_status"] = report.offer.regulatory.status
    if include_notes:
        notes = collect_evidence_notes(report)
        for note in notes:
            controls.reject_unsafe_input(note, field_name="evidence_note")
        payload["evidence_notes"] = list(notes)
    return payload

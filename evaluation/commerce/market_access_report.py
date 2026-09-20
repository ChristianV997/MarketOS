"""Market Access & Import Requirements projection for ProductValidationReport.

Thin, additive consumer of the canonical Mexico compliance evaluator
(``evaluation.trustos.mexico_product_compliance.evaluate_mexico_product_compliance``)
and the canonical ``evaluation.commerce.promotion.GATE_IDS`` ``"compliance"``
gate. This module never re-derives law, never classifies radio bands or
tariff codes on its own, and never treats a packet label (or a product
already being sold in a market) as proof of compliance -- every status
shown here is read straight out of that evaluator's own decision.

Mexico is the only market the evaluator assesses today. United States and
Canada are always reported ``not_assessed`` -- this module does not build a
second evaluator for them; it calls the same canonical evaluator with the
market set to each, which already fails closed to ``not_assessed`` for any
non-Mexico market regardless of what evidence is supplied.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Mapping

from evaluation.commerce.promotion import GATE_IDS
from evaluation.trustos.mexico_product_compliance import (
    MexicoProductCompliancePacket,
    PROMOTION_COMPLIANCE_GATE_ID,
    build_mexico_trust_controls,
    citation_is_stale,
    evaluate_mexico_product_compliance,
)

if PROMOTION_COMPLIANCE_GATE_ID not in GATE_IDS:
    raise ValueError("evaluation.commerce.promotion no longer defines the canonical compliance gate")

VERSION = "market-access-report-v1"

ASSESSED_MARKET = "mexico"
FUTURE_MARKETS: tuple[str, ...] = ("united_states", "canada")
REPORTED_MARKETS: tuple[str, ...] = (ASSESSED_MARKET,) + FUTURE_MARKETS

_MARKET_LABELS: dict[str, str] = {
    "mexico": "Mexico",
    "united_states": "United States",
    "canada": "Canada",
}
_JURISDICTION_NOTE: dict[str, str] = {
    "mexico": "Assessed against the canonical Mexico compliance evaluator (evaluation.trustos.mexico_product_compliance).",
    "united_states": "No United States market-access evaluator exists in this system yet. Not assessed; do not treat as cleared.",
    "canada": "No Canada market-access evaluator exists in this system yet. Not assessed; do not treat as cleared.",
}

# Only these packet fields are ever read from caller-supplied evidence --
# nothing is inferred from candidate title/category/marketing copy.
_PACKET_FIELD_NAMES = frozenset(f.name for f in dataclasses.fields(MexicoProductCompliancePacket)) - {"market"}

NOT_LEGAL_ADVICE = (
    "This section records requirement applicability and evidence gaps only. "
    "It is not legal advice and does not certify a SKU or category as lawful to import or sell."
)


def _control_index() -> dict[str, Any]:
    return {control.control_id: control for control in build_mexico_trust_controls()}


def _packet_kwargs(evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in dict(evidence).items() if k in _PACKET_FIELD_NAMES}


def _requirement_projection(result: Any, controls: Mapping[str, Any], packet: MexicoProductCompliancePacket) -> dict[str, Any]:
    control = controls.get(result.control_id)
    stale = None
    if result.status != "not_assessed":
        stale = citation_is_stale(packet.sources_accessed_at, packet.as_of, packet.citation_freshness_days)
    return {
        "requirement_id": result.requirement_id,
        "family": result.family,
        "status": result.status,
        "blocker": result.blocker,
        "note": result.note,
        "source_citations": list(control.source_refs) if control is not None else [],
        "citation_accessed_at": packet.sources_accessed_at or None,
        "citation_as_of": packet.as_of,
        "citation_stale": stale,
    }


def _market_projection(market: str, evidence: Mapping[str, Any], controls: Mapping[str, Any]) -> dict[str, Any]:
    kwargs = _packet_kwargs(evidence)
    kwargs["market"] = market
    kwargs.setdefault("product_family", "unknown_family")
    try:
        packet = MexicoProductCompliancePacket(**kwargs)
        decision = evaluate_mexico_product_compliance(packet)
    except (TypeError, ValueError) as exc:
        # Fail closed on unusable caller evidence -- never guess a status.
        return {
            "market": market,
            "label": _MARKET_LABELS.get(market, market),
            "status": "needs_evidence",
            "gate": PROMOTION_COMPLIANCE_GATE_ID,
            "gate_satisfied": False,
            "requirements": [],
            "missing_or_uncertain": [f"invalid_market_access_evidence:{exc}"],
            "warnings": [],
            "note": _JURISDICTION_NOTE.get(market, "Not assessed."),
            "not_legal_advice": True,
        }

    requirements = tuple(_requirement_projection(item, controls, packet) for item in decision.results)
    needs_evidence_ids = tuple(item.requirement_id for item in decision.results if item.status == "needs_evidence")
    missing_or_uncertain = tuple(dict.fromkeys((*decision.blockers, *needs_evidence_ids)))

    if decision.compliance_satisfied:
        overall_status = "satisfied"
    elif market != ASSESSED_MARKET:
        overall_status = "not_assessed"
    else:
        overall_status = "needs_evidence"

    return {
        "market": market,
        "label": _MARKET_LABELS.get(market, market),
        "status": overall_status,
        "gate": decision.promotion_gate_id,
        "gate_satisfied": decision.compliance_satisfied,
        "requirements": list(requirements),
        "missing_or_uncertain": list(missing_or_uncertain),
        "warnings": list(decision.warnings),
        "note": _JURISDICTION_NOTE.get(market, ""),
        "not_legal_advice": decision.not_legal_advice,
    }


def build_market_access_projection(
    candidate_id: str,
    candidate_title: str,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the per-candidate Market Access & Import Requirements section.

    ``evidence`` is a caller-supplied mapping of
    ``MexicoProductCompliancePacket`` field names (a supplier claim, an
    ``official_db`` citation, an exact model, observed radio bands, etc.).
    Any key that is not a recognized packet field is ignored rather than
    guessed at. Absent evidence fails closed to ``needs_evidence`` /
    ``not_assessed`` through the canonical evaluator, exactly as it would
    for any other caller of that evaluator.
    """
    controls = _control_index()
    evidence = dict(evidence or {})
    markets = {market: _market_projection(market, evidence, controls) for market in REPORTED_MARKETS}
    return {
        "report_version": VERSION,
        "candidate_id": candidate_id,
        "candidate_title": candidate_title,
        "assessed_markets": list((ASSESSED_MARKET,)),
        "future_markets": list(FUTURE_MARKETS),
        "markets": markets,
        "already_sold_elsewhere_is_not_proof": True,
        "human_verification_required": True,
        "not_legal_advice": NOT_LEGAL_ADVICE,
    }


__all__ = [
    "VERSION",
    "ASSESSED_MARKET",
    "FUTURE_MARKETS",
    "REPORTED_MARKETS",
    "NOT_LEGAL_ADVICE",
    "build_market_access_projection",
]

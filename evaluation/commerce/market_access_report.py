"""Shared market-access / import-compliance report projection.

Every MarketOS surface that can recommend, rank, or advance a product
(ProductValidationReport, opportunity synthesis, launch/site draft packs)
shows the same jurisdiction-by-jurisdiction market-access section built by
this module. It consumes -- and never recomputes -- the canonical Mexico
product-compliance evaluator:

    evaluation.trustos.mexico_product_compliance.evaluate_mexico_product_compliance

which is itself metadata-only and maps onto the single canonical
``evaluation.commerce.promotion.GATE_IDS`` -> ``"compliance"`` gate. This
module adds no GATE_ID, registry, scorer, or legal/tax conclusion of its
own: it only relabels the canonical ``MexicoComplianceDecision`` into the
stable per-jurisdiction shape every consumer needs (jurisdiction,
assessment state, requirement domains, evidence present/missing/stale,
source reference/access date, customs/import considerations,
promotion-gate state, and next human action), and adds the United States
and Canada jurisdictions -- which the canonical evaluator already treats
as ``not_assessed`` for any non-Mexico ``market`` value.

Not legal advice. Missing evidence is reported as a gap to close, never as
a claim that a product is unlawful to import or sell.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from evaluation.trustos.mexico_product_compliance import (
    MexicoComplianceDecision,
    MexicoProductCompliancePacket,
    MexicoRequirementResult,
    build_mexico_trust_controls,
    citation_is_stale,
    evaluate_mexico_product_compliance,
)

JURISDICTIONS: tuple[str, ...] = ("mexico", "united_states", "canada")
JURISDICTION_CODES: dict[str, str] = {"mexico": "MX", "united_states": "US", "canada": "CA"}
ASSESSED_JURISDICTION = "mexico"

# The canonical evaluator keys each requirement's evidence off a specific
# packet field. This mirrors evaluate_mexico_product_compliance()'s own
# call sites exactly (see evaluation/trustos/mexico_product_compliance.py)
# so this projection never guesses which evidence backs which requirement.
# A contract test (tests/test_market_access_report.py) asserts every
# requirement_id the canonical evaluator actually emits has an entry here.
_EVIDENCE_CLASS_FIELD_BY_REQUIREMENT: dict[str, str | None] = {
    "mx_hs_classification": "hs_evidence_class",
    "mx_pedimento": "pedimento_evidence_class",
    "mx_immex": None,
    "mx_importer_rfc": "rfc_evidence_class",
    "mx_cfdi": "cfdi_evidence_class",
    "mx_iva": "iva_evidence_class",
    "mx_nom_electrical_safety": "nom_003_evidence_class",
    "mx_nom_labeling": "nom_024_evidence_class",
    "mx_nom_electrical_installations": None,
    "mx_lfpc_profeco": "lfpc_labeling_evidence_class",
    "mx_infraestructura_calidad": "lfpc_labeling_evidence_class",
    "mx_telecom_homologation": "coh_evidence_class",
    "mx_nom_208_radio": "coh_evidence_class",
    "mx_ley_general_salud": "cofepris_evidence_class",
    "mx_cofepris_sector": "cofepris_evidence_class",
    "mx_semarnat_sector": "semarnat_evidence_class",
}
CUSTOMS_IMPORT_FAMILIES = frozenset({"import_customs", "tax_invoicing"})
_TUPLE_FIELDS = ("radio_bands_observed",)

# MarketOS recommends goods, services, and hybrids. The canonical evaluator
# above only ever modeled goods (import/customs/telecom/NOM requirements);
# no canonical evaluator for Mexican service-sector licensing exists yet.
# ``offering_kind`` is read from the candidate dict and defaults to
# "goods" when absent -- this keeps every existing goods-only caller of
# this module byte-for-byte unchanged. It is never inferred from a title,
# category label, or any other free-text field.
OFFERING_KINDS: tuple[str, ...] = ("goods", "service", "hybrid", "unknown")
DEFAULT_OFFERING_KIND = "goods"

# Requirements that only exist because a physical good is being imported,
# labeled, or radio-homologated. A service-only offering has no such good,
# so these are definitively not_applicable -- not a guess, a direct
# consequence of there being nothing to classify/label/homologate.
_GOODS_PHYSICAL_REQUIREMENTS = frozenset({
    "mx_hs_classification", "mx_pedimento", "mx_immex",
    "mx_nom_electrical_safety", "mx_nom_labeling", "mx_nom_electrical_installations",
    "mx_telecom_homologation", "mx_nom_208_radio",
})
# Requirements whose *current* modeling in the canonical evaluator is
# goods-shaped (consumer packaging/instructivo, sector permits for
# nutrients/hazardous inputs) and for which no service-sector evaluator
# exists. These must stay not_assessed for a service -- never
# not_applicable (we cannot prove they don't apply) and never satisfied.
_SERVICE_UNSUPPORTED_REQUIREMENTS = frozenset({
    "mx_lfpc_profeco", "mx_infraestructura_calidad",
    "mx_ley_general_salud", "mx_cofepris_sector", "mx_semarnat_sector",
})

_source_refs_cache: dict[str, tuple[str, ...]] | None = None


def _source_refs_by_control() -> dict[str, tuple[str, ...]]:
    global _source_refs_cache
    if _source_refs_cache is None:
        _source_refs_cache = {control.control_id: control.source_refs for control in build_mexico_trust_controls()}
    return _source_refs_cache


def _normalize_packet_fields(jurisdiction: str, evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    fields = dict(evidence or {})
    for key in _TUPLE_FIELDS:
        if key in fields and isinstance(fields[key], list):
            fields[key] = tuple(fields[key])
    fields["market"] = jurisdiction
    fields.setdefault("product_family", "unknown_family")
    return fields


def _build_packet(jurisdiction: str, evidence: Mapping[str, Any] | None) -> MexicoProductCompliancePacket | None:
    try:
        return MexicoProductCompliancePacket(**_normalize_packet_fields(jurisdiction, evidence))
    except (TypeError, ValueError):
        return None


def _evidence_state(status: str, evidence_class: str | None, stale: bool) -> str:
    """Derived from ``status`` first, never independently of it: the
    canonical evaluator's own extra_ok checks (non-empty HS/pedimento,
    exact CoH model match, active CoH/permit status, etc.) are the only
    authority for whether supplied evidence was actually adequate, so this
    must never call something "present" that the canonical decision did
    not treat as satisfied -- that would contradict the status shown right
    next to it in every report.
    """
    if status == "satisfied":
        return "present"
    if not evidence_class or evidence_class == "unknown":
        return "missing"
    if stale:
        return "stale"
    return "missing"


def _requirement_projection(result: MexicoRequirementResult, packet: MexicoProductCompliancePacket) -> dict[str, Any]:
    field_name = _EVIDENCE_CLASS_FIELD_BY_REQUIREMENT.get(result.requirement_id)
    evidence_class = getattr(packet, field_name, "unknown") if field_name else "unknown"
    stale = evidence_class == "official_db" and citation_is_stale(packet.sources_accessed_at, packet.as_of, packet.citation_freshness_days)
    return {
        "requirement_id": result.requirement_id,
        "family": result.family,
        "status": result.status,
        "evidence_class": evidence_class,
        "evidence_state": _evidence_state(result.status, evidence_class, stale),
        "source_refs": _source_refs_by_control().get(result.control_id, ()),
        "access_date": packet.sources_accessed_at or "",
        "blocker": result.blocker,
        "note": result.note,
    }


def _next_human_action(jurisdiction: str, decision: MexicoComplianceDecision | None) -> str:
    if decision is None:
        return f"{JURISDICTION_CODES.get(jurisdiction, jurisdiction)} is not assessed by this system; no action recorded here."
    if decision.compliance_satisfied:
        return "All assessed requirements show satisfied or not-applicable evidence; a lawyer/customs-broker/accountant review is still recommended before launch (not legal advice)."
    blockers = decision.blockers
    if blockers:
        return "Resolve before this jurisdiction can clear: " + "; ".join(blockers) + "."
    return "Provide official, fresh, exact-model evidence for the requirements marked needs_evidence."


def _jurisdiction_section(jurisdiction: str, evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    if jurisdiction != ASSESSED_JURISDICTION:
        del evidence  # non-Mexico evidence is never evaluated: always not_assessed regardless of input.
        return {
            "jurisdiction": jurisdiction,
            "jurisdiction_code": JURISDICTION_CODES.get(jurisdiction, jurisdiction),
            "assessment_state": "not_assessed",
            "requirements": (),
            "requirement_domains": (),
            "customs_import_considerations": (),
            "promotion_gate": {"gate_id": "compliance", "satisfied": False},
            "warnings": ("non_mexico_market_not_assessed",),
            "blockers": (),
            "next_human_action": _next_human_action(jurisdiction, None),
            "not_legal_advice": True,
        }

    packet = _build_packet(jurisdiction, evidence)
    if packet is None:
        return {
            "jurisdiction": jurisdiction,
            "jurisdiction_code": JURISDICTION_CODES.get(jurisdiction, jurisdiction),
            "assessment_state": "needs_evidence",
            "requirements": (),
            "requirement_domains": (),
            "customs_import_considerations": (),
            "promotion_gate": {"gate_id": "compliance", "satisfied": False},
            "warnings": ("invalid_market_access_evidence_supplied",),
            "blockers": ("invalid_market_access_evidence_supplied",),
            "next_human_action": "Correct the supplied market_family/evidence_class values; see evaluation.trustos.mexico_product_compliance for allowed values.",
            "not_legal_advice": True,
        }

    decision = evaluate_mexico_product_compliance(packet)
    requirements = tuple(_requirement_projection(result, packet) for result in decision.results)
    assessment_state = "compliant" if decision.compliance_satisfied else "needs_evidence"
    return {
        "jurisdiction": jurisdiction,
        "jurisdiction_code": JURISDICTION_CODES.get(jurisdiction, jurisdiction),
        "assessment_state": assessment_state,
        "requirements": requirements,
        "requirement_domains": tuple(sorted({item["family"] for item in requirements if item["status"] != "not_assessed"})),
        "customs_import_considerations": tuple(item for item in requirements if item["family"] in CUSTOMS_IMPORT_FAMILIES),
        "promotion_gate": {"gate_id": decision.promotion_gate_id, "satisfied": decision.promotion_gate_satisfaction()[decision.promotion_gate_id]},
        "warnings": decision.warnings,
        "blockers": decision.blockers,
        "next_human_action": _next_human_action(jurisdiction, decision),
        "not_legal_advice": True,
    }


def _recognized_offering_kind(candidate: Mapping[str, Any] | None) -> tuple[str, bool]:
    """Return (offering_kind, was_recognized). Absent -> "goods" (the
    default every existing goods-only caller already assumes). Anything
    supplied that isn't one of OFFERING_KINDS fails closed to "unknown"
    rather than being guessed at or silently ignored."""
    raw = (candidate or {}).get("offering_kind")
    if raw in (None, ""):
        return DEFAULT_OFFERING_KIND, True
    value = str(raw).strip().lower()
    if value in OFFERING_KINDS:
        return value, True
    return "unknown", False


def _unassessed_offering_section(jurisdiction: str, reason: str, next_action: str) -> dict[str, Any]:
    return {
        "jurisdiction": jurisdiction,
        "jurisdiction_code": JURISDICTION_CODES.get(jurisdiction, jurisdiction),
        "assessment_state": "not_assessed",
        "requirements": (),
        "requirement_domains": (),
        "customs_import_considerations": (),
        "promotion_gate": {"gate_id": "compliance", "satisfied": False},
        "warnings": (reason,),
        "blockers": (),
        "next_human_action": next_action,
        "not_legal_advice": True,
    }


def _override_requirement_for_service(item: dict[str, Any]) -> dict[str, Any]:
    if item["requirement_id"] in _GOODS_PHYSICAL_REQUIREMENTS:
        return {
            **item, "status": "not_applicable", "evidence_state": "missing", "blocker": "",
            "note": "Not applicable: this offering is declared service-only, so there is no physical good to classify, label, or homologate.",
        }
    if item["requirement_id"] in _SERVICE_UNSUPPORTED_REQUIREMENTS:
        return {
            **item, "status": "not_assessed", "evidence_state": "missing", "blocker": "",
            "note": "No canonical evaluator exists yet for this Mexican service-sector requirement; treat as unassessed, never as cleared.",
        }
    return item


def _apply_service_offering(section: dict[str, Any]) -> dict[str, Any]:
    """Re-derive the Mexico section for a declared service-only offering.

    Goods-only requirements (customs classification, pedimento, IMMEX,
    electrical/labeling NOMs, telecom homologation) become not_applicable
    -- there is no physical good. Requirements this codebase only models
    for goods today (sector permits, LFPC/PROFECO consumer labeling,
    infraestructura de la calidad) become not_assessed -- unsupported, not
    cleared. Fiscal requirements (RFC/CFDI/IVA) are jurisdiction-wide sale
    duties, not goods-specific, so they are left exactly as the canonical
    evaluator computed them.
    """
    requirements = tuple(_override_requirement_for_service(item) for item in section["requirements"])
    if any(item["status"] == "needs_evidence" for item in requirements):
        assessment_state = "needs_evidence"
    elif any(item["status"] == "not_assessed" for item in requirements):
        assessment_state = "not_assessed"
    else:
        assessment_state = "compliant"
    gate_satisfied = all(item["status"] in {"satisfied", "not_applicable"} for item in requirements)
    warnings = tuple(dict.fromkeys((
        *section["warnings"],
        "service_offering_customs_and_physical_requirements_not_applicable",
        "service_offering_sector_requirements_not_assessed_no_evaluator_exists",
    )))
    return {
        **section,
        "assessment_state": assessment_state,
        "requirements": requirements,
        "requirement_domains": tuple(sorted({item["family"] for item in requirements if item["status"] not in {"not_assessed", "not_applicable"}})),
        "customs_import_considerations": (),
        "promotion_gate": {"gate_id": section["promotion_gate"]["gate_id"], "satisfied": gate_satisfied},
        "warnings": warnings,
        "next_human_action": "This offering is declared service-only: customs/telecom/physical-labeling requirements do not apply, but Mexican service-sector licensing/health/environmental rules are not yet covered by any evaluator here and must be reviewed by a lawyer before launch. Fiscal (RFC/CFDI/IVA) requirements still apply and are shown above.",
    }


def _apply_hybrid_offering(section: dict[str, Any]) -> dict[str, Any]:
    """A hybrid offering's goods component is assessed exactly as for a
    pure good (unchanged) -- there is nothing else to base that on -- but
    the section must never imply the service component was also covered,
    since no service evaluator exists."""
    warnings = tuple(dict.fromkeys((*section["warnings"], "hybrid_offering_service_component_not_assessed_no_evaluator_exists")))
    return {**section, "warnings": warnings}


def build_market_access_section(candidate: Mapping[str, Any], evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build the full multi-jurisdiction market-access section for one candidate.

    ``evidence`` maps a jurisdiction name (``"mexico"``/``"united_states"``/
    ``"canada"``) to the caller-supplied evidence fields for
    ``MexicoProductCompliancePacket`` (minus ``market``, which is set here).
    Nothing is fetched, inferred, or guessed beyond what the canonical
    evaluator already does with that evidence.

    ``candidate.get("offering_kind")`` (goods/service/hybrid/unknown,
    defaulting to "goods" when absent) gates which Mexico requirements are
    even applicable -- goods rules are never run against a declared
    service, and a declared/unrecognized "unknown" offering is reported
    not_assessed rather than defaulting to goods.
    """
    offering_kind, recognized = _recognized_offering_kind(candidate)
    evidence = dict(evidence or {})
    jurisdictions = tuple(_jurisdiction_section(jurisdiction, evidence.get(jurisdiction)) for jurisdiction in JURISDICTIONS)

    if offering_kind == "unknown":
        reason = "unrecognized_offering_kind_treated_as_unknown" if not recognized else "offering_kind_unknown"
        next_action = "Declare offering_kind (goods/service/hybrid) so the applicable Mexico requirements can be determined; an unknown offering type is never assessed."
        jurisdictions = tuple(
            _unassessed_offering_section(item["jurisdiction"], reason, next_action) if item["jurisdiction"] == ASSESSED_JURISDICTION else item
            for item in jurisdictions
        )
    elif offering_kind == "service":
        jurisdictions = tuple(
            _apply_service_offering(item) if item["jurisdiction"] == ASSESSED_JURISDICTION else item
            for item in jurisdictions
        )
    elif offering_kind == "hybrid":
        jurisdictions = tuple(
            _apply_hybrid_offering(item) if item["jurisdiction"] == ASSESSED_JURISDICTION else item
            for item in jurisdictions
        )
    # offering_kind == "goods" (the default): jurisdictions are left exactly
    # as the canonical evaluator produced them -- zero behavior change.

    mexico_section = next(item for item in jurisdictions if item["jurisdiction"] == ASSESSED_JURISDICTION)
    return {
        "jurisdictions": jurisdictions,
        "overall_status": mexico_section["assessment_state"],
        "offering_kind": offering_kind,
    }


def build_candidate_market_access(
    candidates: Sequence[Mapping[str, Any]], evidence_by_candidate: Mapping[str, Any] | None = None
) -> tuple[dict[str, Any], ...]:
    """Build the market-access section for every candidate in a report.

    Every candidate gets a full section, even with no supplied evidence --
    Mexico simply resolves to ``needs_evidence`` and US/Canada to
    ``not_assessed`` rather than the section being omitted.
    """
    evidence_by_candidate = dict(evidence_by_candidate or {})
    sections: list[dict[str, Any]] = []
    for candidate in candidates:
        inner = candidate.get("candidate") if isinstance(candidate.get("candidate"), Mapping) else candidate
        candidate_id = str(inner.get("id") or inner.get("candidate_id") or inner.get("title") or "")
        section = build_market_access_section(inner, evidence_by_candidate.get(candidate_id))
        sections.append({"candidate_id": candidate_id, **section})
    return tuple(sections)


__all__ = [
    "JURISDICTIONS",
    "JURISDICTION_CODES",
    "ASSESSED_JURISDICTION",
    "CUSTOMS_IMPORT_FAMILIES",
    "build_market_access_section",
    "build_candidate_market_access",
]

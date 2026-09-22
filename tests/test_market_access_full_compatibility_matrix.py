"""Full offering_kind x evidence-quality compatibility matrix, driven
through every real downstream consumer.

Prior test files each prove one axis at a time: test_market_access_report.py
proves the canonical-evaluator-backed statuses in isolation,
test_market_access_offering_kind.py proves offering_kind gating in
isolation, and test_market_access_offering_kind_cross_consumer.py proves a
handful of representative offering_kind/evidence combinations flow
identically through the four real consumer functions. None of them
enumerate the full cross product of {goods, service, hybrid, unknown} x
{complete official evidence, missing evidence, supplier_claim, fixture,
stale citation, mismatched certificate, cancelled certificate} against
every consumer in one place -- a genuine cross-consumer divergence that
only appears for one specific (offering_kind, evidence) pair could slip
past the existing, narrower spot checks. This file makes that full matrix
explicit and parametrized so every cell is proven, not just the ones a
human happened to pick.

No mocks: every row drives the real
evaluation.commerce.market_access_report.build_market_access_section,
evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis,
evaluation.commerce.launch_draft_pack.build_launch_draft_pack,
evaluation.commerce.site_draft_builder.build_site_draft_pack, and
evaluation.commerce.product_validation_report.generate.

Not legal advice. This file asserts internal consistency and the documented
fail-closed contract; it does not assert that any status is legally correct
for a real product or service.
"""
from __future__ import annotations

import json

import pytest

from evaluation.commerce.launch_draft_pack import build_launch_draft_pack
from evaluation.commerce.market_access_report import build_market_access_section
from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis
from evaluation.commerce.product_validation_report import generate as generate_product_validation_report
from evaluation.commerce.site_draft_builder import build_site_draft_pack

# ---------------------------------------------------------------------------
# Evidence variants -- each one exercises a distinct fail-closed guarantee
# the canonical evaluator (evaluation.trustos.mexico_product_compliance)
# already makes; this file never re-derives or second-guesses any of them.
# ---------------------------------------------------------------------------

_COMPLETE_OFFICIAL_NON_RADIO = {
    "product_family": "hydroponics_non_radio", "sku_model_exact": "MATRIX-1", "radio_present": False,
    "electrical_present": True, "contains_nutrients_or_seeds": False, "contains_hazardous_materials": False,
    "origin_imported": True, "hs_classification": "3105.90", "hs_evidence_class": "official_db",
    "pedimento_ref": "PED-MATRIX-1", "pedimento_evidence_class": "official_db", "importer_rfc": "ABC010101AAA",
    "rfc_evidence_class": "official_db", "cfdi_ready": True, "cfdi_evidence_class": "official_db",
    "iva_treatment_reviewed": True, "iva_evidence_class": "official_db", "nom_003_evidence_class": "official_db",
    "nom_024_evidence_class": "official_db", "lfpc_labeling_evidence_class": "official_db",
    "cofepris_evidence_class": "official_db", "semarnat_evidence_class": "official_db",
    "sources_accessed_at": "2026-09-19", "as_of": "2026-09-19",
}
_COMPLETE_OFFICIAL_RADIO = {
    **_COMPLETE_OFFICIAL_NON_RADIO,
    "product_family": "telecom_wifi_2_4", "radio_present": True, "radio_bands_observed": ["2.4ghz"],
    "coh_number": "COH-MATRIX-1", "coh_model": "MATRIX-1", "coh_status": "active", "coh_evidence_class": "official_db",
}

EVIDENCE_VARIANTS: dict[str, dict] = {
    "missing": {},
    "complete_official": dict(_COMPLETE_OFFICIAL_NON_RADIO),
    "supplier_claim": {**_COMPLETE_OFFICIAL_NON_RADIO, "hs_evidence_class": "supplier_claim"},
    "fixture": {**_COMPLETE_OFFICIAL_NON_RADIO, "hs_evidence_class": "fixture"},
    "stale_citation": {**_COMPLETE_OFFICIAL_NON_RADIO, "sources_accessed_at": "2020-01-01"},
    "mismatched_certificate": {**_COMPLETE_OFFICIAL_RADIO, "coh_model": "SOME-OTHER-MODEL"},
    "cancelled_certificate": {**_COMPLETE_OFFICIAL_RADIO, "coh_status": "cancelled"},
}

OFFERING_KINDS_UNDER_TEST = ("goods", "service", "hybrid", "unknown", "unrecognized_value")

# Expected overall Mexico assessment_state for each (offering_kind,
# evidence_variant) cell. "goods"/"hybrid" inherit the canonical
# evaluator's own status for the assessed requirements; "service" and
# "unknown"/unrecognized never reach "compliant" for these evidence rows
# because sector-permit/unsupported requirements (service) or every
# requirement (unknown) stay not_assessed.
EXPECTED_MEXICO_STATE: dict[tuple[str, str], str] = {
    ("goods", "missing"): "needs_evidence",
    ("goods", "complete_official"): "compliant",
    ("goods", "supplier_claim"): "needs_evidence",
    ("goods", "fixture"): "needs_evidence",
    ("goods", "stale_citation"): "needs_evidence",
    ("goods", "mismatched_certificate"): "needs_evidence",
    ("goods", "cancelled_certificate"): "needs_evidence",
    # For a service, hs_evidence_class only ever gates the goods-only
    # mx_hs_classification requirement, which is forced not_applicable
    # regardless -- so tampering supplier_claim/fixture into that one
    # field never surfaces as needs_evidence for a service (it would for
    # goods/hybrid, where that requirement is actually assessed). Fiscal
    # (RFC/CFDI/IVA) evidence is untouched by those two variants and stays
    # satisfied, so the only remaining reason the overall state isn't
    # "compliant" is the always-not_assessed sector-permit set.
    ("service", "missing"): "needs_evidence",
    ("service", "complete_official"): "not_assessed",
    ("service", "supplier_claim"): "not_assessed",
    ("service", "fixture"): "not_assessed",
    # sources_accessed_at is packet-wide, not per-requirement -- staleness
    # also makes the fiscal (RFC/CFDI/IVA) official_db evidence fail
    # freshness, so a service sees needs_evidence here even though every
    # goods-only requirement it would otherwise care about is
    # not_applicable.
    ("service", "stale_citation"): "needs_evidence",
    # coh_model/coh_status only gate the goods-only telecom requirements,
    # forced not_applicable for a service regardless of the mismatch or
    # cancellation; fiscal evidence in these two variants is fresh and
    # official, so it stays satisfied.
    ("service", "mismatched_certificate"): "not_assessed",
    ("service", "cancelled_certificate"): "not_assessed",
    ("hybrid", "missing"): "needs_evidence",
    ("hybrid", "complete_official"): "compliant",
    ("hybrid", "supplier_claim"): "needs_evidence",
    ("hybrid", "fixture"): "needs_evidence",
    ("hybrid", "stale_citation"): "needs_evidence",
    ("hybrid", "mismatched_certificate"): "needs_evidence",
    ("hybrid", "cancelled_certificate"): "needs_evidence",
}
for _evidence_name in EVIDENCE_VARIANTS:
    EXPECTED_MEXICO_STATE[("unknown", _evidence_name)] = "not_assessed"
    EXPECTED_MEXICO_STATE[("unrecognized_value", _evidence_name)] = "not_assessed"

# service/unknown/unrecognized can never gate-satisfy for these evidence
# rows (unsupported sector rules or blanket not_assessed always block it);
# goods/hybrid gate-satisfy only for the row that reaches "compliant".
EXPECTED_GATE_SATISFIED: dict[tuple[str, str], bool] = {
    key: (state == "compliant") for key, state in EXPECTED_MEXICO_STATE.items()
}


def _normalized(value):
    return json.loads(json.dumps(value))


def _pillars(candidate_id: str, offering_kind: str):
    market = {
        "evidence_mode": "sanitized_report",
        "candidates": [{"candidate_id": candidate_id, "query": "Matrix offering", "offering_kind": offering_kind, "score": {"overall_marketplace_opportunity": 0.8}}],
    }
    supplier = {"evidence_mode": "sanitized_report", "candidates": [{"candidate_id": candidate_id, "score": {"overall_supplier_feasibility": 0.8, "economics": {"gross_margin_percent": 0.3}}}]}
    consumer = {"evidence_mode": "sanitized_report", "candidates": [{"candidate_id": candidate_id, "score": {"overall_consumer_attention": 0.8}}]}
    return market, supplier, consumer


def _all_four_consumer_market_access(candidate_id: str, offering_kind: str, mexico_evidence: dict) -> dict[str, dict]:
    evidence = {"mexico": mexico_evidence} if mexico_evidence else {}
    direct = _normalized(build_market_access_section({"id": candidate_id, "offering_kind": offering_kind}, evidence))

    market, supplier, consumer = _pillars(candidate_id, offering_kind)
    synthesis = build_product_opportunity_synthesis(market, supplier, consumer, market_access_evidence={candidate_id: evidence}).to_dict()
    launch = build_launch_draft_pack(synthesis=synthesis).to_dict()
    site = build_site_draft_pack(launch_draft_pack=launch, opportunity_synthesis=synthesis).to_dict()

    candidate = {"id": candidate_id, "title": "Matrix offering", "offering_kind": offering_kind}
    benchmark = {"candidates": [{"candidate": candidate, "commercial_decision": "hold_for_more_evidence"}], "evidence_mode": "sanitized_report"}
    readiness = {"overall_status": "blocked", "supplier_readiness": {"status": "unknown"}, "blocking_gates": [], "next_best_action": "expand_supplier_research"}
    deployment = {"overall_status": "blocked"}
    report = generate_product_validation_report(
        benchmark=benchmark, readiness=readiness, deployment=deployment, market_access_evidence={candidate_id: evidence}
    ).to_dict()
    report_section = next(item for item in report["market_access"] if item["candidate_id"] == candidate_id)

    return {
        "direct": direct,
        "synthesis_candidate": _normalized(synthesis["candidates"][0]["market_access"]),
        "synthesis_top": _normalized(synthesis["market_access"]),
        "launch": _normalized(launch["market_access"]),
        "site": _normalized(site["market_access"]),
        "product_validation_report": _normalized({k: v for k, v in report_section.items() if k in ("jurisdictions", "overall_status", "offering_kind")}),
    }


def _mexico_jurisdiction(section: dict) -> dict:
    return next(j for j in section["jurisdictions"] if j["jurisdiction"] == "mexico")


@pytest.mark.parametrize("offering_kind", OFFERING_KINDS_UNDER_TEST)
@pytest.mark.parametrize("evidence_name", list(EVIDENCE_VARIANTS))
def test_full_matrix_cell_is_byte_identical_across_every_real_consumer(offering_kind: str, evidence_name: str):
    candidate_id = f"matrix-{offering_kind}-{evidence_name}"
    surfaces = _all_four_consumer_market_access(candidate_id, offering_kind, EVIDENCE_VARIANTS[evidence_name])
    direct = surfaces["direct"]
    for surface_name, section in surfaces.items():
        if surface_name == "direct":
            continue
        assert section == direct, f"{surface_name} diverged from the direct projection for ({offering_kind}, {evidence_name})"


@pytest.mark.parametrize("offering_kind", OFFERING_KINDS_UNDER_TEST)
@pytest.mark.parametrize("evidence_name", list(EVIDENCE_VARIANTS))
def test_full_matrix_cell_matches_the_documented_status_and_gate(offering_kind: str, evidence_name: str):
    candidate_id = f"matrix-status-{offering_kind}-{evidence_name}"
    surfaces = _all_four_consumer_market_access(candidate_id, offering_kind, EVIDENCE_VARIANTS[evidence_name])
    mx = _mexico_jurisdiction(surfaces["direct"])
    key = (offering_kind if offering_kind in OFFERING_KINDS_UNDER_TEST[:4] else "unrecognized_value", evidence_name)
    expected_state = EXPECTED_MEXICO_STATE[key]
    expected_gate = EXPECTED_GATE_SATISFIED[key]
    assert mx["assessment_state"] == expected_state, (offering_kind, evidence_name, mx)
    assert mx["promotion_gate"]["satisfied"] is expected_gate, (offering_kind, evidence_name, mx)
    # A "compliant" cell must never coexist with an unsupported/needs_evidence
    # requirement anywhere in the same jurisdiction -- the whole point of the
    # fail-closed contract is that a single unresolved requirement blocks the
    # overall state, never gets averaged away.
    if expected_state == "compliant":
        assert all(item["status"] in {"satisfied", "not_applicable"} for item in mx["requirements"])


@pytest.mark.parametrize("offering_kind", OFFERING_KINDS_UNDER_TEST)
@pytest.mark.parametrize("evidence_name", list(EVIDENCE_VARIANTS))
def test_full_matrix_cell_never_touches_the_united_states_or_canada(offering_kind: str, evidence_name: str):
    """Regardless of offering_kind or Mexico evidence quality, the future
    jurisdictions must always read not_assessed -- there is no combination
    in this matrix where they inherit Mexico's status."""
    candidate_id = f"matrix-future-{offering_kind}-{evidence_name}"
    surfaces = _all_four_consumer_market_access(candidate_id, offering_kind, EVIDENCE_VARIANTS[evidence_name])
    for jurisdiction_name in ("united_states", "canada"):
        jurisdiction = next(j for j in surfaces["direct"]["jurisdictions"] if j["jurisdiction"] == jurisdiction_name)
        assert jurisdiction["assessment_state"] == "not_assessed"
        assert jurisdiction["promotion_gate"]["satisfied"] is False


@pytest.mark.parametrize("offering_kind", OFFERING_KINDS_UNDER_TEST)
def test_offering_kind_is_preserved_verbatim_at_every_consumer(offering_kind: str):
    candidate_id = f"matrix-kind-{offering_kind}"
    surfaces = _all_four_consumer_market_access(candidate_id, offering_kind, EVIDENCE_VARIANTS["complete_official"])
    expected = offering_kind if offering_kind in OFFERING_KINDS_UNDER_TEST[:4] else "unknown"
    assert surfaces["direct"]["offering_kind"] == expected
    assert surfaces["synthesis_candidate"]["offering_kind"] == expected
    assert surfaces["launch"]["offering_kind"] == expected
    assert surfaces["site"]["offering_kind"] == expected
    assert surfaces["product_validation_report"]["offering_kind"] == expected


def test_service_offering_fiscal_duties_are_assessed_while_goods_customs_are_not_applicable_everywhere():
    """Direct restatement of the mission's explicit requirement: services
    receive fiscal/market-access treatment without invented goods customs
    obligations, and sector licensing stays not_assessed rather than being
    silently cleared or blocked -- checked across all four consumers at
    once, not just the direct projection."""
    surfaces = _all_four_consumer_market_access("matrix-service-fiscal-check", "service", _COMPLETE_OFFICIAL_NON_RADIO)
    for surface_name in ("direct", "synthesis_candidate", "launch", "site"):
        mx = _mexico_jurisdiction(surfaces[surface_name])
        by_id = {item["requirement_id"]: item["status"] for item in mx["requirements"]}
        for goods_only in ("mx_hs_classification", "mx_pedimento", "mx_immex", "mx_telecom_homologation", "mx_nom_208_radio", "mx_nom_electrical_safety", "mx_nom_labeling"):
            assert by_id[goods_only] == "not_applicable", (surface_name, goods_only)
        for unsupported_sector in ("mx_lfpc_profeco", "mx_infraestructura_calidad", "mx_ley_general_salud", "mx_cofepris_sector", "mx_semarnat_sector"):
            assert by_id[unsupported_sector] == "not_assessed", (surface_name, unsupported_sector)
        for fiscal in ("mx_importer_rfc", "mx_cfdi", "mx_iva"):
            assert by_id[fiscal] == "satisfied", (surface_name, fiscal)
        assert mx["assessment_state"] != "compliant"

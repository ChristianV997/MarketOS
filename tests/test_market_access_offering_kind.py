"""offering_kind (goods/service/hybrid/unknown) cross-jurisdiction matrix.

MarketOS recommends goods, services, and hybrids, but the canonical Mexico
evaluator (evaluation.trustos.mexico_product_compliance) only ever modeled
goods. These tests prove evaluation.commerce.market_access_report never
runs goods customs/telecom/NOM rules against a declared service, never
silently claims a service is "compliant" (no service evaluator exists),
keeps a hybrid's goods component assessed exactly as a pure good would be,
defaults absent offering_kind to "goods" (backward compatible with every
existing goods-only caller), and keeps US/Canada not_assessed regardless
of offering_kind.
"""
from evaluation.commerce.market_access_report import (
    JURISDICTIONS,
    OFFERING_KINDS,
    build_market_access_section,
)

_COMPLETE_GOODS_EVIDENCE = {
    "mexico": {
        "product_family": "hydroponics_non_radio", "sku_model_exact": "NUTRIENT-1", "radio_present": False,
        "electrical_present": True, "contains_nutrients_or_seeds": False, "contains_hazardous_materials": False,
        "origin_imported": True, "hs_classification": "3105.90", "hs_evidence_class": "official_db",
        "pedimento_ref": "PED-1", "pedimento_evidence_class": "official_db", "importer_rfc": "ABC010101AAA",
        "rfc_evidence_class": "official_db", "cfdi_ready": True, "cfdi_evidence_class": "official_db",
        "iva_treatment_reviewed": True, "iva_evidence_class": "official_db", "nom_003_evidence_class": "official_db",
        "nom_024_evidence_class": "official_db", "lfpc_labeling_evidence_class": "official_db",
        "cofepris_evidence_class": "official_db", "semarnat_evidence_class": "official_db",
        "sources_accessed_at": "2026-09-19", "as_of": "2026-09-19",
    }
}


def _mx(section):
    return next(j for j in section["jurisdictions"] if j["jurisdiction"] == "mexico")


def test_offering_kind_defaults_to_goods_when_absent():
    section = build_market_access_section({"id": "cand-a"}, _COMPLETE_GOODS_EVIDENCE)
    assert section["offering_kind"] == "goods"
    assert section["overall_status"] == "compliant"


def test_goods_offering_is_byte_identical_to_pre_offering_kind_behavior():
    with_kind = build_market_access_section({"id": "cand-a", "offering_kind": "goods"}, _COMPLETE_GOODS_EVIDENCE)
    without_kind = build_market_access_section({"id": "cand-a"}, _COMPLETE_GOODS_EVIDENCE)
    assert _mx(with_kind)["requirements"] == _mx(without_kind)["requirements"]
    assert _mx(with_kind)["assessment_state"] == _mx(without_kind)["assessment_state"] == "compliant"


def test_service_offering_never_runs_goods_customs_or_telecom_rules():
    # Same evidence that makes a goods offering "compliant" -- for a
    # service, customs/telecom/physical-NOM requirements must never be
    # evaluated against it; they become not_applicable, not satisfied.
    section = build_market_access_section({"id": "cand-b", "offering_kind": "service"}, _COMPLETE_GOODS_EVIDENCE)
    mx = _mx(section)
    reqs = {r["requirement_id"]: r for r in mx["requirements"]}
    for goods_only in ("mx_hs_classification", "mx_pedimento", "mx_immex", "mx_telecom_homologation", "mx_nom_208_radio", "mx_nom_electrical_safety", "mx_nom_labeling"):
        assert reqs[goods_only]["status"] == "not_applicable", goods_only


def test_service_offering_never_falsely_clears_unsupported_sector_rules():
    section = build_market_access_section({"id": "cand-c", "offering_kind": "service"}, _COMPLETE_GOODS_EVIDENCE)
    mx = _mx(section)
    reqs = {r["requirement_id"]: r for r in mx["requirements"]}
    for unsupported in ("mx_lfpc_profeco", "mx_infraestructura_calidad", "mx_ley_general_salud", "mx_cofepris_sector", "mx_semarnat_sector"):
        assert reqs[unsupported]["status"] == "not_assessed", unsupported
    # A pure service can never show "compliant" -- there's no evaluator
    # for the unsupported sector rules, so at best it is not_assessed.
    assert mx["assessment_state"] != "compliant"
    assert mx["promotion_gate"]["satisfied"] is False


def test_service_offering_still_assesses_jurisdiction_wide_fiscal_duties():
    # RFC/CFDI/IVA are Mexico-wide sale duties, not goods-specific -- a
    # service offering still gets them assessed (and they are satisfied
    # here since the fixture supplies complete official evidence).
    section = build_market_access_section({"id": "cand-d", "offering_kind": "service"}, _COMPLETE_GOODS_EVIDENCE)
    reqs = {r["requirement_id"]: r for r in _mx(section)["requirements"]}
    for fiscal in ("mx_importer_rfc", "mx_cfdi", "mx_iva"):
        assert reqs[fiscal]["status"] == "satisfied", fiscal


def test_service_offering_with_no_evidence_is_needs_evidence_not_compliant():
    section = build_market_access_section({"id": "cand-e", "offering_kind": "service"}, {})
    mx = _mx(section)
    assert mx["assessment_state"] in {"needs_evidence", "not_assessed"}
    assert mx["assessment_state"] != "compliant"


def test_hybrid_offering_assesses_goods_component_exactly_like_a_pure_good():
    hybrid = build_market_access_section({"id": "cand-f", "offering_kind": "hybrid"}, _COMPLETE_GOODS_EVIDENCE)
    goods = build_market_access_section({"id": "cand-f", "offering_kind": "goods"}, _COMPLETE_GOODS_EVIDENCE)
    assert _mx(hybrid)["requirements"] == _mx(goods)["requirements"]
    assert _mx(hybrid)["assessment_state"] == _mx(goods)["assessment_state"] == "compliant"
    assert "hybrid_offering_service_component_not_assessed_no_evaluator_exists" in _mx(hybrid)["warnings"]


def test_unknown_offering_kind_is_never_assessed_even_with_complete_evidence():
    section = build_market_access_section({"id": "cand-g", "offering_kind": "unknown"}, _COMPLETE_GOODS_EVIDENCE)
    mx = _mx(section)
    assert mx["assessment_state"] == "not_assessed"
    assert mx["requirements"] == ()
    assert mx["promotion_gate"]["satisfied"] is False
    assert section["overall_status"] == "not_assessed"


def test_unrecognized_offering_kind_fails_closed_to_unknown():
    section = build_market_access_section({"id": "cand-h", "offering_kind": "spaceship"}, _COMPLETE_GOODS_EVIDENCE)
    assert section["offering_kind"] == "unknown"
    assert _mx(section)["assessment_state"] == "not_assessed"
    assert "unrecognized_offering_kind_treated_as_unknown" in _mx(section)["warnings"]


def test_offering_kind_never_affects_future_jurisdictions():
    for kind in OFFERING_KINDS:
        section = build_market_access_section({"id": "cand-i", "offering_kind": kind}, _COMPLETE_GOODS_EVIDENCE)
        for jurisdiction in JURISDICTIONS:
            if jurisdiction == "mexico":
                continue
            entry = next(j for j in section["jurisdictions"] if j["jurisdiction"] == jurisdiction)
            assert entry["assessment_state"] == "not_assessed"
            assert entry["promotion_gate"]["satisfied"] is False

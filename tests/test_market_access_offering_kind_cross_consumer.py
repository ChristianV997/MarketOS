"""Cross-consumer integration coverage for offering_kind gating and the
adversarial evidence scenarios market_access_report.py already proves in
isolation. This file re-proves the same guarantees through the actual
downstream consumer functions (opportunity synthesis -> launch draft ->
site draft, and the standalone ProductValidationReport) -- never mocks --
so a regression that only shows up in the wiring (not the projection
itself) cannot slip through.
"""
import json

from evaluation.commerce.launch_draft_pack import build_launch_draft_pack
from evaluation.commerce.market_access_report import build_market_access_section
from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis
from evaluation.commerce.product_validation_report import generate as generate_product_validation_report
from evaluation.commerce.site_draft_builder import build_site_draft_pack


def _normalized(value):
    return json.loads(json.dumps(value))


def _pillars(candidate_id: str):
    market = {"evidence_mode": "sanitized_report", "candidates": [{"candidate_id": candidate_id, "query": "Offering", "score": {"overall_marketplace_opportunity": 0.8}}]}
    supplier = {"evidence_mode": "sanitized_report", "candidates": [{"candidate_id": candidate_id, "score": {"overall_supplier_feasibility": 0.8, "economics": {"gross_margin_percent": 0.3}}}]}
    consumer = {"evidence_mode": "sanitized_report", "candidates": [{"candidate_id": candidate_id, "score": {"overall_consumer_attention": 0.8}}]}
    return market, supplier, consumer


def _built_chain(candidate_id: str, evidence, *, offering_kind: str | None = None):
    market, supplier, consumer = _pillars(candidate_id)
    if offering_kind is not None:
        market["candidates"][0]["offering_kind"] = offering_kind
    synthesis = build_product_opportunity_synthesis(market, supplier, consumer, market_access_evidence={candidate_id: evidence}).to_dict()
    launch = build_launch_draft_pack(synthesis=synthesis).to_dict()
    site = build_site_draft_pack(launch_draft_pack=launch, opportunity_synthesis=synthesis).to_dict()
    return synthesis, launch, site


def _product_validation_report(candidate_id: str, evidence, *, offering_kind: str | None = None, title="Offering"):
    candidate = {"id": candidate_id, "title": title}
    if offering_kind is not None:
        candidate["offering_kind"] = offering_kind
    benchmark = {"candidates": [{"candidate": candidate, "commercial_decision": "hold_for_more_evidence"}], "evidence_mode": "sanitized_report"}
    readiness = {"overall_status": "blocked", "supplier_readiness": {"status": "unknown"}, "blocking_gates": [], "next_best_action": "expand_supplier_research"}
    deployment = {"overall_status": "blocked"}
    return generate_product_validation_report(benchmark=benchmark, readiness=readiness, deployment=deployment, market_access_evidence={candidate_id: evidence}).to_dict()


_OFFICIAL_GOODS_EVIDENCE = {
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
_SERVICE_FISCAL_EVIDENCE = {
    "mexico": {
        "product_family": "unknown_family", "sku_model_exact": "N/A-SERVICE",
        "importer_rfc": "ABC010101AAA", "rfc_evidence_class": "official_db",
        "cfdi_ready": True, "cfdi_evidence_class": "official_db",
        "iva_treatment_reviewed": True, "iva_evidence_class": "official_db",
        "sources_accessed_at": "2026-09-19", "as_of": "2026-09-19",
    }
}


def test_service_offering_same_status_at_every_consumer_surface_real_functions():
    """A pure-service offering: goods/customs/telecom rules must be
    not_applicable, fiscal duties still assessed, identical at every real
    consumer surface -- proven with the actual functions, not a mock."""
    candidate_id = "svc-1"
    direct = _normalized(build_market_access_section({"id": candidate_id, "offering_kind": "service"}, _SERVICE_FISCAL_EVIDENCE))
    synthesis, launch, site = _built_chain(candidate_id, _SERVICE_FISCAL_EVIDENCE, offering_kind="service")
    report = _product_validation_report(candidate_id, _SERVICE_FISCAL_EVIDENCE, offering_kind="service")

    assert direct["offering_kind"] == "service"
    for payload, section in (
        ("synthesis.candidate", synthesis["candidates"][0]["market_access"]),
        ("synthesis.top", synthesis["market_access"]),
        ("launch", launch["market_access"]),
        ("site", site["market_access"]),
        ("product_validation", next(item for item in report["market_access"] if item["candidate_id"] == candidate_id)),
    ):
        normalized = _normalized(section)
        assert normalized["offering_kind"] == "service", payload
        mx = next(j for j in normalized["jurisdictions"] if j["jurisdiction"] == "mexico")
        physical = next(r for r in mx["requirements"] if r["requirement_id"] == "mx_telecom_homologation")
        customs = next(r for r in mx["requirements"] if r["requirement_id"] == "mx_hs_classification")
        fiscal = next(r for r in mx["requirements"] if r["requirement_id"] == "mx_cfdi")
        assert physical["status"] == "not_applicable", payload
        assert customs["status"] == "not_applicable", payload
        assert fiscal["status"] == "satisfied", payload


def test_hybrid_offering_goods_component_consistent_across_real_consumers():
    candidate_id = "hyb-1"
    synthesis, launch, site = _built_chain(candidate_id, _OFFICIAL_GOODS_EVIDENCE, offering_kind="hybrid")
    report = _product_validation_report(candidate_id, _OFFICIAL_GOODS_EVIDENCE, offering_kind="hybrid")
    direct = _normalized(build_market_access_section({"id": candidate_id, "offering_kind": "hybrid"}, _OFFICIAL_GOODS_EVIDENCE))
    for section in (
        synthesis["candidates"][0]["market_access"], launch["market_access"], site["market_access"],
        next(item for item in report["market_access"] if item["candidate_id"] == candidate_id),
    ):
        normalized = _normalized(section)
        assert {"jurisdictions": normalized["jurisdictions"], "overall_status": normalized["overall_status"], "offering_kind": normalized["offering_kind"]} == direct
        mx = next(j for j in normalized["jurisdictions"] if j["jurisdiction"] == "mexico")
        assert "hybrid_offering_service_component_not_assessed_no_evaluator_exists" in mx["warnings"]


def test_unknown_offering_kind_never_assessed_at_any_real_consumer_even_with_full_evidence():
    candidate_id = "unk-1"
    synthesis, launch, site = _built_chain(candidate_id, _OFFICIAL_GOODS_EVIDENCE, offering_kind="digital_download")
    report = _product_validation_report(candidate_id, _OFFICIAL_GOODS_EVIDENCE, offering_kind="digital_download")
    for section in (
        synthesis["candidates"][0]["market_access"], launch["market_access"], site["market_access"],
        next(item for item in report["market_access"] if item["candidate_id"] == candidate_id),
    ):
        normalized = _normalized(section)
        assert normalized["offering_kind"] == "unknown"
        assert normalized["overall_status"] == "not_assessed"


def test_fixture_and_supplier_claim_evidence_never_satisfies_at_any_real_consumer():
    candidate_id = "fix-1"
    tainted = json.loads(json.dumps(_OFFICIAL_GOODS_EVIDENCE))
    for field in ("hs_evidence_class", "nom_003_evidence_class", "cfdi_evidence_class"):
        tainted["mexico"][field] = "supplier_claim"
    synthesis, launch, site = _built_chain(candidate_id, tainted)
    report = _product_validation_report(candidate_id, tainted)
    for section in (
        synthesis["candidates"][0]["market_access"], launch["market_access"], site["market_access"],
        next(item for item in report["market_access"] if item["candidate_id"] == candidate_id),
    ):
        normalized = _normalized(section)
        assert normalized["overall_status"] != "compliant"


def test_already_sold_in_mexico_never_clears_at_any_real_consumer():
    candidate_id = "sold-1"
    tainted = json.loads(json.dumps(_OFFICIAL_GOODS_EVIDENCE))
    tainted["mexico"]["hs_evidence_class"] = "unknown"
    tainted["mexico"]["hs_classification"] = ""
    tainted["mexico"]["already_sold_in_mexico"] = True
    synthesis, launch, site = _built_chain(candidate_id, tainted)
    report = _product_validation_report(candidate_id, tainted)
    for section in (
        synthesis["candidates"][0]["market_access"], launch["market_access"], site["market_access"],
        next(item for item in report["market_access"] if item["candidate_id"] == candidate_id),
    ):
        normalized = _normalized(section)
        mx = next(j for j in normalized["jurisdictions"] if j["jurisdiction"] == "mexico")
        assert "already_sold_in_mexico_does_not_clear_compliance" in mx["warnings"]
        assert normalized["overall_status"] != "compliant"


def test_conflicting_mismatched_evidence_never_satisfies_at_any_real_consumer():
    candidate_id = "mismatch-1"
    mismatched = json.loads(json.dumps(_OFFICIAL_GOODS_EVIDENCE))
    mismatched["mexico"]["product_family"] = "smart_pet_wifi_2_4"
    mismatched["mexico"]["radio_present"] = True
    mismatched["mexico"]["radio_bands_observed"] = ["2.4ghz"]
    mismatched["mexico"]["coh_number"] = "COH-1"
    mismatched["mexico"]["coh_model"] = "SOME-OTHER-MODEL"
    mismatched["mexico"]["coh_status"] = "active"
    mismatched["mexico"]["coh_evidence_class"] = "official_db"
    synthesis, launch, site = _built_chain(candidate_id, mismatched)
    report = _product_validation_report(candidate_id, mismatched)
    for section in (
        synthesis["candidates"][0]["market_access"], launch["market_access"], site["market_access"],
        next(item for item in report["market_access"] if item["candidate_id"] == candidate_id),
    ):
        normalized = _normalized(section)
        assert normalized["overall_status"] != "compliant"


def test_us_and_canada_never_inherit_mexico_compliant_status_at_any_real_consumer():
    candidate_id = "usca-1"
    synthesis, launch, site = _built_chain(candidate_id, _OFFICIAL_GOODS_EVIDENCE)
    report = _product_validation_report(candidate_id, _OFFICIAL_GOODS_EVIDENCE)
    for section in (
        synthesis["candidates"][0]["market_access"], launch["market_access"], site["market_access"],
        next(item for item in report["market_access"] if item["candidate_id"] == candidate_id),
    ):
        normalized = _normalized(section)
        assert normalized["overall_status"] == "compliant"
        for jurisdiction_name in ("united_states", "canada"):
            j = next(j for j in normalized["jurisdictions"] if j["jurisdiction"] == jurisdiction_name)
            assert j["assessment_state"] == "not_assessed"

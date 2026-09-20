"""Cross-consumer contract: every product-recommendation surface that
flows through opportunity synthesis -> launch draft -> site draft, and the
standalone ProductValidationReport, must carry the exact same
evaluator-backed market_access projection for the same candidate evidence
-- never a second, diverging computation, and never a laxer status by the
time it reaches a downstream draft.
"""
import json

from evaluation.trustos.client_workspace_isolation import INTERNAL_KEYS, check_workspace_leakage
from evaluation.commerce.launch_draft_pack import build_launch_draft_pack
from evaluation.commerce.market_access_report import build_market_access_section
from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis
from evaluation.commerce.product_validation_report import generate as generate_product_validation_report
from evaluation.commerce.site_draft_builder import build_site_draft_pack

def _normalized(value):
    """Tuples become lists on the way through each dataclass's own
    to_dict(); normalize through JSON so equality checks compare content,
    not container type."""
    return json.loads(json.dumps(value))


CANDIDATE_ID = "cand-mx-1"
_NEEDS_EVIDENCE_MX = {"mexico": {"product_family": "smart_pet_wifi_2_4", "sku_model_exact": "FEEDER-100"}}
_MARKET_REPORT = {"evidence_mode": "sanitized_report", "candidates": [{"candidate_id": CANDIDATE_ID, "query": "Smart Pet Feeder", "score": {"overall_marketplace_opportunity": 0.8}}]}
_SUPPLIER_REPORT = {"evidence_mode": "sanitized_report", "candidates": [{"candidate_id": CANDIDATE_ID, "score": {"overall_supplier_feasibility": 0.8, "economics": {"gross_margin_percent": 0.3}}}]}
_CONSUMER_REPORT = {"evidence_mode": "sanitized_report", "candidates": [{"candidate_id": CANDIDATE_ID, "score": {"overall_consumer_attention": 0.8}}]}


def _built_chain(evidence):
    synthesis = build_product_opportunity_synthesis(_MARKET_REPORT, _SUPPLIER_REPORT, _CONSUMER_REPORT, market_access_evidence={CANDIDATE_ID: evidence}).to_dict()
    launch = build_launch_draft_pack(synthesis=synthesis).to_dict()
    site = build_site_draft_pack(launch_draft_pack=launch, opportunity_synthesis=synthesis).to_dict()
    return synthesis, launch, site


def test_needs_evidence_status_is_identical_and_never_upgraded_downstream():
    direct = _normalized(build_market_access_section({"id": CANDIDATE_ID}, _NEEDS_EVIDENCE_MX))
    synthesis, launch, site = _built_chain(_NEEDS_EVIDENCE_MX)

    synthesis_candidate_section = _normalized(synthesis["candidates"][0]["market_access"])
    assert synthesis_candidate_section == direct
    assert _normalized(synthesis["market_access"]) == direct

    assert _normalized(launch["market_access"]) == direct
    assert _normalized(site["market_access"]) == direct

    for section in (direct, synthesis_candidate_section, _normalized(launch["market_access"]), _normalized(site["market_access"])):
        mx = next(j for j in section["jurisdictions"] if j["jurisdiction"] == "mexico")
        assert mx["assessment_state"] == "needs_evidence"
        assert mx["assessment_state"] != "compliant"
        for other in ("united_states", "canada"):
            other_section = next(j for j in section["jurisdictions"] if j["jurisdiction"] == other)
            assert other_section["assessment_state"] == "not_assessed"


def test_product_validation_report_matches_the_same_evaluator_backed_result():
    benchmark = {"candidates": [{"candidate": {"id": CANDIDATE_ID, "title": "Smart Pet Feeder"}, "commercial_decision": "hold_for_more_evidence"}], "evidence_mode": "sanitized_report"}
    readiness = {"overall_status": "blocked", "supplier_readiness": {"status": "unknown"}, "blocking_gates": [], "next_best_action": "expand_supplier_research"}
    deployment = {"overall_status": "blocked"}
    report = generate_product_validation_report(benchmark=benchmark, readiness=readiness, deployment=deployment, market_access_evidence={CANDIDATE_ID: _NEEDS_EVIDENCE_MX}).to_dict()
    direct = _normalized(build_market_access_section({"id": CANDIDATE_ID}, _NEEDS_EVIDENCE_MX))
    report_section = next(item for item in report["market_access"] if item["candidate_id"] == CANDIDATE_ID)
    assert _normalized({"jurisdictions": report_section["jurisdictions"], "overall_status": report_section["overall_status"]}) == direct


def test_full_chain_stays_safe_at_trustos_export():
    _, launch, site = _built_chain(_NEEDS_EVIDENCE_MX)
    for payload in (launch, site):
        findings = check_workspace_leakage(payload)
        for finding in findings:
            assert finding.data_class not in INTERNAL_KEYS


def test_compliant_status_flows_downstream_unchanged_too():
    complete_evidence = {
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
    direct = _normalized(build_market_access_section({"id": CANDIDATE_ID}, complete_evidence))
    assert direct["overall_status"] == "compliant"
    synthesis, launch, site = _built_chain(complete_evidence)
    assert _normalized(synthesis["market_access"]) == direct
    assert _normalized(launch["market_access"]) == direct
    assert _normalized(site["market_access"]) == direct

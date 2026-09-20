from __future__ import annotations

from evaluation.commerce.promotion import GATE_IDS, evaluate_promotion
from evaluation.trustos.control_plane import build_trust_controls
from evaluation.trustos.mexico_product_compliance import (
    ACCESS_DATE,
    LEGAL_DISCLAIMER,
    PROMOTION_COMPLIANCE_GATE_ID,
    MexicoProductCompliancePacket,
    build_mexico_trust_controls,
    citation_is_stale,
    evaluate_mexico_product_compliance,
    mexico_policy_sources,
)
from evaluation.trustos.policy_packs import POLICY_PACK_IDS, build_policy_packs


OFFICIAL = "official_db"


def _official_base(**overrides):
    payload = dict(
        market="mexico",
        product_family="hydroponics_non_radio",
        sku_model_exact="HYDRO-KIT-611",
        radio_present=False,
        electrical_present=False,
        electrical_install_equipment=False,
        contains_nutrients_or_seeds=False,
        contains_hazardous_materials=False,
        origin_imported=True,
        hs_classification="3105.20",
        importer_rfc="XAXX010101000",
        cfdi_ready=True,
        pedimento_ref="PED-2026-0001",
        iva_treatment_reviewed=True,
        hs_evidence_class=OFFICIAL,
        rfc_evidence_class=OFFICIAL,
        cfdi_evidence_class=OFFICIAL,
        iva_evidence_class=OFFICIAL,
        pedimento_evidence_class=OFFICIAL,
        lfpc_labeling_evidence_class=OFFICIAL,
        nom_003_evidence_class=OFFICIAL,
        nom_024_evidence_class=OFFICIAL,
        sources_accessed_at=ACCESS_DATE,
        as_of=ACCESS_DATE,
    )
    payload.update(overrides)
    return MexicoProductCompliancePacket(**payload)


def test_canonical_gate_is_not_a_new_gate():
    assert PROMOTION_COMPLIANCE_GATE_ID == "compliance"
    assert PROMOTION_COMPLIANCE_GATE_ID in GATE_IDS
    assert GATE_IDS.count("compliance") == 1
    assert len(POLICY_PACK_IDS) == 7
    assert "mexico_product_compliance" not in POLICY_PACK_IDS


def test_mexico_controls_land_in_existing_legal_and_tax_packs():
    controls = build_mexico_trust_controls()
    assert controls
    assert all(item.category in {"privacy_legal_baseline", "tax_accounting_readiness"} for item in controls)
    assert all(item.applies_to_jurisdictions == ("mexico",) for item in controls)
    assert all(item.professional_review_required for item in controls)
    assert all(LEGAL_DISCLAIMER in item.description for item in controls)
    packs = {pack.pack_id: pack for pack in build_policy_packs()}
    legal_ids = {item.control_id for item in packs["privacy_legal_baseline"].controls}
    tax_ids = {item.control_id for item in packs["tax_accounting_readiness"].controls}
    assert "control-privacy_legal_baseline-mx_telecom_homologation" in legal_ids
    assert "control-privacy_legal_baseline-mx_lfpc_profeco" in legal_ids
    assert "control-tax_accounting_readiness-mx_importer_rfc" in tax_ids
    assert "control-tax_accounting_readiness-mx_cfdi" in tax_ids
    assert "control-tax_accounting_readiness-mx_pedimento" in tax_ids
    merged = build_trust_controls()
    assert {item.control_id for item in controls} <= {item.control_id for item in merged}


def test_sources_are_classified_and_dated():
    sources = mexico_policy_sources()
    assert all(item.accessed_at == ACCESS_DATE for item in sources)
    assert all(item.classification in {"verified_legal_text", "official_observation", "unresolved_interpretation"} for item in sources)
    assert any(item.source_id == "lmtr" and item.classification == "verified_legal_text" for item in sources)
    assert any(item.source_id == "ehomologados" for item in sources)


def test_non_radio_hydro_is_not_ift_blocked():
    decision = evaluate_mexico_product_compliance(_official_base())
    telecom = decision.requirement("mx_telecom_homologation")
    nom208 = decision.requirement("mx_nom_208_radio")
    assert telecom.status == "not_applicable"
    assert nom208.status == "not_applicable"
    assert not any("mx_telecom_homologation" in item for item in decision.blockers)
    assert decision.compliance_satisfied is True


def test_non_radio_hydro_missing_rfc_cfdi_pedimento_needs_evidence():
    decision = evaluate_mexico_product_compliance(_official_base(
        importer_rfc="", cfdi_ready=False, pedimento_ref="",
        rfc_evidence_class="unknown", cfdi_evidence_class="unknown", pedimento_evidence_class="unknown",
    ))
    assert decision.requirement("mx_importer_rfc").status == "needs_evidence"
    assert decision.requirement("mx_cfdi").status == "needs_evidence"
    assert decision.requirement("mx_pedimento").status == "needs_evidence"
    assert decision.compliance_satisfied is False


def test_missing_customs_classification_needs_evidence():
    decision = evaluate_mexico_product_compliance(_official_base(hs_classification="", hs_evidence_class="unknown"))
    assert decision.requirement("mx_hs_classification").status == "needs_evidence"
    assert decision.compliance_satisfied is False


def test_supplier_claim_coh_never_satisfies_launch():
    packet = _official_base(
        product_family="smart_pet_wifi_2_4",
        radio_present=True,
        radio_bands_observed=("2.4ghz",),
        electrical_present=True,
        nom_003_evidence_class=OFFICIAL,
        nom_024_evidence_class=OFFICIAL,
        coh_number="COH-CLAIM",
        coh_model="Feeder-2",
        sku_model_exact="Feeder-2",
        coh_status="active",
        coh_evidence_class="supplier_claim",
    )
    decision = evaluate_mexico_product_compliance(packet)
    assert decision.requirement("mx_telecom_homologation").status == "needs_evidence"
    assert "non_official_evidence:supplier_claim" in decision.requirement("mx_telecom_homologation").blocker
    assert decision.compliance_satisfied is False


def test_fixture_coh_never_satisfies_launch():
    packet = _official_base(
        product_family="telecom_wifi_2_4",
        radio_present=True,
        radio_bands_observed=("2.4ghz",),
        electrical_present=True,
        sku_model_exact="CAM-24",
        coh_number="COH-FIX",
        coh_model="CAM-24",
        coh_status="active",
        coh_evidence_class="fixture",
    )
    decision = evaluate_mexico_product_compliance(packet)
    assert decision.compliance_satisfied is False
    assert decision.requirement("mx_telecom_homologation").status == "needs_evidence"


def test_exact_model_official_coh_may_satisfy_2_4_radio():
    packet = _official_base(
        product_family="smart_pet_wifi_2_4",
        radio_present=True,
        radio_bands_observed=("2.4ghz",),
        electrical_present=True,
        sku_model_exact="NHA-P610",
        coh_number="IFT-COH-001",
        coh_model="NHA-P610",
        coh_status="active",
        coh_evidence_class=OFFICIAL,
    )
    decision = evaluate_mexico_product_compliance(packet)
    assert decision.requirement("mx_telecom_homologation").status == "satisfied"
    assert decision.requirement("mx_nom_208_radio").status == "satisfied"
    assert decision.compliance_satisfied is True


def test_coh_model_mismatch_holds():
    packet = _official_base(
        product_family="smart_pet_wifi_2_4",
        radio_present=True,
        radio_bands_observed=("2.4ghz",),
        electrical_present=True,
        sku_model_exact="NHA-P610",
        coh_number="IFT-COH-001",
        coh_model="NHA-P610-EU",
        coh_status="active",
        coh_evidence_class=OFFICIAL,
    )
    decision = evaluate_mexico_product_compliance(packet)
    assert decision.requirement("mx_telecom_homologation").status == "needs_evidence"
    assert decision.compliance_satisfied is False


def test_cancelled_coh_holds():
    packet = _official_base(
        product_family="smart_pet_wifi_2_4",
        radio_present=True,
        radio_bands_observed=("2.4ghz",),
        electrical_present=True,
        sku_model_exact="NHA-P610",
        coh_number="IFT-COH-001",
        coh_model="NHA-P610",
        coh_status="cancelled",
        coh_evidence_class=OFFICIAL,
    )
    decision = evaluate_mexico_product_compliance(packet)
    assert decision.requirement("mx_telecom_homologation").status == "needs_evidence"
    assert decision.compliance_satisfied is False


def test_uncertain_dual_band_does_not_guess_disposition():
    packet = _official_base(
        product_family="smart_pet_uncertain_band",
        radio_present=True,
        radio_bands_observed=("2.4ghz", "5ghz"),
        electrical_present=True,
        sku_model_exact="Feeder-2",
        coh_evidence_class="unknown",
    )
    decision = evaluate_mexico_product_compliance(packet)
    assert decision.requirement("mx_telecom_homologation").status == "needs_evidence"
    assert decision.requirement("mx_nom_208_radio").status == "not_applicable"
    assert "radio_disposition_not_guessed" in decision.warnings
    assert decision.compliance_satisfied is False


def test_cellular_4g_holds_without_guessing_ift011():
    packet = _official_base(
        product_family="telecom_cellular_4g",
        radio_present=True,
        radio_bands_observed=("cellular_4g",),
        electrical_present=True,
        sku_model_exact="SOLAR-CAM-4G",
        coh_evidence_class="unknown",
    )
    decision = evaluate_mexico_product_compliance(packet)
    assert decision.requirement("mx_telecom_homologation").status == "needs_evidence"
    assert "uncertain_or_cellular_bands_hold_compliance" in decision.warnings
    assert decision.compliance_satisfied is False


def test_stale_citations_need_evidence():
    assert citation_is_stale("2025-01-01", ACCESS_DATE, 180) is True
    packet = _official_base(sources_accessed_at="2025-01-01")
    decision = evaluate_mexico_product_compliance(packet)
    assert decision.requirement("mx_importer_rfc").status == "needs_evidence"
    assert "stale_citation" in decision.requirement("mx_importer_rfc").blocker
    assert decision.compliance_satisfied is False


def test_us_and_canada_are_not_assessed():
    for market in ("united_states", "canada"):
        decision = evaluate_mexico_product_compliance(_official_base(market=market))
        assert all(item.status == "not_assessed" for item in decision.results)
        assert decision.compliance_satisfied is False
        assert "mexico_requirements_not_assessed" in decision.blockers


def test_already_sold_in_mexico_does_not_auto_clear():
    missing = evaluate_mexico_product_compliance(_official_base(
        already_sold_in_mexico=True,
        importer_rfc="",
        rfc_evidence_class="unknown",
    ))
    assert missing.compliance_satisfied is False
    assert "already_sold_in_mexico_does_not_clear_compliance" in missing.warnings
    cleared = evaluate_mexico_product_compliance(_official_base(already_sold_in_mexico=True))
    assert "already_sold_in_mexico_does_not_clear_compliance" in cleared.warnings
    assert cleared.compliance_satisfied is True


def test_unknown_radio_on_unknown_family_holds_ift():
    decision = evaluate_mexico_product_compliance(_official_base(
        product_family="unknown_family",
        radio_present=None,
        electrical_present=True,
        electrical_install_equipment=False,
    ))
    assert decision.requirement("mx_telecom_homologation").status == "needs_evidence"
    assert decision.compliance_satisfied is False


def test_immex_default_not_applicable():
    decision = evaluate_mexico_product_compliance(_official_base(immex_claimed=False))
    assert decision.requirement("mx_immex").status == "not_applicable"


def test_nom_001_sede_not_applicable_for_consumer_families():
    decision = evaluate_mexico_product_compliance(_official_base())
    assert decision.requirement("mx_nom_electrical_installations").status == "not_applicable"


def test_domestic_origin_makes_pedimento_not_applicable():
    decision = evaluate_mexico_product_compliance(_official_base(origin_imported=False, hs_classification="", pedimento_ref=""))
    assert decision.requirement("mx_pedimento").status == "not_applicable"
    assert decision.requirement("mx_hs_classification").status == "not_applicable"
    assert decision.compliance_satisfied is True


def test_decision_is_metadata_only_and_deterministic():
    first = evaluate_mexico_product_compliance(_official_base())
    second = evaluate_mexico_product_compliance(_official_base())
    assert first.to_dict() == second.to_dict()
    assert first.not_legal_advice is True
    assert first.live_lookup_performed is False
    assert first.legal_conclusion is False
    assert first.tax_conclusion is False
    assert first.new_gate_created is False
    assert first.promotion_gate_satisfaction() == {"compliance": True}


def test_maps_onto_promotion_compliance_without_new_gate():
    satisfied = evaluate_mexico_product_compliance(_official_base())
    gates = {gate_id: True for gate_id in GATE_IDS}
    gates["compliance"] = satisfied.compliance_satisfied
    decision = evaluate_promotion("hydro-mx-1", "supplier_validated", gate_satisfaction=gates, evidence_state="verified")
    assert decision.promoted is True
    held = evaluate_mexico_product_compliance(_official_base(
        product_family="telecom_dual_band",
        radio_present=True,
        radio_bands_observed=("2.4ghz", "5ghz"),
        electrical_present=True,
        sku_model_exact="CAM-DUAL",
    ))
    gates["compliance"] = held.compliance_satisfied
    blocked = evaluate_promotion("cam-mx-1", "supplier_validated", gate_satisfaction=gates, evidence_state="verified")
    assert held.compliance_satisfied is False
    assert blocked.promoted is False
    assert "compliance" in blocked.blockers


def test_hydro_nutrients_without_cofepris_need_evidence():
    decision = evaluate_mexico_product_compliance(_official_base(contains_nutrients_or_seeds=True, cofepris_evidence_class="unknown"))
    assert decision.requirement("mx_cofepris_sector").status == "needs_evidence"
    assert decision.compliance_satisfied is False

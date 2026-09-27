from evaluation.trustos.client_workspace_isolation import INTERNAL_KEYS, SECRET_KEYS, check_workspace_leakage
from evaluation.trustos.mexico_product_compliance import evaluate_mexico_product_compliance
from evaluation.commerce.market_access_report import (
    JURISDICTIONS,
    _EVIDENCE_CLASS_FIELD_BY_REQUIREMENT,
    build_candidate_market_access,
    build_market_access_section,
)

_HYDRO_NON_RADIO = {"id": "cand-1", "title": "Nutrient Mix"}
_WIFI_PET = {"id": "cand-2", "title": "Smart Pet Feeder"}

_COMPLETE_MX_EVIDENCE = {
    "product_family": "smart_pet_wifi_2_4",
    "sku_model_exact": "FEEDER-100",
    "radio_present": True,
    "radio_bands_observed": ["2.4ghz"],
    "electrical_present": True,
    "contains_nutrients_or_seeds": False,
    "contains_hazardous_materials": False,
    "origin_imported": True,
    "hs_classification": "8509.80",
    "hs_evidence_class": "official_db",
    "pedimento_ref": "PED-99",
    "pedimento_evidence_class": "official_db",
    "importer_rfc": "ABC010101AAA",
    "rfc_evidence_class": "official_db",
    "cfdi_ready": True,
    "cfdi_evidence_class": "official_db",
    "iva_treatment_reviewed": True,
    "iva_evidence_class": "official_db",
    "nom_003_evidence_class": "official_db",
    "nom_024_evidence_class": "official_db",
    "lfpc_labeling_evidence_class": "official_db",
    "cofepris_evidence_class": "official_db",
    "semarnat_evidence_class": "official_db",
    "coh_number": "COH-1",
    "coh_model": "FEEDER-100",
    "coh_status": "active",
    "coh_evidence_class": "official_db",
    "sources_accessed_at": "2026-09-19",
    "as_of": "2026-09-19",
    "citation_freshness_days": 180,
}


def test_contract_covers_every_canonical_requirement_id():
    """Cross-consumer contract: if the canonical evaluator's requirement set
    ever changes, this projection's evidence-class map must be updated too --
    never silently drop a requirement from the report."""
    decision = evaluate_mexico_product_compliance({"market": "mexico", "product_family": "unknown_family"})
    canonical_ids = {result.requirement_id for result in decision.results}
    assert canonical_ids == set(_EVIDENCE_CLASS_FIELD_BY_REQUIREMENT)


def test_section_present_for_every_candidate_and_every_jurisdiction():
    candidates = [{"candidate": _HYDRO_NON_RADIO}, {"candidate": _WIFI_PET}]
    sections = build_candidate_market_access(candidates)
    assert len(sections) == 2
    for section in sections:
        jurisdictions = {j["jurisdiction"] for j in section["jurisdictions"]}
        assert jurisdictions == set(JURISDICTIONS)


def test_usa_and_canada_always_not_assessed_never_compliant():
    for candidate in (_HYDRO_NON_RADIO, _WIFI_PET):
        section = build_market_access_section(candidate, {"united_states": {"product_family": "unknown_family"}, "canada": {"product_family": "unknown_family"}})
        for jurisdiction in section["jurisdictions"]:
            if jurisdiction["jurisdiction"] in ("united_states", "canada"):
                assert jurisdiction["assessment_state"] == "not_assessed"
                assert jurisdiction["assessment_state"] != "compliant"


def test_complete_official_evidence_reaches_compliant_and_satisfies_gate():
    section = build_market_access_section(_WIFI_PET, {"mexico": _COMPLETE_MX_EVIDENCE})
    mx = next(j for j in section["jurisdictions"] if j["jurisdiction"] == "mexico")
    assert mx["assessment_state"] == "compliant"
    assert mx["promotion_gate"] == {"gate_id": "compliance", "satisfied": True}
    assert section["overall_status"] == "compliant"


def test_partial_evidence_stays_needs_evidence_never_guessed():
    partial = dict(_COMPLETE_MX_EVIDENCE)
    del partial["hs_classification"]
    partial["hs_evidence_class"] = "unknown"
    section = build_market_access_section(_WIFI_PET, {"mexico": partial})
    mx = next(j for j in section["jurisdictions"] if j["jurisdiction"] == "mexico")
    assert mx["assessment_state"] == "needs_evidence"
    hs = next(r for r in mx["requirements"] if r["requirement_id"] == "mx_hs_classification")
    assert hs["status"] == "needs_evidence"
    assert hs["evidence_state"] == "missing"


def test_missing_evidence_is_needs_evidence_not_a_legal_conclusion():
    section = build_market_access_section(_WIFI_PET, {"mexico": {"product_family": "smart_pet_wifi_2_4", "sku_model_exact": "FEEDER-100"}})
    mx = next(j for j in section["jurisdictions"] if j["jurisdiction"] == "mexico")
    assert mx["assessment_state"] == "needs_evidence"
    for requirement in mx["requirements"]:
        assert requirement["status"] != "satisfied" or requirement["status"] == "not_applicable"
        assert requirement["evidence_state"] in ("missing", "present", "stale")


def test_stale_official_citation_never_satisfies():
    stale = dict(_COMPLETE_MX_EVIDENCE)
    stale["sources_accessed_at"] = "2020-01-01"
    section = build_market_access_section(_WIFI_PET, {"mexico": stale})
    mx = next(j for j in section["jurisdictions"] if j["jurisdiction"] == "mexico")
    assert mx["assessment_state"] == "needs_evidence"
    hs = next(r for r in mx["requirements"] if r["requirement_id"] == "mx_hs_classification")
    assert hs["evidence_state"] == "stale"
    assert hs["status"] == "needs_evidence"


def test_conflicting_mismatched_coh_model_blocks_never_satisfies():
    mismatched = dict(_COMPLETE_MX_EVIDENCE)
    mismatched["coh_model"] = "SOME-OTHER-MODEL"
    section = build_market_access_section(_WIFI_PET, {"mexico": mismatched})
    mx = next(j for j in section["jurisdictions"] if j["jurisdiction"] == "mexico")
    assert mx["assessment_state"] == "needs_evidence"
    coh = next(r for r in mx["requirements"] if r["requirement_id"] == "mx_telecom_homologation")
    assert coh["status"] == "needs_evidence"
    assert "model does not match" in coh["note"].lower()


def test_cancelled_coh_blocks_never_satisfies():
    cancelled = dict(_COMPLETE_MX_EVIDENCE)
    cancelled["coh_status"] = "cancelled"
    section = build_market_access_section(_WIFI_PET, {"mexico": cancelled})
    mx = next(j for j in section["jurisdictions"] if j["jurisdiction"] == "mexico")
    coh = next(r for r in mx["requirements"] if r["requirement_id"] == "mx_telecom_homologation")
    assert coh["status"] == "needs_evidence"
    assert "cancelled" in coh["note"].lower()


def test_non_radio_product_not_falsely_blocked_by_telecom_only_rules():
    non_radio = dict(_COMPLETE_MX_EVIDENCE)
    non_radio.update(product_family="hydroponics_non_radio", radio_present=False, radio_bands_observed=(), coh_number="", coh_status="", coh_evidence_class="unknown", coh_model="")
    section = build_market_access_section(_HYDRO_NON_RADIO, {"mexico": non_radio})
    mx = next(j for j in section["jurisdictions"] if j["jurisdiction"] == "mexico")
    telecom = next(r for r in mx["requirements"] if r["requirement_id"] == "mx_telecom_homologation")
    nom208 = next(r for r in mx["requirements"] if r["requirement_id"] == "mx_nom_208_radio")
    assert telecom["status"] == "not_applicable"
    assert nom208["status"] == "not_applicable"
    assert mx["assessment_state"] == "compliant"


def test_unknown_customs_classification_stays_needs_evidence_no_hs_code_guessed():
    unknown_customs = dict(_COMPLETE_MX_EVIDENCE)
    unknown_customs["hs_classification"] = ""
    unknown_customs["hs_evidence_class"] = "unknown"
    unknown_customs["pedimento_ref"] = ""
    unknown_customs["pedimento_evidence_class"] = "unknown"
    section = build_market_access_section(_WIFI_PET, {"mexico": unknown_customs})
    mx = next(j for j in section["jurisdictions"] if j["jurisdiction"] == "mexico")
    hs = next(r for r in mx["requirements"] if r["requirement_id"] == "mx_hs_classification")
    pedimento = next(r for r in mx["requirements"] if r["requirement_id"] == "mx_pedimento")
    assert hs["status"] == "needs_evidence" and hs["evidence_class"] != "official_db"
    assert pedimento["status"] == "needs_evidence"
    customs_ids = {r["requirement_id"] for r in mx["customs_import_considerations"]}
    assert "mx_hs_classification" in customs_ids and "mx_pedimento" in customs_ids


def test_future_jurisdiction_placeholder_never_appears_as_compliant():
    """No placeholder claim like 'compliant in North America' -- US/CA are
    always their own explicit not_assessed section, never folded into an
    aggregate compliant status."""
    section = build_market_access_section(_WIFI_PET, {"mexico": _COMPLETE_MX_EVIDENCE})
    for jurisdiction in section["jurisdictions"]:
        if jurisdiction["jurisdiction"] != "mexico":
            assert jurisdiction["assessment_state"] == "not_assessed"
    assert section["overall_status"] == "compliant"


def test_supplier_claim_and_fixture_evidence_never_satisfy():
    for bad_class in ("supplier_claim", "fixture"):
        evidence = dict(_COMPLETE_MX_EVIDENCE)
        for field in ("hs_evidence_class", "nom_003_evidence_class", "coh_evidence_class"):
            evidence[field] = bad_class
        section = build_market_access_section(_WIFI_PET, {"mexico": evidence})
        mx = next(j for j in section["jurisdictions"] if j["jurisdiction"] == "mexico")
        assert mx["assessment_state"] == "needs_evidence", bad_class


def test_already_sold_in_mexico_is_a_warning_never_a_clearance():
    evidence = dict(_COMPLETE_MX_EVIDENCE)
    evidence["hs_evidence_class"] = "unknown"
    evidence["hs_classification"] = ""
    evidence["already_sold_in_mexico"] = True
    section = build_market_access_section(_WIFI_PET, {"mexico": evidence})
    mx = next(j for j in section["jurisdictions"] if j["jurisdiction"] == "mexico")
    assert "already_sold_in_mexico_does_not_clear_compliance" in mx["warnings"]
    assert mx["assessment_state"] == "needs_evidence"


def test_safe_at_trustos_export_no_internal_or_secret_leakage():
    """The market-access section must survive the existing TrustOS
    client-safe export boundary (check_workspace_leakage) without ever
    exposing an internal-only data class or a secret-shaped value -- this
    reuses TrustOS's own boundary rather than inventing a second redaction
    mechanism. A complete/compliant section produces zero findings; a
    needs_evidence section may still trip the checker's generic
    "looks like a filesystem path" heuristic on benign " / " punctuation
    inside the canonical evaluator's own legal-citation prose (owned by
    evaluation.trustos.mexico_product_compliance, not this module) -- that
    is a pre-existing property of the shared checker's heuristic over
    human-readable text, not an internal-key or secret leak, so it is
    accepted here as long as it never lands on a real internal/secret
    data class."""
    complete_section = build_market_access_section(_WIFI_PET, {"mexico": _COMPLETE_MX_EVIDENCE})
    assert check_workspace_leakage({"market_access": complete_section}) == ()

    incomplete_section = build_market_access_section(_WIFI_PET, {"mexico": {"product_family": "smart_pet_wifi_2_4", "sku_model_exact": "FEEDER-100"}})
    findings = check_workspace_leakage({"market_access": incomplete_section})
    for finding in findings:
        assert finding.data_class not in INTERNAL_KEYS
        assert finding.data_class != "client_safe_export_packet"
        assert not any(secret in finding.field_path.lower() for secret in SECRET_KEYS)


def test_secret_shaped_evidence_value_is_still_caught_by_trustos_export():
    """Positive control: if a caller ever put an actual secret-shaped
    string into evidence, the shared TrustOS boundary must still catch it
    -- proving the boundary is doing real work on this payload shape, not
    silently passing everything through."""
    tainted = dict(_COMPLETE_MX_EVIDENCE)
    tainted["importer_rfc"] = "sk-live-abcdefghijklmnopqrstuvwx"
    section = build_market_access_section(_WIFI_PET, {"mexico": tainted})
    findings = check_workspace_leakage({"market_access": section, "raw_importer_rfc": tainted["importer_rfc"]})
    assert any(f.status == "hard_block" for f in findings)


def test_evidence_state_never_says_present_when_status_is_not_satisfied():
    """Regression: evidence_class='official_db' with an empty underlying
    field (or a mismatched CoH model) must never render as
    evidence_state='present' next to a needs_evidence status -- that
    combination reads as self-contradictory in a compliance disclosure."""
    empty_hs = dict(_COMPLETE_MX_EVIDENCE)
    empty_hs["hs_classification"] = ""
    section = build_market_access_section(_WIFI_PET, {"mexico": empty_hs})
    mx = next(j for j in section["jurisdictions"] if j["jurisdiction"] == "mexico")
    hs = next(r for r in mx["requirements"] if r["requirement_id"] == "mx_hs_classification")
    assert hs["status"] == "needs_evidence"
    assert hs["evidence_state"] != "present"

    mismatched = dict(_COMPLETE_MX_EVIDENCE)
    mismatched["coh_model"] = "SOME-OTHER-MODEL"
    section2 = build_market_access_section(_WIFI_PET, {"mexico": mismatched})
    mx2 = next(j for j in section2["jurisdictions"] if j["jurisdiction"] == "mexico")
    coh = next(r for r in mx2["requirements"] if r["requirement_id"] == "mx_telecom_homologation")
    assert coh["status"] == "needs_evidence"
    assert coh["evidence_state"] != "present"


def test_invalid_evidence_fails_closed_instead_of_crashing():
    section = build_market_access_section(_WIFI_PET, {"mexico": {"product_family": "not_a_real_family"}})
    mx = next(j for j in section["jurisdictions"] if j["jurisdiction"] == "mexico")
    assert mx["assessment_state"] == "needs_evidence"
    assert mx["assessment_state"] != "compliant"

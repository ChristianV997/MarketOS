"""Regression tests for the Market Access & Import Requirements report boundary.

These tests exercise ``evaluation.commerce.market_access_report`` (this
lane's thin consumer) and its wiring into
``evaluation.commerce.product_validation_report``. They deliberately do
NOT re-implement or re-verify the canonical Mexico compliance evaluator's
own legal logic (``evaluation.trustos.mexico_product_compliance``, owned
by a different lane and covered by its own test suite) -- they prove the
report boundary: every recommendation gets the section, its status is
consistent with the canonical evaluator and the promotion.compliance gate,
fixture/supplier-claim evidence never becomes live proof, an already-sold
product is never treated as proof, future jurisdictions stay not_assessed,
and bad/absent evidence fails closed instead of crashing report generation.
"""
from __future__ import annotations

import json

from evaluation.commerce.market_access_report import (
    ASSESSED_MARKET,
    FUTURE_MARKETS,
    build_market_access_projection,
)
from evaluation.commerce.product_validation_report import generate, markdown
from evaluation.commerce.promotion import GATE_IDS
from evaluation.trustos.mexico_product_compliance import PROMOTION_COMPLIANCE_GATE_ID

_COMPLETE_NON_RADIO = {
    "product_family": "hydroponics_non_radio",
    "sku_model_exact": "HYDRO-100",
    "radio_present": False,
    "electrical_present": True,
    "origin_imported": True,
    "contains_nutrients_or_seeds": False,
    "contains_hazardous_materials": False,
    "hs_classification": "8419.89",
    "hs_evidence_class": "official_db",
    "pedimento_ref": "PED-2026-001",
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
    "sources_accessed_at": "2026-09-19",
    "as_of": "2026-09-19",
    "citation_freshness_days": 180,
}


def test_promotion_gate_is_the_canonical_single_gate():
    assert PROMOTION_COMPLIANCE_GATE_ID == "compliance"
    assert PROMOTION_COMPLIANCE_GATE_ID in GATE_IDS


def test_no_evidence_supplied_fails_closed():
    section = build_market_access_projection("cand-1", "Widget", {})
    mx = section["markets"]["mexico"]
    assert mx["status"] == "needs_evidence"
    assert mx["gate_satisfied"] is False
    assert "missing_exact_sku_model" in mx["missing_or_uncertain"]
    for market in FUTURE_MARKETS:
        assert section["markets"][market]["status"] == "not_assessed"
        assert section["markets"][market]["gate_satisfied"] is False


def test_complete_official_fresh_evidence_can_satisfy_non_radio_product():
    section = build_market_access_projection("cand-2", "Hydro Kit", _COMPLETE_NON_RADIO)
    mx = section["markets"]["mexico"]
    assert mx["status"] == "satisfied"
    assert mx["gate_satisfied"] is True
    assert mx["missing_or_uncertain"] == []


def test_non_radio_product_never_blocked_by_telecom_requirements():
    section = build_market_access_projection("cand-3", "Hydro Kit", _COMPLETE_NON_RADIO)
    reqs = {r["requirement_id"]: r for r in section["markets"]["mexico"]["requirements"]}
    assert reqs["mx_telecom_homologation"]["status"] == "not_applicable"
    assert reqs["mx_nom_208_radio"]["status"] == "not_applicable"


def test_partial_evidence_yields_needs_evidence_not_a_guess():
    evidence = dict(_COMPLETE_NON_RADIO)
    del evidence["cfdi_ready"]
    evidence["cfdi_evidence_class"] = "unknown"
    section = build_market_access_projection("cand-4", "Hydro Kit", evidence)
    mx = section["markets"]["mexico"]
    assert mx["status"] == "needs_evidence"
    reqs = {r["requirement_id"]: r for r in mx["requirements"]}
    assert reqs["mx_cfdi"]["status"] == "needs_evidence"


def test_missing_hs_classification_never_reads_as_cleared():
    evidence = dict(_COMPLETE_NON_RADIO)
    evidence["hs_classification"] = ""
    evidence["hs_evidence_class"] = "unknown"
    section = build_market_access_projection("cand-5", "Hydro Kit", evidence)
    reqs = {r["requirement_id"]: r for r in section["markets"]["mexico"]["requirements"]}
    assert reqs["mx_hs_classification"]["status"] == "needs_evidence"
    assert section["markets"]["mexico"]["status"] != "satisfied"


def test_stale_citation_falls_back_to_needs_evidence():
    evidence = dict(_COMPLETE_NON_RADIO)
    evidence["sources_accessed_at"] = "2024-01-01"  # far outside 180-day freshness window
    section = build_market_access_projection("cand-6", "Hydro Kit", evidence)
    mx = section["markets"]["mexico"]
    assert mx["status"] == "needs_evidence"
    reqs = {r["requirement_id"]: r for r in mx["requirements"]}
    assert reqs["mx_hs_classification"]["citation_stale"] is True


def test_supplier_claim_and_fixture_evidence_never_satisfy_launch():
    for bad_class in ("supplier_claim", "fixture", "unknown"):
        evidence = dict(_COMPLETE_NON_RADIO)
        evidence["hs_evidence_class"] = bad_class
        section = build_market_access_projection("cand-7", "Hydro Kit", evidence)
        reqs = {r["requirement_id"]: r for r in section["markets"]["mexico"]["requirements"]}
        assert reqs["mx_hs_classification"]["status"] == "needs_evidence"
        assert section["markets"]["mexico"]["status"] != "satisfied"


def test_conflicting_coh_model_mismatch_blocks_telecom_requirement():
    evidence = {
        "product_family": "telecom_wifi_2_4",
        "sku_model_exact": "RTR-9",
        "radio_present": True,
        "radio_bands_observed": ("2.4ghz",),
        "coh_number": "COH-123",
        "coh_model": "RTR-DIFFERENT-MODEL",
        "coh_status": "active",
        "coh_evidence_class": "official_db",
        "sources_accessed_at": "2026-09-19",
    }
    section = build_market_access_projection("cand-8", "Router", evidence)
    reqs = {r["requirement_id"]: r for r in section["markets"]["mexico"]["requirements"]}
    telecom = reqs["mx_telecom_homologation"]
    assert telecom["status"] == "needs_evidence"
    assert "does not match" in telecom["note"]
    assert section["markets"]["mexico"]["gate_satisfied"] is False


def test_radio_dual_band_uncertain_holds_compliance_never_guesses_disposition():
    evidence = {
        "product_family": "telecom_dual_band",
        "sku_model_exact": "RTR-DUAL-1",
        "radio_present": True,
        "radio_bands_observed": ("2.4ghz", "5ghz"),
    }
    section = build_market_access_projection("cand-9", "Dual-band Router", evidence)
    mx = section["markets"]["mexico"]
    reqs = {r["requirement_id"]: r for r in mx["requirements"]}
    assert reqs["mx_telecom_homologation"]["status"] == "needs_evidence"
    assert mx["gate_satisfied"] is False
    assert "uncertain_or_cellular_bands_hold_compliance" in mx["warnings"]


def test_already_sold_in_mexico_is_a_warning_never_proof():
    evidence = {"product_family": "hydroponics_non_radio", "already_sold_in_mexico": True}
    section = build_market_access_projection("cand-10", "Hydro Kit", evidence)
    mx = section["markets"]["mexico"]
    assert mx["status"] != "satisfied"
    assert "already_sold_in_mexico_does_not_clear_compliance" in mx["warnings"]


def test_future_jurisdictions_stay_not_assessed_even_with_complete_evidence_supplied():
    section = build_market_access_projection("cand-11", "Hydro Kit", _COMPLETE_NON_RADIO)
    for market in FUTURE_MARKETS:
        m = section["markets"][market]
        assert m["status"] == "not_assessed"
        assert m["gate_satisfied"] is False
        assert all(r["status"] in {"not_assessed"} for r in m["requirements"])


def test_invalid_evidence_fails_closed_instead_of_crashing():
    section = build_market_access_projection("cand-12", "Mystery Item", {"product_family": "not-a-real-family"})
    mx = section["markets"][ASSESSED_MARKET]
    assert mx["status"] == "needs_evidence"
    assert mx["gate_satisfied"] is False
    assert any("invalid_market_access_evidence" in item for item in mx["missing_or_uncertain"])


def test_unrelated_evidence_keys_are_ignored_not_guessed_from():
    # A caller-supplied "category" string must never be read as a radio/NOM
    # signal -- only the evaluator's own declared packet fields are honored.
    evidence = dict(_COMPLETE_NON_RADIO)
    evidence["category"] = "wireless bluetooth cellular"
    section = build_market_access_projection("cand-13", "Hydro Kit", evidence)
    reqs = {r["requirement_id"]: r for r in section["markets"]["mexico"]["requirements"]}
    assert reqs["mx_telecom_homologation"]["status"] == "not_applicable"


def _benchmark_with_candidates():
    return {
        "evidence_mode": "sanitized_report",
        "candidates": [
            {
                "candidate": {"candidate_id": "cand-a", "title": "Hydro Kit"},
                "commercial_decision": "advance_to_live_supplier_validation",
                "assumption_ratio": 0.1,
                "evidence_completeness": 0.9,
                "economics": {"margin_quality": "good"},
            },
            {
                "candidate": {"candidate_id": "cand-b", "title": "Smart Router"},
                "commercial_decision": "hold_for_credentials",
                "assumption_ratio": 0.2,
                "evidence_completeness": 0.4,
                "economics": {"margin_quality": "fair"},
            },
        ],
    }


def test_report_attaches_market_access_to_every_top_recommendation():
    benchmark = _benchmark_with_candidates()
    evidence = {"cand-a": _COMPLETE_NON_RADIO}
    report = generate(benchmark=benchmark, market_access_evidence=evidence).to_dict()
    assert len(report["market_access"]) == 2
    by_id = {section["candidate_id"]: section for section in report["market_access"]}
    assert by_id["cand-a"]["markets"]["mexico"]["status"] == "satisfied"
    # cand-b has no supplied evidence at all -- must fail closed, not crash
    # or silently report as cleared.
    assert by_id["cand-b"]["markets"]["mexico"]["status"] == "needs_evidence"
    for market in FUTURE_MARKETS:
        assert by_id["cand-a"]["markets"][market]["status"] == "not_assessed"


def test_report_markdown_includes_market_access_section_and_is_json_safe():
    benchmark = _benchmark_with_candidates()
    evidence = {"cand-a": _COMPLETE_NON_RADIO}
    report_obj = generate(benchmark=benchmark, market_access_evidence=evidence)
    report = report_obj.to_dict()
    text = markdown(report)
    assert "Market Access & Import Requirements" in text
    assert "Hydro Kit" in text
    assert "Smart Router" in text
    # Export must remain TrustOS-safe / client-safe: plain JSON, no crash.
    blob = json.dumps(report)
    assert "not legal advice" in blob.lower()


def test_bare_report_call_has_no_market_access_and_never_crashes():
    report = generate().to_dict()
    assert report["market_access"] == []
    markdown(report)  # must not raise even with an empty section

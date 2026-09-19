from evaluation.commerce.market_compliance import (
    ASSESSED_MARKETS,
    NOT_ASSESSED_MARKETS,
    build_market_compliance_section,
    evaluate_candidate_market_compliance,
)
from evaluation.commerce.product_validation_report import generate

_NON_RADIO = {"id": "cand-1", "title": "Ceramic Mug", "category": "kitchenware"}
_RADIO = {"id": "cand-2", "title": "Bluetooth Speaker", "category": "wireless_audio"}

_LIVE_MATCH_EVIDENCE = {
    "evidence_state": "observed",
    "requirements": {
        "exact_sku_model_match": {"match": True, "source": "supplier_portal", "access_date": "2026-09-01"},
        "tariff_classification": {"hs_code": "8517.62", "source": "customs_broker", "access_date": "2026-09-01"},
        "nom_applicability": {"applicable": False, "source": "legal_counsel", "access_date": "2026-09-01"},
        "customs_import_permit": {"status": "granted", "source": "customs_broker", "access_date": "2026-09-01"},
    },
}


def test_section_present_for_every_candidate():
    candidates = [{"candidate": _NON_RADIO}, {"candidate": _RADIO}]
    section = build_market_compliance_section(candidates)
    assert len(section) == 2
    ids = {s["candidate_id"] for s in section}
    assert ids == {"cand-1", "cand-2"}
    for entry in section:
        markets = {r["market"] for r in entry["requirements"]}
        assert set(ASSESSED_MARKETS) | set(NOT_ASSESSED_MARKETS) <= markets


def test_usa_and_canada_always_not_assessed_never_compliant():
    for candidate in (_NON_RADIO, _RADIO):
        results = evaluate_candidate_market_compliance(candidate, {"US": {"evidence_state": "verified"}, "CA": {"evidence_state": "verified"}})
        for market in NOT_ASSESSED_MARKETS:
            entries = [r for r in results if r["market"] == market]
            assert entries and all(r["status"] == "not_assessed" for r in entries)
            assert all(r["status"] != "compliant" for r in entries)


def test_exact_model_evidence_required_before_compliant():
    results = evaluate_candidate_market_compliance(_NON_RADIO, {"MX": _LIVE_MATCH_EVIDENCE})
    match_result = next(r for r in results if r["market"] == "MX" and r["requirement"] == "exact_sku_model_match")
    assert match_result["status"] == "compliant"

    no_match_evidence = {"evidence_state": "observed", "requirements": {}}
    results_missing = evaluate_candidate_market_compliance(_NON_RADIO, {"MX": no_match_evidence})
    missing_result = next(r for r in results_missing if r["market"] == "MX" and r["requirement"] == "exact_sku_model_match")
    assert missing_result["status"] == "needs_evidence"
    assert "exact_sku_or_model_match" in missing_result["missing_input"]


def test_mismatched_evidence_blocks_not_guessed_compliant():
    evidence = {"evidence_state": "observed", "requirements": {"exact_sku_model_match": {"match": False}}}
    results = evaluate_candidate_market_compliance(_NON_RADIO, {"MX": evidence})
    result = next(r for r in results if r["market"] == "MX" and r["requirement"] == "exact_sku_model_match")
    assert result["status"] == "blocked"


def test_stale_and_cancelled_certificate_evidence_blocks():
    for bad_state in ("stale", "cancelled", "expired", "mismatched", "revoked"):
        evidence = {
            "evidence_state": "observed",
            "requirements": {
                "nom_applicability": {"applicable": True, "nom_status": bad_state},
            },
        }
        results = evaluate_candidate_market_compliance(_RADIO, {"MX": evidence})
        result = next(r for r in results if r["market"] == "MX" and r["requirement"] == "nom_applicability")
        assert result["status"] == "blocked", bad_state
        assert result["status"] != "compliant"


def test_unknown_tariff_and_homologation_stay_needs_evidence_never_guessed():
    evidence = {"evidence_state": "observed", "requirements": {}}
    results = evaluate_candidate_market_compliance(_RADIO, {"MX": evidence})
    for requirement in ("tariff_classification", "nom_applicability", "ift_crt_homologation", "customs_import_permit"):
        result = next(r for r in results if r["market"] == "MX" and r["requirement"] == requirement)
        assert result["status"] == "needs_evidence"
        assert result["missing_input"]


def test_fixture_and_manual_evidence_never_reaches_compliant():
    for fixture_state in ("fixture", "assumed", "derived", "simulated", "unknown", "missing"):
        evidence = {"evidence_state": fixture_state, "requirements": _LIVE_MATCH_EVIDENCE["requirements"]}
        results = evaluate_candidate_market_compliance(_NON_RADIO, {"MX": evidence})
        assessed = [r for r in results if r["market"] in ASSESSED_MARKETS]
        assert all(r["status"] != "compliant" for r in assessed), fixture_state


def test_ambiguous_match_value_never_guessed_compliant():
    for ambiguous in (0, "TBD", "unknown", "n/a", "aplicable"):
        evidence = {"evidence_state": "observed", "requirements": {"exact_sku_model_match": {"match": ambiguous}}}
        results = evaluate_candidate_market_compliance(_NON_RADIO, {"MX": evidence})
        result = next(r for r in results if r["market"] == "MX" and r["requirement"] == "exact_sku_model_match")
        assert result["status"] == "needs_evidence", ambiguous


def test_ambiguous_nom_applicability_never_guessed_compliant():
    for ambiguous in (0, "TBD", "unknown", "aplicable"):
        evidence = {"evidence_state": "observed", "requirements": {"nom_applicability": {"applicable": ambiguous}}}
        results = evaluate_candidate_market_compliance(_RADIO, {"MX": evidence})
        result = next(r for r in results if r["market"] == "MX" and r["requirement"] == "nom_applicability")
        assert result["status"] == "needs_evidence", ambiguous


def test_non_radio_products_not_falsely_blocked_by_telecom_only_rules():
    evidence = {"evidence_state": "observed", "requirements": {}}
    results = evaluate_candidate_market_compliance(_NON_RADIO, {"MX": evidence})
    requirements_present = {r["requirement"] for r in results if r["market"] == "MX"}
    assert "ift_crt_homologation" not in requirements_present

    section = build_market_compliance_section([{"candidate": _NON_RADIO}])
    assert section[0]["overall_status"] == "needs_evidence"


def test_radio_products_include_ift_crt_requirement():
    evidence = {"evidence_state": "observed", "requirements": {}}
    results = evaluate_candidate_market_compliance(_RADIO, {"MX": evidence})
    requirements_present = {r["requirement"] for r in results if r["market"] == "MX"}
    assert "ift_crt_homologation" in requirements_present


def test_report_includes_market_compliance_section_for_every_candidate():
    benchmark = {
        "candidates": [{"candidate": _NON_RADIO, "commercial_decision": "hold_for_more_evidence"}, {"candidate": _RADIO, "commercial_decision": "hold_for_more_evidence"}],
        "evidence_mode": "sanitized_report",
    }
    readiness = {"overall_status": "blocked", "supplier_readiness": {"status": "unknown"}, "blocking_gates": [], "next_best_action": "expand_supplier_research"}
    deployment = {"overall_status": "blocked"}
    report = generate(benchmark=benchmark, readiness=readiness, deployment=deployment).to_dict()
    assert len(report["market_compliance"]) == 2
    for entry in report["market_compliance"]:
        markets = {r["market"] for r in entry["requirements"]}
        assert "US" in markets and "CA" in markets and "MX" in markets


def test_report_default_bare_call_still_has_market_compliance_key():
    report = generate().to_dict()
    assert report["market_compliance"] == []

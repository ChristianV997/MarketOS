"""Focused tests for the bounded offline research-to-decision seam."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.research_to_decision import ResearchToDecisionError, build_research_to_decision


ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures" / "research_to_decision"
LANE = {
    "origin_country": "China",
    "ship_from_country": "China",
    "warehouse": "Shenzhen manual warehouse",
    "destination_country": "Mexico",
    "destination_state_region": "Mexico City",
    "postal_code_assumption": "01000",
    "currency": "MXN",
    "tax_model": "destination VAT modeled as an assumption",
    "duty_model": "unknown until broker quote",
    "brokerage_model": "unknown until broker quote",
    "shipping_model": "offer shipping included when observed",
    "return_destination": "Mexico warehouse or supplier address unknown",
    "return_cost_payer": "unknown",
    "payment_method": "card with platform fee assumption",
    "compliance_requirements": ["product-specific review required"],
    "customer_support_language": ["es-MX"],
    "marketplace_eligibility": ["Mercado Libre subject to approval"],
    "delivery_promise": "supplier window only; not a customer promise",
    "evidence_state": "fixture",
    "confidence": 0.5,
}
SCENARIOS = (
    "hydroponics_promising.json",
    "smart_pet_support_risk.json",
    "solar_4g_blocked.json",
    "commodity_electronics_rejected.json",
    "walking_pad_deferred.json",
    "b2b_insufficient_data.json",
)


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario_builds_existing_client_safe_packet(name: str) -> None:
    report = build_research_to_decision(load_fixture(name), base_dir=FIXTURES)
    appendix = report["appendix"]
    assert report["report_version"] == "product-validation-report-v1"
    assert report["source_reports"]["research_to_decision"] == "supplied"
    assert report["read_only"] is True
    assert report["network_calls"] is False
    assert report["mutated"] is False
    assert appendix["validation"]["status"] == "hold_for_manual_review"
    assert appendix["validation"]["provider_calls"] is False
    assert len(appendix["replay_fingerprint"]) == 64
    assert appendix["candidate_audit"][0]["lifecycle_state"]
    assert "lane" in appendix["candidate_audit"][0]
    assert report["overall_recommendation"] != "advance_to_launch_draft"


def test_packet_is_deterministic_and_contains_ranked_evidence() -> None:
    manifest = load_fixture("hydroponics_promising.json")
    first = build_research_to_decision(manifest, base_dir=FIXTURES)
    second = build_research_to_decision(manifest, base_dir=FIXTURES)
    assert first == second
    assert first["candidate_rankings"]
    assert first["appendix"]["candidate_audit"][0]["action"]
    assert "economics" in first["appendix"]["candidate_audit"][0]


def test_promotion_lifecycle_is_auditable_and_replay_stable() -> None:
    manifest = load_fixture("hydroponics_promising.json")
    first = build_research_to_decision(manifest, base_dir=FIXTURES)
    second = build_research_to_decision(manifest, base_dir=FIXTURES)
    audit = first["appendix"]["candidate_audit"][0]
    transitions = audit["promotion_lifecycle"]
    assert transitions == second["appendix"]["candidate_audit"][0]["promotion_lifecycle"]
    assert {item["next_state"] for item in transitions} >= {
        "discovered",
        "normalized",
        "screened",
        "supplier_claimed",
        "supplier_documented",
        "sample_required",
        "direct_ship_required",
        "promotion_blocked",
        "launch_authorized_false",
    }
    for item in transitions:
        assert set(item) == {
            "candidate_id",
            "prior_state",
            "next_state",
            "reason_code",
            "evidence_ids",
            "evidence_state",
            "actor_source",
            "timestamp",
            "blocking_conditions",
            "replay_identity",
        }
        assert len(item["replay_identity"]) == 64
        assert item["timestamp"] == manifest["captured_at"]
    assert audit["decision_outcome"] == "candidate_only"
    assert first["appendix"]["client_safe_projection"]["launch_authorized"] is False
    assert first["appendix"]["client_safe_projection"]["candidates"][0]["promotion_state"] == "launch_authorized_false"


def test_conflicting_offers_are_visible_but_cannot_promote() -> None:
    report = build_research_to_decision(load_fixture("conflicting_quotes.json"), base_dir=FIXTURES)
    audit = report["appendix"]["candidate_audit"][0]
    states = {item["next_state"] for item in audit["promotion_lifecycle"]}
    assert {"supplier_claimed", "offer_conflicted", "promotion_blocked", "launch_authorized_false"} <= states
    assert "launch_candidate" not in states
    assert "live_validated" not in states
    assert audit["decision_outcome"] == "needs_evidence"


def test_missing_supplier_evidence_is_an_explicit_promotion_blocker() -> None:
    report = build_research_to_decision(load_fixture("b2b_insufficient_data.json"), base_dir=FIXTURES)
    audit = report["appendix"]["candidate_audit"][0]
    states = {item["next_state"] for item in audit["promotion_lifecycle"]}
    assert "evidence_incomplete" in states
    assert "supplier_offer_evidence_missing" in audit["evidence_gaps"]
    assert audit["decision_outcome"] == "needs_evidence"
    assert audit["promotion_lifecycle"][-1]["next_state"] == "launch_authorized_false"


@pytest.mark.parametrize("name", SCENARIOS)
def test_offline_evidence_never_emits_live_promotion_states(name: str) -> None:
    report = build_research_to_decision(load_fixture(name), base_dir=FIXTURES)
    states = {item["next_state"] for item in report["appendix"]["candidate_audit"][0]["promotion_lifecycle"]}
    assert "live_validated" not in states
    assert "manually_approved" not in states
    assert report["appendix"]["client_safe_projection"]["launch_authorized"] is False


def test_market_lane_and_supplier_offer_are_explicit_and_bounded() -> None:
    report = build_research_to_decision(load_fixture("hydroponics_promising.json"), base_dir=FIXTURES)
    appendix = report["appendix"]
    assert appendix["market_lane"]["destination_country"] == "Mexico"
    assert appendix["market_lane"]["warehouse"] == "Shenzhen manual warehouse"
    offer = appendix["supplier_offers"][0]
    assert offer["exact_sku"] == "HYD-01"
    assert offer["price"]["currency"] == "MXN"
    assert offer["delivery"] == {"p50_days": 7.0, "p95_days": 12.0}
    assert offer["shipping"]["method"] == "dropship"
    assert offer["evidence"]["state"] == "fixture"
    assert offer["status"] == "accepted"
    assert "no_launch_or_spend_authority" in appendix["candidate_audit"][0]["hard_gates"]


def test_evidence_references_and_client_projection_are_stable() -> None:
    manifest = load_fixture("hydroponics_promising.json")
    manifest["supplier_inputs"][0].update(
        {
            "source_reference": "fixture:hydroponics-quote.pdf",
            "extraction_method": "manual_quote_review",
            "warnings": ["return terms remain manual"],
        }
    )
    report = build_research_to_decision(manifest, base_dir=FIXTURES)
    appendix = report["appendix"]
    offer = appendix["supplier_offers"][0]
    audit = appendix["candidate_audit"][0]
    projection = appendix["client_safe_projection"]
    assert offer["evidence"]["reference_id"].startswith("evidence:")
    assert len(offer["evidence"]["reference_id"]) == 25
    assert offer["evidence"]["extraction_method"] == "manual_quote_review"
    assert offer["evidence"]["warnings"] == ["return terms remain manual"]
    assert offer["evidence"]["reference_id"] in audit["evidence_refs"]
    assert len(audit["evidence_refs"]) == 3
    assert audit["extraction_methods"] == ["manual_quote_review"]
    assert audit["freshness"] == "current"
    assert audit["risk_state"] == "hold"
    assert audit["conflicts"] == []
    assert projection["launch_authorized"] is False
    assert projection["candidates"][0]["evidence_refs"] == audit["evidence_refs"]
    assert appendix["integration_contract"]["cockpit"] == "appendix.client_safe_projection"
    assert "hydroponics-quote.pdf" not in json.dumps(report)


def test_lane_and_supplier_identity_do_not_accept_implicit_global_defaults(tmp_path: Path) -> None:
    manifest = load_fixture("b2b_insufficient_data.json")
    manifest["lane"] = {"origin": "Shenzhen", "destination": "Mexico", "currency": "MXN"}
    with pytest.raises(ResearchToDecisionError, match="lane is missing required fields"):
        build_research_to_decision(manifest, base_dir=FIXTURES)

    evidence = tmp_path / "malformed.json"
    evidence.write_text(json.dumps({"candidate_id": "x", "offer_id": "offer-x", "supplier_sku": "SKU-X", "currency": "MXN", "destination_region": "Mexico", "unit_cost": {"amount": 1}}), encoding="utf-8")
    manifest = {"captured_at": "2026-09-16T09:00:00-06:00", "lane": dict(LANE), "candidates": [{"candidate_id": "x", "lifecycle_state": "candidate"}], "supplier_inputs": [{"path": "malformed.json"}]}
    with pytest.raises(ResearchToDecisionError, match="malformed nested"):
        build_research_to_decision(manifest, base_dir=tmp_path)


def test_stale_offer_is_quarantined_without_becoming_a_pass() -> None:
    report = build_research_to_decision(load_fixture("stale_offer.json"), base_dir=FIXTURES)
    offer = report["appendix"]["supplier_offers"][0]
    assert offer["status"] == "quarantined"
    assert "offer_expired" in offer["issues"]
    assert report["appendix"]["validation"]["status"] == "hold_for_manual_review"


def test_missing_return_address_is_preserved_as_a_supplier_gate() -> None:
    report = build_research_to_decision(load_fixture("catalog_no_return_address.json"), base_dir=FIXTURES)
    offer = report["appendix"]["supplier_offers"][0]
    assert offer["returns"]["address"] == "unknown"
    assert "return_address_missing" in offer["issues"]
    assert offer["status"] == "quarantined"


def test_conflicting_quotes_and_currency_mismatch_fail_closed() -> None:
    report = build_research_to_decision(load_fixture("conflicting_quotes.json"), base_dir=FIXTURES)
    offers = report["appendix"]["supplier_offers"]
    assert len(offers) == 2
    assert {offer["status"] for offer in offers} == {"quarantined"}
    assert all("conflicting_offer" in offer["issues"] for offer in offers)
    assert all(audit["supplier_offers_accepted"] == 0 for audit in report["appendix"]["input_audit"] if audit["role"] == "supplier")
    assert report["appendix"]["candidate_audit"][0]["risk_state"] == "blocked"
    with pytest.raises(ResearchToDecisionError, match="currency mismatch"):
        build_research_to_decision(load_fixture("usd_quote.json"), base_dir=FIXTURES)


def test_pdf_derived_manual_evidence_requires_terms_and_freshness(tmp_path: Path) -> None:
    evidence = tmp_path / "quote.json"
    evidence.write_text(
        json.dumps(
            {
                "candidate_id": "pdf-candidate",
                "source": "supplier-quote.pdf",
                "source_reference": "supplier-quote.pdf",
                "extraction_method": "manual_pdf_review",
                "supplier_sku": "PDF-01",
                "destination_country": "Mexico",
                "currency": "MXN",
                "captured_at": "2026-09-16T09:00:00-06:00",
                "expires_at": "2027-01-01T00:00:00Z",
                "evidence_state": "manual",
                "confidence": 0.8,
                "terms": "quote terms reviewed",
                "returns": "return address pending",
                "warranty": "warranty text reviewed",
                "support": "support owner pending",
                "delivery": "7-12 days",
                "permissions": "dropshipping permission pending",
            }
        ),
        encoding="utf-8",
    )
    manifest = {"captured_at": "2026-09-16T09:00:00-06:00", "lane": dict(LANE), "candidates": [{"candidate_id": "pdf-candidate", "lifecycle_state": "candidate"}], "observation_inputs": [{"path": "quote.json", "kind": "pdf_derived"}]}
    report = build_research_to_decision(manifest, base_dir=tmp_path)
    assert report["appendix"]["input_audit"][0]["kind"] == "pdf_derived"
    assert report["appendix"]["input_audit"][0]["extraction_methods"] == ["manual_pdf_review"]
    assert report["appendix"]["input_audit"][0]["evidence_refs"][0].startswith("evidence:")

    evidence.write_text(json.dumps({"candidate_id": "pdf-candidate", "source": "supplier-quote.pdf"}), encoding="utf-8")
    with pytest.raises(ResearchToDecisionError, match="pdf_derived evidence is missing"):
        build_research_to_decision(manifest, base_dir=tmp_path)


def test_consumer_attention_does_not_become_supplier_proof() -> None:
    report = build_research_to_decision(load_fixture("b2b_insufficient_data.json"), base_dir=FIXTURES)
    audit = report["appendix"]["candidate_audit"][0]
    assert audit["supplier_offers"] == []
    assert "supplier_offer_evidence_missing" in audit["hard_gates"]
    assert "supplier_evidence_missing" in report["appendix"]["validation"]["warnings"]


def test_missing_supplier_evidence_is_explicitly_hold_for_review() -> None:
    report = build_research_to_decision(load_fixture("b2b_insufficient_data.json"), base_dir=FIXTURES)
    validation = report["appendix"]["validation"]
    assert "supplier_evidence_missing" in validation["warnings"]
    assert "marketplace_evidence_missing" in validation["warnings"]
    assert "consumer_attention_evidence_missing" in validation["warnings"]


def test_reviewed_url_observation_is_summarized_without_raw_url(tmp_path: Path) -> None:
    observation = tmp_path / "review.json"
    observation.write_text(json.dumps({"candidate_id": "x", "url": "https://example.test/item?token=not-kept"}), encoding="utf-8")
    manifest = {
        "captured_at": "2026-09-16T09:00:00-06:00",
        "lane": dict(LANE),
        "candidates": [{"candidate_id": "x"}],
        "observation_inputs": [{"path": "review.json", "kind": "reviewed_url"}],
    }
    report = build_research_to_decision(manifest, base_dir=tmp_path)
    assert report["appendix"]["input_audit"][0]["kind"] == "reviewed_url"
    assert "example.test" not in json.dumps(report)


@pytest.mark.parametrize("source_reference", ["../private.json", "https://example.test/quote?token=hidden"])
def test_explicit_source_references_reject_traversal_and_query_strings(source_reference: str) -> None:
    manifest = load_fixture("hydroponics_promising.json")
    manifest["supplier_inputs"][0]["source_reference"] = source_reference
    with pytest.raises(ResearchToDecisionError, match="safe reference|query or fragment"):
        build_research_to_decision(manifest, base_dir=FIXTURES)


@pytest.mark.parametrize(
    ("manifest_patch", "expected"),
    [
        ({"captured_at": "2026-09-16T09:00:00"}, "timezone"),
        ({"lane": {**LANE, "currency": "ZZZ"}}, "unsupported currency"),
        ({"lane": {**LANE, "destination_country": "unsupported"}}, "unsupported"),
    ],
)
def test_manifest_rejects_unsafe_lane_or_capture_time(manifest_patch: dict, expected: str) -> None:
    manifest = load_fixture("b2b_insufficient_data.json")
    manifest.update(manifest_patch)
    with pytest.raises(ResearchToDecisionError, match=expected):
        build_research_to_decision(manifest, base_dir=FIXTURES)


def test_secret_html_duplicate_and_traversal_inputs_fail_closed(tmp_path: Path) -> None:
    secret = tmp_path / "secret.json"
    secret.write_text(json.dumps({"candidate_id": "x", "api_key": "sk_test_nope"}), encoding="utf-8")
    manifest = {
        "captured_at": "2026-09-16T09:00:00-06:00",
        "lane": dict(LANE),
        "candidates": [{"candidate_id": "x"}],
        "supplier_inputs": [{"path": "secret.json"}],
    }
    with pytest.raises(ResearchToDecisionError, match="secret-like"):
        build_research_to_decision(manifest, base_dir=tmp_path)

    html = tmp_path / "page.json"
    html.write_text("<html>not an evidence packet</html>", encoding="utf-8")
    manifest["supplier_inputs"] = [{"path": "page.json"}]
    with pytest.raises(ResearchToDecisionError, match="HTML"):
        build_research_to_decision(manifest, base_dir=tmp_path)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(json.dumps([{"candidate_id": "x"}, {"candidate_id": "x"}]), encoding="utf-8")
    manifest["supplier_inputs"] = [{"path": "duplicate.json"}]
    with pytest.raises(ResearchToDecisionError, match="duplicate"):
        build_research_to_decision(manifest, base_dir=tmp_path)

    manifest["supplier_inputs"] = [{"path": "..\\outside.json"}]
    with pytest.raises(ResearchToDecisionError, match="relative"):
        build_research_to_decision(manifest, base_dir=tmp_path)


def test_currency_and_destination_mismatch_fail_closed(tmp_path: Path) -> None:
    evidence = tmp_path / "supplier.json"
    evidence.write_text(json.dumps({"candidate_id": "x", "supplier": "manual", "offer_id": "offer-x", "supplier_sku": "SKU-X", "currency": "USD", "destination_region": "Canada"}), encoding="utf-8")
    manifest = {
        "captured_at": "2026-09-16T09:00:00-06:00",
        "lane": dict(LANE),
        "candidates": [{"candidate_id": "x"}],
        "supplier_inputs": [{"path": "supplier.json"}],
    }
    with pytest.raises(ResearchToDecisionError, match="currency mismatch"):
        build_research_to_decision(manifest, base_dir=tmp_path)


def test_conflicting_same_identity_across_inputs_fails_closed(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    base = {"candidate_id": "x", "supplier": "manual", "offer_id": "offer-x", "supplier_sku": "SKU-1", "currency": "MXN", "destination_region": "Mexico", "unit_cost": 10}
    first.write_text(json.dumps(base), encoding="utf-8")
    second.write_text(json.dumps({**base, "unit_cost": 12}), encoding="utf-8")
    manifest = {
        "captured_at": "2026-09-16T09:00:00-06:00",
        "lane": dict(LANE),
        "candidates": [{"candidate_id": "x"}],
        "supplier_inputs": [{"path": "first.json"}, {"path": "second.json"}],
    }
    report = build_research_to_decision(manifest, base_dir=tmp_path)
    offers = report["appendix"]["supplier_offers"]
    assert len(offers) == 2
    assert all(offer["status"] == "quarantined" for offer in offers)
    assert all("conflicting_offer" in offer["issues"] for offer in offers)

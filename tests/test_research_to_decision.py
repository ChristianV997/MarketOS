"""Focused tests for the bounded offline research-to-decision seam."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
import types
from pathlib import Path

import pytest

import scripts.research_to_decision as rtd
from scripts.research_to_decision import (
    ResearchToDecisionError,
    _open_verified_evidence_file,
    _open_verified_evidence_file_windows,
    _WIN32_FILE_ATTRIBUTE_DIRECTORY,
    _WIN32_FILE_ATTRIBUTE_REPARSE_POINT,
    _WIN32_INVALID_HANDLE_VALUE,
    build_research_to_decision,
    main,
)


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
        "sample_required",
        "direct_ship_required",
        "promotion_blocked",
        "launch_authorized_false",
    }
    assert "supplier_documented" not in {item["next_state"] for item in transitions}
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


# ---------------------------------------------------------------------------
# Manual quotation/form intake (lane SUPPLIER-MANUAL-QUOTE-EVIDENCE-INTAKE-V1):
# a human-transcribed quote must never earn supplier_documented merely by
# filling in terms/policy text -- only a genuine document reference AND an
# external local operator attestation for that exact offer/SKU/reference can
# unlock the manual-import state.
# ---------------------------------------------------------------------------

def _manual_quote_manifest(
    tmp_path: Path,
    offer: dict,
    *,
    candidate_id: str = "quote-candidate",
    file_format: str = "json",
) -> dict:
    evidence = tmp_path / f"quote.{file_format}"
    row = {"candidate_id": candidate_id, **offer}
    if file_format == "csv":
        with evidence.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)
    else:
        evidence.write_text(json.dumps(row), encoding="utf-8")
    return {
        "captured_at": "2026-09-16T09:00:00-06:00",
        "lane": dict(LANE),
        "candidates": [{"candidate_id": candidate_id}],
        "supplier_inputs": [{"path": evidence.name}],
    }


def _base_hydroponics_quote() -> dict:
    return {
        "supplier": "manual",
        "offer_id": "HYD-Q-01",
        "supplier_sku": "HYD-Q-01-SKU",
        "currency": "MXN",
        "destination_region": "Mexico",
        "unit_cost": 32,
        "shipping_cost": 9,
        "delivery_min_days": 8,
        "delivery_max_days": 13,
        "extraction_method": "manual_pdf_review",
        "confidence": 0.75,
        "contract_evidence": "hand-transcribed from supplier PDF quote",
        "policy_evidence": "return and refund terms transcribed from the same PDF",
        "return_address": "Mexico return hub",
        "return_cost_payer": "supplier",
        "warranty": "12 months, supplier-handled",
        "rma_process": "email supplier RMA desk",
        "support_owner": "supplier support",
        "support_response_sla_hours": 48,
        "dropshipping_permission": "confirmed in PDF",
    }


def test_hydroponics_manual_quote_form_without_human_confirmation_caps_at_supplier_claimed(tmp_path: Path) -> None:
    """A hand-transcribed hydroponics quote with full terms/policy text but no
    document reference and no human_confirmed stays a claim, not a document."""
    offer = _base_hydroponics_quote()
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="hydroponics-quote")
    report = build_research_to_decision(manifest, base_dir=tmp_path)
    audit = report["appendix"]["candidate_audit"][0]
    states = {item["next_state"] for item in audit["promotion_lifecycle"]}
    assert "supplier_claimed" in states
    assert "supplier_documented" not in states
    blocking = {condition for item in audit["promotion_lifecycle"] for condition in item["blocking_conditions"]}
    assert "supplier_offer:human_review_or_document_reference_missing" in blocking
    offer_record = report["appendix"]["supplier_offers"][0]
    assert offer_record["evidence"]["human_confirmed"] is False
    assert offer_record["evidence"]["document_reference_provided"] is False


def test_supplier_json_cannot_self_attest_document_review(tmp_path: Path) -> None:
    """A supplier-controlled JSON reference and boolean remain source claims."""
    offer = _base_hydroponics_quote()
    offer.update({
        "offer_id": "PET-Q-01",
        "supplier_sku": "PET-Q-01-SKU",
        "source_reference": "manual:smart-pet-feeder-quote.pdf",
        "human_confirmed": True,
        "evidence_state": "observed",
    })
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="smart-pet-quote")
    report = build_research_to_decision(manifest, base_dir=tmp_path)
    audit = report["appendix"]["candidate_audit"][0]
    states = {item["next_state"] for item in audit["promotion_lifecycle"]}
    assert "supplier_claimed" in states
    assert "supplier_documented" not in states
    offer_record = report["appendix"]["supplier_offers"][0]
    assert offer_record["evidence"]["human_confirmed"] is False
    assert offer_record["evidence"]["supplier_claimed_human_confirmation"] is True
    assert offer_record["evidence"]["state"] == "fixture"
    assert offer_record["evidence"]["source_claimed_state"] == "observed"
    assert offer_record["evidence"]["document_reference_provided"] is True
    assert offer_record["evidence"]["reference_id"].startswith("evidence:")


def test_fixture_json_stays_at_fixture_ceiling_after_operator_confirmation(tmp_path: Path) -> None:
    offer = _base_hydroponics_quote()
    offer.update({
        "offer_id": "PET-FIXTURE-01",
        "supplier_sku": "PET-FIXTURE-01-SKU",
        "source_reference": "manual:smart-pet-feeder-quote.pdf",
    })
    manifest = _manual_quote_manifest(tmp_path, offer, file_format="json")
    report = build_research_to_decision(
        manifest,
        base_dir=tmp_path,
        operator_confirmed_supplier_documents=[
            ("PET-FIXTURE-01", "PET-FIXTURE-01-SKU", "manual:smart-pet-feeder-quote.pdf")
        ],
    )
    states = {item["next_state"] for item in report["appendix"]["candidate_audit"][0]["promotion_lifecycle"]}
    offer_record = report["appendix"]["supplier_offers"][0]
    assert "supplier_documented" not in states
    assert offer_record["evidence"]["state"] == "fixture"
    assert offer_record["evidence"]["human_confirmed"] is True


def test_supplier_csv_cannot_self_attest_document_review(tmp_path: Path) -> None:
    offer = _base_hydroponics_quote()
    offer.update({
        "offer_id": "PET-CSV-01",
        "supplier_sku": "PET-CSV-01-SKU",
        "source_reference": "manual:smart-pet-feeder-quote.pdf",
        "human_confirmed": "true",
        "evidence_state": "observed",
    })
    manifest = _manual_quote_manifest(tmp_path, offer, file_format="csv")
    report = build_research_to_decision(manifest, base_dir=tmp_path)
    states = {item["next_state"] for item in report["appendix"]["candidate_audit"][0]["promotion_lifecycle"]}
    offer_record = report["appendix"]["supplier_offers"][0]
    assert "supplier_documented" not in states
    assert offer_record["evidence"]["human_confirmed"] is False
    assert offer_record["evidence"]["supplier_claimed_human_confirmation"] is True
    assert offer_record["evidence"]["state"] == "manual"
    assert offer_record["evidence"]["source_claimed_state"] == "observed"


def test_local_operator_attestation_is_bound_to_exact_offer_sku_and_reference(tmp_path: Path) -> None:
    offer = _base_hydroponics_quote()
    offer.update({
        "offer_id": "PET-Q-01",
        "supplier_sku": "PET-Q-01-SKU",
        "source_reference": "manual:smart-pet-feeder-quote.pdf",
        "human_confirmed": True,
    })
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="smart-pet-quote", file_format="csv")
    report = build_research_to_decision(
        manifest,
        base_dir=tmp_path,
        operator_confirmed_supplier_documents=[("PET-Q-01", "PET-Q-01-SKU", "manual:smart-pet-feeder-quote.pdf")],
    )
    audit = report["appendix"]["candidate_audit"][0]
    states = {item["next_state"] for item in audit["promotion_lifecycle"]}
    offer_record = report["appendix"]["supplier_offers"][0]
    assert "supplier_documented" in states
    assert offer_record["evidence"]["state"] == "manual"
    assert offer_record["evidence"]["human_confirmed"] is True
    assert offer_record["evidence"]["human_confirmation_source"] == "operator_input"
    assert offer_record["evidence"]["supplier_claimed_human_confirmation"] is True


def test_cli_operator_confirmation_is_separate_from_imported_quote(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    offer = _base_hydroponics_quote()
    offer.update({
        "offer_id": "PET-CLI-01",
        "supplier_sku": "PET-CLI-01-SKU",
        "source_reference": "manual:smart-pet-feeder-quote.pdf",
        "human_confirmed": True,
    })
    manifest = _manual_quote_manifest(tmp_path, offer, file_format="csv")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = main([
        "--manifest", str(manifest_path),
        "--confirm-supplier-document", "PET-CLI-01", "PET-CLI-01-SKU", "manual:smart-pet-feeder-quote.pdf",
        "--json",
    ])

    assert result == 0
    report = json.loads(capsys.readouterr().out)
    states = {
        item["next_state"]
        for item in report["appendix"]["candidate_audit"][0]["promotion_lifecycle"]
    }
    assert "supplier_documented" in states
    assert report["appendix"]["supplier_offers"][0]["evidence"]["human_confirmation_source"] == "operator_input"


@pytest.mark.parametrize(
    "confirmation",
    [
        ("OTHER-OFFER", "PET-Q-01-SKU", "manual:smart-pet-feeder-quote.pdf"),
        ("PET-Q-01", "OTHER-SKU", "manual:smart-pet-feeder-quote.pdf"),
        ("PET-Q-01", "PET-Q-01-SKU", "manual:other-quote.pdf"),
    ],
)
def test_operator_confirmation_must_match_exact_sku_and_document_reference(
    tmp_path: Path, confirmation: tuple[str, str, str]
) -> None:
    offer = _base_hydroponics_quote()
    offer.update({
        "offer_id": "PET-Q-01",
        "supplier_sku": "PET-Q-01-SKU",
        "source_reference": "manual:smart-pet-feeder-quote.pdf",
    })
    manifest = _manual_quote_manifest(tmp_path, offer, file_format="csv")
    report = build_research_to_decision(
        manifest,
        base_dir=tmp_path,
        operator_confirmed_supplier_documents=[confirmation],
    )
    states = {item["next_state"] for item in report["appendix"]["candidate_audit"][0]["promotion_lifecycle"]}
    assert "supplier_documented" not in states


def test_supplier_import_preserves_explicit_zero_costs_as_manual_values(tmp_path: Path) -> None:
    offer = _base_hydroponics_quote()
    offer.update({"unit_cost": 0, "shipping_cost": 0})
    manifest = _manual_quote_manifest(tmp_path, offer, file_format="csv")
    report = build_research_to_decision(manifest, base_dir=tmp_path)
    normalized = report["appendix"]["supplier_offers"][0]
    assert normalized["price"]["amount"] == 0
    assert normalized["shipping"]["cost"] == 0
    assert normalized["evidence"]["state"] == "manual"


def test_manual_quote_form_rejects_a_malformed_human_confirmed_value(tmp_path: Path) -> None:
    offer = _base_hydroponics_quote()
    offer["human_confirmed"] = "maybe"
    manifest = _manual_quote_manifest(tmp_path, offer)
    with pytest.raises(ResearchToDecisionError, match="human_confirmed must be a boolean"):
        build_research_to_decision(manifest, base_dir=tmp_path)


def test_manual_quote_form_missing_sku_is_rejected_with_an_actionable_error(tmp_path: Path) -> None:
    offer = _base_hydroponics_quote()
    del offer["supplier_sku"]
    manifest = _manual_quote_manifest(tmp_path, offer)
    with pytest.raises(ResearchToDecisionError, match="supplier offer identity requires offer_id and exact supplier_sku"):
        build_research_to_decision(manifest, base_dir=tmp_path)


def test_manual_quote_form_missing_support_owner_is_a_quarantine_issue(tmp_path: Path) -> None:
    offer = _base_hydroponics_quote()
    del offer["support_owner"]
    manifest = _manual_quote_manifest(tmp_path, offer)
    report = build_research_to_decision(manifest, base_dir=tmp_path)
    offer_record = report["appendix"]["supplier_offers"][0]
    assert offer_record["support"]["owner"] == "unknown"
    assert "support_owner_missing" in offer_record["issues"]
    assert offer_record["status"] == "quarantined"


def test_manual_quote_form_cannot_escalate_evidence_state_or_confidence_into_documentation(tmp_path: Path) -> None:
    """Claiming a strong evidence_state/confidence and human_confirmed on a
    manual, self-reported quote still cannot earn supplier_documented without
    a genuine document reference -- confirmation alone is not enough, and a
    confident self-report is not evidence."""
    offer = _base_hydroponics_quote()
    offer.update({"evidence_state": "observed", "confidence": 0.99, "human_confirmed": True})
    manifest = _manual_quote_manifest(tmp_path, offer)
    report = build_research_to_decision(manifest, base_dir=tmp_path)
    audit = report["appendix"]["candidate_audit"][0]
    states = {item["next_state"] for item in audit["promotion_lifecycle"]}
    assert "supplier_documented" not in states
    assert "live_validated" not in states
    assert "manually_approved" not in states
    offer_record = report["appendix"]["supplier_offers"][0]
    assert offer_record["evidence"]["document_reference_provided"] is False


# ---------------------------------------------------------------------------
# Document byte-integrity binding: --confirm-supplier-document-digest.
#
# This binds a manual quote reference to the *actual bytes* of a local
# evidence file (a real sha256 of file content, resolved only under an
# explicit --supplier-evidence-root). It is a distinct signal from
# human_confirmed (an operator's textual attestation) and from
# evidence_state/promotion (which never advance past supplier_documented
# here): a verified digest proves the referenced file wasn't altered/
# substituted since the operator looked at it, nothing about the
# supplier's identity or a real transaction.
# ---------------------------------------------------------------------------

_SYNTHETIC_QUOTE_BYTES = b"SYNTHETIC TEST QUOTE - not a real supplier document - HYD-DOC-01"


def _write_evidence_document(root: Path, name: str, content: bytes = _SYNTHETIC_QUOTE_BYTES) -> tuple[Path, str]:
    root.mkdir(parents=True, exist_ok=True)
    doc = root / name
    doc.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    return doc, digest


def test_document_digest_binding_confirms_byte_integrity_independent_of_human_confirmed(tmp_path: Path) -> None:
    """A verified content digest and an operator's human_confirmed
    attestation are independent signals -- one without the other proves
    only its own thing, and the promotion ceiling stays exactly where it
    was before either existed."""
    evidence_root = tmp_path / "evidence"
    _, digest = _write_evidence_document(evidence_root, "hyd-quote.pdf")
    offer = _base_hydroponics_quote()
    offer.update({"offer_id": "HYD-DOC-01", "supplier_sku": "HYD-DOC-01-SKU", "source_reference": "manual:hyd-quote.pdf"})
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="hyd-doc-candidate", file_format="csv")

    # Digest verified, but never separately human-confirmed: still supplier_claimed.
    report = build_research_to_decision(
        manifest,
        base_dir=tmp_path,
        supplier_evidence_root=evidence_root,
        confirmed_supplier_document_evidence=[("HYD-DOC-01", "HYD-DOC-01-SKU", "manual:hyd-quote.pdf", digest)],
    )
    offer_record = report["appendix"]["supplier_offers"][0]
    states = {item["next_state"] for item in report["appendix"]["candidate_audit"][0]["promotion_lifecycle"]}
    assert offer_record["evidence"]["document_bytes_confirmed"] is True
    assert offer_record["evidence"]["document_digest"] == digest
    assert offer_record["evidence"]["document_size_bytes"] == len(_SYNTHETIC_QUOTE_BYTES)
    assert offer_record["evidence"]["human_confirmed"] is False
    assert "supplier_documented" not in states

    # Both digest and human confirmation present: reaches supplier_documented,
    # but never anything beyond it -- byte integrity plus an operator's
    # review is still not supplier identity or a live transaction.
    report2 = build_research_to_decision(
        manifest,
        base_dir=tmp_path,
        supplier_evidence_root=evidence_root,
        confirmed_supplier_document_evidence=[("HYD-DOC-01", "HYD-DOC-01-SKU", "manual:hyd-quote.pdf", digest)],
        operator_confirmed_supplier_documents=[("HYD-DOC-01", "HYD-DOC-01-SKU", "manual:hyd-quote.pdf")],
    )
    offer_record2 = report2["appendix"]["supplier_offers"][0]
    states2 = {item["next_state"] for item in report2["appendix"]["candidate_audit"][0]["promotion_lifecycle"]}
    assert offer_record2["evidence"]["document_bytes_confirmed"] is True
    assert offer_record2["evidence"]["human_confirmed"] is True
    assert "supplier_documented" in states2
    assert "supplier_validated" not in states2
    assert "live_validated" not in states2
    assert "manually_approved" not in states2


def test_document_digest_mismatch_is_rejected_fail_closed(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    _write_evidence_document(evidence_root, "hyd-quote.pdf")
    offer = _base_hydroponics_quote()
    offer.update({"offer_id": "HYD-DOC-02", "supplier_sku": "HYD-DOC-02-SKU", "source_reference": "manual:hyd-quote.pdf"})
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="hyd-doc-2")
    wrong_digest = "0" * 64
    with pytest.raises(ResearchToDecisionError, match="digest mismatch"):
        build_research_to_decision(
            manifest,
            base_dir=tmp_path,
            supplier_evidence_root=evidence_root,
            confirmed_supplier_document_evidence=[("HYD-DOC-02", "HYD-DOC-02-SKU", "hyd-quote.pdf", wrong_digest)],
        )


def test_document_digest_binding_rejects_path_traversal(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(_SYNTHETIC_QUOTE_BYTES)
    digest = hashlib.sha256(_SYNTHETIC_QUOTE_BYTES).hexdigest()
    offer = _base_hydroponics_quote()
    offer.update({"offer_id": "HYD-DOC-03", "supplier_sku": "HYD-DOC-03-SKU", "source_reference": "manual:../outside.pdf"})
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="hyd-doc-3")
    with pytest.raises(ResearchToDecisionError):
        build_research_to_decision(
            manifest,
            base_dir=tmp_path,
            supplier_evidence_root=evidence_root,
            confirmed_supplier_document_evidence=[("HYD-DOC-03", "HYD-DOC-03-SKU", "../outside.pdf", digest)],
        )


def test_document_digest_binding_rejects_a_nul_byte_in_the_reference(tmp_path: Path) -> None:
    """A NUL byte in document_evidence.reference must be rejected as a
    clean ResearchToDecisionError, not surface an unhandled ValueError.
    Path.resolve() raises ValueError("embedded null byte") deep inside
    posixpath's realpath -- reproduced directly before this test existed.
    Not a containment bypass (nothing is ever read), but an unhandled
    exception breaks this module's fail-closed contract, which every
    other rejection honors via ResearchToDecisionError."""
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    offer = _base_hydroponics_quote()
    offer.update({"offer_id": "HYD-DOC-07", "supplier_sku": "HYD-DOC-07-SKU", "source_reference": "manual:evil\x00.pdf"})
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="hyd-doc-7")
    with pytest.raises(ResearchToDecisionError, match="safe reference"):
        build_research_to_decision(
            manifest,
            base_dir=tmp_path,
            supplier_evidence_root=evidence_root,
            confirmed_supplier_document_evidence=[("HYD-DOC-07", "HYD-DOC-07-SKU", "manual:evil\x00.pdf", "0" * 64)],
        )


def test_supplier_input_path_rejects_a_nul_byte(tmp_path: Path) -> None:
    """The same NUL-byte-crashes-Path.resolve() class of bug reproduced
    via _resolve() directly (supplier_inputs.path), which shares _resolve
    with document_evidence.reference and observation_inputs.path -- the
    fix belongs in _resolve() itself, not only in the document-evidence
    reference validator, since all three call sites share it."""
    manifest = {
        "captured_at": "2026-09-16T09:00:00-06:00",
        "lane": dict(LANE),
        "candidates": [{"candidate_id": "nul-byte-candidate"}],
        "supplier_inputs": [{"path": "evil\x00.json"}],
    }
    with pytest.raises(ResearchToDecisionError, match="NUL byte"):
        build_research_to_decision(manifest, base_dir=tmp_path)


def _create_symlink_or_simulate(monkeypatch: pytest.MonkeyPatch, link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError):
        # Windows runners without Developer Mode or symlink privilege cannot
        # create a link. Simulate the filesystem's symlink observation so the
        # production rejection path is still executed rather than skipped.
        is_symlink = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda path: path == link or is_symlink(path))


def test_document_digest_binding_rejects_symlink_escaping_the_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A symlink inside the evidence root pointing outside it must never
    resolve -- caught by the same root-containment check the manifest path
    resolver already uses."""
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(_SYNTHETIC_QUOTE_BYTES)
    link = evidence_root / "link.pdf"
    _create_symlink_or_simulate(monkeypatch, link, outside)
    digest = hashlib.sha256(_SYNTHETIC_QUOTE_BYTES).hexdigest()
    offer = _base_hydroponics_quote()
    offer.update({"offer_id": "HYD-DOC-04", "supplier_sku": "HYD-DOC-04-SKU", "source_reference": "manual:link.pdf"})
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="hyd-doc-4")
    with pytest.raises(ResearchToDecisionError, match="symlink"):
        build_research_to_decision(
            manifest,
            base_dir=tmp_path,
            supplier_evidence_root=evidence_root,
            confirmed_supplier_document_evidence=[("HYD-DOC-04", "HYD-DOC-04-SKU", "manual:link.pdf", digest)],
        )


def test_document_digest_binding_rejects_symlink_within_the_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A symlink that stays inside the evidence root (so the root-
    containment check alone would not catch it) must still be rejected --
    a symlink is never treated as the evidence file itself."""
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    real_file, digest = _write_evidence_document(evidence_root, "real.pdf")
    link = evidence_root / "link.pdf"
    _create_symlink_or_simulate(monkeypatch, link, real_file)
    offer = _base_hydroponics_quote()
    offer.update({"offer_id": "HYD-DOC-04B", "supplier_sku": "HYD-DOC-04B-SKU", "source_reference": "manual:link.pdf"})
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="hyd-doc-4b")
    with pytest.raises(ResearchToDecisionError, match="symlink"):
        build_research_to_decision(
            manifest,
            base_dir=tmp_path,
            supplier_evidence_root=evidence_root,
            confirmed_supplier_document_evidence=[("HYD-DOC-04B", "HYD-DOC-04B-SKU", "manual:link.pdf", digest)],
        )


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are POSIX-only; os.mkfifo does not exist on this platform")
def test_document_digest_binding_rejects_a_named_pipe_without_hanging(tmp_path: Path) -> None:
    """The FIFO-DoS closure has direct helper-level coverage
    (``test_secure_open_rejects_a_named_pipe_without_hanging``), but that
    alone does not prove the real caller ever reaches it, and the PR
    description's claim of a live production-entrypoint FIFO reproduction
    was previously untested at this level -- this closes that gap.

    A FIFO placed statically at the reference path (as opposed to one
    swapped in mid-race) is actually rejected one layer earlier than
    ``_open_verified_evidence_file``'s O_NONBLOCK guard: ``_resolve()``
    (called first, at line ~612) uses ``Path.is_file()``, a non-blocking
    ``stat()``-based check that already reports False for a FIFO, so the
    binding never reaches the open call at all for this static placement.
    That earlier check is itself non-blocking (stat never blocks on a
    FIFO; only an actual open()/read() against one with no writer does),
    so the no-hang guarantee holds end to end -- just via a different,
    earlier check than the FIFO-specific one. The O_NONBLOCK guard in
    ``_open_verified_evidence_file`` remains real, load-bearing
    defense-in-depth for the disclosed TOCTOU case: a file swapped for a
    FIFO in the race window between ``_resolve()``'s check and the actual
    open, which a static placement like this one cannot exercise."""
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    fifo = evidence_root / "hyd-quote.pdf"
    os.mkfifo(fifo)
    offer = _base_hydroponics_quote()
    offer.update({"offer_id": "HYD-DOC-FIFO", "supplier_sku": "HYD-DOC-FIFO-SKU", "source_reference": "manual:hyd-quote.pdf"})
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="hyd-doc-fifo")
    with pytest.raises(ResearchToDecisionError, match="does not exist"):
        build_research_to_decision(
            manifest,
            base_dir=tmp_path,
            supplier_evidence_root=evidence_root,
            confirmed_supplier_document_evidence=[("HYD-DOC-FIFO", "HYD-DOC-FIFO-SKU", "hyd-quote.pdf", "0" * 64)],
        )


def test_document_digest_binding_rejects_oversized_file(tmp_path: Path) -> None:
    from scripts.research_to_decision import MAX_EVIDENCE_DOCUMENT_BYTES

    evidence_root = tmp_path / "evidence"
    oversized = b"x" * (MAX_EVIDENCE_DOCUMENT_BYTES + 1)
    _, digest = _write_evidence_document(evidence_root, "hyd-quote.pdf", oversized)
    offer = _base_hydroponics_quote()
    offer.update({"offer_id": "HYD-DOC-05", "supplier_sku": "HYD-DOC-05-SKU", "source_reference": "manual:hyd-quote.pdf"})
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="hyd-doc-5")
    with pytest.raises(ResearchToDecisionError, match="exceeds"):
        build_research_to_decision(
            manifest,
            base_dir=tmp_path,
            supplier_evidence_root=evidence_root,
            confirmed_supplier_document_evidence=[("HYD-DOC-05", "HYD-DOC-05-SKU", "hyd-quote.pdf", digest)],
        )


def test_document_digest_binding_rejects_duplicate_keys(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    _, digest_a = _write_evidence_document(evidence_root, "a.pdf", b"first synthetic document")
    _, digest_b = _write_evidence_document(evidence_root, "b.pdf", b"second synthetic document")
    offer = _base_hydroponics_quote()
    offer.update({"offer_id": "HYD-DOC-06", "supplier_sku": "HYD-DOC-06-SKU", "source_reference": "manual:a.pdf"})
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="hyd-doc-6")
    with pytest.raises(ResearchToDecisionError, match="duplicate"):
        build_research_to_decision(
            manifest,
            base_dir=tmp_path,
            supplier_evidence_root=evidence_root,
            confirmed_supplier_document_evidence=[
                ("HYD-DOC-06", "HYD-DOC-06-SKU", "a.pdf", digest_a),
                ("HYD-DOC-06", "HYD-DOC-06-SKU", "b.pdf", digest_b),
            ],
        )


def test_document_digest_binding_rejects_unsupported_format(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    _, digest = _write_evidence_document(evidence_root, "hyd-quote.exe")
    offer = _base_hydroponics_quote()
    offer.update({"offer_id": "HYD-DOC-07", "supplier_sku": "HYD-DOC-07-SKU", "source_reference": "manual:hyd-quote.exe"})
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="hyd-doc-7")
    with pytest.raises(ResearchToDecisionError, match="unsupported format"):
        build_research_to_decision(
            manifest,
            base_dir=tmp_path,
            supplier_evidence_root=evidence_root,
            confirmed_supplier_document_evidence=[("HYD-DOC-07", "HYD-DOC-07-SKU", "hyd-quote.exe", digest)],
        )


def test_document_digest_binding_requires_evidence_root(tmp_path: Path) -> None:
    offer = _base_hydroponics_quote()
    offer.update({"offer_id": "HYD-DOC-08", "supplier_sku": "HYD-DOC-08-SKU", "source_reference": "manual:hyd-quote.pdf"})
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="hyd-doc-8")
    digest = hashlib.sha256(_SYNTHETIC_QUOTE_BYTES).hexdigest()
    with pytest.raises(ResearchToDecisionError, match="evidence root"):
        build_research_to_decision(
            manifest,
            base_dir=tmp_path,
            confirmed_supplier_document_evidence=[("HYD-DOC-08", "HYD-DOC-08-SKU", "hyd-quote.pdf", digest)],
        )


def test_document_digest_binding_rejects_malformed_digest(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    _write_evidence_document(evidence_root, "hyd-quote.pdf")
    offer = _base_hydroponics_quote()
    offer.update({"offer_id": "HYD-DOC-09", "supplier_sku": "HYD-DOC-09-SKU", "source_reference": "manual:hyd-quote.pdf"})
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="hyd-doc-9")
    with pytest.raises(ResearchToDecisionError, match="64-character hex"):
        build_research_to_decision(
            manifest,
            base_dir=tmp_path,
            supplier_evidence_root=evidence_root,
            confirmed_supplier_document_evidence=[("HYD-DOC-09", "HYD-DOC-09-SKU", "hyd-quote.pdf", "not-a-digest")],
        )


def test_document_digest_binding_does_not_attach_if_reference_does_not_match_offer(tmp_path: Path) -> None:
    """A valid, verified binding for a *different* reference string than the
    one the offer actually declares must never attach -- offer identity,
    exact SKU, and reference must all agree together."""
    evidence_root = tmp_path / "evidence"
    _, digest = _write_evidence_document(evidence_root, "hyd-quote.pdf")
    offer = _base_hydroponics_quote()
    offer.update({"offer_id": "HYD-DOC-10", "supplier_sku": "HYD-DOC-10-SKU", "source_reference": "manual:a-different-reference.pdf"})
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="hyd-doc-10")
    report = build_research_to_decision(
        manifest,
        base_dir=tmp_path,
        supplier_evidence_root=evidence_root,
        confirmed_supplier_document_evidence=[("HYD-DOC-10", "HYD-DOC-10-SKU", "hyd-quote.pdf", digest)],
    )
    offer_record = report["appendix"]["supplier_offers"][0]
    assert offer_record["evidence"]["document_bytes_confirmed"] is False
    assert offer_record["evidence"]["document_digest"] is None


def test_document_digest_binding_never_appears_in_report_as_raw_content(tmp_path: Path) -> None:
    """Only the digest, size, and boolean confirmation status ever appear in
    the report -- never the underlying bytes."""
    evidence_root = tmp_path / "evidence"
    secret_content = b"SYNTHETIC-QUOTE-MARKER-should-never-leak-into-report"
    _, digest = _write_evidence_document(evidence_root, "hyd-quote.pdf", secret_content)
    offer = _base_hydroponics_quote()
    offer.update({"offer_id": "HYD-DOC-11", "supplier_sku": "HYD-DOC-11-SKU", "source_reference": "manual:hyd-quote.pdf"})
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="hyd-doc-11")
    report = build_research_to_decision(
        manifest,
        base_dir=tmp_path,
        supplier_evidence_root=evidence_root,
        confirmed_supplier_document_evidence=[("HYD-DOC-11", "HYD-DOC-11-SKU", "manual:hyd-quote.pdf", digest)],
    )
    serialized = json.dumps(report)
    assert secret_content.decode() not in serialized
    assert digest in serialized


def test_cli_document_digest_confirmation_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    evidence_root = tmp_path / "evidence"
    _, digest = _write_evidence_document(evidence_root, "hyd-quote.pdf")
    offer = _base_hydroponics_quote()
    offer.update({"offer_id": "HYD-DOC-12", "supplier_sku": "HYD-DOC-12-SKU", "source_reference": "manual:hyd-quote.pdf"})
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="hyd-doc-12", file_format="csv")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = main([
        "--manifest", str(manifest_path),
        "--confirm-supplier-document", "HYD-DOC-12", "HYD-DOC-12-SKU", "manual:hyd-quote.pdf",
        "--supplier-evidence-root", str(evidence_root),
        "--confirm-supplier-document-digest", "HYD-DOC-12", "HYD-DOC-12-SKU", "manual:hyd-quote.pdf", digest,
        "--json",
    ])

    assert result == 0
    report = json.loads(capsys.readouterr().out)
    offer_record = report["appendix"]["supplier_offers"][0]
    assert offer_record["evidence"]["human_confirmed"] is True
    assert offer_record["evidence"]["document_bytes_confirmed"] is True
    states = {item["next_state"] for item in report["appendix"]["candidate_audit"][0]["promotion_lifecycle"]}
    assert "supplier_documented" in states
    assert "supplier_validated" not in states
    assert "live_validated" not in states


def test_document_digest_confirmation_omitted_reproduces_prior_behavior_exactly(tmp_path: Path) -> None:
    """#279's consumer calls build_research_to_decision without either new
    parameter -- confirm that path is byte-for-byte unaffected."""
    offer = _base_hydroponics_quote()
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="no-digest-candidate")
    report_without_new_params = build_research_to_decision(manifest, base_dir=tmp_path)
    report_with_empty_new_params = build_research_to_decision(
        manifest, base_dir=tmp_path, supplier_evidence_root=None, confirmed_supplier_document_evidence=()
    )
    assert report_without_new_params == report_with_empty_new_params


# ---------------------------------------------------------------------------
# Secure-read boundary: _open_verified_evidence_file (TOCTOU closure).
#
# These exercise the open-once/fstat-based read directly, distinct from the
# path-level tests above (path traversal, root escape, reference matching).
# The security question here is narrower and more concrete: once a path has
# already been deemed safe to resolve, does the code that turns it into
# hashed bytes ever perform a *separate* filesystem check-then-read against
# the path string (the actual TOCTOU gap), or does it validate and read the
# same open object throughout? No test here relies on real timing/sleeps --
# each one proves the property deterministically, either by exercising the
# real filesystem object type directly or by simulating "the earlier check
# didn't catch it" and confirming the open-time guarantee still holds.
# ---------------------------------------------------------------------------


def test_secure_open_accepts_a_valid_in_root_regular_file(tmp_path: Path) -> None:
    doc = tmp_path / "doc.pdf"
    doc.write_bytes(b"genuine evidence bytes")
    fd, file_stat = _open_verified_evidence_file(doc, label="x")
    try:
        assert file_stat.st_size == len(b"genuine evidence bytes")
        assert os.read(fd, 1024) == b"genuine evidence bytes"
    finally:
        os.close(fd)


def test_secure_open_rejects_a_symlinked_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "target.pdf"
    target.write_bytes(b"data")
    link = tmp_path / "link.pdf"
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("this platform/runner cannot create symlinks (no Developer Mode / privilege)")
    with pytest.raises(ResearchToDecisionError, match="symlink"):
        _open_verified_evidence_file(link, label="x")


def test_secure_open_rejects_a_directory() -> None:
    # POSIX typically opens a directory descriptor and lets fstat reject it;
    # Windows may deny os.open() before a descriptor is returned. Both paths
    # must fail closed with the public domain error.
    with pytest.raises(ResearchToDecisionError):
        _open_verified_evidence_file(Path(__file__).resolve().parent, label="x")


def test_secure_open_rejects_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ResearchToDecisionError):
        _open_verified_evidence_file(tmp_path / "does-not-exist.pdf", label="x")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are POSIX-only; os.mkfifo does not exist on this platform")
def test_secure_open_rejects_a_named_pipe_without_hanging(tmp_path: Path) -> None:
    """Non-regular-file rejection must never block: a plain blocking
    open() on a FIFO with no writer on the other end hangs forever, which
    would itself be a denial-of-service the moment a caller placed a named
    pipe inside the evidence root. This test times out (via pytest-timeout
    if installed, or simply hangs the run and is visible in CI) rather
    than silently passing if that regression is reintroduced -- it does
    not itself use a sleep/timing race, it proves the call returns at
    all."""
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(ResearchToDecisionError, match="regular file"):
        _open_verified_evidence_file(fifo, label="x")


def test_secure_open_rejects_symlink_even_when_the_pre_open_walk_check_is_bypassed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deterministic proof that the open-time guarantee does not depend on
    the caller's earlier walk-based symlink check having run correctly --
    it is a second, independent layer. Simulates "the walk-check already
    missed this" (e.g. because the file was replaced by a symlink in the
    window between that check and this open) by monkeypatching
    Path.is_symlink to always report False, then proving
    _open_verified_evidence_file itself still refuses to follow the
    symlink, via O_NOFOLLOW at open time."""
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("O_NOFOLLOW is POSIX-only -- on Windows this specific race is a disclosed, unfixed-by-stdlib limitation")
    target = tmp_path / "target.pdf"
    target.write_bytes(b"data")
    link = tmp_path / "link.pdf"
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("this platform/runner cannot create symlinks (no Developer Mode / privilege)")
    monkeypatch.setattr(Path, "is_symlink", lambda self: False)
    with pytest.raises(ResearchToDecisionError, match="symlink"):
        _open_verified_evidence_file(link, label="x")


def test_secure_open_without_o_nonblock_or_o_nofollow_still_reads_a_genuine_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulates the Windows code path on this (POSIX) test runner: with
    O_NOFOLLOW/O_NONBLOCK unavailable, a genuine in-root regular file must
    still open and read correctly -- the platform-specific denial
    behavior only removes a guarantee, it must never break the ordinary
    valid-file path."""
    monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
    monkeypatch.delattr(os, "O_NONBLOCK", raising=False)
    doc = tmp_path / "doc.pdf"
    doc.write_bytes(b"still readable without the posix-only flags")
    fd, file_stat = _open_verified_evidence_file(doc, label="x")
    try:
        assert os.read(fd, 1024) == b"still readable without the posix-only flags"
    finally:
        os.close(fd)


def test_secure_open_without_o_nofollow_relies_solely_on_the_pre_open_walk_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confirms the disclosed Windows limitation is real and precisely
    scoped: with O_NOFOLLOW simulated unavailable, _open_verified_evidence_file
    alone (i.e. without the caller's pre-open walk-check) does NOT reject a
    symlink -- proving the walk-check in _supplier_document_evidence_bindings
    is load-bearing on that platform, not redundant, and that this
    function never silently claims a guarantee it cannot provide there."""
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("already running on a platform without O_NOFOLLOW; nothing to simulate")
    monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
    target = tmp_path / "target.pdf"
    target.write_bytes(b"data")
    link = tmp_path / "link.pdf"
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("this platform/runner cannot create symlinks (no Developer Mode / privilege)")
    fd, file_stat = _open_verified_evidence_file(link, label="x")
    os.close(fd)  # reaching here at all is the point: no guarantee without O_NOFOLLOW


def test_document_digest_binding_rejects_a_symlinked_parent_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A symlinked *intermediate directory* on the path to the evidence
    file -- distinct from the file itself being a symlink -- must also be
    rejected by the per-component walk-check, which walks every path part
    including intermediate directories, not just the final component."""
    evidence_root = tmp_path / "evidence"
    real_dir = evidence_root / "real_subdir"
    real_dir.mkdir(parents=True)
    real_file = real_dir / "quote.pdf"
    real_file.write_bytes(_SYNTHETIC_QUOTE_BYTES)
    digest = hashlib.sha256(_SYNTHETIC_QUOTE_BYTES).hexdigest()
    linked_dir = evidence_root / "linked_subdir"
    try:
        linked_dir.symlink_to(real_dir, target_is_directory=True)
    except (NotImplementedError, OSError):
        is_symlink = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda path: path == linked_dir or is_symlink(path))
    offer = _base_hydroponics_quote()
    offer.update({"offer_id": "HYD-DOC-05", "supplier_sku": "HYD-DOC-05-SKU", "source_reference": "manual:linked_subdir/quote.pdf"})
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="hyd-doc-5")
    with pytest.raises(ResearchToDecisionError, match="symlink"):
        build_research_to_decision(
            manifest,
            base_dir=tmp_path,
            supplier_evidence_root=evidence_root,
            confirmed_supplier_document_evidence=[("HYD-DOC-05", "HYD-DOC-05-SKU", "manual:linked_subdir/quote.pdf", digest)],
        )


def test_document_digest_binding_rejects_reference_pointing_at_a_directory(tmp_path: Path) -> None:
    """A reference resolving to a directory rather than a file must be
    rejected, not silently mishandled. _resolve()'s own is_file() check is
    the first line of defense (raising "does not exist" for a directory,
    since is_file() is False for one) -- _open_verified_evidence_file's
    S_ISREG check is the deeper, race-closing layer for the case where a
    regular file is swapped for a directory/non-regular node *after*
    _resolve() looked at it (see the _open_verified_evidence_file-level
    tests above for that property proven directly, without _resolve() in
    the way)."""
    evidence_root = tmp_path / "evidence"
    as_dir = evidence_root / "not_a_file.pdf"
    as_dir.mkdir(parents=True)
    offer = _base_hydroponics_quote()
    offer.update({"offer_id": "HYD-DOC-06", "supplier_sku": "HYD-DOC-06-SKU", "source_reference": "manual:not_a_file.pdf"})
    manifest = _manual_quote_manifest(tmp_path, offer, candidate_id="hyd-doc-6")
    with pytest.raises(ResearchToDecisionError, match="does not exist"):
        build_research_to_decision(
            manifest,
            base_dir=tmp_path,
            supplier_evidence_root=evidence_root,
            confirmed_supplier_document_evidence=[("HYD-DOC-06", "HYD-DOC-06-SKU", "manual:not_a_file.pdf", "0" * 64)],
        )


# ---------------------------------------------------------------------------
# Windows secure-read path: _open_verified_evidence_file_windows.
#
# This sandbox is Linux; ``ctypes.WinDLL`` does not exist here at all, so the
# real Win32 syscalls (CreateFileW, GetFileInformationByHandle, CloseHandle)
# cannot be executed or verified by these tests, on this run, or in this
# repository's CI (every workflow under .github/workflows/ runs on
# ubuntu-latest only -- there is no Windows runner to fall back to). What
# CAN be verified deterministically, and is verified below, is every line of
# _open_verified_evidence_file_windows's own branching and descriptor-
# ownership logic: the fake kernel32 installed via _win32_kernel32_dll (the
# one seam that is genuinely Windows-only) drives that real Python function
# body through each path, exactly as a real CreateFileW/GetFileInformation-
# ByHandle response would. This is proof of the Python-level contract only
# -- never sleep-based, never a substitute for real Windows CI execution.
# ---------------------------------------------------------------------------


def _install_fake_win32_kernel32(
    monkeypatch: pytest.MonkeyPatch,
    *,
    create_file_result: int,
    attributes: int = 0,
    get_file_information_result: bool = True,
) -> dict[str, list]:
    calls: dict[str, list] = {"close_handle": [], "create_file": [], "get_file_information": []}

    class _FakeKernel32:
        def CreateFileW(self, *args: object) -> int:
            calls["create_file"].append(args)
            return create_file_result

        def GetFileInformationByHandle(self, handle: int, info_ptr: object) -> bool:
            calls["get_file_information"].append(handle)
            if not get_file_information_result:
                return False
            info_ptr.contents.dwFileAttributes = attributes
            return True

        def CloseHandle(self, handle: int) -> bool:
            calls["close_handle"].append(handle)
            return True

    monkeypatch.setattr(rtd, "_win32_kernel32_dll", lambda: _FakeKernel32())
    return calls


def _install_fake_msvcrt(monkeypatch: pytest.MonkeyPatch, *, open_osfhandle) -> None:
    monkeypatch.setitem(sys.modules, "msvcrt", types.SimpleNamespace(open_osfhandle=open_osfhandle))


_FAKE_WIN32_HANDLE = 4242


def test_win32_open_accepts_a_valid_in_root_regular_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Success path: CreateFileW returns a handle, the fake's attributes
    report neither a reparse point nor a directory, and the resulting fd
    (wired here to a real POSIX fd over a real file, since the fake Win32
    handle is only a sentinel int) reads the genuine bytes. CloseHandle
    must never run once ownership has transferred to the fd -- a real
    Windows double-close on the same handle is undefined behavior."""
    doc = tmp_path / "doc.pdf"
    doc.write_bytes(b"genuine windows-path evidence bytes")
    real_fd_holder: dict[str, int] = {}

    def fake_open_osfhandle(handle: int, flags: int) -> int:
        assert handle == _FAKE_WIN32_HANDLE
        assert flags & os.O_RDONLY == os.O_RDONLY
        # Explicit binary mode must always be requested -- _open_osfhandle
        # defaults to CRLF/Ctrl-Z text-mode translation without it, which
        # would silently corrupt the hashed bytes of a genuine binary
        # evidence file (see the O_BINARY comment at the call site).
        assert flags & getattr(os, "O_BINARY", 0) == getattr(os, "O_BINARY", 0)
        fd = os.open(doc, os.O_RDONLY)
        real_fd_holder["fd"] = fd
        return fd

    calls = _install_fake_win32_kernel32(monkeypatch, create_file_result=_FAKE_WIN32_HANDLE, attributes=0)
    _install_fake_msvcrt(monkeypatch, open_osfhandle=fake_open_osfhandle)
    fd, file_stat = _open_verified_evidence_file_windows(doc, label="x")
    try:
        assert fd == real_fd_holder["fd"]
        assert file_stat.st_size == len(b"genuine windows-path evidence bytes")
        assert os.read(fd, 1024) == b"genuine windows-path evidence bytes"
        assert calls["close_handle"] == []  # ownership transferred to the fd, not closed separately
    finally:
        os.close(fd)


def test_win32_open_rejects_a_final_component_reparse_point(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The Windows analogue of O_NOFOLLOW: CreateFileW with
    FILE_FLAG_OPEN_REPARSE_POINT opens the reparse point itself rather
    than following it, and GetFileInformationByHandle on that same handle
    reports FILE_ATTRIBUTE_REPARSE_POINT -- this must be rejected before
    msvcrt.open_osfhandle (i.e. before any read) ever runs, and the raw
    handle must be closed since it never became an fd."""
    doc = tmp_path / "link.pdf"
    doc.write_bytes(b"placeholder")

    def fake_open_osfhandle(*_args: object) -> int:
        raise AssertionError("must not convert a rejected reparse-point handle to an fd")

    calls = _install_fake_win32_kernel32(
        monkeypatch, create_file_result=_FAKE_WIN32_HANDLE, attributes=_WIN32_FILE_ATTRIBUTE_REPARSE_POINT
    )
    _install_fake_msvcrt(monkeypatch, open_osfhandle=fake_open_osfhandle)
    with pytest.raises(ResearchToDecisionError, match="symlink"):
        _open_verified_evidence_file_windows(doc, label="x")
    assert calls["close_handle"] == [_FAKE_WIN32_HANDLE]


def test_win32_open_rejects_a_directory_reparse_point_junction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A junction (directory reparse point) reports both
    FILE_ATTRIBUTE_REPARSE_POINT and FILE_ATTRIBUTE_DIRECTORY;
    the reparse-point check runs first and must still reject it, with
    the handle closed rather than leaked."""
    calls = _install_fake_win32_kernel32(
        monkeypatch,
        create_file_result=_FAKE_WIN32_HANDLE,
        attributes=_WIN32_FILE_ATTRIBUTE_REPARSE_POINT | _WIN32_FILE_ATTRIBUTE_DIRECTORY,
    )
    _install_fake_msvcrt(monkeypatch, open_osfhandle=lambda *_a: (_ for _ in ()).throw(AssertionError("unreachable")))
    with pytest.raises(ResearchToDecisionError, match="symlink"):
        _open_verified_evidence_file_windows(tmp_path, label="x")
    assert calls["close_handle"] == [_FAKE_WIN32_HANDLE]


def test_win32_open_rejects_a_plain_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A directory that is not a reparse point (FILE_ATTRIBUTE_DIRECTORY
    only) must also be rejected -- Windows has no S_ISREG-equivalent bit,
    so "not a directory and not a reparse point" is the closest same-
    handle approximation of "regular file" available."""
    calls = _install_fake_win32_kernel32(monkeypatch, create_file_result=_FAKE_WIN32_HANDLE, attributes=_WIN32_FILE_ATTRIBUTE_DIRECTORY)
    _install_fake_msvcrt(monkeypatch, open_osfhandle=lambda *_a: (_ for _ in ()).throw(AssertionError("unreachable")))
    with pytest.raises(ResearchToDecisionError, match="regular file"):
        _open_verified_evidence_file_windows(tmp_path, label="x")
    assert calls["close_handle"] == [_FAKE_WIN32_HANDLE]


def test_win32_open_rejects_when_create_file_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CreateFileW itself returning INVALID_HANDLE_VALUE (e.g. the file
    was removed, or access is denied) must fail closed with no handle to
    close -- CloseHandle must not be called on a value that never
    represented an open handle."""
    calls = _install_fake_win32_kernel32(monkeypatch, create_file_result=_WIN32_INVALID_HANDLE_VALUE)
    _install_fake_msvcrt(monkeypatch, open_osfhandle=lambda *_a: (_ for _ in ()).throw(AssertionError("unreachable")))
    with pytest.raises(ResearchToDecisionError, match="could not be opened"):
        _open_verified_evidence_file_windows(tmp_path / "missing.pdf", label="x")
    assert calls["close_handle"] == []


def test_win32_open_rejects_when_get_file_information_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful CreateFileW followed by a failing
    GetFileInformationByHandle (e.g. the file vanished between the two
    calls) must fail closed rather than proceeding with unknown
    attributes, and must still close the handle it did obtain."""
    calls = _install_fake_win32_kernel32(monkeypatch, create_file_result=_FAKE_WIN32_HANDLE, get_file_information_result=False)
    _install_fake_msvcrt(monkeypatch, open_osfhandle=lambda *_a: (_ for _ in ()).throw(AssertionError("unreachable")))
    with pytest.raises(ResearchToDecisionError, match="could not be inspected"):
        _open_verified_evidence_file_windows(tmp_path, label="x")
    assert calls["close_handle"] == [_FAKE_WIN32_HANDLE]


def test_win32_open_same_handle_read_survives_a_path_level_file_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deterministic (non-sleep) proof of the invariant the whole design
    relies on: once the handle/fd is obtained, replacing what the *path*
    points to must not change what the *already-open descriptor* reads.
    The fake wires the sentinel Win32 handle to a real descriptor opened
    before the path is overwritten. POSIX can exercise the same-path
    replacement directly. Windows' ``os.open`` test double cannot emulate
    the ``FILE_SHARE_DELETE`` flags used by the production ``CreateFileW``
    call, so the Windows test double uses a descriptor-bound copy instead;
    that still proves the reader consumes the already-open descriptor and
    does not reopen the path. This demonstrates the Python-level closure
    principle without claiming real Win32 execution, which remains
    unverified in this project (see the module docstring above)."""
    doc = tmp_path / "doc.pdf"
    doc.write_bytes(b"original bytes bound to the handle")

    def fake_open_osfhandle(handle: int, _flags: int) -> int:
        descriptor_source = doc
        if os.name == "nt":
            # A Python ``os.open`` handle does not expose the share-delete
            # flags that the production CreateFileW call supplies. Keep the
            # fake descriptor stable without making os.replace fail on the
            # Windows test runner; the real Win32 share mode is covered by
            # the audited production call and remains execution-unverified.
            descriptor_source = tmp_path / "descriptor-bound-copy.pdf"
            descriptor_source.write_bytes(doc.read_bytes())
        return os.open(descriptor_source, os.O_RDONLY)

    _install_fake_win32_kernel32(monkeypatch, create_file_result=_FAKE_WIN32_HANDLE, attributes=0)
    _install_fake_msvcrt(monkeypatch, open_osfhandle=fake_open_osfhandle)
    fd, file_stat = _open_verified_evidence_file_windows(doc, label="x")
    try:
        assert file_stat.st_size == len(b"original bytes bound to the handle")
        # os.replace (not an in-place write) swaps in a genuinely different
        # inode at the same path -- an in-place write/truncate would mutate
        # the very inode the open descriptor already points to and would
        # therefore prove nothing about a *replacement* race.
        replacement = tmp_path / "replacement.pdf"
        replacement.write_bytes(b"REPLACED CONTENT, different inode, same path")
        os.replace(replacement, doc)
        assert os.read(fd, 1024) == b"original bytes bound to the handle"
    finally:
        os.close(fd)


def test_win32_open_dispatches_from_the_shared_entry_point_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """_open_verified_evidence_file itself must route to the Windows
    implementation when sys.platform reports win32, not only when called
    directly -- proving the dispatch, not just the Windows function in
    isolation."""
    monkeypatch.setattr(rtd.sys, "platform", "win32")
    sentinel = object()

    def fake_windows_open(resolved: Path, *, label: str):
        assert label == "x"
        return sentinel

    monkeypatch.setattr(rtd, "_open_verified_evidence_file_windows", fake_windows_open)
    assert rtd._open_verified_evidence_file(Path("irrelevant"), label="x") is sentinel


@pytest.mark.parametrize(
    "raw",
    [
        "..\\outside.json",
        "sub\\..\\outside.json",
        "../outside.json",
        "sub/../outside.json",
        "sub/../../outside.json",
        "/abs.json",
        r"\rooted.json",
        "C:\\x\\y.json",
        "C:rel.json",
        "\\\\server\\share\\x.json",
    ],
)
def test_manifest_paths_are_judged_identically_under_posix_and_windows_rules(tmp_path: Path, raw: str) -> None:
    (tmp_path / "ok.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ResearchToDecisionError, match="relative to the manifest"):
        rtd._resolve(tmp_path, raw, label="supplier_inputs.path")
    assert rtd._resolve(tmp_path, "ok.json", label="supplier_inputs.path") == (tmp_path / "ok.json").resolve()


def test_posix_literal_backslash_filename_not_normalized_into_separator(tmp_path: Path) -> None:
    assert not rtd._is_unsafe_relative_path("safe\\name.json")
    if os.name == "posix":
        target = tmp_path / "safe\\name.json"
        target.write_text("[]", encoding="utf-8")
        assert rtd._resolve(tmp_path, "safe\\name.json", label="supplier_inputs.path") == target.resolve()


def test_web_url_paths_are_not_mistaken_for_absolute_local_paths() -> None:
    assert rtd._reference_text("https://example.test/item", "f") == "https://example.test/item"
    assert rtd._reference_text("https://example.test/a/b.json", "f") == "https://example.test/a/b.json"
    assert rtd._reference_text("https://example.test/item?x=1", "f", allow_url_query=True) == "https://example.test/item"
    for unsafe in (
        "https://example.test/a/../b",
        "https://example.test/a\\..\\b",
        "https://example.test/a\x00b",
        "http://../x",
        "https://../x",
        "http://..",
        "https://..",
        "http://./x",
        "http://:80/x",
        "http://..:80/x",
        "https://example.test/item<script>",
        "javascript:alert(1)",
        "https://user:abc@example.test/item",
    ):
        with pytest.raises(ResearchToDecisionError, match="safe reference"):
            rtd._reference_text(unsafe, "f")
    for local in ("/etc/passwd", "C:\\x\\y.json", "\\\\server\\share", "../x.json", "file:///etc/passwd", "fixture:../x"):
        with pytest.raises(ResearchToDecisionError, match="safe reference"):
            rtd._reference_text(local, "f")
    assert rtd._reference_text("fixture:evidence/quote.json", "f") == "fixture:evidence/quote.json"


@pytest.mark.parametrize(
    "reference",
    [
        "https://example.test/item?x=\x00",
        "https://example.test/item#\x00",
    ],
)
def test_web_url_query_and_fragment_reject_nul_before_stripping(reference: str) -> None:
    with pytest.raises(ResearchToDecisionError, match="safe reference"):
        rtd._reference_text(reference, "f", allow_url_query=True)


def test_reviewed_url_with_unsafe_components_fails_closed(tmp_path: Path) -> None:
    observation = tmp_path / "review.json"
    manifest = {
        "captured_at": "2026-09-16T09:00:00-06:00",
        "lane": dict(LANE),
        "candidates": [{"candidate_id": "x"}],
        "observation_inputs": [{"path": "review.json", "kind": "reviewed_url"}],
    }
    for bad_url in (
        "https://example.test/item/../forbidden",
        "http://../x",
        "https://example.test/item<script>",
        "javascript:alert(1)",
        "https://user:abc@example.test/item",
    ):
        observation.write_text(json.dumps([{"candidate_id": "x", "url": bad_url}]), encoding="utf-8")
        with pytest.raises(ResearchToDecisionError, match="safe reference|reviewed_url requires"):
            build_research_to_decision(manifest, base_dir=tmp_path)


@pytest.mark.parametrize(
    "source_reference",
    [
        "..\\private.json",
        "/private.json",
        "C:/private.json",
        "https://example.test/quote?q=param",
        "https://example.test/quote/../forbidden",
        "http://../x",
        "https://example.test/quote<script>",
    ],
)
def test_cross_platform_source_references_reject_traversal_and_escapes(source_reference: str) -> None:
    manifest = load_fixture("hydroponics_promising.json")
    manifest["supplier_inputs"][0]["source_reference"] = source_reference
    with pytest.raises(ResearchToDecisionError, match="safe reference|query or fragment"):
        build_research_to_decision(manifest, base_dir=FIXTURES)


_MALFORMED_HTTP_HOSTS = [
    "http://[::1",  # unterminated bracketed host: urlparse itself raises ValueError
    "https://e.test.%2e%2e%2e[::1]h",
    "http://a b/x",
    "http://\t//x",
    "http://.../x",
    "http://a..b/x",
    "http://.example.test/x",
    "http://%2e%2e/x",
    "http://e.test\\x",
    "http://e.test:abc/x",
    "http://e.test:99999/x",
]


@pytest.mark.parametrize("url", _MALFORMED_HTTP_HOSTS)
def test_malformed_http_hosts_and_ports_fail_closed_with_the_module_error(url: str) -> None:
    for allow in (False, True):
        with pytest.raises(ResearchToDecisionError, match="safe reference"):  # never a bare ValueError
            rtd._reference_text(url, "f", allow_url_query=allow)


@pytest.mark.parametrize(
    "url",
    ["http://[::1]/x", "http://[::1]:8080/x", "https://e.test:8443/a", "https://example.test./x", "https://bücher.example/x"],
)
def test_well_formed_http_hosts_ipv6_ports_and_idn_are_still_accepted(url: str) -> None:
    assert rtd._reference_text(url, "f") == url


def test_reviewed_url_with_a_malformed_host_fails_closed_end_to_end(tmp_path: Path) -> None:
    observation = tmp_path / "review.json"
    manifest = {
        "captured_at": "2026-09-16T09:00:00-06:00",
        "lane": dict(LANE),
        "candidates": [{"candidate_id": "x"}],
        "observation_inputs": [{"path": "review.json", "kind": "reviewed_url"}],
    }
    for bad_url, expected in (
        ("http://[::1", "requires an http"),
        ("http://a b/x", "safe reference"),
        ("http://e.test:abc/x", "safe reference"),
    ):
        observation.write_text(json.dumps({"candidate_id": "x", "url": bad_url}), encoding="utf-8")
        with pytest.raises(ResearchToDecisionError, match=expected):
            build_research_to_decision(manifest, base_dir=tmp_path)


def test_record_source_url_with_a_malformed_host_fails_closed() -> None:
    record = types.SimpleNamespace(source_url="http://[::1")
    with pytest.raises(ResearchToDecisionError, match="unsafe source_url"):
        rtd._check_lane([record], dict(LANE), label="supplier_inputs")


# --- Bounded deterministic adversarial corpus: filesystem and symlink containment ---

_FAIL_CLOSED_RESOLVE = "could not be resolved safely"
_EMOJI_OVER_255_BYTES = "\U0001F600" * 70 + ".json"  # 70 characters, 280 bytes: under MAX_TEXT, over NAME_MAX


def _symlink_or_skip(link: Path, target: str) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this platform")


@pytest.mark.parametrize("shape", ["two-cycle", "self-loop", "loop-as-parent", "loop-chain"])
def test_symlink_loops_fail_closed_with_the_module_error_and_never_echo_the_path(tmp_path: Path, shape: str) -> None:
    if shape == "two-cycle":
        _symlink_or_skip(tmp_path / "a.json", "b.json")
        _symlink_or_skip(tmp_path / "b.json", "a.json")
        raw = "a.json"
    elif shape == "self-loop":
        _symlink_or_skip(tmp_path / "self.json", "self.json")
        raw = "self.json"
    elif shape == "loop-as-parent":
        _symlink_or_skip(tmp_path / "loopdir", "loopdir")
        raw = "loopdir/x.json"
    else:
        _symlink_or_skip(tmp_path / "c1.json", "c2.json")
        _symlink_or_skip(tmp_path / "c2.json", "c3.json")
        _symlink_or_skip(tmp_path / "c3.json", "c1.json")
        raw = "c1.json"
    with pytest.raises(ResearchToDecisionError, match=_FAIL_CLOSED_RESOLVE) as caught:
        rtd._resolve(tmp_path, raw, label="supplier_inputs.path")
    assert str(tmp_path) not in str(caught.value)


@pytest.mark.parametrize(
    "raw",
    ["a\ud800b.json", "\ud800", "dir/\udfffx.json"],
    ids=["lone-high-surrogate-in-name", "lone-surrogate-only", "lone-low-surrogate-in-subpath"],
)
def test_lone_surrogates_in_a_path_fail_closed_instead_of_unicode_errors(tmp_path: Path, raw: str) -> None:
    with pytest.raises(ResearchToDecisionError, match="relative to the manifest|" + _FAIL_CLOSED_RESOLVE):
        rtd._resolve(tmp_path, raw, label="supplier_inputs.path")


def test_a_multibyte_name_over_the_filesystem_limit_fails_closed(tmp_path: Path) -> None:
    assert len(_EMOJI_OVER_255_BYTES) < rtd.MAX_TEXT
    with pytest.raises(ResearchToDecisionError, match=_FAIL_CLOSED_RESOLVE) as caught:
        rtd._resolve(tmp_path, _EMOJI_OVER_255_BYTES, label="supplier_inputs.path")
    assert str(tmp_path) not in str(caught.value) and "\U0001F600" not in str(caught.value)


@pytest.mark.parametrize("reference", ["loop.txt", _EMOJI_OVER_255_BYTES.replace(".json", ".txt"), "a\ud800b.txt"], ids=["symlink-loop", "multibyte-over-limit", "surrogate"])
def test_evidence_bindings_fail_closed_on_hostile_references(tmp_path: Path, reference: str) -> None:
    _symlink_or_skip(tmp_path / "loop.txt", "loop.txt")
    digest = hashlib.sha256(b"x").hexdigest()
    with pytest.raises(ResearchToDecisionError):
        rtd._supplier_document_evidence_bindings([("o1", "sku1", reference, digest)], evidence_root=tmp_path)


def test_symlink_loop_in_the_cli_exits_with_a_rejection_and_no_traceback_or_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifest = load_fixture("hydroponics_promising.json")
    manifest["supplier_inputs"][0]["path"] = "loop.json"
    _symlink_or_skip(tmp_path / "loop.json", "loop.json")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert main(["--manifest", str(manifest_path)]) == 2
    out = capsys.readouterr().out
    assert json.loads(out)["status"] == "rejected" and str(tmp_path) not in out


@pytest.mark.parametrize("shape", ["file-symlink-out", "dir-symlink-out", "chain-out", "dangling-out", "nested-dir-symlink-out"])
def test_symlink_escapes_are_rejected_and_inside_symlinks_never_resolve_outside(tmp_path: Path, shape: str) -> None:
    base = tmp_path / "base"
    outside = tmp_path / "outside"
    (base / "sub").mkdir(parents=True)
    outside.mkdir()
    (outside / "out.json").write_text("[]", encoding="utf-8")
    if shape == "file-symlink-out":
        _symlink_or_skip(base / "l.json", str(outside / "out.json"))
        raw = "l.json"
    elif shape == "dir-symlink-out":
        _symlink_or_skip(base / "ld", str(outside))
        raw = "ld/out.json"
    elif shape == "chain-out":
        _symlink_or_skip(base / "c2.json", str(outside / "out.json"))
        _symlink_or_skip(base / "c1.json", "c2.json")
        raw = "c1.json"
    elif shape == "dangling-out":
        _symlink_or_skip(base / "d.json", str(outside / "missing.json"))
        raw = "d.json"
    else:
        _symlink_or_skip(base / "sub" / "up", "../../outside")
        raw = "sub/up/out.json"
    with pytest.raises(ResearchToDecisionError, match="escapes the manifest directory|does not exist"):
        rtd._resolve(base, raw, label="supplier_inputs.path")


@pytest.mark.parametrize("name", ["a..b.json", "..hidden.json", "x..json", "dots.. in name.json"])
def test_names_that_merely_contain_dots_are_not_traversal(tmp_path: Path, name: str) -> None:
    (tmp_path / name).write_text("[]", encoding="utf-8")
    assert rtd._resolve(tmp_path, name, label="supplier_inputs.path") == (tmp_path / name).resolve()


_ADVERSARIAL_PATHS_REJECTED_ON_EVERY_PLATFORM = [
    "/etc/passwd", "//srv/share/x", "\\", "\\\\", "\\\\?\\C:\\x", "\\\\.\\C:\\x", "//?/C:/x", "c:/x", "C:", "C:x", "C:\\x",
    "a\\..\\b", "a/..\\b", "a\\../b", "sub/../../x", "..", "../", "..\\", ".\\..\\x", "./../x",
    "file.json:stream", "file.json::$DATA", "sub/file.json:stream", "file.json:stream:$DATA", "sub\\file.json:stream",
]


@pytest.mark.parametrize("raw", _ADVERSARIAL_PATHS_REJECTED_ON_EVERY_PLATFORM)
def test_adversarial_manifest_paths_are_rejected_under_posix_and_windows_rules(tmp_path: Path, raw: str) -> None:
    assert rtd._is_unsafe_relative_path(raw)
    with pytest.raises(ResearchToDecisionError, match="relative to the manifest"):
        rtd._resolve(tmp_path, raw, label="supplier_inputs.path")


@pytest.mark.parametrize("stream_path", ["file.json:stream", "file.json::$DATA", "dir/file.json:stream", "file.json:stream:$DATA"])
def test_ntfs_alternate_data_streams_are_rejected_as_unsafe_manifest_paths(tmp_path: Path, stream_path: str) -> None:
    (tmp_path / "file.json").write_text("[]", encoding="utf-8")
    assert rtd._is_unsafe_relative_path(stream_path)
    with pytest.raises(ResearchToDecisionError, match="relative to the manifest"):
        rtd._resolve(tmp_path, stream_path, label="supplier_inputs.path")


@pytest.mark.skipif(os.name != "posix", reason="a backslash is only an ordinary filename character on POSIX")
@pytest.mark.parametrize("name", ["safe\\name.json", "a\\b\\c.json", "trailing\\.json", "x\\y..json"])
def test_posix_literal_backslash_filenames_are_accepted_and_stay_inside(tmp_path: Path, name: str) -> None:
    assert not rtd._is_unsafe_relative_path(name)
    (tmp_path / name).write_text("[]", encoding="utf-8")
    assert rtd._resolve(tmp_path, name, label="supplier_inputs.path") == (tmp_path / name).resolve()


# --- Bounded deterministic adversarial corpus: URL parsing ---

_FOLDING_DOT = "\uff0e\uff0e"  # fullwidth full stops: IDNA folds this host to ".."
_REJECTED_HTTP_URLS = [
    # hosts that fold, or hide, under IDNA / NFKC
    f"http://{_FOLDING_DOT}/x", "http://\u3002/x", "http://\ufe52/x",
    "http://ex\u00adample.test/x", "http://ex\u200bample.test/x", "http://ex\ufeffample.test/x",
    "http://ex\u200eample.test/x", "http://ex\u202eample.test/x",
    "http://good.test\uff3cevil/x", "http://\uff05\uff12\uff45\uff05\uff12\uff45/x",
    # empty or present userinfo, stray authority characters
    "http://@evil/x", "http://:@evil/x", "http://good@evil/x", "http://good:pw@evil/x", "http://good\\@evil/x",
    "http://evil\\.good/x", "http://e.test\\x",
    # non-hostname characters, hyphen-edged and ambiguous numeric hosts
    "http://ex$ample/x", "http://ex;ample/x", "http://ex,ample/x", "http://ex'ample/x", "http://ex*ample/x",
    "http://ex!ample/x", "http://ex|ample/x", "http://ex^ample/x", "http://ex`ample/x", "http://ex{ample}/x",
    "http://-bad.test/x", "http://bad-.test/x", "http://0x7f.1/x", "http://999.1.1.1/x", "http://1.2.3/x",
    # malformed brackets, IPv6 literals and ports
    "http://[::1", "http://[::1]x/", "http://[]/x", "http://[::g]/x", "http://[[::1]]/x", "http://a[::1]/x",
    "http://[v1.x]/x", "http://[1.2.3.4]/x", "http://[fe80::1%25eth0]/x", "http://[::1]:99999/x", "http://[::1]:80x/x",
    "http://example.test:0/x", "http://example.test:99999/x", "http://example.test:abc/x", "http://example.test:-1/x",
    "http://example.test:+80/x", "http://example.test: 80/x", "http://example.test:\uff18\uff10/x",
    # dot hosts and empty labels
    "http://./x", "http://../x", "http://.../x", "http://a..b/x", "http://.example.test/x", "http://:80/x",
    # percent-, double-percent-, ;- and backslash-encoded traversal in the URL path
    "http://example.test/a/../b", "http://example.test/a/%2e%2e/b", "http://example.test/a/%2E%2E/b",
    "http://example.test/a/.%2e/b", "http://example.test/a/%2e./b", "http://example.test/a/%252e%252e/b",
    "http://example.test/a/..;/b", "http://example.test/a/..;x=1/b", "http://example.test/a/..%5cb",
    "http://example.test/a/%5c..%5cb", "http://example.test/a/..%2fb", "http://example.test/a\\..\\b", "http://example.test/..",
    # raw control characters and markup
    "http://example.test/x\r\nHost: evil", "http://example.test/x\nY", "http://example.test/x\x00", "http://example.test/<x>",
    "http://exa\nmple.test/x", "ht\ttp://example.test/x",
    # lone surrogates (would raise when the reference is hashed)
    "http://example.test/\ud800", "http://\ud800.test/x",
    # scheme and authority shapes
    "http:/x", "http:x", "http:///x", "https:\\\\x", "//evil/x", "http:", "ftp://example.test/x", "javascript:alert(1)", "mailto:a@b.test",
]
_ACCEPTED_HTTP_URLS = [
    "https://example.test/item", "HTTP://EXAMPLE.TEST/x", "hTTps://example.test/a/b.json", "https://example.test./x",
    "http://[::1]/x", "http://[::1]:8080/x", "http://[2001:db8::1]/x", "http://[::ffff:1.2.3.4]/x",
    "https://e.test:8443/a", "https://e.test:/a", "http://1.2.3.4/x", "http://127.0.0.1:8080/x",
    "https://b\u00fccher.example/x", "https://xn--bcher-kva.example/x", "https://sub-domain.e_x.test/x",
    "https://example.test/a/./b", "https://example.test/a/..b", "https://example.test/a/b..", "https://example.test/100%25",
    "http://a\u3002b/x",  # U+3002 is an IDNA dot: the host is simply a.b
]
_CORPUS_BOUND = 400


def test_url_adversarial_corpus_is_bounded() -> None:
    assert len(_REJECTED_HTTP_URLS) + len(_ACCEPTED_HTTP_URLS) <= _CORPUS_BOUND


@pytest.mark.parametrize("allow_query", [False, True], ids=["no-query", "query-allowed"])
@pytest.mark.parametrize("url", _REJECTED_HTTP_URLS)
def test_adversarial_urls_fail_closed_with_the_module_error_and_never_echo_the_input(url: str, allow_query: bool) -> None:
    with pytest.raises(ResearchToDecisionError, match="must be a safe reference") as caught:
        rtd._reference_text(url, "f", allow_url_query=allow_query)
    message = str(caught.value)
    assert message == "f must be a safe reference" and "example" not in message and "evil" not in message


@pytest.mark.parametrize("url", _ACCEPTED_HTTP_URLS)
def test_legitimate_urls_with_unusual_but_valid_forms_stay_accepted(url: str) -> None:
    assert rtd._reference_text(url, "f") == " ".join(url.split())
    assert rtd._reference_text(url, "f", allow_url_query=True)


def test_idna_form_of_every_accepted_host_is_a_real_name_or_address() -> None:
    from urllib.parse import urlsplit

    for url in _ACCEPTED_HTTP_URLS:
        host = urlsplit(url).hostname
        assert host and ".." not in host and not host.startswith(".")
        if ":" not in host:
            ascii_host = host.encode("idna").decode("ascii")
            assert all(label for label in ascii_host.rstrip(".").split("."))


@pytest.mark.parametrize("url", ["a\ud800b", "http://example.test/\ud800"])
def test_a_lone_surrogate_never_escapes_when_the_reference_is_hashed(url: str) -> None:
    with pytest.raises(ResearchToDecisionError, match="safe reference"):
        rtd._evidence_reference(url, "f")


@pytest.mark.parametrize("url", ["http://good@evil.test/x", "http://example.test:99999/x", "http://ex\u00adample.test/x", "ht\ttp://example.test/x", "http://exa\nmple.test/x", "http://[::1"])
def test_record_source_urls_get_the_same_authority_rules_as_references(url: str) -> None:
    with pytest.raises(ResearchToDecisionError, match="unsafe source_url"):
        rtd._check_lane([types.SimpleNamespace(source_url=url)], dict(LANE), label="supplier_inputs")


@pytest.mark.parametrize("url", ["https://example.test/item", "http://[::1]:8080/x", "https://b\u00fccher.example/x"])
def test_record_source_urls_that_are_well_formed_still_pass(url: str) -> None:
    assert rtd._check_lane([types.SimpleNamespace(source_url=url)], dict(LANE), label="supplier_inputs") is not None


@pytest.mark.parametrize("bad_url", ["http://good@evil.test:99999/x", "http://ex\u00adample.test/x", "http://example.test/a/%2e%2e/b"])
def test_reviewed_url_is_validated_even_when_a_source_reference_supplies_the_evidence_id(tmp_path: Path, bad_url: str) -> None:
    (tmp_path / "review.json").write_text(json.dumps([{"candidate_id": "x", "url": bad_url, "source_reference": "manual:ok"}]), encoding="utf-8")
    manifest = {
        "captured_at": "2026-09-16T09:00:00-06:00",
        "lane": dict(LANE),
        "candidates": [{"candidate_id": "x"}],
        "observation_inputs": [{"path": "review.json", "kind": "reviewed_url"}],
    }
    with pytest.raises(ResearchToDecisionError, match="reviewed_url.url must be a safe reference"):
        build_research_to_decision(manifest, base_dir=tmp_path)


@pytest.mark.parametrize("raw", ["ok\nname.json", "ok\rname.json", "a\r\nb"])
def test_raw_cr_lf_in_a_local_reference_is_rejected_before_whitespace_folding(raw: str) -> None:
    with pytest.raises(ResearchToDecisionError, match="safe reference"):
        rtd._reference_text(raw, "f")


@pytest.mark.parametrize("name", ["safe\\name.json", "dir\\safe\\name.json", "fixture:a\\name.json"])
def test_literal_backslash_references_stay_accepted_while_rooted_and_traversing_forms_do_not(name: str) -> None:
    assert rtd._reference_text(name, "f") == name
    for unsafe in ("a\\..\\b", "..\\x", "\\x", "\\\\srv\\share", "C:\\x", "fixture:C:\\x", "file:C:\\x"):
        with pytest.raises(ResearchToDecisionError, match="safe reference"):
            rtd._reference_text(unsafe, "f")


def test_no_corpus_entry_ever_escapes_as_a_bare_exception() -> None:
    for url in [*_REJECTED_HTTP_URLS, *_ACCEPTED_HTTP_URLS]:
        for allow_query in (False, True):
            for call in (
                lambda: rtd._reference_text(url, "f", allow_url_query=allow_query),
                lambda: rtd._evidence_reference(url, "f", allow_url_query=allow_query),
                lambda: rtd._check_lane([types.SimpleNamespace(source_url=url)], dict(LANE), label="x"),
            ):
                try:
                    call()
                except ResearchToDecisionError:
                    pass


def test_http_document_reference_with_an_absolute_url_path_never_probes_host_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # _reference_text accepts an http(s) URL with a path; as a local evidence reference its absolute
    # path ("/bin/x.pdf") must be rejected BEFORE the symlink walk, which would otherwise call
    # is_symlink() on host paths outside the evidence root (and answer "must not be a symlink").
    root = tmp_path / "evidence"
    root.mkdir()
    probed: list[Path] = []
    real_is_symlink = Path.is_symlink

    def recording_is_symlink(self: Path) -> bool:
        probed.append(self)
        return real_is_symlink(self)

    monkeypatch.setattr(Path, "is_symlink", recording_is_symlink)
    for reference in ("https://h.example/bin/x.pdf", "https://h.example/proc/self/x.pdf", "https://h.example/x.pdf"):
        with pytest.raises(ResearchToDecisionError, match="must remain relative to the manifest"):
            rtd._supplier_document_evidence_bindings([("o", "s", reference, "0" * 64)], evidence_root=root)
    resolved_root = root.resolve()
    assert all(resolved_root in (p, *p.parents) for p in probed), probed


@pytest.mark.skipif(os.name == "nt", reason="needs unprivileged symlink creation")
@pytest.mark.parametrize("which", ["evidence_root", "base_dir"])
def test_symlink_loop_roots_fail_closed_without_echoing_the_path(tmp_path: Path, which: str) -> None:
    loop_a, loop_b = tmp_path / "loop_a", tmp_path / "loop_b"
    loop_a.symlink_to(loop_b)
    loop_b.symlink_to(loop_a)
    good = tmp_path / "good"
    good.mkdir()
    expected = "could not be resolved safely|does not exist or is not a directory"  # 3.13 resolves loops lazily
    if which == "evidence_root":
        with pytest.raises(ResearchToDecisionError, match=expected) as caught:
            rtd._supplier_document_evidence_bindings([("o", "s", "manual:a.pdf", "0" * 64)], evidence_root=loop_a)
    else:
        manifest = {"captured_at": "2026-09-16T09:00:00-06:00", "lane": dict(LANE), "candidates": [{"candidate_id": "x"}]}
        with pytest.raises((ResearchToDecisionError, FileNotFoundError, NotADirectoryError)) as caught:
            build_research_to_decision(manifest, base_dir=loop_a)
        assert not isinstance(caught.value, RuntimeError)
    assert str(tmp_path) not in str(caught.value)


# --- cross-platform path / reference contract -------------------------------------------------
# Pure-string cases: nothing below touches the filesystem, so no device path is ever opened.
# They run on the host OS but judge the *text*; the Windows rules they encode (device names, ADS,
# drive-relative, UNC, trailing dots/spaces) are documented behaviour, exercised here by string
# policy and NOT validated on a native Windows host.

# (path text, unsafe_as_local_manifest_file, why)
_LOCAL_FILE_PATH_CONTRACT = [
    # ordinary names stay legitimate
    ("data.json", False, "plain"),
    ("sub/data.json", False, "nested"),
    ("./data.json", False, "dot segment"),
    ("sub//data.json", False, "empty segment"),
    ("report.v2.json", False, "multi-dot"),
    ("my file.json", False, "inner space"),
    ("caf\u00e9.json", False, "non-ascii"),
    ("a,b.json", False, "comma"),
    (".hidden/data.json", False, "dotfile dir"),
    ("contract.json", False, "starts with 'con'"),
    ("console.csv", False, "starts with 'con'"),
    ("com10.json", False, "not a reserved COM device"),
    ("auxiliary/data.json", False, "starts with 'aux'"),
    ("nullable.json", False, "starts with 'nul'"),
    ("a\\b.json", False, "literal backslash is a separator-like character, not traversal"),
    # traversal
    ("../x.json", True, "posix traversal"),
    ("..\\x.json", True, "windows traversal"),
    ("a/../../x.json", True, "nested traversal"),
    # absolute / drive / UNC / device
    ("/etc/passwd", True, "posix absolute"),
    ("\\rooted.json", True, "windows rooted"),
    ("C:data.json", True, "drive-relative"),
    ("C:\\data.json", True, "drive absolute"),
    ("\\\\server\\share\\x.json", True, "unc"),
    ("//server/share/x.json", True, "unc with slashes"),
    ("\\\\.\\C:\\x.json", True, "device namespace"),
    ("\\\\?\\C:\\x.json", True, "extended-length"),
    # NTFS alternate data streams
    ("data.json:stream", True, "ads"),
    ("data.json::$DATA", True, "ads default stream"),
    # reserved device names, any case/extension/directory
    ("nul", True, "device"),
    ("NUL", True, "device upper"),
    ("Con.json", True, "device with extension"),
    ("aux.txt", True, "device with extension"),
    ("prn", True, "device"),
    ("COM1", True, "device"),
    ("com9.csv", True, "device with extension"),
    ("LPT1", True, "device"),
    ("nul .txt", True, "space before extension"),
    ("COM\u00b9", True, "superscript digit device"),
    ("sub/nul", True, "device in subdir"),
    ("sub\\nul", True, "device in subdir backslash"),
    ("CONIN$", True, "console input"),
    # trailing dots and spaces (Windows drops them)
    ("data.json.", True, "trailing dot"),
    ("sub./data.json", True, "trailing dot dir"),
    ("sub /data.json", True, "trailing space dir"),
    ("a/.. /b.json", True, "space-padded parent segment"),
    ("...", True, "all dots"),
]


@pytest.mark.parametrize(("text", "unsafe", "why"), _LOCAL_FILE_PATH_CONTRACT, ids=[f"{t!r}" for t, _, _ in _LOCAL_FILE_PATH_CONTRACT])
def test_local_manifest_file_path_contract(text: str, unsafe: bool, why: str) -> None:
    assert rtd._is_unsafe_local_file_path(text) is unsafe, why


@pytest.mark.parametrize(
    "text",
    [
        "nul",
        "Con.json",
        "COM1",
        "sub/lpt2.csv",
        "data.json.",
        "sub /data.json",
        "data.json:stream",
        "C:data.json",
        "\\\\server\\share\\x.json",
    ],
)
def test_resolve_rejects_non_portable_manifest_paths_before_touching_the_filesystem(tmp_path: Path, text: str) -> None:
    (tmp_path / "data.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ResearchToDecisionError, match="must remain relative to the manifest") as caught:
        rtd._resolve(tmp_path, text, label="supplier_inputs.path")
    assert text not in str(caught.value)


def test_resolve_still_accepts_a_legitimate_nested_file(tmp_path: Path) -> None:
    (tmp_path / "contract files").mkdir()
    target = tmp_path / "contract files" / "console.v2.json"
    target.write_text("{}", encoding="utf-8")
    assert rtd._resolve(tmp_path, "contract files/console.v2.json", label="supplier_inputs.path") == target.resolve()


# (reference, accepted, why): URL references are NOT local paths.
_REFERENCE_CONTRACT = [
    ("https://example.com/a/b.pdf", True, "https"),
    ("http://example.com:8080/a", True, "explicit port"),
    ("https://[2001:db8::1]:443/x", True, "bracketed ipv6 with port"),
    ("https://example.com/con", True, "device-like URL path segment is just a URL path"),
    ("https://example.com/a.json.", True, "trailing dot in a URL path is not a local file name"),
    ("fixture:data/offer.json", True, "fixture scheme"),
    ("manual:quote 2026-10", True, "manual note"),
    ("file:offer.json", True, "file scheme relative"),
    ("Acme price sheet.", True, "free-text reference with a trailing dot"),
    ("https://example.com:99999/x", False, "port out of range"),
    ("https://example.com:0/x", False, "port zero"),
    ("https://example.com:abc/x", False, "non-numeric port"),
    ("https://[::1/x", False, "unterminated ipv6"),
    ("https://[::1%25eth0]/x", False, "ipv6 zone id"),
    ("https://user:pw@example.com/x", False, "userinfo"),
    ("https://example.com/../x", False, "url traversal"),
    ("https://example.com/%2e%2e/x", False, "encoded traversal"),
    ("https://example.com/%252e%252e/x", False, "double-encoded traversal"),
    ("https://example.com/a\\..\\x", False, "backslash traversal in url path"),
    ("https://exa mple.com/x", False, "space in host"),
    ("ftp://example.com/x", False, "foreign scheme"),
    ("//example.com/x", False, "scheme-relative treated as rooted path"),
    ("file:///etc/passwd", False, "file absolute"),
    ("fixture:../x.json", False, "fixture traversal"),
    ("manual:C:\\x", False, "drive in manual ref"),
    ("data.json:stream", False, "ads in bare ref"),
    ("C:\\x.json", False, "drive path"),
    ("\\\\server\\share", False, "unc"),
    ("a\x00b", False, "nul"),
    ("a\nb", False, "newline"),
    ("..\\x", False, "backslash traversal"),
    ("a\\b.json", True, "literal backslash is an ordinary character on POSIX"),
]


@pytest.mark.parametrize(("reference", "accepted", "why"), _REFERENCE_CONTRACT, ids=[f"{r!r}" for r, _, _ in _REFERENCE_CONTRACT])
def test_reference_contract_separates_urls_from_local_paths(reference: str, accepted: bool, why: str) -> None:
    if accepted:
        assert rtd._reference_text(reference, "source_reference") == reference.strip(), why
    else:
        with pytest.raises(ResearchToDecisionError, match="safe reference|query or fragment") as caught:
            rtd._reference_text(reference, "source_reference")
        assert reference not in str(caught.value) or reference == ""


def test_document_evidence_reference_rejects_reserved_device_names_without_opening_them(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[object] = []
    monkeypatch.setattr(rtd.os, "open", lambda *a, **k: opened.append(a) or (_ for _ in ()).throw(AssertionError("open must not be reached")))
    for reference in ("fixture:nul", "fixture:sub/CON.pdf", "fixture:COM1.pdf", "fixture:doc.pdf."):
        with pytest.raises(ResearchToDecisionError, match="must remain relative to the manifest"):
            rtd._supplier_document_evidence_bindings(
                [("offer-1", "SKU-1", reference, "0" * 64)],
                evidence_root=tmp_path,
            )
    assert opened == []

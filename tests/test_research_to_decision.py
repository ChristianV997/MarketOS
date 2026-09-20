"""Focused tests for the bounded offline research-to-decision seam."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path

import pytest

from scripts.research_to_decision import (
    ResearchToDecisionError,
    _open_verified_evidence_file,
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

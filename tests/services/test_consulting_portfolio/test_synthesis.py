from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.consulting_portfolio import PortfolioInputError, synthesize_portfolio

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "consulting_portfolio"


def load_fixture(name: str) -> list[dict]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_synthesis_aggregates_facts_without_competing_score() -> None:
    payload = synthesize_portfolio(load_fixture("complete_portfolio.json")).to_dict()

    assert payload["status"] == "human_review_required"
    assert payload["report_ids"] == ["report-customer-001", "report-economics-001", "report-market-001", "report-product-001"]
    assert payload["report_fingerprints"]["report-economics-001"] == "sha256:economics-001"
    assert payload["facts_by_area"]["market_research"] == ["Demand is documented in the supplied research report."]
    assert payload["facts_by_area"]["unit_service_economics"] == ["Margin assumptions are recorded for review."]
    assert payload["facts_by_area"]["demand_consumer_attention"] == [
        "Attention signals are directional only.",
        "Consumer attention signals are directional and fixture-backed.",
    ]
    assert payload["facts_by_area"]["supplier_logistics"] == ["Supplier and logistics findings remain fixture-backed."]
    assert payload["facts_by_area"]["marketing_publicity_strategy"] == ["Publicity strategy is documented for human review."]
    assert payload["provenance_by_area"]["market_research"] == [
        {"fact": "Demand is documented in the supplied research report.", "report_id": "report-market-001"}
    ]
    assert "score" not in payload
    assert "confidence_score" not in json.dumps(payload).lower()
    assert payload["decision_boundary"]["scoring"] == "not_performed"
    assert payload["human_review"]["required"] is True
    assert payload["safety"]["external_actions_authorized"] is False


def test_synthesis_is_byte_deterministic() -> None:
    first = synthesize_portfolio(load_fixture("complete_portfolio.json")).to_json()
    second = synthesize_portfolio(list(reversed(load_fixture("complete_portfolio.json")))).to_json()

    assert first == second
    assert synthesize_portfolio(load_fixture("complete_portfolio.json")).fingerprint == synthesize_portfolio(
        list(reversed(load_fixture("complete_portfolio.json")))
    ).fingerprint


def test_partial_and_unavailable_capabilities_are_explicit() -> None:
    result = synthesize_portfolio(load_fixture("partial_unavailable.json"))

    assert result.status == "human_review_required"
    assert result.capabilities["customer_intelligence"] == "unavailable"
    assert result.capabilities["creative_testing"] == "partial"
    assert "customer intelligence report unavailable" in result.limitations
    assert "creative testing has evidence gaps" in result.evidence_gaps
    assert result.human_review["required"] is True


def test_stale_and_conflicting_evidence_are_preserved_as_blockers() -> None:
    result = synthesize_portfolio(load_fixture("stale_conflicting.json"))

    assert "report-market-stale" in result.stale_reports
    assert "report-economics-conflict" in result.conflicting_reports
    assert "stale evidence requires refresh" in result.blockers
    assert "conflicting evidence requires reconciliation" in result.blockers
    assert result.package_readiness == "not_ready"


def test_client_safe_projection_excludes_internal_and_unsafe_fields() -> None:
    result = synthesize_portfolio(load_fixture("client_safe_adversarial.json"))
    serialized = json.dumps(result.client_safe_projection, sort_keys=True).lower()

    assert result.client_safe_projection["status"] == "human_review_required"
    assert "internal_prompt" not in serialized
    assert "api_key" not in serialized
    assert "raw_provider_payload" not in serialized
    assert "publishing" not in serialized
    assert "payment" not in serialized
    assert result.client_safe_projection["report_ids"] == ["report-safe-001"]


def test_nested_non_string_facts_are_not_exported() -> None:
    result = synthesize_portfolio(load_fixture("nested_secret_adversarial.json"))
    serialized = json.dumps(result.to_dict(), sort_keys=True).lower()

    assert "nested-secret-marker" not in serialized
    assert "api_key" not in json.dumps(result.client_safe_projection, sort_keys=True).lower()


def test_duplicate_report_id_and_missing_fingerprint_fail_closed() -> None:
    duplicate = load_fixture("complete_portfolio.json")
    duplicate.append(dict(duplicate[0]))
    with pytest.raises(PortfolioInputError, match="duplicate report_id"):
        synthesize_portfolio(duplicate)

    missing_fingerprint = [dict(duplicate[0])]
    missing_fingerprint[0].pop("fingerprint")
    with pytest.raises(PortfolioInputError, match="fingerprint"):
        synthesize_portfolio(missing_fingerprint)


def test_provenance_is_preserved_in_client_safe_projection() -> None:
    result = synthesize_portfolio(load_fixture("complete_portfolio.json"))

    assert result.client_safe_projection["provenance_by_area"]["market_research"] == [
        {"fact": "Demand is documented in the supplied research report.", "report_id": "report-market-001"}
    ]


def test_external_action_claims_are_rejected() -> None:
    reports = load_fixture("complete_portfolio.json")
    reports[0]["facts"]["launch_authorized"] = True

    with pytest.raises(PortfolioInputError, match="external action"):
        synthesize_portfolio(reports)


def test_empty_input_is_unavailable_and_deterministic() -> None:
    result = synthesize_portfolio([])

    assert result.status == "unavailable"
    assert result.package_readiness == "not_ready"
    assert result.human_review["required"] is True
    assert "no component reports supplied" in result.limitations
    assert result.report_ids == []

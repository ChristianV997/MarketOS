import json
from pathlib import Path

import pytest

from services.consulting_evidence_register import (
    ConsultingEvidenceInputError,
    build_evidence_register,
)


FIXTURES = Path(__file__).parents[2] / "fixtures" / "consulting_evidence_register"


def load_fixture(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_register_preserves_report_refs_and_fact_provenance() -> None:
    result = build_evidence_register(load_fixture("complete.json"), generated_at="2026-09-22T00:00:00Z")

    assert result.workspace_id == "workspace_demo"
    assert [item["report_id"] for item in result.report_refs] == ["report-demand", "report-supply"]
    assert result.evidence_by_area["demand"][0]["source_report_id"] == "report-demand"
    assert result.evidence_by_area["supply"][0]["source_report_id"] == "report-supply"
    assert result.decision_boundary["scoring"] == "not_performed"


def test_partial_and_unavailable_capabilities_are_explicit() -> None:
    result = build_evidence_register(load_fixture("partial_unavailable.json"), generated_at="2026-09-22T00:00:00Z")

    assert result.capability_states == {
        "consumer_attention": "partial",
        "supplier_logistics": "unavailable",
    }
    assert result.status == "partial"
    assert "supplier_logistics" in result.gaps
    assert result.human_review["required"] is True


def test_stale_and_conflicting_evidence_are_not_resolved() -> None:
    result = build_evidence_register(load_fixture("stale_conflicting.json"), generated_at="2026-09-22T00:00:00Z")

    entries = result.evidence_by_area["economics"]
    assert {entry["evidence_state"] for entry in entries} == {"stale", "conflict"}
    assert result.conflicts == ["economics:unit_cost"]
    assert "stale evidence remains unresolved" in result.limitations


def test_serialization_and_fingerprint_are_order_independent() -> None:
    reports = load_fixture("complete.json")
    first = build_evidence_register(reports, generated_at="2026-09-22T00:00:00Z")
    second = build_evidence_register(list(reversed(reports)), generated_at="2026-09-23T00:00:00Z")

    assert first.to_dict() == second.to_dict()
    assert first.fingerprint == second.fingerprint


def test_client_safe_projection_excludes_internal_values() -> None:
    result = build_evidence_register(load_fixture("complete.json"), generated_at="2026-09-22T00:00:00Z")

    projection = result.client_safe_projection
    assert projection["workspace_id"] == "workspace_demo"
    assert "raw_payload" not in json.dumps(projection)
    assert projection["external_actions_authorized"] is False
    assert projection["human_review_required"] is True


def test_external_action_claims_fail_closed() -> None:
    with pytest.raises(ConsultingEvidenceInputError, match="external action"):
        build_evidence_register(load_fixture("unsafe.json"), generated_at="2026-09-22T00:00:00Z")


def test_nested_sensitive_content_fails_closed() -> None:
    with pytest.raises(ConsultingEvidenceInputError, match="sensitive"):
        build_evidence_register(load_fixture("nested_secret.json"), generated_at="2026-09-22T00:00:00Z")


def test_malformed_report_reference_fails_closed() -> None:
    with pytest.raises(ConsultingEvidenceInputError, match="report_id"):
        build_evidence_register([{"workspace_id": "workspace_demo", "status": "completed"}])


def test_empty_input_is_explicit_and_not_ready() -> None:
    result = build_evidence_register([], workspace_id="workspace_demo", generated_at="2026-09-22T00:00:00Z")

    assert result.status == "empty"
    assert result.human_review["required"] is True
    assert result.readiness is False
    assert result.evidence_by_area == {}

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.adapters.research.consumer_attention import ConsumerAttentionImportError, import_json, normalize_record
from evaluation.commerce.consumer_attention import (
    ConsumerAttentionEvidence,
    build_report,
    freshness_state,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "consumer_attention" / "service_market_generic.json"


def row(**overrides):
    value = {
        "candidate_id": "generic-service",
        "query": "service outcome",
        "source": "manual-observation",
        "source_type": "manual_csv_import",
        "platform": "manual",
        "offering_kind": "service",
        "geography": "MX",
        "language": "es-MX",
        "observed_at": "2026-09-01T12:00:00Z",
        "observation_key": "intent",
        "observation_value": "high",
        "hook": "Make the next step easier",
        "pain_point": "manual coordination",
        "desired_outcome": "clearer completion",
        "source_confidence": 0.8,
    }
    value.update(overrides)
    result = normalize_record(value, mode="fixture")
    assert result is not None
    return result


def test_observed_at_is_optional_but_never_invented():
    missing = row(observed_at=None)
    assert missing.observed_at is None
    assert missing.to_dict()["observed_at"] is None
    assert freshness_state(missing.observed_at, as_of="2026-09-10T00:00:00Z") == "unavailable"


@pytest.mark.parametrize(
    ("observed_at", "as_of", "expected"),
    [
        ("2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z", "fresh"),
        ("2026-01-01T00:00:00Z", "2026-09-10T00:00:00Z", "stale"),
        ("2026-09-20T00:00:00Z", "2026-09-10T00:00:00Z", "future_dated"),
        (None, "2026-09-10T00:00:00Z", "unavailable"),
        ("2026-09-01T00:00:00Z", None, "unavailable"),
    ],
)
def test_freshness_requires_explicit_reference_time(observed_at, as_of, expected):
    assert freshness_state(observed_at, as_of=as_of, max_age_days=90) == expected
    report = build_report([row(observed_at=observed_at)], as_of=as_of).to_dict()
    assert report["freshness_status"] == expected


@pytest.mark.parametrize("value", ["2026-09-01", "not-a-date", "2026-09-01T00:00:00"])
def test_malformed_or_timezone_less_observations_are_unavailable(value):
    payload = row().to_dict()
    payload["observed_at"] = value
    assert normalize_record(payload, mode="fixture") is None


@pytest.mark.parametrize("field", ["geography", "language", "offering_kind"])
def test_identity_metadata_survives_normalization_and_serialization(field):
    record = row()
    assert field in record.to_dict()
    assert record.to_dict()[field] == getattr(record, field)
    report = build_report([record], as_of="2026-09-10T00:00:00Z").to_dict()
    report_key = {"offering_kind": "offering_kinds", "geography": "geographies", "language": "languages"}[field]
    assert report[report_key] == [getattr(record, field)]
    assert report["candidates"][0][report_key] == [getattr(record, field)]


def test_explicit_zero_counts_are_distinct_from_missing_counts():
    zero = row(view_count=0, review_count=0)
    missing = row()

    assert zero.view_count == 0
    assert zero.review_count == 0
    assert missing.view_count is None
    assert missing.review_count is None


def test_candidate_identity_must_be_text_not_a_coerced_number():
    payload = row().to_dict()

    assert normalize_record({**payload, "candidate_id": 42}, mode="fixture") is None


def test_live_evidence_mode_is_downgraded_to_unavailable():
    record = normalize_record(row().to_dict(), mode="live_validated")
    assert record is not None

    report = build_report([record], evidence_mode="live_validated").to_dict()

    assert record.evidence_mode == "unavailable"
    assert report["evidence_mode"] == "unavailable"


def test_json_duplicate_keys_and_oversized_inputs_fail_closed(tmp_path):
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"candidate_id":"first","candidate_id":"second"}', encoding="utf-8")
    with pytest.raises(ConsumerAttentionImportError, match="duplicate JSON object key"):
        import_json(duplicate)

    oversized = tmp_path / "oversized.json"
    oversized.write_text("x" * (64 * 1024 + 1), encoding="utf-8")
    with pytest.raises(ConsumerAttentionImportError, match="exceeds size limit"):
        import_json(oversized)


def test_conflicting_observations_are_visible_and_block_attention_recommendation():
    first = row(source="source-a", content_title="Positive observation", observation_value="high")
    second = row(source="source-b", content_title="Negative observation", observation_value="low", hook="A different service concern")
    report = build_report([first, second], as_of="2026-09-10T00:00:00Z").to_dict()
    candidate = report["candidates"][0]
    assert report["conflict_count"] == 1
    assert candidate["conflicting_observation_keys"] == ["intent"]
    assert candidate["score"]["recommendation"] == "reject_low_attention"
    assert "conflicting_consumer_observations" in report["warnings"]
    assert report["next_best_action"] == "resolve_consumer_attention_conflicts"


def test_conflicting_same_key_duplicates_are_not_silently_collapsed():
    first = row(source="same-source", content_title="Same observation", observation_value="high", source_confidence=0.9)
    second = row(source="same-source", content_title="Same observation", observation_value="low", source_confidence=0.4)
    report = build_report([first, second], as_of="2026-09-10T00:00:00Z").to_dict()
    assert report["evidence_count"] == 2
    assert report["conflict_count"] == 1
    assert report["candidates"][0]["conflicting_observation_keys"] == ["intent"]


@pytest.mark.parametrize("observed_at", ["2026-01-01T00:00:00Z", "2026-09-20T00:00:00Z", None])
def test_nonfresh_explicitly_reviewed_attention_is_blocked(observed_at):
    report = build_report([row(observed_at=observed_at)], as_of="2026-09-10T00:00:00Z").to_dict()
    assert report["freshness_status"] in {"stale", "future_dated", "unavailable"}
    assert report["candidates"][0]["score"]["recommendation"] == "reject_low_attention"
    assert report["next_best_action"] == "refresh_consumer_attention_evidence"


def test_same_observation_value_does_not_create_a_conflict():
    first = row(source="source-a", content_title="Observation one")
    second = row(source="source-b", content_title="Observation two")
    report = build_report([first, second], as_of="2026-09-10T00:00:00Z").to_dict()
    assert report["conflict_count"] == 0
    assert "conflicting_consumer_observations" not in report["warnings"]


def test_unknown_offering_kind_is_explicit_and_not_inferred_from_candidate_name():
    record = row(candidate_id="service-looking-name", offering_kind=None)
    assert record.offering_kind == "unknown"
    report = build_report([record]).to_dict()
    assert report["offering_kinds"] == ["unknown"]
    assert report["candidates"][0]["offering_kinds"] == ["unknown"]


def test_generic_service_fixture_is_product_agnostic_and_json_safe():
    records = import_json(FIXTURE, platform="manual", source_type="manual_csv_import")
    report = build_report(records, evidence_mode="fixture_demo", as_of="2026-09-10T00:00:00Z").to_dict()
    assert report["evidence_mode"] == "fixture_demo"
    assert report["freshness_status"] == "fresh"
    assert report["offering_kinds"] == ["hybrid", "service"]
    assert report["geographies"] == ["MX", "US"]
    assert report["languages"] == ["en-US", "es-MX"]
    assert {item["candidate_id"] for item in report["candidates"]} == {"service-offer-alpha", "service-offer-beta"}
    assert all(item["score"]["recommendation"] != "advance_to_launch" for item in report["candidates"])
    json.dumps(report)


def test_attention_does_not_infer_supplier_proof_or_live_validation():
    report = build_report([row()], evidence_mode="fixture_demo").to_dict()
    assert report["warnings"] == ["consumer_attention_is_not_supplier_proof"]
    assert report["read_only"] is True
    assert report["network_calls"] is False
    assert report["mutated"] is False
    assert '"supplier_proof": true' not in json.dumps(report).lower()


def test_record_rejects_control_characters_and_unsafe_flags():
    payload = row().to_dict()
    payload["observation_key"] = "intent\nsecret"
    assert normalize_record(payload, mode="fixture") is None
    with pytest.raises(ValueError, match="safe text"):
        ConsumerAttentionEvidence("candidate\nforged", "query", "source", "fixture_demo")
    with pytest.raises(ValueError, match="offline"):
        ConsumerAttentionEvidence("candidate", "query", "source", "fixture_demo", read_only=False)


def test_nested_secret_like_rows_are_dropped_before_model_creation():
    unsafe = row()
    raw = unsafe.to_dict()
    raw["content"] = {"api_key": "fixture-secret-must-not-pass"}
    assert normalize_record(raw, mode="fixture") is None

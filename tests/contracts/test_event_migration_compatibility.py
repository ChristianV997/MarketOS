import json
from pathlib import Path

from backend.events.migration_compatibility import (
    assert_canonical_non_authoritative,
    build_dual_write_compatibility_report,
    compare_legacy_record_to_canonical_event,
    validate_dual_write_order,
    validate_legacy_pilot_record,
)
from backend.events.replay_certification import load_canonical_jsonl


ROOT = Path("tests/fixtures/event_migration_pilot")


def _legacy():
    return [json.loads(line) for line in (ROOT / "legacy_only_input.jsonl").read_text().splitlines() if line]


def test_fixture_parity_report_is_clean_and_deterministic():
    canonical = load_canonical_jsonl(ROOT / "canonical_expected.jsonl")
    first = build_dual_write_compatibility_report(_legacy(), canonical)
    second = build_dual_write_compatibility_report(_legacy(), canonical)
    expected = json.loads((ROOT / "dual_write_expected_report.json").read_text())
    assert first.to_dict() == second.to_dict()
    for key, value in expected.items():
        assert first.to_dict()[key] == value


def test_compatibility_detects_payload_or_metadata_mismatch():
    canonical = load_canonical_jsonl(ROOT / "canonical_expected.jsonl")[0]
    assert assert_canonical_non_authoritative(canonical) == []
    altered = canonical.from_dict({**canonical.to_dict(), "metadata": {**canonical.metadata, "dry_run": False}})
    assert "metadata_mismatch:dry_run" in compare_legacy_record_to_canonical_event(_legacy()[0], altered)


def test_compatibility_detects_missing_or_extra_canonical_records():
    canonical = load_canonical_jsonl(ROOT / "canonical_expected.jsonl")
    missing = build_dual_write_compatibility_report(_legacy(), [])
    assert missing.parity is False
    assert missing.mismatches == ["missing_canonical_event:0"]
    extra = build_dual_write_compatibility_report(_legacy(), canonical + canonical)
    assert extra.parity is False
    assert "unexpected_extra_canonical_events" in extra.migration_blockers


def test_compatibility_validates_legacy_input_and_canonical_ordering():
    canonical = load_canonical_jsonl(ROOT / "canonical_expected.jsonl")
    assert validate_legacy_pilot_record(_legacy()[0]) == []
    assert validate_dual_write_order(_legacy(), canonical) == []
    broken = dict(_legacy()[0])
    broken["workflow_id"] = ""
    assert "legacy_workflow_id" in validate_legacy_pilot_record(broken)
    altered = canonical[0].from_dict({**canonical[0].to_dict(), "event_id": "different-ordering-id"})
    assert "ordering_event_id:0" in validate_dual_write_order(_legacy(), [altered])

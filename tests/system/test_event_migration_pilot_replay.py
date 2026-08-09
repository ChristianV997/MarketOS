import json
from pathlib import Path

from backend.events.migration_compatibility import build_dual_write_compatibility_report
from backend.events.replay_certification import hash_sequence, load_canonical_jsonl, validate_event_sequence


ROOT = Path("tests/fixtures/event_migration_pilot")


def test_canonical_pilot_fixture_replays_and_matches_legacy_parity():
    events = load_canonical_jsonl(ROOT / "canonical_expected.jsonl")
    legacy = [json.loads(line) for line in (ROOT / "legacy_only_input.jsonl").read_text().splitlines() if line]
    assert validate_event_sequence(events) == []
    assert hash_sequence(events) == hash_sequence(load_canonical_jsonl(ROOT / "canonical_expected.jsonl"))
    report = build_dual_write_compatibility_report(legacy, events)
    assert report.parity is True
    assert report.migration_blockers == []

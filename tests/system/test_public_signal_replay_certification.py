from pathlib import Path

from backend.events.replay_certification import assert_no_live_authority, hash_sequence, load_canonical_jsonl, replay_summary, validate_event_sequence
from backend.events.repository import JsonlEventRepository
from backend.signals.public_sources import append_public_signal_events, ingest_public_rss


ROOT = Path("tests/fixtures/public_signals")


def test_public_signal_events_are_replay_safe_and_advisory(tmp_path):
    result = ingest_public_rss("ecommerce trends", fixture_xml=(ROOT / "rss_sample.xml").read_text())
    repository = JsonlEventRepository(tmp_path / "signals.jsonl")
    append_public_signal_events(result.signals, repository, workspace_id="fixture-workspace", cache_status="fixture")
    events = load_canonical_jsonl(tmp_path / "signals.jsonl")
    assert validate_event_sequence(events) == []
    assert hash_sequence(events) == hash_sequence(load_canonical_jsonl(tmp_path / "signals.jsonl"))
    assert assert_no_live_authority(events) == []
    summary = replay_summary(events)
    assert summary["event_types"] == {"public_signal_observed": 2}
    assert all(event.metadata["non_authoritative"] and event.metadata["advisory"] for event in events)

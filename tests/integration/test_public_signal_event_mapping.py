from pathlib import Path

from backend.events.replay_certification import load_canonical_jsonl
from backend.events.repository import InMemoryEventRepository
from backend.signals.public_sources import append_public_signal_events, ingest_public_rss, public_signal_event


ROOT = Path("tests/fixtures/public_signals")


def test_fixture_signal_maps_to_expected_canonical_event_and_metadata():
    result = ingest_public_rss("ecommerce trends", fixture_xml=(ROOT / "rss_sample.xml").read_text())
    actual = public_signal_event(result.signals[0], "fixture-workspace", cache_status="fixture")
    expected = load_canonical_jsonl(ROOT / "canonical_events.expected.jsonl")[0]
    assert actual.to_dict() == expected.to_dict()
    assert actual.metadata["no_credentials"] is True
    assert actual.metadata["no_launch_authority"] is True
    assert actual.metadata["no_spend_authority"] is True


def test_events_append_only_to_explicit_canonical_repository():
    result = ingest_public_rss("ecommerce trends", fixture_xml=(ROOT / "rss_sample.xml").read_text())
    repository = InMemoryEventRepository()
    identifiers = append_public_signal_events(result.signals, repository, workspace_id="fixture-workspace", cache_status="fixture")
    assert len(identifiers) == 2
    assert [item.event_type for item in repository.stream()] == ["public_signal_observed", "public_signal_observed"]

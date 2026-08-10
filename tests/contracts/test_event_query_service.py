from pathlib import Path
from backend.events.query_models import EventQuery
from backend.events.query_service import build_commerce_run_summaries, build_event_timeline, build_shopify_import_summaries, load_events_from_jsonl, query_events

ROOT = Path(__file__).resolve().parents[2]
def test_jsonl_filters_timeline_and_summaries_are_deterministic():
    events, warnings = load_events_from_jsonl(ROOT / "tests/fixtures/event_queries/mixed_canonical_events.jsonl")
    query = EventQuery(workspace_id="demo", limit=10)
    assert len(query_events(events, query)) == 4 and build_event_timeline(events, query).events[0].replay_hash
    assert build_commerce_run_summaries(events)[0].candidate_count == 1
    assert build_shopify_import_summaries(events)[0].observed_revenue_total == 118.66
    _, malformed = load_events_from_jsonl(ROOT / "tests/fixtures/event_queries/malformed_mixed_canonical_events.jsonl")
    assert malformed == ["malformed_jsonl_row:2"]

from pathlib import Path
from backend.events.query_models import EventQuery
from backend.events.query_service import event_query_report, load_events_from_jsonl

ROOT = Path(__file__).resolve().parents[2]
def test_read_view_hides_payload_and_metadata_values():
    events, warnings = load_events_from_jsonl(ROOT / "tests/fixtures/event_queries/mixed_canonical_events.jsonl")
    report = event_query_report(events, EventQuery(workspace_id="demo"), warnings)
    record = report["timeline"]["events"][-1]
    assert "observed_revenue_total" not in record["payload_summary"]
    assert report["read_only"] and not report["mutated"]

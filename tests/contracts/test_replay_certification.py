from pathlib import Path
from backend.contracts.events import Event
from backend.events.replay_certification import hash_sequence,load_canonical_jsonl,validate_event_sequence
ROOT=Path(__file__).resolve().parents[1]/"fixtures/golden_replay"
def test_all_golden_fixtures_are_canonical_and_hash_stable():
    for path in ROOT.glob("*.jsonl"):
        events=load_canonical_jsonl(path);assert events and not validate_event_sequence(events)
        assert hash_sequence(events)==hash_sequence(load_canonical_jsonl(path))
def test_malformed_fixture_fails_with_path_and_line(tmp_path):
    path=tmp_path/"bad.jsonl";path.write_text("{}\n",encoding="utf-8")
    try:load_canonical_jsonl(path)
    except Exception as exc:assert "bad.jsonl:1" in str(exc)
    else:raise AssertionError("malformed fixture must fail")

def _event(event_id, *, workspace_id="ws-1", occurred_at=1.0):
    return Event(event_id=event_id, workspace_id=workspace_id, aggregate_type="advisory", aggregate_id="agg-1", event_type="step_completed", schema_version=1, occurred_at=occurred_at, source="test")

def test_duplicate_event_id_is_actually_flagged_not_just_absent_from_clean_fixtures():
    """The clean-fixture hash-stability test above never exercises the
    duplicate branch of validate_event_sequence -- every golden fixture is
    already duplicate-free by construction. Feed it an actual duplicate
    event_id directly so a replayed/re-delivered event is provably caught,
    not merely assumed caught because no test ever fed it one."""
    events = [_event("evt-1", occurred_at=1.0), _event("evt-2", occurred_at=2.0), _event("evt-1", occurred_at=3.0)]
    issues = validate_event_sequence(events)
    assert "duplicate_event_id:evt-1" in issues

def test_non_monotonic_timestamp_is_actually_flagged():
    events = [_event("evt-1", occurred_at=5.0), _event("evt-2", occurred_at=1.0)]
    issues = validate_event_sequence(events)
    assert "non_monotonic_timestamp:evt-2" in issues

def test_missing_workspace_id_is_actually_flagged():
    events = [_event("evt-1", workspace_id=None, occurred_at=1.0)]
    issues = validate_event_sequence(events)
    assert "missing_workspace_id:evt-1" in issues

def test_clean_sequence_has_no_issues():
    events = [_event("evt-1", occurred_at=1.0), _event("evt-2", occurred_at=2.0)]
    assert validate_event_sequence(events) == []

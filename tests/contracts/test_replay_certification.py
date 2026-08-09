from pathlib import Path
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

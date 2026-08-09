import json
from pathlib import Path
from backend.events.replay_certification import load_canonical_jsonl,replay_summary
ROOT=Path(__file__).resolve().parents[1]/"fixtures/golden_replay"
def test_workflow_golden_summary_matches_expected():
    report=replay_summary(load_canonical_jsonl(ROOT/"workflow_basic.jsonl"));summary=report["workflow"];expected=json.loads((ROOT/"expected/workflow_basic.expected.json").read_text())
    assert report["event_count"]==expected["event_count"]
    for key,value in expected.items():
        if key!="event_count":assert summary[key]==value

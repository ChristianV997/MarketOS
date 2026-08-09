import json
from pathlib import Path
from backend.events.replay_certification import load_canonical_jsonl,summarize_shadow_flags
ROOT=Path(__file__).resolve().parents[1]/"fixtures/golden_replay"
def test_shadow_fixture_has_required_fields_and_conservative_classifications():
    events=load_canonical_jsonl(ROOT/"shadow_flags_financial.jsonl")
    for event in events:
        for key in ("legacy_decision","candidate_decision","delta","metric_name","safety_metric","classification_placeholder"):assert key in event.payload
    assert [x["classification"] for x in summarize_shadow_flags(events)]==json.loads((ROOT/"expected/shadow_flags_financial.expected.json").read_text())["classifications"]

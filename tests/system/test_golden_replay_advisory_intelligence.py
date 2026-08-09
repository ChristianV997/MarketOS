import json
from pathlib import Path
from backend.events.replay_certification import load_canonical_jsonl,summarize_advisory_artifacts
ROOT=Path(__file__).resolve().parents[1]/"fixtures/golden_replay"
def test_advisory_fixture_is_non_authoritative():
    actual=summarize_advisory_artifacts(load_canonical_jsonl(ROOT/"advisory_intelligence_artifacts.jsonl"));expected=json.loads((ROOT/"expected/advisory_intelligence_artifacts.expected.json").read_text())
    assert {key:actual[key] for key in expected}==expected

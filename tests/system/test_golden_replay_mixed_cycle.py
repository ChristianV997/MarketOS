import json
from pathlib import Path
from backend.events.replay_certification import build_migration_readiness_report,load_canonical_jsonl
ROOT=Path(__file__).resolve().parents[1]/"fixtures/golden_replay"
def test_mixed_cycle_has_complete_chain_and_stable_summary():
    report=build_migration_readiness_report(load_canonical_jsonl(ROOT/"mixed_marketos_cycle.jsonl"));expected=json.loads((ROOT/"expected/mixed_marketos_cycle.expected.json").read_text())
    for key,value in expected.items():assert report[key]==value
    assert not report["migration_blockers"]

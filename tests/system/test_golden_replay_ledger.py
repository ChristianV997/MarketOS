import json
from pathlib import Path
from backend.events.replay_certification import load_canonical_jsonl,summarize_ledger
ROOT=Path(__file__).resolve().parents[1]/"fixtures/golden_replay"
def test_ledger_golden_projection_matches_expected_and_reconciles_attribution():
    actual=summarize_ledger(load_canonical_jsonl(ROOT/"ledger_commerce_cycle.jsonl"));expected=json.loads((ROOT/"expected/ledger_commerce_cycle.expected.json").read_text())
    assert {key:actual[key] for key in expected}==expected
    assert actual["attribution_reconciled_revenue"]<actual["attribution_claimed_revenue"]

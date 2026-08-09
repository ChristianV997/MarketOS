import json
from pathlib import Path

from backend.evaluation.shadow_features.evaluator import evaluate_all_shadow_features
from backend.evaluation.shadow_features.fixtures import fixture_scenarios
from backend.events.replay_certification import load_canonical_jsonl


ROOT = Path("tests/fixtures/shadow_evaluation")


def test_all_fixture_events_are_canonical_and_match_expected_classifications():
    for path in sorted(ROOT.glob("*.jsonl")):
        events = load_canonical_jsonl(path)
        evaluations = evaluate_all_shadow_features(events, fixture_name=path.name)
        assert len(evaluations) == 1
        expected = json.loads((ROOT / "expected" / f"{path.stem}.expected.json").read_text())
        actual = evaluations[0]
        assert actual.feature_id == expected["feature_id"]
        assert actual.classification == expected["classification"]
        if "blocker" in expected:
            assert expected["blocker"] in actual.blockers


def test_fixture_inventory_is_complete_and_auditable():
    scenarios = fixture_scenarios()
    assert len(scenarios) == 12
    assert {scenario.filename for scenario in scenarios} == {path.name for path in ROOT.glob("*.jsonl")}
    assert all(scenario.purpose and scenario.expected_classification for scenario in scenarios)

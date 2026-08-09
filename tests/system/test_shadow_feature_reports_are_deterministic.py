import json
from pathlib import Path

from backend.evaluation.shadow_features.evaluator import build_shadow_evaluation_report
from backend.evaluation.shadow_features.fixtures import default_fixture_paths
from backend.evaluation.shadow_features.reporting import report_to_json, report_to_markdown


ROOT = Path("tests/fixtures/shadow_evaluation/expected")


def test_report_json_and_markdown_are_deterministic_and_safe():
    first = build_shadow_evaluation_report(default_fixture_paths())
    second = build_shadow_evaluation_report(default_fixture_paths())
    assert report_to_json(first) == report_to_json(second)
    assert report_to_markdown(first) == report_to_markdown(second)
    expected = json.loads((ROOT / "all_features_report.expected.json").read_text())
    assert first.summary_counts == expected["summary_counts"]
    assert first.migration_readiness["promote_candidates"] == expected["promote_candidates"]
    assert first.migration_readiness["production_mutation"] is expected["production_mutation"]
    assert "does not change feature flags" in report_to_markdown(first)

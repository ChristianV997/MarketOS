import json
import subprocess
import sys
from pathlib import Path


def test_cli_supports_fixture_json_markdown_and_output(tmp_path):
    root = Path.cwd()
    command = [sys.executable, "scripts/shadow_feature_evaluation.py", "--fixtures", "--json"]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout)
    assert payload["summary_counts"]["REWORK"] == 6
    markdown = subprocess.run([sys.executable, "scripts/shadow_feature_evaluation.py", "--fixtures", "--markdown"], cwd=root, capture_output=True, text=True, check=True)
    assert "read-only certification" in markdown.stdout
    output = tmp_path / "evaluation.json"
    subprocess.run(command + ["--output", str(output)], cwd=root, capture_output=True, text=True, check=True)
    assert json.loads(output.read_text())["migration_readiness"]["feature_flags_changed"] is False


def test_cli_filters_feature_and_rejects_unknown_input_path():
    root = Path.cwd()
    filtered = subprocess.run(
        [sys.executable, "scripts/shadow_feature_evaluation.py", "--fixtures", "--feature", "adaptive_risk", "--json"],
        cwd=root, capture_output=True, text=True, check=True,
    )
    assert {item["feature_id"] for item in json.loads(filtered.stdout)["features"]} == {"adaptive_risk"}
    invalid = subprocess.run(
        [sys.executable, "scripts/shadow_feature_evaluation.py", "--path", "does-not-exist.jsonl"],
        cwd=root, capture_output=True, text=True,
    )
    assert invalid.returncode == 2
    assert "invalid input path" in invalid.stderr

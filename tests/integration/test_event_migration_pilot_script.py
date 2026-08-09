import json
import subprocess
import sys
from pathlib import Path


def test_pilot_report_script_json_markdown_and_output(tmp_path):
    root = Path.cwd()
    command = [sys.executable, "scripts/event_migration_pilot_report.py", "--fixtures", "--json"]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout)
    assert payload["parity"] is True
    assert payload["canonical_non_authoritative"] is True
    markdown = subprocess.run([sys.executable, "scripts/event_migration_pilot_report.py", "--fixtures", "--markdown"], cwd=root, capture_output=True, text=True, check=True)
    assert "legacy journal remains authoritative" in markdown.stdout
    output = tmp_path / "pilot.json"
    subprocess.run(command + ["--output", str(output)], cwd=root, capture_output=True, text=True, check=True)
    assert json.loads(output.read_text())["legacy_fields_preserved"] is True


def test_pilot_report_script_rejects_missing_fixture_path():
    result = subprocess.run(
        [sys.executable, "scripts/event_migration_pilot_report.py", "--legacy-path", "missing.jsonl"],
        cwd=Path.cwd(), capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "input files must exist" in result.stderr

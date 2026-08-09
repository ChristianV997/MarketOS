import json
import subprocess
import sys
from pathlib import Path

from backend.events.replay_certification import load_canonical_jsonl


def test_cli_fixture_mode_preview_and_explicit_jsonl_write(tmp_path):
    root = Path.cwd()
    command = [sys.executable, "scripts/ingest_public_signals.py", "--fixtures", "--json"]
    preview = subprocess.run(command, cwd=root, capture_output=True, text=True, check=True)
    payload = json.loads(preview.stdout)
    assert payload["status"] == "fixture"
    assert payload["network_used"] is False
    assert payload["written_event_ids"] == []
    assert payload["audit"]["advisory_only"] is True
    target = tmp_path / "signals.jsonl"
    written = subprocess.run(command + ["--write-jsonl", str(target)], cwd=root, capture_output=True, text=True, check=True)
    assert len(json.loads(written.stdout)["written_event_ids"]) == 2
    assert len(load_canonical_jsonl(target)) == 2


def test_cli_blocks_real_network_without_explicit_allow_network():
    result = subprocess.run([sys.executable, "scripts/ingest_public_signals.py", "--json"], cwd=Path.cwd(), capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked"
    assert payload["network_used"] is False
    assert payload["errors"] == ["network_opt_in_required"]


def test_cli_markdown_fixture_output_has_advisory_warning():
    result = subprocess.run(
        [sys.executable, "scripts/ingest_public_signals.py", "--fixtures", "--markdown"],
        cwd=Path.cwd(), capture_output=True, text=True, check=True,
    )
    assert "advisory public observations" in result.stdout
    assert "No launch, spend, publishing" in result.stdout

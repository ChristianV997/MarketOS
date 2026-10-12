"""Regression test: the ingestion CLI reports only IDs stored for the workspace that ran it.

Two synthetic workspaces ingest the same fixture article into one JSONL file.
The second run's ``written_event_ids`` must equal the rows the file holds for
that workspace. Fails on current main, where the second run lists IDs it did not
write. Decision-neutral: holds whether the collision is fixed by identity (a/c)
or by refusal (b). See docs/ai/PUBLIC_SIGNAL_EVENT_IDENTITY.md.
"""
import json
import subprocess
import sys
from pathlib import Path

from backend.events.replay_certification import load_canonical_jsonl

WORKSPACE_ALPHA = "synthetic-workspace-alpha"
WORKSPACE_BETA = "synthetic-workspace-beta"


def _run_ingest(workspace_id, target, cache_dir):
    command = [
        sys.executable, "scripts/ingest_public_signals.py", "--fixtures", "--json",
        "--workspace-id", workspace_id, "--write-jsonl", str(target), "--cache-dir", str(cache_dir),
    ]
    result = subprocess.run(command, cwd=Path.cwd(), capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_cli_second_workspace_written_event_ids_match_rows_stored_for_it(tmp_path):
    target = tmp_path / "shared-signals.jsonl"
    cache_dir = tmp_path / "cache"
    _run_ingest(WORKSPACE_ALPHA, target, cache_dir)
    beta_report = _run_ingest(WORKSPACE_BETA, target, cache_dir)
    stored_for_beta = {event.event_id for event in load_canonical_jsonl(target) if event.workspace_id == WORKSPACE_BETA}
    assert set(beta_report["written_event_ids"]) == stored_for_beta

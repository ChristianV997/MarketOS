import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_cli_public_query_is_blocked_without_explicit_network_gate(tmp_path):
    result = subprocess.run([sys.executable, "scripts/run_commerce_mvp_slice.py", "--public-query", "portable espresso maker", "--public-cache-dir", str(tmp_path), "--json"], cwd=ROOT, capture_output=True, text=True, check=True)
    report = json.loads(result.stdout)
    assert report["public_source_status"] == "blocked"
    assert report["network_used"] is False
    assert any("network_not_allowed" in item for item in report["blockers"])


def test_cli_fixture_mode_never_uses_network():
    result = subprocess.run([sys.executable, "scripts/run_commerce_mvp_slice.py", "--fixture", "tests/fixtures/commerce_mvp/public_signals.json", "--query", "portable espresso maker", "--json"], cwd=ROOT, capture_output=True, text=True, check=True)
    report = json.loads(result.stdout)
    assert report["network_used"] is False
    assert report["public_source_status"] == "fixture"

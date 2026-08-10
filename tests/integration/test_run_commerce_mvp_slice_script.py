from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
FIXTURE = "tests/fixtures/commerce_mvp/public_signals.json"

def _run(*args: str): return subprocess.run([sys.executable, "scripts/run_commerce_mvp_slice.py", *args], cwd=ROOT, text=True, capture_output=True, check=True)
def test_cli_json_markdown_and_explicit_jsonl_write() -> None:
    first = _run("--fixture", FIXTURE, "--query", "portable espresso maker", "--json")
    assert first.stdout == _run("--fixture", FIXTURE, "--query", "portable espresso maker", "--json").stdout
    assert json.loads(first.stdout)["metadata"]["provider_calls"] is False
    assert "No provider" in _run("--fixture", FIXTURE, "--query", "portable espresso maker", "--markdown").stdout
    target = ROOT / "artifacts/test-commerce-mvp-events.jsonl"
    try:
        _run("--fixture", FIXTURE, "--query", "portable espresso maker", "--write-jsonl", "artifacts/test-commerce-mvp-events.jsonl", "--json")
        assert len(target.read_text(encoding="utf-8").splitlines()) >= 10
    finally: target.unlink(missing_ok=True)

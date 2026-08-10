from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = "tests/fixtures/competition_intelligence/competitor_urls.json"


def _run(*args: str):
    return subprocess.run([sys.executable, "scripts/run_competition_intelligence_scan.py", *args], cwd=ROOT, text=True, capture_output=True, check=True)


def test_cli_dry_run_never_touches_network_and_degrades_honestly():
    result = _run("--query", "portable espresso maker", "--competitor-urls-fixture", FIXTURE, "--json")
    payload = json.loads(result.stdout)
    assert payload["network_used"] is False
    assert payload["observed_competitor_count"] == 0
    assert payload["read_only"] is True
    assert payload["mutated"] is False


def test_cli_json_output_is_structurally_stable_across_invocations():
    # gather_market_intelligence() itself is deterministic given an
    # explicit generated_at (see tests/test_competition_intelligence.py's
    # test_deterministic_given_identical_inputs); the CLI doesn't pin one,
    # so every wall-clock timestamp in the payload (generated_at,
    # crawl_timestamp per offer) legitimately varies between invocations --
    # this only asserts the non-timestamp content is stable.
    first = json.loads(_run("--query", "portable espresso maker", "--competitor-urls-fixture", FIXTURE, "--json").stdout)
    second = json.loads(_run("--query", "portable espresso maker", "--competitor-urls-fixture", FIXTURE, "--json").stdout)
    for payload in (first, second):
        assert payload["observed_competitor_count"] == 0
        assert payload["event_type_counts"] == {"competition_observed": 2, "competition_summary_created": 1, "market_pricing_computed": 1, "market_intelligence_completed": 1}
    assert first["event_count"] == second["event_count"]
    assert first["market_saturation"] == second["market_saturation"]


def test_cli_markdown_output():
    result = _run("--query", "portable espresso maker", "--competitor-urls-fixture", FIXTURE, "--markdown")
    assert "Competition Intelligence scan" in result.stdout
    assert "Advisory only" in result.stdout


def test_cli_rejects_both_json_and_markdown():
    result = subprocess.run(
        [sys.executable, "scripts/run_competition_intelligence_scan.py", "--query", "x", "--json", "--markdown"],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode != 0
    assert "choose --json or --markdown" in result.stderr


def test_cli_rejects_competitor_urls_and_fixture_combined():
    result = subprocess.run(
        [sys.executable, "scripts/run_competition_intelligence_scan.py", "--query", "x", "--competitor-urls", "https://example.com/a",
         "--competitor-urls-fixture", FIXTURE, "--json"],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode != 0
    assert "cannot be combined" in result.stderr


def test_cli_writes_explicit_jsonl():
    target = ROOT / "artifacts/test-competition-intelligence-events.jsonl"
    try:
        _run("--query", "portable espresso maker", "--competitor-urls-fixture", FIXTURE, "--write-jsonl", "artifacts/test-competition-intelligence-events.jsonl", "--json")
        lines = target.read_text(encoding="utf-8").splitlines()
        assert len(lines) >= 1
        assert all(json.loads(line)["event_type"] for line in lines)
    finally:
        target.unlink(missing_ok=True)


def test_cli_margin_computed_when_supplier_cost_supplied():
    result = _run("--query", "portable espresso maker", "--competitor-urls-fixture", FIXTURE, "--supplier-unit-cost", "9.5", "--supplier-shipping-cost", "2.0", "--json")
    payload = json.loads(result.stdout)
    assert "margin" in payload
    assert payload["margin"]["provenance"]["supplier_cost"] == "observed"

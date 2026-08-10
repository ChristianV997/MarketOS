from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = "tests/fixtures/commerce_mvp/public_signals.json"


def _run(*args: str):
    return subprocess.run([sys.executable, "scripts/run_product_research_engine.py", *args], cwd=ROOT, text=True, capture_output=True, check=True)


def test_cli_fixture_mode_json_output():
    result = _run("--fixture", FIXTURE, "--json")
    payload = json.loads(result.stdout)
    assert payload["read_only"] is True
    assert payload["mutated"] is False
    assert payload["network_used"] is False
    assert len(payload["candidate_ids"]) >= 1
    assert "quality" in payload


def test_cli_markdown_portfolio_report():
    result = _run("--fixture", FIXTURE, "--markdown")
    assert "Product Research portfolio" in result.stdout
    assert "Advisory only" in result.stdout


def test_cli_markdown_cluster_report():
    result = _run("--fixture", FIXTURE, "--markdown", "--clusters")
    assert "Product Research clusters" in result.stdout
    assert "Members:" in result.stdout


def test_cli_rejects_both_json_and_markdown():
    result = subprocess.run(
        [sys.executable, "scripts/run_product_research_engine.py", "--fixture", FIXTURE, "--json", "--markdown"],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode != 0
    assert "choose --json or --markdown" in result.stderr


def test_cli_requires_fixture_or_public_query():
    result = subprocess.run([sys.executable, "scripts/run_product_research_engine.py", "--json"], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode != 0
    assert "--fixture or --public-query is required" in result.stderr


def test_cli_writes_explicit_jsonl():
    target = ROOT / "artifacts/test-product-research-events.jsonl"
    try:
        _run("--fixture", FIXTURE, "--write-jsonl", "artifacts/test-product-research-events.jsonl", "--json")
        lines = target.read_text(encoding="utf-8").splitlines()
        assert len(lines) >= 1
        assert all(json.loads(line)["event_type"] for line in lines)
    finally:
        target.unlink(missing_ok=True)


def test_cli_comparison_round_trips_against_prior_json_output(tmp_path):
    # pathlib's `/` operator returns the right side unchanged when it is
    # already absolute, so an absolute tmp_path works directly against the
    # CLI's `ROOT / args.previous_portfolio_json` resolution.
    previous_path = tmp_path / "previous.json"
    first = _run("--fixture", FIXTURE, "--json")
    previous_path.write_text(first.stdout, encoding="utf-8")
    second = _run("--fixture", FIXTURE, "--previous-portfolio-json", str(previous_path), "--json")
    payload = json.loads(second.stdout)
    assert "comparison" in payload
    assert all(m["change_kind"] == "unchanged" for m in payload["comparison"]["movements"])


def test_cli_deterministic_bucket_placement_across_invocations():
    first = json.loads(_run("--fixture", FIXTURE, "--json").stdout)
    second = json.loads(_run("--fixture", FIXTURE, "--json").stdout)
    assert first["top_opportunities"] == second["top_opportunities"]
    assert first["high_uncertainty_opportunities"] == second["high_uncertainty_opportunities"]

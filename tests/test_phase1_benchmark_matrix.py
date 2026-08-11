from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest
from evaluation.commerce.benchmark_matrix import build_benchmark_from_paths, build_benchmark_matrix, default_candidates, evaluate_candidate, normalize_candidate, supplier_score, competition_score

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "tests/fixtures/benchmark_matrix/candidates.json"

def test_default_report_is_fixture_safe_and_deterministic():
    first = build_benchmark_matrix().to_dict(); assert first == build_benchmark_matrix().to_dict()
    assert first["evidence_mode"] == "fixture_demo" and first["network_calls"] is False and first["mutated"] is False
    assert first["candidate_count"] == 6

def test_seed_parses_and_top_candidate_is_deterministic():
    report = build_benchmark_from_paths(candidate_seed=SEED).to_dict()
    assert report["candidate_count"] == 6
    assert report["top_candidate_id"] == "mini-thermal-printer"

@pytest.mark.parametrize("fields,expected", [([], 0), (["price"], .32), (["price", "sku", "inventory", "variant", "shipping", "delivery"], 1.0)])
def test_supplier_score_observation_weights(fields, expected):
    value = supplier_score({"observed_fields": fields, "source_type": "unavailable"})
    assert value.score == expected

@pytest.mark.parametrize("offers,coverage,minimum", [(0, 0, 0), (1, .25, .1), (3, 1, .75)])
def test_competition_score_increases_with_observed_pricing(offers, coverage, minimum):
    assert competition_score({"observed_offers": offers, "pricing_coverage": coverage}).score >= minimum

def test_low_margin_candidate_is_rejected():
    candidate = next(item for item in default_candidates() if item.candidate_id == "led-therapy-mask")
    snapshot = evaluate_candidate(candidate)
    assert snapshot.commercial_decision == "reject_insufficient_margin"

def test_missing_supplier_credentials_hold_high_opportunity_candidate():
    candidate = next(item for item in default_candidates() if item.candidate_id == "portable-espresso-maker")
    assert evaluate_candidate(candidate).commercial_decision == "hold_for_credentials"

def test_observed_supplier_and_competition_can_advance_to_deployment():
    candidate = normalize_candidate({"candidate_id":"ready","title":"Ready","supplier_evidence":{"source_type":"authenticated_live","observed_fields":["price","sku","inventory","variant","shipping","delivery"],"confidence":.9},"competition_evidence":{"observed_offers":3,"pricing_coverage":1,"sources":["a","b","c"],"availability_observed":True,"reviews_observed":True},"opportunity_score":.8,"commerce_run":{"gross_margin":.45,"assumption_ratio":.1}})
    assert evaluate_candidate(candidate).commercial_decision == "ready_for_readonly_deployment"

def test_malformed_seed_degrades(tmp_path):
    path = tmp_path / "bad.json"; path.write_text("[]", encoding="utf-8")
    report = build_benchmark_from_paths(candidate_seed=path).to_dict()
    assert report["candidate_count"] == 0 and report["status"] == "degraded"

@pytest.mark.parametrize("key", ["CJ_API_KEY", "authorization", "email"])
def test_seed_secret_like_fields_are_redacted(tmp_path, key):
    path = tmp_path / "seed.json"; path.write_text(json.dumps({"candidates":[{"candidate_id":"x","title":"x",key:"Bearer secret-token-123456789"}]}), encoding="utf-8")
    report = build_benchmark_from_paths(candidate_seed=path).to_dict()
    assert "secret-token" not in json.dumps(report)

def test_cli_json_markdown_and_output(tmp_path):
    command = [sys.executable, "scripts/phase1_benchmark_matrix.py", "--candidate-seed", str(SEED), "--json"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["top_candidate_id"] == "mini-thermal-printer"
    markdown = subprocess.run(command[:-1] + ["--markdown"], cwd=ROOT, capture_output=True, text=True, check=True)
    assert "# Phase 1 Evidence Benchmark Matrix" in markdown.stdout
    output = tmp_path / "out"; subprocess.run(command + ["--output", str(output)], cwd=ROOT, capture_output=True, text=True, check=True)
    assert (output / "benchmark_matrix_report.json").exists()

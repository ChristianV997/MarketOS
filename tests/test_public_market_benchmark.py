from __future__ import annotations

import json
from pathlib import Path

from backend.adapters.research.competition_evidence import CompetitorOffer
from evaluation.commerce.public_market_benchmark import build_public_market_benchmark, load_public_market_seed, markdown_report
from scripts.run_phase1_public_market_benchmark import main


ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "tests" / "fixtures" / "public_market_benchmark" / "candidates.json"


def test_fixture_seed_is_bounded_and_deterministic():
    candidates, warnings = load_public_market_seed(SEED)
    one = build_public_market_benchmark(candidates, max_candidates=3).to_dict()
    two = build_public_market_benchmark(candidates, max_candidates=3).to_dict()
    assert not warnings
    assert one == two
    assert one["network_used"] is False
    assert one["competitor_offers_observed"] == 3
    assert one["top_candidate_from_public_market"] == "mini-thermal-printer"


def test_fixture_evidence_is_explicitly_not_live_proof():
    candidates, _ = load_public_market_seed(SEED)
    report = build_public_market_benchmark(candidates, max_candidates=1).to_dict()
    assert report["evidence_mode"] == "fixture_demo"
    assert report["warnings"] == ["fixture_demo_evidence_only_not_live_proof"]
    assert report["next_best_action"].startswith("set_cj_credentials_and_validate_candidate:")
    assert "supplier" in report["remaining_supplier_blocker"]


def test_live_mode_is_bounded_and_uses_injected_fetcher_only():
    candidates, _ = load_public_market_seed(SEED)
    calls: list[str] = []
    def fetch(url: str, *, context):
        calls.append(url)
        return CompetitorOffer("fixture", url, 1.0, "listing", "Observed offer", {"title": "observed", "price": "observed"}, price=42.0, confidence=0.6)
    report = build_public_market_benchmark(candidates, allow_network=True, max_candidates=1, max_competitors_per_candidate=1, fetcher=fetch).to_dict()
    assert calls == ["https://example-shop.test/products/mini-printer"]
    assert report["network_used"] is True
    assert report["competitor_pages_attempted"] == 1
    assert report["competitor_offers_observed"] == 1


def test_sanitized_evidence_removes_url_query_values():
    candidate = {"candidate_id": "safe", "title": "Safe", "query": "safe", "category": "test", "competitor_urls": [], "fixture_offers": [{"competitor_url": "https://public.example/p?a=secret-token", "source_domain": "public.example", "product_title": "Safe", "price": 1.0, "source_confidence": 1.0}]}
    evidence = build_public_market_benchmark([candidate]).to_dict()["candidate_results"][0]["evidence"][0]
    assert evidence["competitor_url"] == "https://public.example/p"
    assert "secret-token" not in json.dumps(evidence)


def test_malformed_seed_degrades_without_crashing(tmp_path: Path):
    path = tmp_path / "bad.json"; path.write_text("not-json", encoding="utf-8")
    candidates, warnings = load_public_market_seed(path)
    assert candidates == []
    assert warnings == ["candidate_seed_unavailable:JSONDecodeError"]


def test_markdown_has_no_raw_html_or_authority_claim():
    candidates, _ = load_public_market_seed(SEED)
    rendered = markdown_report(build_public_market_benchmark(candidates, max_candidates=2).to_dict())
    assert "Public-market evidence is read-only market context" in rendered
    assert "<html" not in rendered.lower()


def test_cli_writes_only_when_output_is_explicit(tmp_path: Path, capsys):
    output = tmp_path / "report"
    assert main(["--candidate-seed", str(SEED), "--output", str(output), "--json"]) == 0
    assert (output / "public_market_benchmark_report.json").is_file()
    assert (output / "benchmark_matrix_report.json").is_file()
    assert (output / "readiness_summary.json").is_file()
    assert "fixture_demo" in capsys.readouterr().out

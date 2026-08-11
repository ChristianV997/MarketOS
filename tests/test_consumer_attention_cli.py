from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.adapters.research.consumer_attention import import_json
from evaluation.commerce.consumer_attention import build_report
from evaluation.commerce.product_validation_report import generate, markdown
from evaluation.commerce.opportunity_synthesis import build_synthesis_report
from scripts.run_consumer_attention_intelligence import main

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "consumer_attention"


def test_default_json_is_deterministic(capsys):
    main(["--json"])
    first = json.loads(capsys.readouterr().out)
    main(["--json"])
    second = json.loads(capsys.readouterr().out)
    assert first == second


def test_markdown_contains_attention_and_safety(capsys):
    main(["--markdown"])
    output = capsys.readouterr().out
    assert "Consumer Attention and Creative Evidence" in output
    assert "not ad authorization" in output
    assert "mini-thermal-printer" in output


def test_candidate_seed_is_safe_empty_evidence(capsys):
    main(["--candidate-seed", str(FIXTURES / "candidates.json"), "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["candidate_count"] == 10
    assert report["warnings"] == ["consumer_attention_is_not_supplier_proof"]


def test_manual_import_mode(capsys):
    main(["--manual-import", str(FIXTURES / "reddit_comments_manual_import.csv"), "--source", "reddit", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["evidence_mode"] == "manual_import"
    assert report["platforms_observed"] == ["reddit"]


@pytest.mark.parametrize("source,file_name", [("tiktok", "tiktok_ad_snapshot.json"), ("meta", "meta_ad_library_snapshot.json"), ("google_trends", "google_trends_fixture.json")])
def test_source_filter(source, file_name, capsys):
    main(["--candidate-seed", str(FIXTURES / file_name), "--source", source, "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["platforms_observed"] == [source]


def test_output_writes_sanitized_files(tmp_path, capsys):
    main(["--output", str(tmp_path), "--json"])
    capsys.readouterr()
    assert {path.name for path in tmp_path.iterdir()} == {"consumer_attention_report.json", "consumer_attention_report.md", "consumer_source_summary.json", "creative_angle_summary.md"}
    output = " ".join(path.read_text(encoding="utf8") for path in tmp_path.iterdir())
    assert "Bearer " not in output
    assert "API_KEY" not in output


def test_creative_summary_contains_hooks(tmp_path, capsys):
    main(["--output", str(tmp_path), "--json"])
    capsys.readouterr()
    summary = (tmp_path / "creative_angle_summary.md").read_text(encoding="utf8")
    assert "Hooks:" in summary


def test_invalid_path_is_reported(capsys, tmp_path):
    with pytest.raises(SystemExit):
        main(["--candidate-seed", str(tmp_path / "missing.json"), "--json"])
    assert "does not exist" in capsys.readouterr().err


def test_json_and_markdown_are_exclusive():
    with pytest.raises(SystemExit):
        main(["--json", "--markdown"])


def test_product_report_accepts_attention_report():
    rows = import_json(FIXTURES / "tiktok_creative_center_snapshot.json", platform="tiktok", source_type="tiktok_creative_center_snapshot")
    report = generate(consumer_attention=build_report(rows).to_dict()).to_dict()
    section = report["executive_summary"]["consumer_attention_signals"]
    assert section["status"] == "supplied"
    assert section["top_candidate"] == "mini-thermal-printer"


def test_product_report_markdown_contains_attention_section():
    rows = import_json(FIXTURES / "tiktok_creative_center_snapshot.json", platform="tiktok", source_type="tiktok_creative_center_snapshot")
    report = generate(consumer_attention=build_report(rows).to_dict()).to_dict()
    output = markdown(report)
    assert "## Consumer Attention Signals" in output
    assert "mini-thermal-printer" in output


def test_product_report_without_attention_degrades():
    report = generate().to_dict()
    assert report["executive_summary"]["consumer_attention_signals"]["status"] == "consumer_attention_not_supplied"


def test_three_way_synthesis_has_consumer_attention():
    market = {"candidates": [{"candidate_id": "x", "score": {"overall_marketplace_opportunity": 0.8}}]}
    supplier = {"candidates": [{"candidate_id": "x", "score": {"overall_supplier_feasibility": 0.75, "recommendation": "hold_for_manual_review"}}]}
    consumer = {"candidates": [{"candidate_id": "x", "score": {"overall_consumer_attention": 0.7, "recommendation": "generate_creative_tests", "objection_density": 0.1}}]}
    report = build_synthesis_report(market, supplier, consumer)
    item = report["candidates"][0]
    assert item["consumer_attention"] == 0.7
    assert "combined_risk" in item


def test_three_way_synthesis_rejects_attention_risk():
    consumer = {"candidates": [{"candidate_id": "x", "score": {"overall_consumer_attention": 0.2, "recommendation": "reject_low_attention", "objection_density": 0.2}}]}
    report = build_synthesis_report(None, None, consumer)
    assert report["candidates"][0]["combined_recommendation"] == "reject_low_attention"


def test_three_way_synthesis_requires_supplier_when_attention_is_strong():
    consumer = {"candidates": [{"candidate_id": "x", "score": {"overall_consumer_attention": 0.8, "recommendation": "validate_supplier_first"}}]}
    report = build_synthesis_report(None, None, consumer)
    assert report["next_best_action"] == "validate_live_supplier_first:x"


def test_attention_report_json_is_safe():
    rows = import_json(FIXTURES / "tiktok_creative_center_snapshot.json", platform="tiktok", source_type="tiktok_creative_center_snapshot")
    payload = build_report(rows).to_dict()
    json.dumps(payload)
    assert payload["mutated"] is False

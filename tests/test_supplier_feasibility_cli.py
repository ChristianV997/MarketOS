"""CLI and Product Validation Report integration tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_supplier_feasibility_intelligence import main
from evaluation.commerce.opportunity_synthesis import build_synthesis_report
from backend.adapters.research.supplier_feasibility import import_cj_validation_pack
from evaluation.commerce.supplier_feasibility import build_report
from evaluation.commerce.product_validation_report import generate, markdown

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "supplier_feasibility"


def test_default_json_is_deterministic(capsys):
    main(["--json"])
    first = json.loads(capsys.readouterr().out)
    main(["--json"])
    second = json.loads(capsys.readouterr().out)
    assert first == second
    assert first["read_only"] and not first["network_calls"] and not first["mutated"]


def test_markdown_contains_feasibility_sections(capsys):
    main(["--markdown"])
    output = capsys.readouterr().out
    assert "Supplier Feasibility Intelligence" in output
    assert "not supplier authorization" in output
    assert "mini-thermal-printer" in output


def test_candidate_seed_is_offline_and_safe(capsys):
    main(["--candidate-seed", str(FIXTURES / "candidates.json"), "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["candidate_count"] == 10
    assert report["warnings"] == ["supplier_feasibility_is_not_live_supplier_authorization"]


def test_manual_cj_import(capsys):
    main(["--manual-import", str(FIXTURES / "cj_manual_import.csv"), "--supplier", "cj", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["evidence_mode"] == "manual_import"
    assert report["suppliers_observed"] == ["cj"]


@pytest.mark.parametrize("supplier,file_name", [("alibaba", "alibaba_supplier_snapshot.json"), ("aliexpress", "aliexpress_supplier_snapshot.json")])
def test_supplier_filter_with_local_json(supplier, file_name, capsys):
    main(["--candidate-seed", str(FIXTURES / file_name), "--supplier", supplier, "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["suppliers_observed"] == [supplier]


def test_output_writes_only_sanitized_files(tmp_path, capsys):
    main(["--output", str(tmp_path), "--json"])
    capsys.readouterr()
    assert {path.name for path in tmp_path.iterdir()} == {"supplier_feasibility_report.json", "supplier_feasibility_report.md", "supplier_source_summary.json"}
    payload = (tmp_path / "supplier_feasibility_report.json").read_text(encoding="utf8")
    assert "CJ_API_KEY" not in payload
    assert "CJ_API_KEY" not in payload
    assert "Bearer " not in payload


def test_report_target_price_adds_economics(capsys):
    main(["--target-sell-price", "30", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["candidates"][0]["score"]["economics"]["target_sell_price"] == 30


def test_invalid_path_is_reported(capsys, tmp_path):
    with pytest.raises(SystemExit):
        main(["--candidate-seed", str(tmp_path / "missing.json"), "--json"])
    assert "does not exist" in capsys.readouterr().err


def test_json_and_markdown_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        main(["--json", "--markdown"])


def test_zero_candidate_bound_is_rejected():
    with pytest.raises(SystemExit):
        main(["--max-candidates", "0", "--json"])


def test_product_report_includes_supplier_section():
    rows = import_cj_validation_pack(FIXTURES / "cj_validation_pack_success.json")
    supplier = build_report(rows).to_dict()
    report = generate(supplier_feasibility=supplier).to_dict()
    section = report["executive_summary"]["supplier_feasibility_signals"]
    assert section["status"] == "supplied"
    assert section["top_candidate"] == "mini-thermal-printer"
    assert "supplier_feasibility" in report["source_reports"]


def test_product_report_markdown_includes_supplier_section():
    rows = import_cj_validation_pack(FIXTURES / "cj_validation_pack_success.json")
    report = generate(supplier_feasibility=build_report(rows).to_dict()).to_dict()
    text = markdown(report)
    assert "## Supplier Feasibility Signals" in text
    assert "mini-thermal-printer" in text


def test_product_report_without_supplier_report_degrades():
    report = generate().to_dict()
    assert report["executive_summary"]["supplier_feasibility_signals"]["status"] == "supplier_feasibility_not_supplied"


def test_marketplace_and_supplier_reports_synthesize():
    marketplace = {"candidates": [{"candidate_id": "x", "score": {"overall_marketplace_opportunity": 0.8}}]}
    supplier = {"candidates": [{"candidate_id": "x", "score": {"overall_supplier_feasibility": 0.7, "recommendation": "hold_for_manual_review"}}]}
    report = build_synthesis_report(marketplace, supplier)
    assert report["top_candidate_id"] == "x"
    assert report["candidates"][0]["combined_opportunity"] == 0.755


def test_synthesis_rejects_supplier_risk():
    report = build_synthesis_report(
        {"candidates": [{"candidate_id": "x", "score": {"overall_marketplace_opportunity": 0.9}}]},
        {"candidates": [{"candidate_id": "x", "score": {"overall_supplier_feasibility": 0.6, "recommendation": "reject_poor_margin"}}]},
    )
    assert report["candidates"][0]["combined_recommendation"] == "reject_poor_margin"


def test_synthesis_without_supplier_report_requires_validation():
    report = build_synthesis_report({"candidates": [{"candidate_id": "x", "score": {"overall_marketplace_opportunity": 0.8}}]}, None)
    assert report["next_best_action"] == "validate_live_supplier_first:x"


def test_synthesis_is_safe():
    report = build_synthesis_report(None, None)
    assert report["read_only"] and not report["network_calls"] and not report["mutated"]

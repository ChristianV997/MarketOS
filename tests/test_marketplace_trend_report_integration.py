"""Product Validation Report integration for marketplace trend evidence."""
from __future__ import annotations

import json
from pathlib import Path

from evaluation.commerce.marketplace_trends import build_report
from evaluation.commerce.product_validation_report import generate, markdown
from backend.adapters.research.marketplace_trends import import_amazon_best_sellers

ROOT = Path(__file__).resolve().parents[1]


def trend_report() -> dict:
    rows = import_amazon_best_sellers(ROOT / "tests/fixtures/marketplace_trends/amazon_best_sellers_snapshot.json")
    return build_report(rows).to_dict()


def test_report_accepts_marketplace_trend_report():
    report = generate(client_name="Demo", marketplace_trends=trend_report()).to_dict()
    signals = report["executive_summary"]["marketplace_demand_signals"]
    assert signals["status"] == "supplied"
    assert signals["top_candidate"] == "mini-thermal-printer"


def test_report_preserves_supplier_blocker_with_marketplace_signals():
    report = generate(marketplace_trends=trend_report()).to_dict()
    assert report["overall_recommendation"] == "validate_supplier_first"
    assert report["supplier_evidence"]["proof_present"] is False


def test_report_markdown_contains_marketplace_section():
    report = generate(marketplace_trends=trend_report()).to_dict()
    text = markdown(report)
    assert "## Marketplace Demand Signals" in text
    assert "mini-thermal-printer" in text
    assert "not supplier proof" in text


def test_report_missing_trends_degrades_cleanly():
    report = generate().to_dict()
    assert report["executive_summary"]["marketplace_demand_signals"]["status"] == "marketplace_trends_not_supplied"
    assert report["source_reports"]["marketplace_trends"] == "marketplace_trends_not_supplied"


def test_report_json_is_safe_to_serialize():
    report = generate(marketplace_trends=trend_report()).to_dict()
    json.dumps(report)
    assert report["read_only"] is True
    assert report["network_calls"] is False
    assert report["mutated"] is False


def test_report_marketplace_section_exposes_saturation():
    report = generate(marketplace_trends=trend_report()).to_dict()
    assert 0 <= report["executive_summary"]["marketplace_demand_signals"]["saturation"] <= 1

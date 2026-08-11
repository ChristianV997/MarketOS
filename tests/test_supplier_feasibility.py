"""Deterministic supplier-feasibility model and importer tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.adapters.research.supplier_feasibility import (
    SupplierImportError,
    contains_secret,
    import_alibaba,
    import_aliexpress,
    import_csv,
    import_cj_validation_pack,
    import_json,
    normalize_record,
    validate_input_path,
)
from evaluation.commerce.supplier_feasibility import (
    PROVENANCE,
    SOURCE_TYPES,
    SUPPLIERS,
    SupplierFeasibilityEvidence,
    build_report,
    calculate_unit_economics,
    collapse_duplicates,
    normalize_delivery_window,
    normalize_inventory_status,
    score_candidate,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "supplier_feasibility"


def fixture(name: str) -> Path:
    return FIXTURES / name


def test_supplier_vocabulary_is_bounded():
    assert SUPPLIERS == {"cj", "alibaba", "aliexpress", "zendrop", "autods", "dsers", "spocket", "manual"}


def test_provenance_has_live_readonly_without_authorizing_mutation():
    assert "live_readonly" in PROVENANCE
    assert "mutated" not in PROVENANCE


def test_source_types_include_each_requested_family():
    for source in ("cj_validation_pack_report", "cj_manual_import", "alibaba_supplier_snapshot", "alibaba_high_profit_snapshot", "aliexpress_supplier_snapshot", "zendrop_manual_import", "autods_manual_import", "dsers_manual_import", "spocket_manual_import", "manual_csv_import"):
        assert source in SOURCE_TYPES


@pytest.mark.parametrize(
    "value,expected",
    [("7-15 days", (7, 15)), ("10 days", (10, 10)), ("7–14", (7, 14)), ([3, 9], (3, 9)), (None, (None, None)), ("unknown", (None, None))],
)
def test_delivery_window_normalization(value, expected):
    assert normalize_delivery_window(value) == expected


@pytest.mark.parametrize("value,quantity,expected", [("available", None, "in_stock"), ("out of stock", None, "out_of_stock"), ("", 5, "in_stock"), ("", 0, "out_of_stock"), ("", None, "unknown"), ("ready", None, "in_stock")])
def test_inventory_normalization(value, quantity, expected):
    assert normalize_inventory_status(value, quantity) == expected


@pytest.mark.parametrize("value,expected", [("$12.50", 12.5), ("USD 1,200", 1200), ("€9", 9), (None, None), ("bad", None)])
def test_cost_number_normalization(value, expected):
    row = normalize_record({"candidate_id": "x", "supplier": "cj", "unit_cost": value})
    assert (row.unit_cost if row else None) == expected


def test_cj_success_fixture_normalizes_landed_cost_and_fields():
    rows = import_cj_validation_pack(fixture("cj_validation_pack_success.json"))
    row = rows[0]
    assert row.supplier == "cj"
    assert row.unit_cost == 8.5
    assert row.shipping_cost == 3.25
    assert row.estimated_landed_cost == 11.75
    assert (row.delivery_min_days, row.delivery_max_days) == (7, 12)
    assert row.inventory_status == "in_stock"
    assert row.field_provenance["estimated_landed_cost"] == "derived"


def test_cj_missing_credentials_fixture_keeps_warning_without_secrets():
    rows = import_json(fixture("cj_validation_pack_missing_credentials.json"), supplier="cj", source_type="cj_validation_pack_report")
    assert len(rows) == 1
    assert "credential_missing" in rows[0].warnings
    assert rows[0].unit_cost is None
    assert "synthetic" not in json.dumps(rows[0].to_dict()).lower()


def test_cj_manual_import_is_manual():
    rows = import_csv(fixture("cj_manual_import.csv"), supplier="cj", source_type="cj_manual_import")
    assert len(rows) == 2
    assert all(row.evidence_mode == "manual_import" for row in rows)
    assert all(row.supplier == "cj" for row in rows)


@pytest.mark.parametrize(
    "name,supplier,source",
    [
        ("alibaba_supplier_snapshot.json", "alibaba", "alibaba_supplier_snapshot"),
        ("alibaba_dropshipping_trending_snapshot.json", "alibaba", "alibaba_dropshipping_trending_snapshot"),
        ("alibaba_high_profit_snapshot.json", "alibaba", "alibaba_high_profit_snapshot"),
        ("aliexpress_supplier_snapshot.json", "aliexpress", "aliexpress_supplier_snapshot"),
    ],
)
def test_json_supplier_families(name, supplier, source):
    rows = import_json(fixture(name), supplier=supplier, source_type=source)
    assert len(rows) == 1
    assert rows[0].supplier == supplier
    assert rows[0].source_type == source


@pytest.mark.parametrize(
    "name,supplier,source",
    [
        ("zendrop_manual_import.csv", "zendrop", "zendrop_manual_import"),
        ("autods_manual_import.csv", "autods", "autods_manual_import"),
        ("dsers_manual_import.csv", "dsers", "dsers_manual_import"),
        ("spocket_manual_import.csv", "spocket", "spocket_manual_import"),
    ],
)
def test_manual_supplier_families(name, supplier, source):
    rows = import_csv(fixture(name), supplier=supplier, source_type=source)
    assert len(rows) == 1
    assert rows[0].supplier == supplier
    assert rows[0].source_type == source
    assert rows[0].evidence_mode == "manual_import"


def test_mixed_supplier_csv_keeps_multiple_suppliers():
    rows = import_csv(fixture("mixed_supplier_import.csv"), supplier="manual")
    assert {row.supplier for row in rows} == {"cj", "alibaba", "aliexpress"}
    assert len(rows) == 3


def test_malformed_supplier_csv_degrades_to_empty():
    assert import_csv(fixture("malformed_supplier_import.csv")) == []


def test_secret_like_supplier_json_is_rejected():
    assert import_json(fixture("secret_like_supplier_import_rejected.json"), supplier="cj") == []


@pytest.mark.parametrize("payload", [{"api_key": "secret"}, {"authorization": "Bearer secret"}, {"cookie": "private"}, {"nested": {"token": "secret"}}])
def test_secret_detection_catches_forbidden_keys(payload):
    assert contains_secret(payload)


def test_secret_detection_does_not_flag_normal_product_values():
    assert not contains_secret({"candidate_id": "x", "supplier_title": "Safe product", "unit_cost": 4})


def test_path_traversal_is_rejected():
    with pytest.raises(SupplierImportError):
        validate_input_path(FIXTURES / ".." / "secrets.json")


def test_unsupported_file_type_is_rejected(tmp_path):
    target = tmp_path / "input.txt"
    target.write_text("private", encoding="utf8")
    with pytest.raises(SupplierImportError):
        validate_input_path(target)


def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(SupplierImportError):
        validate_input_path(tmp_path / "missing.json")


def test_nested_product_shape_is_supported():
    row = normalize_record({"candidate_id": "x", "supplier": "cj", "product": {"unit_cost": "$8", "shipping_cost": "$2", "delivery_window": "5-9 days"}})
    assert row is not None
    assert row.unit_cost == 8
    assert row.estimated_landed_cost == 10
    assert row.delivery_max_days == 9


def test_missing_candidate_id_is_skipped():
    assert normalize_record({"supplier": "cj", "unit_cost": 5}) is None


def test_unknown_supplier_is_skipped():
    assert normalize_record({"candidate_id": "x", "supplier": "unknown", "unit_cost": 5}) is None


def test_unknown_source_type_uses_safe_default():
    row = normalize_record({"candidate_id": "x", "supplier": "cj", "source_type": "private_response", "unit_cost": 5})
    assert row is not None
    assert row.source_type == "fixture_demo"


def test_duplicate_supplier_offers_keep_best_confidence():
    rows = import_cj_validation_pack(fixture("cj_validation_pack_success.json"))
    first = rows[0]
    second = normalize_record({**first.to_dict(), "source_confidence": 0.99, "shipping_cost": 2})
    assert second is not None
    result = collapse_duplicates([first, second])
    assert len(result) == 1
    assert result[0].source_confidence == 0.99


def test_evidence_json_is_safe_and_read_only():
    row = import_cj_validation_pack(fixture("cj_validation_pack_success.json"))[0]
    json.dumps(row.to_dict())
    assert row.read_only and not row.network_calls and not row.mutated


def test_evidence_rejects_mutation_flag():
    with pytest.raises(ValueError):
        SupplierFeasibilityEvidence("x", "x", "cj", "fixture_demo", mutated=True)


@pytest.mark.parametrize("sell,cost,shipping,expected", [(30, 10, 5, 12.63), (30, 10, None, 17.63), (30, None, 5, None), (None, 10, 5, None)])
def test_unit_economics_profit(sell, cost, shipping, expected):
    scenario = calculate_unit_economics(target_sell_price=sell, unit_cost=cost, shipping_cost=shipping)
    if expected is None:
        assert scenario.gross_margin is None
    else:
        assert round(scenario.gross_margin or 0, 2) == round(expected, 2)


def test_unit_economics_derives_landed_cost():
    scenario = calculate_unit_economics(target_sell_price=40, unit_cost=10, shipping_cost=5)
    assert scenario.estimated_landed_cost == 15
    assert scenario.profit_per_order_before_ad_spend == scenario.gross_margin


def test_unit_economics_marks_shipping_assumption():
    scenario = calculate_unit_economics(target_sell_price=40, unit_cost=10)
    assert "shipping_cost_missing" in scenario.assumptions


def test_unit_economics_calculates_break_even_cpa_and_roas():
    scenario = calculate_unit_economics(target_sell_price=40, unit_cost=10, shipping_cost=5)
    assert scenario.break_even_cpa is not None
    assert scenario.break_even_roas is not None
    assert scenario.break_even_roas > 1


def test_unit_economics_does_not_hide_negative_margin():
    scenario = calculate_unit_economics(target_sell_price=20, unit_cost=18, shipping_cost=8)
    assert (scenario.gross_margin or 0) < 0
    assert scenario.break_even_roas is None


def test_no_supplier_evidence_requires_live_validation():
    score = score_candidate("x", [])
    assert score.recommendation == "validate_live_supplier_first"
    assert "no_supplier_evidence" in score.reasons


def test_cj_fixture_has_cost_and_inventory_confidence():
    row = import_cj_validation_pack(fixture("cj_validation_pack_success.json"))[0]
    score = score_candidate(row.candidate_id, [row], target_sell_price=29.99)
    assert score.supplier_cost_confidence > 0
    assert score.inventory_confidence > 0


def test_missing_shipping_adds_risk():
    row = normalize_record({"candidate_id": "x", "supplier": "cj", "unit_cost": 5, "inventory_status": "in_stock"})
    assert row is not None
    score = score_candidate("x", [row], target_sell_price=30)
    assert "shipping_cost_missing" in score.reasons


def test_high_moq_adds_risk():
    row = normalize_record({"candidate_id": "x", "supplier": "cj", "unit_cost": 5, "shipping_cost": 2, "delivery_window": "5-9", "moq": 50})
    assert row is not None
    assert "high_moq" in score_candidate("x", [row], target_sell_price=30).reasons


def test_long_delivery_recommends_logistics_risk():
    row = normalize_record({"candidate_id": "x", "supplier": "cj", "unit_cost": 5, "shipping_cost": 2, "delivery_window": "40-60", "inventory_status": "in_stock"})
    assert row is not None
    assert score_candidate("x", [row], target_sell_price=30).recommendation == "reject_logistics_risk"


def test_out_of_stock_recommends_inventory_risk():
    row = normalize_record({"candidate_id": "x", "supplier": "cj", "unit_cost": 5, "shipping_cost": 2, "delivery_window": "5-9", "inventory_status": "out_of_stock"})
    assert row is not None
    assert score_candidate("x", [row], target_sell_price=30).recommendation == "reject_inventory_risk"


def test_low_margin_recommends_poor_margin():
    row = normalize_record({"candidate_id": "x", "supplier": "cj", "unit_cost": 18, "shipping_cost": 8, "delivery_window": "5-9", "inventory_status": "in_stock"})
    assert row is not None
    assert score_candidate("x", [row], target_sell_price=30).recommendation == "reject_poor_margin"


def test_high_quality_live_readonly_evidence_can_advance():
    row = normalize_record({"candidate_id": "x", "supplier": "cj", "source_type": "cj_validation_pack_report", "unit_cost": 5, "shipping_cost": 2, "delivery_window": "3-7", "inventory_status": "in_stock", "inventory_quantity": 1000, "supplier_rating": 4.9, "supplier_review_count": 5000, "fulfillment_method": "domestic_fulfillment", "source_confidence": 1, "field_provenance": {"unit_cost": "live_readonly", "shipping_cost": "live_readonly"}}, mode="live_readonly")
    assert row is not None
    score = score_candidate("x", [row], target_sell_price=30)
    assert score.overall_supplier_feasibility > 0.5


def test_score_contributions_are_explainable():
    row = import_cj_validation_pack(fixture("cj_validation_pack_success.json"))[0]
    score = score_candidate(row.candidate_id, [row], target_sell_price=30)
    assert set(score.contributions) >= {"supplier_cost_confidence", "delivery_risk_score", "margin_feasibility_proxy"}
    json.dumps(score.to_dict())


def test_fixture_confidence_is_lower_than_live_readonly():
    fixture_row = import_cj_validation_pack(fixture("cj_validation_pack_success.json"))[0]
    live_row = normalize_record({**fixture_row.to_dict(), "field_provenance": {"unit_cost": "live_readonly"}}, mode="live_readonly")
    assert live_row is not None
    assert score_candidate("x", [live_row]).supplier_cost_confidence > score_candidate("x", [fixture_row]).supplier_cost_confidence


def test_report_selects_top_candidate_and_supplier():
    rows = import_cj_validation_pack(fixture("cj_validation_pack_success.json"))
    report = build_report(rows).to_dict()
    assert report["top_candidate_id"] == "mini-thermal-printer"
    assert report["suppliers_observed"] == ["cj"]
    assert report["warnings"] == ["supplier_feasibility_is_not_live_supplier_authorization"]


def test_report_without_evidence_is_explicit():
    report = build_report([]).to_dict()
    assert report["candidate_count"] == 0
    assert report["next_best_action"] == "validate_live_supplier_first"
    assert report["warnings"] == ["supplier_feasibility_not_supplied"]


def test_report_is_deterministically_sorted():
    rows = import_csv(fixture("mixed_supplier_import.csv"))
    first = build_report(rows).to_dict()
    second = build_report(list(reversed(rows))).to_dict()
    assert first == second


def test_missing_credentials_remains_a_warning_not_a_live_success():
    rows = import_json(fixture("cj_validation_pack_missing_credentials.json"), supplier="cj", source_type="cj_validation_pack_report")
    report = build_report(rows).to_dict()
    assert report["candidates"][0]["score"]["recommendation"] == "validate_live_supplier_first"


def test_supplier_feasibility_never_claims_supplier_authorization():
    report = build_report(import_cj_validation_pack(fixture("cj_validation_pack_success.json"))).to_dict()
    assert "authorization" in " ".join(report["warnings"])

"""Deterministic supplier-feasibility model and importer tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.economics import MarketLane
from backend.adapters.research.supplier_feasibility import (
    SupplierImportError,
    client_safe_offer,
    contains_html,
    contains_secret,
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


@pytest.mark.parametrize(
    "payload",
    [
        "<html><body>x</body></html>",
        "<!DOCTYPE html><html></html>",
        "<body>",
        "<script>alert(1)</script>",
        {"supplier_title": "<HTML lang='en'>"},
        b"<!doctype html>",
    ],
)
def test_html_detection_catches_document_markers(payload):
    assert contains_html(payload)


@pytest.mark.parametrize(
    "payload",
    [
        "Widget size < 10cm",
        "a < b",
        {"supplier_title": "Price < $12"},
        {"candidate_id": "x", "unit_cost": 4},
        None,
    ],
)
def test_html_detection_does_not_flag_lone_less_than(payload):
    assert not contains_html(payload)


def test_html_json_import_is_rejected():
    with pytest.raises(SupplierImportError, match="raw HTML"):
        import_json(fixture("html_supplier_import_rejected.json"), supplier="cj")


def test_html_csv_import_is_rejected():
    with pytest.raises(SupplierImportError, match="raw HTML"):
        import_csv(fixture("html_supplier_import_rejected.csv"))


def test_html_in_record_raises():
    with pytest.raises(SupplierImportError, match="raw HTML"):
        normalize_record({"candidate_id": "x", "supplier": "cj", "supplier_title": "<html><body>raw</body></html>", "unit_cost": 5})


def test_less_than_in_title_is_not_html():
    row = normalize_record({"candidate_id": "x", "supplier": "cj", "supplier_title": "Widget size < 10cm", "unit_cost": 5})
    assert row is not None
    assert row.supplier_title == "Widget size < 10cm"


def test_raw_html_file_is_rejected_before_json_parse(tmp_path):
    target = tmp_path / "dump.json"
    target.write_text("<!DOCTYPE html><html><body></body></html>", encoding="utf8")
    with pytest.raises(SupplierImportError, match="raw HTML"):
        import_json(target)


def test_missing_observed_at_is_not_invented():
    rows = import_cj_validation_pack(fixture("cj_validation_pack_success.json"))
    assert rows[0].observed_at == ""


def test_observed_at_is_preserved_when_present():
    row = normalize_record({"candidate_id": "x", "supplier": "cj", "unit_cost": 5, "observed_at": "2026-09-01T12:00:00Z"})
    assert row is not None
    assert row.observed_at == "2026-09-01T12:00:00Z"


def test_stale_evidence_mode_survives_normalize_record():
    row = normalize_record({"candidate_id": "x", "supplier": "cj", "unit_cost": 5, "evidence_mode": "stale"})
    assert row is not None
    assert row.evidence_mode == "stale"


def test_stale_evidence_mode_survives_import_json():
    rows = import_json(fixture("stale_evidence_mode.json"), supplier="cj")
    assert len(rows) == 1
    assert rows[0].evidence_mode == "stale"


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


def test_supplier_report_forwards_market_lane_to_canonical_economics():
    row = normalize_record({"candidate_id": "x", "supplier": "cj", "unit_cost": 10, "shipping_cost": 5, "currency": "MXN", "delivery_window": "5-9", "inventory_status": "in_stock"})
    assert row is not None
    lane = MarketLane("cn-mx", "CN", "CN", "fixture-warehouse", "MX", currency="MXN", tax_rate="0.16")
    score = score_candidate("x", [row], target_sell_price=30, lane=lane)
    assert score.economics is not None
    assert score.economics.currency == "MXN"
    assert score.economics.canonical_economics["currency"] == "MXN"
    report = build_report([row], target_sell_prices={"x": 30}, lane=lane).to_dict()
    assert report["candidates"][0]["score"]["economics"]["currency"] == "MXN"


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


def test_nested_variants_flatten_to_one_row_each():
    rows = import_json(fixture("shopify_woo_nested_variants.json"), supplier="manual")
    assert len(rows) == 2
    assert {row.supplier_sku for row in rows} == {"HOOD-S", "HOOD-M"}
    assert {row.supplier_product_id for row in rows} == {"var-s", "var-m"}
    assert {row.unit_cost for row in rows} == {12.0, 13.5}
    assert {row.inventory_quantity for row in rows} == {10, 6}
    assert all(row.variant_count == 2 for row in rows)
    assert all(row.candidate_id == "cotton-hoodie" for row in rows)
    assert all(row.shipping_cost == 4.0 for row in rows)


def test_integer_variants_still_sets_variant_count():
    row = normalize_record({"candidate_id": "x", "supplier": "cj", "variants": 3, "unit_cost": 5})
    assert row is not None
    assert row.variant_count == 3


def test_cj_dump_keys_map_onto_existing_fields():
    rows = import_json(fixture("cj_dump_key_aliases.json"), supplier="cj", source_type="cj_validation_pack_report")
    assert len(rows) == 1
    row = rows[0]
    assert row.candidate_id == "CJ-PID-THERMAL-001"
    assert row.supplier_product_id == "CJ-PID-THERMAL-001"
    assert row.supplier_title == "Mini Bluetooth Thermal Printer"
    assert row.unit_cost == 8.5
    assert row.moq == 1
    assert (row.delivery_min_days, row.delivery_max_days) == (7, 12)
    assert row.inventory_quantity == 420
    assert row.warehouse_region == "CN"
    assert row.destination_region == "US"
    assert row.supplier_sku == "THERMAL-001"


def test_mixed_currency_is_not_converted():
    rows = import_json(fixture("mixed_currency_eur.json"), supplier="cj")
    assert len(rows) == 1
    assert rows[0].unit_cost == 9.5
    assert rows[0].currency == "EUR"
    assert rows[0].estimated_landed_cost == 11.5
    assert "currency_assumed_usd" not in rows[0].warnings


def test_conflicting_unit_cost_marks_kept_row():
    rows = import_json(fixture("conflicting_unit_cost.json"), supplier="cj")
    assert len(rows) == 1
    assert rows[0].unit_cost == 12
    assert "conflicting_supplier_offer" in rows[0].warnings


def test_similar_titles_with_different_product_ids_do_not_collapse():
    rows = import_json(fixture("alias_titles_do_not_collapse.json"), supplier="cj")
    assert len(rows) == 2
    assert {row.supplier_product_id for row in rows} == {"A-1", "B-2"}
    assert {row.supplier_title for row in rows} == {"Mini Thermal Printer"}


def test_missing_cost_fields_emit_assumption_warnings():
    rows = import_json(fixture("missing_fields.json"), supplier="cj")
    assert len(rows) == 1
    assert rows[0].unit_cost is None
    assert rows[0].shipping_cost is None
    assert rows[0].currency == "USD"
    assert rows[0].source_confidence == 0.55
    assert "unit_cost_unavailable" in rows[0].warnings
    assert "shipping_cost_unavailable" in rows[0].warnings
    assert "currency_assumed_usd" in rows[0].warnings
    assert "source_confidence_defaulted" in rows[0].warnings


def test_derived_landed_cost_adds_warning():
    row = import_cj_validation_pack(fixture("cj_validation_pack_success.json"))[0]
    assert row.field_provenance["estimated_landed_cost"] == "derived"
    assert "landed_cost_derived" in row.warnings


def test_client_safe_offer_strips_nested_secret_and_html():
    row = normalize_record({"candidate_id": "x", "supplier": "cj", "unit_cost": 5, "supplier_title": "Safe product"})
    assert row is not None
    payload = row.to_dict()
    payload["nested"] = {"api_key": "synthetic-secret", "ok": "keep"}
    payload["note"] = "<html><body>raw</body></html>"
    safe = client_safe_offer(payload)
    blob = json.dumps(safe).lower()
    assert "api_key" not in blob
    assert "synthetic-secret" not in blob
    assert "<html" not in blob
    assert safe["nested"]["ok"] == "keep"
    assert "note" not in safe
    assert client_safe_offer(row)["candidate_id"] == "x"


def test_unit_economics_same_currency_preserves_provenance():
    # Same currency (EUR vs EUR)
    scenario_eur = calculate_unit_economics(
        target_sell_price=100.0,
        unit_cost=30.0,
        shipping_cost=10.0,
        cost_currency="EUR",
        lane=MarketLane("cn-de", "CN", "CN", "fixture-warehouse", "DE", currency="EUR"),
    )
    assert scenario_eur.currency == "EUR"
    assert scenario_eur.cost_currency == "EUR"
    assert scenario_eur.shipping_currency == "EUR"
    assert scenario_eur.gross_margin is not None
    assert scenario_eur.gross_margin_percent is not None
    assert "currency_mismatch" not in scenario_eur.assumptions

    # Same currency (MXN vs MXN)
    scenario_mxn = calculate_unit_economics(
        target_sell_price=500.0,
        unit_cost=150.0,
        shipping_cost=50.0,
        cost_currency="MXN",
        lane=MarketLane("cn-mx", "CN", "CN", "fixture-warehouse", "MX", currency="MXN"),
    )
    assert scenario_mxn.currency == "MXN"
    assert scenario_mxn.cost_currency == "MXN"
    assert scenario_mxn.shipping_currency == "MXN"
    assert scenario_mxn.gross_margin is not None
    assert "currency_mismatch" not in scenario_mxn.assumptions


def test_unit_economics_currency_mismatch_fails_closed():
    # EUR supplier offer vs MXN market lane
    row = normalize_record({
        "candidate_id": "eur-offer-1",
        "supplier": "cj",
        "unit_cost": 10.0,
        "shipping_cost": 2.0,
        "currency": "EUR",
        "delivery_window": "5-9",
        "inventory_status": "in_stock",
    })
    assert row is not None
    assert row.currency == "EUR"
    lane = MarketLane("cn-mx", "CN", "CN", "fixture-warehouse", "MX", currency="MXN", tax_rate="0.16")

    score = score_candidate("eur-offer-1", [row], target_sell_price=100.0, lane=lane)

    # Derived economics must be unavailable
    assert score.economics is not None
    assert score.economics.currency == "MXN"
    assert score.economics.cost_currency == "EUR"
    assert score.economics.gross_margin is None
    assert score.economics.gross_margin_percent is None
    assert score.economics.break_even_cpa is None
    assert score.economics.break_even_roas is None
    assert score.economics.profit_per_order_before_ad_spend is None
    assert "currency_mismatch" in score.economics.assumptions

    # Risk flags and readiness must block fail-closed
    assert "currency_mismatch" in score.reasons
    matching_flags = [f for f in score.risk_flags if f.code == "currency_mismatch"]
    assert len(matching_flags) == 1
    assert matching_flags[0].severity == "blocker"
    assert score.recommendation == "hold_for_manual_review"
    assert score.contributions["margin_feasibility_proxy"] == 0.0

    # Report level must reflect the blocker
    report = build_report([row], target_sell_prices={"eur-offer-1": 100.0}, lane=lane).to_dict()
    assert report["top_candidate_id"] == "eur-offer-1"
    assert report["next_best_action"] == "hold_for_manual_review:eur-offer-1"
    assert report["candidates"][0]["score"]["economics"]["gross_margin"] is None
    assert "currency_mismatch" in report["candidates"][0]["score"]["economics"]["assumptions"]


def test_unit_economics_absent_currency_fails_closed():
    # Cost currency is empty/missing
    scenario = calculate_unit_economics(
        target_sell_price=100.0,
        unit_cost=25.0,
        shipping_cost=5.0,
        cost_currency="",
        lane=MarketLane("cn-us", "CN", "CN", "fixture-warehouse", "US", currency="USD"),
    )
    assert scenario.gross_margin is None
    assert "currency_missing" in scenario.assumptions

    # Evidence with empty currency fails closed in scoring
    evidence = SupplierFeasibilityEvidence(
        candidate_id="absent-cur-1",
        query="widget",
        supplier="cj",
        source_type="fixture_demo",
        unit_cost=15.0,
        shipping_cost=3.0,
        currency="",
    )
    lane = MarketLane("cn-us", "CN", "CN", "fixture-warehouse", "US", currency="USD")
    score = score_candidate("absent-cur-1", [evidence], target_sell_price=40.0, lane=lane)
    assert score.economics is not None
    assert score.economics.gross_margin is None
    assert "currency_missing" in score.economics.assumptions
    assert "currency_missing" in score.reasons
    assert any(f.code == "currency_missing" and f.severity == "blocker" for f in score.risk_flags)
    assert score.recommendation == "hold_for_manual_review"


def test_unit_economics_explicit_zero_costs_preserved():
    # Explicit zero costs must not be coerced to None or missing
    scenario_zero = calculate_unit_economics(
        target_sell_price=50.0,
        unit_cost=0.0,
        shipping_cost=0.0,
    )
    assert scenario_zero.unit_cost == 0.0
    assert scenario_zero.shipping_cost == 0.0
    assert scenario_zero.estimated_landed_cost == 0.0
    assert "shipping_cost_missing" not in scenario_zero.assumptions
    assert "sell_price_or_landed_cost_missing" not in scenario_zero.assumptions
    assert scenario_zero.gross_margin is not None
    assert scenario_zero.gross_margin > 0.0

    # Missing shipping cost is cleanly distinguished
    scenario_missing = calculate_unit_economics(
        target_sell_price=50.0,
        unit_cost=10.0,
        shipping_cost=None,
    )
    assert scenario_missing.shipping_cost is None
    assert "shipping_cost_missing" in scenario_missing.assumptions

    # In candidate scoring, 0.0 cost is not flagged as supplier_cost_missing
    row_zero = normalize_record({
        "candidate_id": "zero-cost",
        "supplier": "cj",
        "unit_cost": 0.0,
        "shipping_cost": 0.0,
        "delivery_window": "5-9",
        "inventory_status": "in_stock",
    })
    assert row_zero is not None
    score_zero = score_candidate("zero-cost", [row_zero], target_sell_price=50.0)
    assert "supplier_cost_missing" not in score_zero.reasons
    assert "shipping_cost_missing" not in score_zero.reasons
    assert score_zero.economics.unit_cost == 0.0
    assert score_zero.economics.shipping_cost == 0.0


def test_unit_economics_shipping_currency_mismatch():
    # Unit cost in EUR, shipping cost in USD, market in EUR -> mismatch
    scenario = calculate_unit_economics(
        target_sell_price=60.0,
        unit_cost=20.0,
        shipping_cost=5.0,
        cost_currency="EUR",
        shipping_currency="USD",
        lane=MarketLane("cn-de", "CN", "CN", "fixture-warehouse", "DE", currency="EUR"),
    )
    assert scenario.gross_margin is None
    assert "currency_mismatch" in scenario.assumptions
    assert scenario.cost_currency == "EUR"
    assert scenario.shipping_currency == "USD"

    # Evidence with mismatched shipping_currency
    evidence = SupplierFeasibilityEvidence(
        candidate_id="ship-mismatch",
        query="widget",
        supplier="cj",
        source_type="fixture_demo",
        unit_cost=20.0,
        currency="EUR",
        shipping_cost=5.0,
        shipping_currency="USD",
    )
    lane = MarketLane("cn-de", "CN", "CN", "fixture-warehouse", "DE", currency="EUR")
    score = score_candidate("ship-mismatch", [evidence], target_sell_price=60.0, lane=lane)
    assert score.economics is not None
    assert score.economics.gross_margin is None
    assert "currency_mismatch" in score.economics.assumptions
    assert "currency_mismatch" in score.reasons
    assert any(f.code == "currency_mismatch" and f.severity == "blocker" for f in score.risk_flags)
    assert score.recommendation == "hold_for_manual_review"


def test_supplier_feasibility_evidence_labels_unescalated():
    # Evidence labels stay fixture/manual and never escalate to live authorization
    rows_fixture = import_cj_validation_pack(fixture("cj_validation_pack_success.json"))
    report_fixture = build_report(rows_fixture, evidence_mode="fixture")
    assert report_fixture.evidence_mode == "fixture"
    assert "supplier_feasibility_is_not_live_supplier_authorization" in report_fixture.warnings
    assert not report_fixture.network_calls
    assert not report_fixture.mutated
    assert report_fixture.read_only

    rows_manual = import_csv(fixture("cj_manual_import.csv"), supplier="cj", source_type="cj_manual_import")
    report_manual = build_report(rows_manual, evidence_mode="manual_import")
    assert report_manual.evidence_mode == "manual_import"
    assert all(r.evidence_mode == "manual_import" for r in rows_manual)
    # Manual evidence cannot escalate to advance_to_launch_draft
    for candidate in report_manual.candidates:
        assert candidate.score.recommendation != "advance_to_launch_draft"

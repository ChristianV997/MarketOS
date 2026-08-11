"""Deterministic coverage for the offline marketplace-trend vertical slice."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.adapters.research.marketplace_trends import (
    MarketplaceImportError,
    import_alibaba_high_profit,
    import_alibaba_trending,
    import_aliexpress_trending,
    import_amazon_best_sellers,
    import_amazon_product,
    import_csv,
    import_etsy_listing,
    import_json,
    import_mercadolibre_best_sellers,
    import_mercadolibre_highlights,
    import_mercadolibre_trends,
    import_shopify_storefront,
    import_walmart_listing,
    import_woocommerce_storefront,
    normalize_record,
    validate_input_path,
)
from evaluation.commerce.marketplace_trends import (
    PROVENANCE,
    SOURCE_TYPES,
    SUPPORTED,
    MarketplaceTrendEvidence,
    build_report,
    collapse_duplicates,
    evidence_field_status,
    score_candidate,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "marketplace_trends"


def fixture(name: str) -> Path:
    return FIXTURES / name


def test_supported_marketplaces_are_explicit():
    assert SUPPORTED == {"amazon", "ebay", "mercadolibre", "alibaba", "aliexpress", "etsy", "walmart", "shopify", "woocommerce"}


def test_provenance_vocabulary_is_bounded():
    assert PROVENANCE == {"observed", "derived", "assumed", "unavailable", "malformed", "blocked", "manual_import", "fixture"}


def test_source_types_include_requested_offline_sources():
    for name in ("amazon_best_sellers_snapshot", "ebay_terapeak_manual_import", "mercadolibre_trends_snapshot", "alibaba_high_profit_snapshot", "manual_csv_import", "fixture_demo"):
        assert name in SOURCE_TYPES


def test_amazon_best_seller_fixture_normalizes_and_scores():
    rows = import_amazon_best_sellers(fixture("amazon_best_sellers_snapshot.json"))
    report = build_report(rows).to_dict()
    assert len(rows) == 2
    assert report["top_candidate_id"] == "mini-thermal-printer"
    assert report["candidates"][0]["score"]["recommendation"] == "validate_supplier_first"


def test_amazon_product_fixture_uses_product_source_type():
    rows = import_amazon_product(fixture("amazon_product_snapshot.json"))
    assert rows[0].source_type == "amazon_product_snapshot"
    assert rows[0].price == 29.99
    assert rows[0].field_provenance["price"] == "fixture"


@pytest.mark.parametrize(
    "loader,name,marketplace,source",
    [
        (import_mercadolibre_trends, "mercadolibre_trends_mlm.json", "mercadolibre", "mercadolibre_trends_snapshot"),
        (import_mercadolibre_highlights, "mercadolibre_highlights_mlm_category.json", "mercadolibre", "mercadolibre_highlights_snapshot"),
        (import_mercadolibre_best_sellers, "mercadolibre_best_sellers_snapshot.json", "mercadolibre", "mercadolibre_best_sellers_snapshot"),
        (import_alibaba_trending, "alibaba_market_trending_snapshot.json", "alibaba", "alibaba_market_trending_snapshot"),
        (import_alibaba_high_profit, "alibaba_high_profit_snapshot.json", "alibaba", "alibaba_high_profit_snapshot"),
        (import_aliexpress_trending, "aliexpress_trending_snapshot.json", "aliexpress", "aliexpress_trending_snapshot"),
        (import_etsy_listing, "etsy_public_listing_snapshot.json", "etsy", "etsy_public_listing_snapshot"),
        (import_walmart_listing, "walmart_public_listing_snapshot.json", "walmart", "walmart_public_listing_snapshot"),
        (import_shopify_storefront, "shopify_storefront_snapshot.json", "shopify", "shopify_storefront_snapshot"),
        (import_woocommerce_storefront, "woocommerce_storefront_snapshot.json", "woocommerce", "woocommerce_storefront_snapshot"),
    ],
)
def test_marketplace_fixture_loader(loader, name, marketplace, source):
    rows = loader(fixture(name))
    assert len(rows) == 1
    assert rows[0].marketplace == marketplace
    assert rows[0].source_type == source
    assert rows[0].read_only is True
    assert rows[0].network_calls is False
    assert rows[0].mutated is False


def test_ebay_terapeak_csv_is_manual_import():
    rows = import_csv(fixture("ebay_terapeak_import.csv"), marketplace="ebay")
    assert len(rows) == 2
    assert all(row.evidence_mode == "manual_import" for row in rows)
    assert all(row.source_type == "ebay_terapeak_manual_import" for row in rows)
    assert rows[0].field_provenance["price"] == "manual_import"


def test_mixed_csv_preserves_marketplace_rows():
    rows = import_csv(fixture("manual_import_mixed_marketplaces.csv"))
    assert {row.marketplace for row in rows} == {"amazon", "ebay"}
    assert {row.candidate_id for row in rows} == {"mini-thermal-printer", "portable-projector"}


def test_malformed_csv_degrades_without_crashing():
    rows = import_csv(fixture("malformed_marketplace_import.csv"))
    assert rows == []


def test_secret_like_json_is_rejected_before_normalization():
    assert import_json(fixture("secret_like_import_rejected.json")) == []


def test_unknown_marketplace_row_is_skipped():
    assert normalize_record({"candidate_id": "x", "marketplace": "unknown"}) is None


def test_missing_candidate_id_is_skipped():
    assert normalize_record({"query": "missing id", "marketplace": "amazon"}) is None


def test_nested_product_fields_are_normalized():
    row = normalize_record({"candidate_id": "x", "marketplace": "amazon", "product": {"price": "$19.50", "rating": "4.5"}})
    assert row is not None
    assert row.price == 19.5
    assert row.rating == 4.5


def test_price_and_count_strings_are_normalized():
    row = normalize_record({"candidate_id": "x", "marketplace": "amazon", "price": "$1,299.00", "review_count": "1,200", "rating": "4.8 stars"})
    assert row is not None
    assert row.price == 1299
    assert row.review_count == 1200
    assert row.rating == 4.8


def test_missing_price_has_explicit_warning():
    row = normalize_record({"candidate_id": "x", "marketplace": "amazon"})
    assert row is not None
    assert "price_unavailable" in row.warnings
    assert evidence_field_status(row, "price") == "unavailable"


def test_invalid_provenance_is_made_malformed():
    row = normalize_record({"candidate_id": "x", "marketplace": "amazon", "field_provenance": {"price": "invented"}, "price": 10})
    assert row is not None
    assert row.field_provenance["price"] == "malformed"


def test_duplicate_evidence_keeps_more_complete_row():
    rows = import_json(fixture("amazon_best_sellers_snapshot.json"))
    duplicate = {**rows[0].to_dict(), "source_confidence": 0.99, "review_count": 12345}
    first = normalize_record(rows[0].to_dict())
    second = normalize_record(duplicate)
    assert first is not None and second is not None
    result = collapse_duplicates([first, second])
    assert len(result) == 1
    assert result[0].source_confidence == 0.99


def test_evidence_serialization_is_json_safe():
    row = import_amazon_best_sellers(fixture("amazon_best_sellers_snapshot.json"))[0]
    payload = row.to_dict()
    json.dumps(payload)
    assert payload["warnings"] == []
    assert payload["read_only"] is True


def test_evidence_rejects_mutation_flags():
    with pytest.raises(ValueError):
        MarketplaceTrendEvidence("x", "x", "amazon", "fixture_demo", mutated=True)


def test_empty_candidate_is_low_signal():
    score = score_candidate("empty", [])
    assert score.recommendation == "reject_low_signal"
    assert "no_marketplace_evidence" in score.reasons


def test_high_demand_without_supplier_proof_requires_supplier_validation():
    rows = import_amazon_best_sellers(fixture("amazon_best_sellers_snapshot.json"))[:1]
    score = score_candidate(rows[0].candidate_id, rows)
    assert score.recommendation == "validate_supplier_first"
    assert "supplier_proof_not_observed" in score.reasons


def test_supplier_proof_is_an_explicit_input_not_inferred():
    rows = import_amazon_best_sellers(fixture("amazon_best_sellers_snapshot.json"))[:1]
    without = score_candidate(rows[0].candidate_id, rows, supplier_proof=False)
    with_proof = score_candidate(rows[0].candidate_id, rows, supplier_proof=True)
    assert without.recommendation == "validate_supplier_first"
    assert "supplier_proof_observed" in with_proof.reasons


def test_best_seller_dimension_increases_for_badged_evidence():
    row = import_amazon_best_sellers(fixture("amazon_best_sellers_snapshot.json"))[0]
    score = score_candidate(row.candidate_id, [row])
    assert score.dimensions["best_seller_presence"] == 1


def test_trend_growth_dimension_is_bounded():
    row = normalize_record({"candidate_id": "x", "marketplace": "amazon", "search_growth_signal": 4})
    assert row is not None
    assert score_candidate("x", [row]).dimensions["trend_growth_signal"] == 1


def test_review_density_dimension_is_bounded():
    row = normalize_record({"candidate_id": "x", "marketplace": "amazon", "review_count": 100000})
    assert row is not None
    assert score_candidate("x", [row]).dimensions["review_density"] == 1


def test_rating_quality_uses_five_point_scale():
    row = normalize_record({"candidate_id": "x", "marketplace": "amazon", "rating": 5})
    assert row is not None
    assert score_candidate("x", [row]).dimensions["rating_quality"] == 1


def test_price_confidence_requires_price_and_source_confidence():
    row = normalize_record({"candidate_id": "x", "marketplace": "amazon", "price": 20, "source_confidence": 0.8})
    assert row is not None
    score = score_candidate("x", [row])
    assert 0 < score.price_confidence <= 1


def test_source_diversity_increases_across_marketplaces():
    rows = [
        normalize_record({"candidate_id": "x", "marketplace": "amazon", "price": 20}),
        normalize_record({"candidate_id": "x", "marketplace": "etsy", "price": 25}),
    ]
    score = score_candidate("x", [row for row in rows if row is not None])
    assert score.dimensions["cross_marketplace_presence"] > 0
    assert score.source_diversity_score > 0


def test_seller_competition_informs_saturation():
    row = normalize_record({"candidate_id": "x", "marketplace": "amazon", "seller_count": 95})
    assert row is not None
    assert score_candidate("x", [row]).saturation_score == 0.95


def test_high_saturation_recommends_rejection():
    row = normalize_record({"candidate_id": "x", "marketplace": "amazon", "seller_count": 100, "price": 20, "best_seller_badge": True, "review_count": 9000, "rating": 4.8})
    assert row is not None
    assert score_candidate("x", [row], supplier_proof=True).recommendation == "reject_oversaturated"


def test_missing_price_adds_reason():
    row = normalize_record({"candidate_id": "x", "marketplace": "amazon", "review_count": 20})
    assert row is not None
    assert "price_missing" in score_candidate("x", [row]).reasons


def test_manual_import_confidence_is_reported():
    row = import_csv(fixture("ebay_terapeak_import.csv"))[0]
    score = score_candidate(row.candidate_id, [row])
    assert score.dimensions["manual_import_confidence"] > 0


def test_report_sorts_by_opportunity_then_candidate_id():
    rows = import_amazon_best_sellers(fixture("amazon_best_sellers_snapshot.json"))
    report = build_report(list(reversed(rows))).to_dict()
    assert report["candidates"][0]["candidate_id"] == "mini-thermal-printer"
    assert report["next_best_action"].endswith(":mini-thermal-printer")


def test_report_has_safety_assertions():
    report = build_report(import_amazon_best_sellers(fixture("amazon_best_sellers_snapshot.json"))).to_dict()
    assert report["read_only"] is True
    assert report["network_calls"] is False
    assert report["mutated"] is False
    assert "marketplace_evidence_is_not_supplier_proof" in report["warnings"]


def test_report_without_records_is_explicitly_unsupplied():
    report = build_report([]).to_dict()
    assert report["candidate_count"] == 0
    assert report["next_best_action"] == "hold_for_manual_review"
    assert report["warnings"] == ["marketplace_trends_not_supplied"]


def test_report_candidate_contains_source_summary():
    row = import_amazon_best_sellers(fixture("amazon_best_sellers_snapshot.json"))[0]
    candidate = build_report([row]).to_dict()["candidates"][0]
    assert candidate["marketplaces"] == ["amazon"]
    assert candidate["source_types"] == ["amazon_best_sellers_snapshot"]


def test_validate_input_path_rejects_traversal():
    with pytest.raises(MarketplaceImportError):
        validate_input_path(FIXTURES / ".." / "secret.json")


def test_validate_input_path_rejects_unsupported_extension(tmp_path):
    path = tmp_path / "source.txt"
    path.write_text("not allowed", encoding="utf8")
    with pytest.raises(MarketplaceImportError):
        validate_input_path(path)


def test_missing_file_is_classified_as_import_error(tmp_path):
    with pytest.raises(MarketplaceImportError):
        validate_input_path(tmp_path / "missing.json")


def test_json_object_records_are_supported(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps({"records": [{"candidate_id": "x", "marketplace": "amazon", "price": 5}]}), encoding="utf8")
    assert len(import_json(path)) == 1


def test_json_products_key_is_supported(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps({"products": [{"product_id": "x", "marketplace": "amazon", "price": 5}]}), encoding="utf8")
    assert import_json(path)[0].candidate_id == "x"


def test_unknown_source_type_falls_back_to_marketplace_default():
    row = normalize_record({"candidate_id": "x", "marketplace": "amazon", "source_type": "private_api_response"})
    assert row is not None
    assert row.source_type == "amazon_best_sellers_snapshot"


def test_manual_rows_are_not_live_network_evidence():
    row = import_csv(fixture("ebay_terapeak_import.csv"))[0]
    assert row.evidence_mode == "manual_import"
    assert row.network_calls is False
    assert row.mutated is False


def test_fixture_rows_are_not_supplier_proof():
    rows = import_amazon_best_sellers(fixture("amazon_best_sellers_snapshot.json"))
    assert all(row.provenance_mode == "fixture" for row in rows)
    assert score_candidate(rows[0].candidate_id, rows).recommendation == "validate_supplier_first"

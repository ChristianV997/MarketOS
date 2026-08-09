from backend.discovery.source_quality import score_source_quality


def test_quality_profiles_are_signal_specific():
    trends = score_source_quality("trends", "local_file", "google_trends_csv", {"type": "export"}, 1, ["trend_score"])
    supplier = score_source_quality("supplier", "local_file", "supplier_catalog_csv", {"type": "export"}, 1, ["supplier_cost"])
    own_store = score_source_quality("shop", "local_file", "shopify_orders_csv", {"type": "export"}, 1, ["net_sales"])
    synthetic = score_source_quality("fixture", "fixture", "local_json_dataset", {"type": "synthetic_fixture", "not_real_market_data": True}, 1, ["value"])
    assert "trend_proxy" in trends.allowed_signal_types and "profit_proxy" in trends.blocked_signal_types
    assert "margin_proxy" in supplier.allowed_signal_types
    assert own_store.confidence_multiplier > supplier.confidence_multiplier
    assert synthetic.quality_score < trends.quality_score

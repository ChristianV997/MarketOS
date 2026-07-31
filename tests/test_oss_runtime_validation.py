from scripts.validate_oss_runtime import build_report


def test_oss_runtime_report_is_read_only_and_validates_boundaries():
    report = build_report()
    assert report["read_only"] is True
    assert report["inventory_errors"] == []
    assert report["dry_run_boundaries"]["medusa"]["dry_run"] is True
    assert report["dry_run_boundaries"]["postiz"]["dry_run"] is True
    assert report["dry_run_boundaries"]["n8n"]["dry_run"] is True
    assert report["dry_run_boundaries"]["woocommerce"]["dry_run"] is True
    assert report["dry_run_boundaries"]["stripe_mx"]["dry_run"] is True
    assert report["dry_run_boundaries"]["mercado_pago_mx"]["dry_run"] is True
    assert {item["name"] for item in report["providers"]} >= {
        "medusa", "postiz", "crawl4ai", "woocommerce", "stripe_mx", "mercado_pago_mx",
    }

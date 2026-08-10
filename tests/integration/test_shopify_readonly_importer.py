from pathlib import Path
from backend.ecommerce.shopify_readonly.importer import import_shopify_readonly


ROOT = Path(__file__).resolve().parents[2]


def test_import_normalizes_context_and_is_deterministic():
    path = ROOT / "tests/fixtures/shopify_readonly/shopify_sample.json"
    first = import_shopify_readonly(path); second = import_shopify_readonly(path)
    batch, context = first
    assert batch.to_dict() == second[0].to_dict()
    assert (len(batch.products), len(batch.variants), len(batch.orders), len(batch.line_items)) == (2, 3, 2, 3)
    assert context.observed_revenue_total == 118.66 and context.out_of_stock_variant_count == 1


def test_import_skips_malformed_records_without_network():
    batch, context = import_shopify_readonly(ROOT / "tests/fixtures/shopify_readonly/shopify_malformed_sample.json")
    assert batch.skipped_records and context.metadata["read_only"]

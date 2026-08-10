from pathlib import Path
from backend.ecommerce.shopify_readonly.events import shopify_batch_events
from backend.ecommerce.shopify_readonly.importer import import_shopify_readonly


ROOT = Path(__file__).resolve().parents[2]


def test_shopify_events_validate_and_forbid_mutation():
    batch, context = import_shopify_readonly(ROOT / "tests/fixtures/shopify_readonly/shopify_sample.json")
    events = shopify_batch_events(batch, context)
    assert events[0].event_type == "shopify_import_batch_started"
    assert events[-1].event_type == "shopify_import_batch_completed"
    assert all(event.metadata["read_only"] and event.metadata["no_store_mutation_authority"] for event in events)
    assert all("ada@example.test" not in event.canonical_json() for event in events)

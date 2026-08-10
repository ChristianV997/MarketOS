from pathlib import Path
from backend.ecommerce.shopify_readonly.events import shopify_batch_events
from backend.ecommerce.shopify_readonly.importer import import_shopify_readonly
from backend.ecommerce.shopify_readonly.reporting import report_to_dict
from backend.events.replay_certification import load_canonical_jsonl
from backend.events.repository import JsonlEventRepository

ROOT = Path(__file__).resolve().parents[2]


def test_packet_replays_from_optional_jsonl(tmp_path):
    batch, context = import_shopify_readonly(ROOT / "tests/fixtures/shopify_readonly/shopify_sample.json")
    path = tmp_path / "shopify.jsonl"; repo = JsonlEventRepository(path); repo.append_many(shopify_batch_events(batch, context))
    events = load_canonical_jsonl(path)
    assert len(events) == report_to_dict(batch, context)["canonical_event_count"]
    assert all(event.metadata["no_payment_authority"] for event in events)

from backend.integrations.medusa import MedusaCommerceAdapter
from backend.integrations.postiz import PostizPublisherAdapter
from backend.integrations.webhook_dedup import WebhookEventLedger
from pathlib import Path


def test_webhook_ledger_accepts_once_and_is_source_scoped():
    ledger = WebhookEventLedger()
    assert ledger.accept("medusa", "evt-1") is True
    assert ledger.accept("medusa", "evt-1") is False
    assert ledger.accept("postiz", "evt-1") is True
    assert ledger.accept("medusa", "") is False


def test_sidecar_adapters_expose_webhook_deduplication():
    medusa = MedusaCommerceAdapter()
    postiz = PostizPublisherAdapter()
    assert medusa.accept_webhook("order-1") is True
    assert medusa.accept_webhook("order-1") is False
    assert postiz.accept_webhook("post-1") is True
    assert postiz.accept_webhook("post-1") is False


def test_webhook_ledger_can_persist_across_instances(tmp_path: Path):
    db_path = str(tmp_path / "webhooks.sqlite")
    first = WebhookEventLedger(db_path=db_path)
    second = WebhookEventLedger(db_path=db_path)
    assert first.accept("medusa", "evt-persisted") is True
    assert second.accept("medusa", "evt-persisted") is False

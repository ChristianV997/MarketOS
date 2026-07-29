from backend.integrations.medusa import MedusaCommerceAdapter
from backend.integrations.postiz import PostizPublisherAdapter
from backend.integrations.webhook_dedup import WebhookEventLedger


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

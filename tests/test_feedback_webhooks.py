from backend.commerce.feedback import observation_from_metrics, observation_from_order, observation_from_webhook
from backend.commerce.feedback import FeedbackRecorder
from backend.commerce.observation_ledger import FeedbackObservationLedger


def test_polling_metrics_normalize_only_attributable_evidence():
    observation = observation_from_metrics(
        observation_id="tiktok:campaign-1:42",
        source="tiktok",
        campaign_id="campaign-1",
        product_id="p1",
        spend=10,
        revenue=25,
        metadata={"hook": "hook-1"},
    )
    assert observation is not None
    assert observation.quality.is_live_attributed is True
    assert observation.metadata["source"] == "tiktok"
    assert observation.metadata["hook"] == "hook-1"


def test_polling_spend_only_rows_do_not_train_feedback():
    assert observation_from_metrics(
        observation_id="meta:campaign-1:42",
        source="meta",
        campaign_id="campaign-1",
        spend=10,
        revenue=0,
    ) is None


def test_polling_observation_ids_are_preserved_for_deduplication():
    first = observation_from_metrics(
        observation_id="tiktok:campaign-1:42",
        source="tiktok",
        campaign_id="campaign-1",
        spend=10,
        revenue=25,
    )
    second = observation_from_metrics(
        observation_id="tiktok:campaign-1:42",
        source="tiktok",
        campaign_id="campaign-1",
        spend=11,
        revenue=27,
    )
    assert first is not None and second is not None
    assert first.observation_id == second.observation_id


def test_order_mapping_requires_explicit_marketos_lineage():
    assert observation_from_order({"id": "order-1", "total_price": 10}, source="shopify") is None
    observation = observation_from_order({
        "id": "order-2", "total_price": 25, "currency": "usd",
        "metadata": {"marketos_campaign_id": "campaign-1", "marketos_product_id": "p1"},
    }, source="shopify")
    assert observation is not None
    assert observation.campaign_id == "campaign-1"
    assert observation.revenue == 25


def test_feedback_ledger_survives_recorder_restart(tmp_path):
    db = str(tmp_path / "feedback.sqlite3")
    first_ledger = FeedbackObservationLedger(db)
    first = observation_from_metrics(
        observation_id="tiktok:c1:1", source="tiktok", campaign_id="c1", spend=5, revenue=10,
    )
    assert first is not None
    memory = type("Memory", (), {
        "index_campaign": lambda self, **kwargs: None,
        "record_outcome": lambda self, **kwargs: None,
        "index_keyword": lambda self, *args, **kwargs: None,
    })()
    recorder = FeedbackRecorder(memory, memory, memory, first_ledger)
    assert recorder.record_observation(first)["recorded"] is True
    first_ledger.close()

    second_ledger = FeedbackObservationLedger(db)
    restarted = FeedbackRecorder(memory, memory, memory, second_ledger)
    assert restarted.record_observation(first)["deduplicated"] is True
    second_ledger.close()


def test_revenue_only_order_waits_for_spend_then_reconciles(tmp_path):
    ledger = FeedbackObservationLedger(str(tmp_path / "feedback.sqlite3"))
    memory = type("Memory", (), {
        "index_campaign": lambda self, **kwargs: None,
        "record_outcome": lambda self, **kwargs: None,
        "index_keyword": lambda self, *args, **kwargs: None,
    })()
    recorder = FeedbackRecorder(memory, memory, memory, ledger)
    order = observation_from_order({
        "id": "order-3", "total_price": 40,
        "metadata": {"marketos_campaign_id": "c3", "marketos_product_id": "p3"},
    }, source="shopify")
    assert order is not None
    assert recorder.record_observation(order)["pending_attribution"] is True
    result = recorder.reconcile_pending(campaign_id="c3", spend=10, observation_id="tiktok:c3:2", source="tiktok")
    assert result is not None and result["recorded"] is True
    assert ledger.pending_for_campaign("c3") == []
    ledger.close()


def test_webhook_metrics_normalize_to_campaign_observation():
    observation = observation_from_webhook({
        "id": "metric-1", "campaign_id": "campaign-1", "product_id": "p1",
        "metrics": {"spend": 4, "revenue": 12, "impressions": 100, "clicks": 5, "conversions": 1},
    }, source="postiz")
    assert observation is not None
    assert observation.revenue == 12
    assert observation.quality.is_live_attributed is True
    assert observation.metadata["source"] == "postiz"


def test_webhook_metrics_without_campaign_or_event_id_are_rejected():
    assert observation_from_webhook({"id": "metric-1", "metrics": {"spend": 4}}, source="postiz") is None
    assert observation_from_webhook({"campaign_id": "campaign-1", "metrics": {"spend": 4}}, source="postiz") is None


def test_medusa_webhook_requires_marketos_lineage_and_maps_order_revenue():
    payload = {
        "id": "medusa-order-1", "type": "order.completed",
        "data": {"order": {
            "id": "order-1", "total": 49.95, "currency_code": "usd",
            "metadata": {"marketos_campaign_id": "campaign-1", "marketos_product_id": "product-1", "marketos_creative_id": "creative-1"},
        }},
    }
    observation = observation_from_webhook(payload, source="medusa")
    assert observation is not None
    assert observation.campaign_id == "campaign-1"
    assert observation.revenue == 49.95
    assert observation.conversions == 1
    assert observation.metadata["lineage"] == "order_metadata"
    assert observation_from_webhook({"id": "medusa-order-2", "type": "order.completed", "data": {"order": {"total": 50}}}, source="medusa") is None


def test_medusa_refund_webhook_maps_only_explicit_refund_amount():
    observation = observation_from_webhook({
        "id": "medusa-refund-1", "type": "order.refund.created",
        "data": {"order": {"id": "order-1", "currency_code": "USD", "metadata": {"marketos_campaign_id": "campaign-1"}, "refund": {"amount": 19.95}}},
    }, source="medusa")
    assert observation is not None
    assert observation.revenue == 0.0
    assert observation.refunds == 19.95
    assert observation.conversions == 0


def test_feedback_recorder_accepts_observation_without_launch_bundle():
    class Memory:
        def __init__(self):
            self.calls = []
        def index_campaign(self, **kwargs):
            self.calls.append(("campaign", kwargs))
        def record_outcome(self, **kwargs):
            self.calls.append(("reinforcement", kwargs))
        def index_keyword(self, *args, **kwargs):
            self.calls.append(("signal", args, kwargs))
    from backend.commerce.feedback import CampaignObservation, DataQuality
    observation = CampaignObservation(
        observation_id="feedback-1", campaign_id="c1", product_id="p1", creative_id="cr1",
        spend=5, revenue=15, quality=DataQuality(provenance="live", attribution="attributed"),
    )
    memory = Memory()
    result = FeedbackRecorder(campaign_memory=memory, reinforcement_memory=memory, signal_memory=memory).record_observation(observation)
    assert result["recorded"] is True
    assert len(memory.calls) == 3


def test_feedback_observation_can_retry_after_memory_failure():
    class Memory:
        def __init__(self):
            self.fail = True
        def index_campaign(self, **_kwargs):
            if self.fail:
                raise RuntimeError("temporary vector failure")
        def record_outcome(self, **_kwargs):
            return None
        def index_keyword(self, *_args, **_kwargs):
            return None
    from backend.commerce.feedback import CampaignObservation, DataQuality
    observation = CampaignObservation(observation_id="retry-feedback", campaign_id="c1", product_id="p1", spend=1, revenue=2, quality=DataQuality(provenance="live", attribution="attributed"))
    memory = Memory()
    recorder = FeedbackRecorder(campaign_memory=memory, reinforcement_memory=memory, signal_memory=memory)
    assert recorder.record_observation(observation)["recorded"] is False
    memory.fail = False
    assert recorder.record_observation(observation)["recorded"] is True

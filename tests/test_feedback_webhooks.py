from backend.commerce.feedback import observation_from_webhook
from backend.commerce.feedback import FeedbackRecorder


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

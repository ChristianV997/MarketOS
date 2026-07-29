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

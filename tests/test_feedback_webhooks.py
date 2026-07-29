from backend.commerce.feedback import observation_from_webhook


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

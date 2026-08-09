"""Tests for the organic branch in core.content.feedback (D3 fix).

Organic events (source="organic", roas=0) must NEVER be classified LOSER —
absence of purchase signal is not negative evidence. They win on engagement
alone when reach is sufficient.
"""
import pytest

from core.content.feedback import batch_classify, classify_video, engagement_score


def _organic(engagement_rate: float, impressions: int = 5000) -> dict:
    return {
        "product": "p", "source": "organic",
        "engagement_rate": engagement_rate, "impressions": impressions,
        "roas": 0.0, "ctr": 0.0, "cvr": 0.0,
    }


def test_high_engagement_organic_is_winner():
    assert classify_video(_organic(0.08)) == "WINNER"


def test_low_engagement_organic_is_neutral_not_loser():
    assert classify_video(_organic(0.001)) == "NEUTRAL"


def test_low_reach_organic_never_winner():
    # High engagement on tiny reach is noise, not a winner
    assert classify_video(_organic(0.10, impressions=50)) == "NEUTRAL"


def test_organic_never_loser_regardless_of_values():
    for rate in (0.0, 0.001, 0.05, 0.5):
        for imp in (0, 10, 1000, 100000):
            assert classify_video(_organic(rate, imp)) != "LOSER"


def test_paid_classification_unchanged():
    # Regression lock: paid events classify exactly as before
    assert classify_video({"roas": 2.0, "ctr": 0.03, "cvr": 0.02}) == "WINNER"
    assert classify_video({"roas": 0.5, "ctr": 0.001, "cvr": 0.0}) == "LOSER"
    assert classify_video({"roas": 1.0, "ctr": 0.015, "cvr": 0.01}) == "NEUTRAL"


def test_engagement_rate_reaches_eng_score():
    score_with = engagement_score({"roas": 0, "ctr": 0, "cvr": 0,
                                   "engagement_rate": 0.15})
    score_without = engagement_score({"roas": 0, "ctr": 0, "cvr": 0})
    assert score_with > score_without


def test_batch_classify_annotates_organic():
    events = [_organic(0.08), _organic(0.001)]
    annotated = batch_classify(events)
    assert annotated[0]["label"] == "WINNER"
    assert annotated[1]["label"] == "NEUTRAL"

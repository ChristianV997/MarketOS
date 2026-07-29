"""Tests for backend.decision.scoring.competition_penalty — bounds and
neutral-fallback behavior for the documented, tunable penalty constants."""
from backend.decision.scoring import (
    competition_penalty,
    COMPETITION_PENALTY_MAX,
    COMPETITION_PENALTY_NEUTRAL_DENSITY,
)


def test_competition_penalty_neutral_fallback_without_token():
    penalty = competition_penalty("some keyword", token="")
    assert penalty == round(COMPETITION_PENALTY_NEUTRAL_DENSITY * COMPETITION_PENALTY_MAX, 4)


def test_competition_penalty_bounded_by_max(monkeypatch):
    monkeypatch.setattr("backend.decision.scoring._META_TOKEN", "")
    penalty = competition_penalty("keyword")
    assert 0.0 <= penalty <= COMPETITION_PENALTY_MAX


def test_competition_penalty_falls_back_to_neutral_on_api_failure(monkeypatch):
    monkeypatch.setattr("backend.decision.scoring._META_TOKEN", "fake-token")

    class _RaisingIntel:
        def competition_score(self, keyword, token):
            raise RuntimeError("api down")

    monkeypatch.setattr(
        "connectors.meta_ads_intel.MetaAdsIntel", lambda: _RaisingIntel(),
    )
    penalty = competition_penalty("keyword")
    assert penalty == round(COMPETITION_PENALTY_NEUTRAL_DENSITY * COMPETITION_PENALTY_MAX, 4)

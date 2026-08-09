"""Tests for backend.decision.organic_gate — blends organic engagement
evidence into the paid-launch confidence gate."""
import pytest


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    import backend.core.persistence as pers
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))
    monkeypatch.delenv("ORGANIC_GATE_LIVE", raising=False)


class _FakePlaybook:
    def __init__(self, product="Widget", confidence=0.65, evidence_count=20):
        self.product = product
        self.confidence = confidence
        self.evidence_count = evidence_count
        self.phase = "SCALE"


def _stub_organic(monkeypatch, posts=0, impressions=0, engagement_rate=0.0):
    monkeypatch.setattr(
        "backend.organic.engagement.product_engagement",
        lambda product: {"posts": posts, "impressions": impressions,
                        "mean_engagement_rate": engagement_rate},
    )


class TestGateLaunchLegacyBehavior:
    def test_flag_off_uses_legacy_confidence_only(self, monkeypatch):
        _stub_organic(monkeypatch, posts=0, impressions=0)
        pb = _FakePlaybook(confidence=0.65)
        assert gate_launch_result(pb) is True

    def test_flag_off_below_threshold_fails_even_with_great_organic(self, monkeypatch):
        _stub_organic(monkeypatch, posts=10, impressions=50000, engagement_rate=0.5)
        pb = _FakePlaybook(confidence=0.3)  # below 0.6, legacy would reject
        assert gate_launch_result(pb) is False

    def test_shadow_journal_always_written(self, monkeypatch):
        _stub_organic(monkeypatch, posts=1, impressions=2000, engagement_rate=0.1)
        from backend.orchestration.event_store import event_store
        pb = _FakePlaybook(confidence=0.65)
        gate_launch_result(pb)
        events = [e for e in event_store._iter_events()
                 if e.get("event") == "shadow_organic_gate"]
        assert events
        assert events[-1]["data"]["live"] is False
        assert "blended_confidence" in events[-1]["data"]


class TestGateLaunchLiveBlending:
    def test_strong_organic_evidence_can_push_below_threshold_paid_confidence_over(self, monkeypatch):
        monkeypatch.setenv("ORGANIC_GATE_LIVE", "true")
        _stub_organic(monkeypatch, posts=8, impressions=20000, engagement_rate=0.35)
        # paid_evidence alone (low) would fail the legacy 0.6 bar
        pb = _FakePlaybook(confidence=0.3, evidence_count=3)
        assert gate_launch_result(pb) is True

    def test_reach_gate_prevents_low_impression_posts_from_dominating(self, monkeypatch):
        monkeypatch.setenv("ORGANIC_GATE_LIVE", "true")
        # Huge engagement_rate but impressions below the reach floor —
        # must not count as strong evidence (a single lucky post to 50
        # people cannot look like a validated winner).
        _stub_organic(monkeypatch, posts=1, impressions=50, engagement_rate=0.9)
        pb = _FakePlaybook(confidence=0.3, evidence_count=3)
        assert gate_launch_result(pb) is False

    def test_no_organic_evidence_falls_back_to_paid_only(self, monkeypatch):
        monkeypatch.setenv("ORGANIC_GATE_LIVE", "true")
        _stub_organic(monkeypatch, posts=0, impressions=0, engagement_rate=0.0)
        pb = _FakePlaybook(confidence=0.65, evidence_count=20)
        assert gate_launch_result(pb) is True
        pb_low = _FakePlaybook(confidence=0.3, evidence_count=3)
        assert gate_launch_result(pb_low) is False

    def test_organic_lookup_failure_never_raises(self, monkeypatch):
        monkeypatch.setenv("ORGANIC_GATE_LIVE", "true")
        monkeypatch.setattr(
            "backend.organic.engagement.product_engagement",
            lambda product: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        pb = _FakePlaybook(confidence=0.65)
        assert gate_launch_result(pb) is True  # degrades to legacy-equivalent, doesn't crash


def gate_launch_result(pb):
    from backend.decision.organic_gate import gate_launch
    return gate_launch(pb)

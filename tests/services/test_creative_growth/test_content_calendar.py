"""Tests for services.creative_growth.content_calendar_report.build_content_calendar."""
import uuid

from services.creative_growth.content_calendar_report import build_content_calendar


def _unique_product():
    return f"product_{uuid.uuid4().hex[:8]}"


class TestBuildContentCalendar:
    def test_reports_gap_for_never_scheduled_product(self):
        result = build_content_calendar(_unique_product())
        assert result["has_content_gap"] is True
        assert result["gap_details"]["no_posts_ever"] is True
        assert result["newly_scheduled"] == []

    def test_schedule_gap_fill_creates_calendar_entries(self):
        product = _unique_product()
        briefs = [{"content_type": "unboxing"}, {"content_type": "review"}]
        result = build_content_calendar(product, briefs=briefs, schedule_gap_fill=True)
        assert len(result["newly_scheduled"]) == 2
        assert {p["content_type"] for p in result["newly_scheduled"]} == {"unboxing", "review"}

    def test_no_scheduling_when_schedule_gap_fill_false(self):
        product = _unique_product()
        result = build_content_calendar(product, briefs=[{"content_type": "post"}], schedule_gap_fill=False)
        assert result["newly_scheduled"] == []

    def test_no_gap_reported_once_a_post_is_scheduled(self):
        product = _unique_product()
        from core.ugc.content_calendar import content_calendar
        content_calendar.schedule_post(creator_id="c1", product_id=product)

        result = build_content_calendar(product)
        assert result["has_content_gap"] is False

    def test_never_raises_when_content_calendar_fails(self, monkeypatch):
        def _boom(product_id, ts=None):
            raise RuntimeError("boom")
        monkeypatch.setattr("core.ugc.content_calendar.content_calendar.has_content_gap", _boom)
        result = build_content_calendar(_unique_product())
        assert result["has_content_gap"] is True  # safe default

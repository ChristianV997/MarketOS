"""Tests for services.creative_growth.ugc_plan.generate_ugc_briefs."""
from services.creative_growth.ugc_plan import generate_ugc_briefs


class TestGenerateUgcBriefs:
    def test_one_brief_per_angle(self):
        briefs = generate_ugc_briefs("Widget", ["curiosity", "convenience"])
        assert len(briefs) == 2
        assert {b["angle"] for b in briefs} == {"curiosity", "convenience"}

    def test_briefs_include_guardrails_against_unsupported_claims(self):
        briefs = generate_ugc_briefs("Widget", ["curiosity"])
        assert any("unsupported claims" in g or "claims" in g for g in briefs[0]["guardrails"])

    def test_falls_back_to_generic_creator_tiers_with_no_seeding_history(self, monkeypatch):
        monkeypatch.setattr(
            "core.ugc.creator_tracker.creator_tracker.top_creators",
            lambda n, by: [],
        )
        briefs = generate_ugc_briefs("Widget", ["curiosity"], n_creators=3)
        assert briefs[0]["creator_suggestions"]
        assert briefs[0]["creator_suggestions"][0]["tier"] in ("nano", "micro", "macro")

    def test_uses_real_top_creators_when_seeding_history_exists(self, monkeypatch):
        monkeypatch.setattr(
            "core.ugc.creator_tracker.creator_tracker.top_creators",
            lambda n, by: [("creator_123", {"avg_cost_per_order": 5.0})],
        )
        briefs = generate_ugc_briefs("Widget", ["curiosity"])
        assert briefs[0]["creator_suggestions"][0]["creator_id"] == "creator_123"

    def test_empty_angles_returns_empty_list(self):
        assert generate_ugc_briefs("Widget", []) == []

    def test_never_raises_when_creator_tracker_fails(self, monkeypatch):
        def _boom(n, by):
            raise RuntimeError("boom")
        monkeypatch.setattr("core.ugc.creator_tracker.creator_tracker.top_creators", _boom)
        briefs = generate_ugc_briefs("Widget", ["curiosity"])
        assert briefs  # falls back to generic tiers

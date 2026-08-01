"""Tests for services.creative_growth.plan."""
import backend.core.persistence as pers
import pytest
from services.creative_growth.plan import build_creative_growth_plan, recommend_next_creative_batch
from services.creative_growth.schemas import CreativeGrowthPlan


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))


class TestRecommendNextCreativeBatch:
    def test_recommends_non_fatigued_items(self):
        fatigue = {"fatigued_hooks": ["hook_a"], "fatigued_angles": []}
        rec = recommend_next_creative_batch(["hook_a", "hook_b"], ["angle_a"], fatigue)
        assert rec["action"] == "test_fresh_batch"
        assert rec["hooks_to_test"] == ["hook_b"]

    def test_full_refresh_when_everything_fatigued(self):
        fatigue = {"fatigued_hooks": ["hook_a"], "fatigued_angles": ["angle_a"]}
        rec = recommend_next_creative_batch(["hook_a"], ["angle_a"], fatigue)
        assert rec["action"] == "full_refresh"

    def test_no_hooks_or_angles_does_not_force_full_refresh(self):
        rec = recommend_next_creative_batch([], [], {"fatigued_hooks": [], "fatigued_angles": []})
        assert rec["action"] == "test_fresh_batch"


class TestBuildCreativeGrowthPlan:
    def test_returns_plan_and_completed_envelope(self, monkeypatch):
        monkeypatch.setattr("core.creative.selection.select_angles", lambda n, fallback: [])
        monkeypatch.setattr("core.creative.selection.select_hooks", lambda n, fallback: [])

        plan, envelope = build_creative_growth_plan("Widget", category="wellness")

        assert isinstance(plan, CreativeGrowthPlan)
        assert plan.hooks and plan.angles
        assert plan.hook_matrix
        assert plan.ugc_briefs
        assert envelope.service_name == "creative_growth"
        assert envelope.status == "completed"

    def test_saved_to_artifact_store(self, monkeypatch):
        from backend.workspaces.artifact_store import ArtifactStore
        monkeypatch.setattr("core.creative.selection.select_angles", lambda n, fallback: [])
        monkeypatch.setattr("core.creative.selection.select_hooks", lambda n, fallback: [])

        plan, envelope = build_creative_growth_plan("Widget")
        store = ArtifactStore()
        saved = store.load(envelope.workspace_id, envelope.experiment_id, "result.json")
        assert saved == plan.to_dict()

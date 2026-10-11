"""Plan-only validation sprint against real registry files: read-only, deterministic, and handoff-compatible."""
from __future__ import annotations

import inspect
import json

import pytest

from backend.discovery import validation_sprint_runner as runner
from backend.discovery.opportunity_pipeline import Opportunity
from backend.discovery.opportunity_registry import OpportunityRegistry
from backend.discovery.validation_sprint import ValidationScorecard
from backend.discovery.validation_sprint_registry import ValidationSprintRegistry

FULL_METADATA = {"price": 40, "product": {"sku": "synthetic-desk-clamp-lamp"}, "offer": {"price": 40}}


class _EvidenceStub:
    def list_evidence(self, **kwargs):
        return [type("Evidence", (), {"evidence_id": "ev-1", "provenance": {}})()]


def _opportunity(opportunity_id, score, *, stage="validation_ready", metadata=None):
    return Opportunity(
        opportunity_id, "default", "product_hypothesis", f"Name {opportunity_id}", "Desk", stage=stage,
        score=score, confidence=0.8, evidence_ids=["ev-1"], metadata=dict(FULL_METADATA if metadata is None else metadata),
    )


@pytest.fixture
def seeded_registry(tmp_path, monkeypatch):
    opportunity_path = tmp_path / "opportunities.json"
    sprint_path = tmp_path / "sprints" / "validation_sprint_registry.json"
    seed = OpportunityRegistry(opportunity_path)
    for item in (_opportunity("seam-a", 80), _opportunity("seam-b", 70), _opportunity("seam-c", 90, stage="discovered")):
        seed.opportunities[item.opportunity_id] = item
    seed.save()
    monkeypatch.setattr(runner, "get_opportunity_registry", lambda: OpportunityRegistry(opportunity_path))
    monkeypatch.setattr(runner, "get_discovery_registry", lambda: _EvidenceStub())
    monkeypatch.setenv("MARKETOS_VALIDATION_SPRINT_STATE", str(sprint_path))
    return opportunity_path, sprint_path


def test_seam_plans_from_real_registry_files_without_writing_anything(seeded_registry):
    opportunity_path, sprint_path = seeded_registry
    before = opportunity_path.read_bytes()
    plan = runner.build_validation_sprint_plan("default", None, 10)
    assert {t.opportunity_id: t.status for t in plan.targets} == {"seam-a": "planned", "seam-b": "planned"}
    assert opportunity_path.read_bytes() == before
    assert not sprint_path.exists() and not sprint_path.parent.exists()


def test_seam_is_deterministic_across_repeated_calls(seeded_registry):
    first = runner.build_validation_sprint_plan("default", None, 10).to_dict()
    second = runner.build_validation_sprint_plan("default", None, 10).to_dict()
    assert first == second


def test_requested_ids_through_the_seam_report_missing_and_stage_gaps(seeded_registry):
    plan = runner.build_validation_sprint_plan("default", ["seam-c", "seam-a", "not-there"], 10)
    by_id = {t.opportunity_id: t for t in plan.targets}
    assert by_id["seam-c"].reasons == ["stage_not_validation_ready:discovered"]
    assert by_id["seam-a"].status == "planned"
    assert by_id["not-there"].reasons == ["opportunity_not_found"]


def test_plan_writes_no_scorecards_or_sprints_into_the_registry(seeded_registry, monkeypatch):
    _, sprint_path = seeded_registry
    plan = runner.build_validation_sprint_plan("default", None, 10)
    assert plan.targets
    registry = ValidationSprintRegistry(sprint_path)
    assert registry.list_scorecards(workspace_id="default") == []
    assert registry.list_sprints("default") == []
    previews = [ValidationScorecard.from_dict(t.scorecard_preview) for t in plan.targets]
    assert all(item.metadata["registered"] is False for item in previews)


def test_plan_never_invokes_the_run_entry_point(seeded_registry, monkeypatch):
    def _forbidden(*args, **kwargs):
        raise AssertionError("plan invoked run_validation_sprint")

    monkeypatch.setattr(runner, "run_validation_sprint", _forbidden)
    plan = runner.build_validation_sprint_plan("default", None, 10)
    assert plan.safety["execution_authorized"] is False


def test_handoff_payload_binds_to_the_run_entry_point_signature_without_invoking_it(seeded_registry):
    plan = runner.build_validation_sprint_plan("default", None, 10)
    payload = plan.execution_handoff["payload"]
    assert payload is not None
    bound = inspect.signature(runner.run_validation_sprint).bind(**payload)
    assert bound.arguments["apply_transitions"] is False
    assert bound.arguments["opportunity_ids"] == ["seam-a", "seam-b"]
    assert plan.execution_handoff["authorized"] is False


def test_plan_serializes_to_json_without_registry_objects(seeded_registry):
    plan = runner.build_validation_sprint_plan("default", None, 10)
    round_tripped = json.loads(json.dumps(plan.to_dict(), sort_keys=True))
    assert round_tripped["plan_id"] == plan.plan_id
    assert round_tripped["safety"]["planning_only"] is True


def test_seam_flags_a_possibly_truncated_evidence_pool(seeded_registry, monkeypatch):
    class _FullPageStub:
        def list_evidence(self, **kwargs):
            return [type("Evidence", (), {"evidence_id": "ev-1", "provenance": {}})() for _ in range(1000)]

    monkeypatch.setattr(runner, "get_discovery_registry", lambda: _FullPageStub())
    plan = runner.build_validation_sprint_plan("default", None, 10)
    assert plan.warnings == ["evidence_pool_may_be_truncated"]


def test_seam_with_per_candidate_acknowledgement_and_learning_fixture(seeded_registry):
    context = {
        "events": [
            {
                "learning_event_id": "fixture-prior-kill-seam-a",
                "event_type": "product_validation",
                "outcome": "killed",
                "action_taken": "deep_validate_product",
                "candidate_id": "seam-a",
                "workspace_id": "default",
                "failure_reasons": ["poor_margin"],
            }
        ]
    }
    blocked = runner.build_validation_sprint_plan("default", None, 10, learning_context=context)
    assert {t.opportunity_id: t.status for t in blocked.targets}["seam-a"] == "blocked"
    released = runner.build_validation_sprint_plan("default", None, 10, learning_context=context, acknowledged_learning_for=["seam-a"])
    assert {t.opportunity_id: t.status for t in released.targets}["seam-a"] == "planned"
    assert {t.opportunity_id: t.status for t in released.targets}["seam-b"] == "planned"


def test_explicit_empty_selection_is_blocked_rather_than_planning_the_whole_pool(seeded_registry):
    plan = runner.build_validation_sprint_plan("default", [], 10)
    assert plan.status == "blocked"
    assert plan.reasons == ["no_validation_targets"]
    assert plan.targets == []


def test_truncated_opportunity_pool_is_reported_as_a_warning(seeded_registry, monkeypatch):
    class _FullPoolRegistry:
        def list_opportunities(self, workspace_id, stage=None, limit=100, **kwargs):
            return [_opportunity(f"bulk-{i}", 50.0) for i in range(1000)]

        def get_opportunity(self, item_id):
            return None

    monkeypatch.setattr(runner, "get_opportunity_registry", lambda: _FullPoolRegistry())
    plan = runner.build_validation_sprint_plan("default", None, 10)
    assert "opportunity_pool_may_be_truncated" in plan.warnings


def test_importing_the_runner_does_not_load_the_governance_packages():
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    code = "import sys, backend.discovery.validation_sprint_runner as r; print(any(m.startswith('evaluation.companyos') for m in sys.modules))"
    result = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"

"""Tests for services.ecommerce_operator — create_commerce_experiment +
evaluate_launch_readiness (the launch guard)."""
import backend.core.persistence as pers
import pytest
from backend.orchestration.event_store import event_store
from backend.workspaces.client_workspace import ClientWorkspace
from services.ecommerce_operator.experiment import create_commerce_experiment
from services.ecommerce_operator.launch_guard import evaluate_launch_readiness

_FULL_KWARGS = dict(
    validation={"recommendation": "green"},
    unit_economics={"verdict": "profitable"},
    supplier_assumptions={"supplier": "CJ"},
    kill_criteria={"min_roas": 1.2},
    attribution_method="shopify_ground_truth",
)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))


class TestLaunchGuardBlocksMissingPrerequisites:
    def test_blocks_when_no_prerequisites_provided(self):
        ws = ClientWorkspace(name="x")
        env = create_commerce_experiment("Widget", workspace=ws)
        readiness = evaluate_launch_readiness(env, workspace=ws)

        assert readiness.ready is False
        assert "no product validation exists" in readiness.blocked_reasons
        assert "no margin analysis exists" in readiness.blocked_reasons
        assert "no supplier assumptions exist" in readiness.blocked_reasons
        assert "no kill criteria exists" in readiness.blocked_reasons
        assert "no attribution method configured" in readiness.blocked_reasons
        assert env.status == "blocked"

    def test_blocks_when_only_budget_ceiling_missing(self):
        ws = ClientWorkspace(name="x", budget_ceiling_per_experiment=0.0)
        env = create_commerce_experiment("Widget", workspace=ws, **_FULL_KWARGS)
        readiness = evaluate_launch_readiness(env, workspace=ws)

        assert readiness.ready is False
        assert "no budget ceiling exists" in readiness.blocked_reasons

    def test_budget_ceiling_defaults_from_workspace(self):
        ws = ClientWorkspace(name="x", budget_ceiling_per_experiment=100.0)
        env = create_commerce_experiment("Widget", workspace=ws, **_FULL_KWARGS)
        assert env.inputs["budget_ceiling"] == 100.0


class TestLaunchGuardReadyWithFullPrerequisites:
    def test_ready_when_dry_run_and_no_live_action_requested(self):
        ws = ClientWorkspace(name="x", budget_ceiling_per_experiment=100.0)
        env = create_commerce_experiment("Widget", workspace=ws, **_FULL_KWARGS)
        readiness = evaluate_launch_readiness(env, workspace=ws)  # live_action_requested defaults False

        assert readiness.ready is True
        assert readiness.blocked_reasons == []
        assert env.status != "blocked"

    def test_blocks_live_action_when_workspace_not_in_live_mode(self):
        ws = ClientWorkspace(name="x", budget_ceiling_per_experiment=100.0, live_mode_enabled=False)
        env = create_commerce_experiment("Widget", workspace=ws, **_FULL_KWARGS)
        readiness = evaluate_launch_readiness(env, workspace=ws, live_action_requested=True, proposed_amount=10.0)

        assert readiness.ready is False
        assert readiness.checklist["live_approved"] is False
        assert readiness.live_mode_checklist is not None

    def test_no_live_approval_exists_when_no_workspace_supplied_for_live_action(self):
        env = create_commerce_experiment("Widget", **_FULL_KWARGS)
        readiness = evaluate_launch_readiness(env, workspace=None, live_action_requested=True)

        assert readiness.ready is False
        assert any("no live approval exists" in r for r in readiness.blocked_reasons)


class TestLaunchGuardJournaling:
    def test_evaluation_journaled_to_event_store(self):
        ws = ClientWorkspace(name="x")
        env = create_commerce_experiment("Widget", workspace=ws)
        evaluate_launch_readiness(env, workspace=ws)

        events = [e for e in event_store._iter_events() if e.get("event") == "launch_readiness_evaluated"]
        assert events
        assert events[-1]["data"]["ready"] is False


class TestLaunchGuardNeverRaises:
    def test_never_raises_with_none_workspace_and_none_envelope_inputs(self):
        env = create_commerce_experiment("Widget")
        env.inputs = None  # simulate a corrupted/unexpected envelope state
        readiness = evaluate_launch_readiness(env)
        assert readiness.ready is False

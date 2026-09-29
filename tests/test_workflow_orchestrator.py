from unittest.mock import patch
from backend.workflows.orchestrator import replay_workflow_stage, resume_workflow, run_workflow
from backend.workflows.workflow_registry import get_workflow_registry


def test_workflow_runs_safe_stage_plan_and_persists_checkpoints():
    result = run_workflow(
        workspace_id="workflow-test-safe",
        workflow_type="import_discovery_cycle",
        payload={},
        stop_after_stage="import_evidence",
    )
    assert result["workflow_id"]
    assert result["status"] in {"partial", "completed"}
    assert result["checkpoints"]
    assert any(x["stage_name"] == "import_evidence" for x in result["stages"])


def test_unsafe_workflow_is_blocked_before_stage_execution():
    result = run_workflow(workspace_id="workflow-test-unsafe", payload={"nested": {"send_message": True}})
    assert result["status"] == "blocked"
    assert result["errors"]
    assert result["stages"] == []


def test_resume_keeps_existing_workflow_and_replay_is_scoped():
    initial = run_workflow(workspace_id="workflow-test-resume", workflow_type="import_discovery_cycle", payload={}, stop_after_stage="import_evidence")
    resumed = resume_workflow(initial["workflow_id"], from_stage="market_discovery")
    assert resumed["workflow_id"] == initial["workflow_id"]
    assert resumed["stages"][0]["stage_name"] == "import_evidence"
    replayed = replay_workflow_stage(initial["workflow_id"], "market_discovery")
    assert replayed["workflow_id"] == initial["workflow_id"]
    if replayed["status"] == "blocked":
        assert replayed["blocked_reasons"] == ["stage_checkpoint_not_replayable"]
    else:
        assert any(x["event_type"] == "replay_started" for x in replayed.get("obsidian", {}).get("timeline", {}).get("detail", {}).get("events", []) if isinstance(x, dict)) or replayed["status"] in {"completed", "partial"}


def test_recoverable_checkpoint_resumption_and_unrecoverable_blocking():
    # Test that recoverable failures produce recoverable checkpoints and allow resumption,
    # while unrecoverable failures produce non-recoverable checkpoints and block resumption.
    registry = get_workflow_registry()

    # 1. Recoverable failure (missing evidence)
    with patch("backend.workflows.orchestrator.execute_workflow_stage") as mock_exec:
        mock_exec.side_effect = Exception("missing evidence for discovery")
        failed_run = run_workflow(
            workspace_id="test-recoverable",
            workflow_type="import_discovery_cycle",
            payload={},
            stop_after_stage="import_evidence",
        )
    assert failed_run["status"] == "partial"
    cp = registry.latest_checkpoint(failed_run["workflow_id"], "import_evidence")
    assert cp is not None
    assert cp.recoverable is True
    assert cp.replayable is True

    # Resuming from the recoverable checkpoint succeeds
    with patch("backend.workflows.orchestrator.execute_workflow_stage") as mock_exec:
        mock_exec.return_value = {"status": "completed", "output": {"data": 123}, "produced_object_ids": []}
        resumed = resume_workflow(failed_run["workflow_id"], checkpoint_id=cp.checkpoint_id)
    assert resumed["status"] in {"completed", "partial"}
    assert resumed["workflow_id"] == failed_run["workflow_id"]

    # 2. Unrecoverable failure (unsafe path escape)
    with patch("backend.workflows.orchestrator.execute_workflow_stage") as mock_exec:
        mock_exec.side_effect = Exception("unsafe path escape detected")
        unrec_run = run_workflow(
            workspace_id="test-unrecoverable",
            workflow_type="import_discovery_cycle",
            payload={},
            stop_after_stage="import_evidence",
        )
    assert unrec_run["status"] == "partial"
    unrec_cp = registry.latest_checkpoint(unrec_run["workflow_id"], "import_evidence")
    assert unrec_cp is not None
    assert unrec_cp.recoverable is False
    assert unrec_cp.replayable is False

    # Resuming from unrecoverable checkpoint is blocked
    blocked_resume = resume_workflow(unrec_run["workflow_id"], checkpoint_id=unrec_cp.checkpoint_id)
    assert blocked_resume["status"] == "blocked"
    assert "checkpoint_not_recoverable" in blocked_resume["blocked_reasons"]


def test_recovery_clears_stale_errors_and_deduplicates_produced_objects():
    # Test idempotency: when a failed stage is recovered, stale errors are cleared
    # and produced_object_ids are deduplicated across runs and replays.
    with patch("backend.workflows.orchestrator.execute_workflow_stage") as mock_exec:
        mock_exec.side_effect = Exception("temporary unavailable service error")
        initial = run_workflow(
            workspace_id="test-idempotency",
            workflow_type="import_discovery_cycle",
            payload={},
            stop_after_stage="import_evidence",
        )
    assert initial["status"] == "partial"
    assert len(initial["errors"]) > 0

    # Recover the stage with success and produced objects
    mock_obj = [{"object_type": "discovery_run", "object_id": "disc_101", "registry": "marketos", "relation": "produced"}]
    with patch("backend.workflows.orchestrator.execute_workflow_stage") as mock_exec:
        mock_exec.return_value = {"status": "completed", "output": {}, "produced_object_ids": mock_obj}
        resumed = resume_workflow(initial["workflow_id"], from_stage="import_evidence")

    # Workflow completed, errors cleared, operator_actions_required empty of old errors
    assert resumed["status"] == "completed"
    assert resumed["errors"] == []
    assert not any("temporary unavailable" in act for act in resumed["final_output"]["operator_actions_required"])
    assert any(x["object_id"] == "disc_101" for x in resumed["produced_object_ids"])

    # Replay stage: refs marked replay_of and deduplicated
    with patch("backend.workflows.orchestrator.execute_workflow_stage") as mock_exec:
        mock_exec.return_value = {"status": "completed", "output": {}, "produced_object_ids": mock_obj}
        replayed = replay_workflow_stage(initial["workflow_id"], "import_evidence")

    assert replayed["status"] == "completed"
    replayed_refs = [x for x in replayed["stages"][0]["produced_object_ids"]]
    assert all(x.get("relation") == "replay_of" for x in replayed_refs)
    # Check that produced_object_ids on workflow is deduplicated
    disc_ids = [x["object_id"] for x in replayed["produced_object_ids"] if x["object_id"] == "disc_101"]
    assert len(disc_ids) == 1


def test_run_workflow_with_resume_from_checkpoint_id():
    # Test starting a workflow from an existing checkpoint
    registry = get_workflow_registry()
    with patch("backend.workflows.orchestrator.execute_workflow_stage") as mock_exec:
        mock_exec.return_value = {"status": "completed", "output": {}, "produced_object_ids": []}
        first = run_workflow(
            workspace_id="test-seed",
            workflow_type="import_discovery_cycle",
            payload={},
            stop_after_stage="import_evidence",
        )
    cp = registry.latest_checkpoint(first["workflow_id"], "import_evidence")
    assert cp is not None

    with patch("backend.workflows.orchestrator.execute_workflow_stage") as mock_exec:
        mock_exec.return_value = {"status": "completed", "output": {}, "produced_object_ids": []}
        second = run_workflow(
            workspace_id="test-seeded",
            workflow_type="import_discovery_cycle",
            payload={},
            resume_from_checkpoint_id=cp.checkpoint_id,
        )
    assert second["status"] == "completed"
    assert any("resumed_from_checkpoint" in w for w in second["warnings"])

from unittest.mock import patch
from backend.workflows.orchestrator import replay_workflow_stage, resume_workflow, run_workflow
from backend.workflows.workflow_registry import get_workflow_registry
from backend.workflows.workflow_models import WorkflowCheckpoint


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
    registry = get_workflow_registry()

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

    with patch("backend.workflows.orchestrator.execute_workflow_stage") as mock_exec:
        mock_exec.return_value = {"status": "completed", "output": {"data": 123}, "produced_object_ids": []}
        resumed = resume_workflow(failed_run["workflow_id"], checkpoint_id=cp.checkpoint_id)
    assert resumed["status"] in {"completed", "partial"}
    assert resumed["workflow_id"] == failed_run["workflow_id"]

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

    blocked_resume = resume_workflow(unrec_run["workflow_id"], checkpoint_id=unrec_cp.checkpoint_id)
    assert blocked_resume["status"] == "blocked"
    assert "checkpoint_not_recoverable" in blocked_resume["blocked_reasons"]


def test_recovery_clears_stale_errors_and_deduplicates_produced_objects():
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

    mock_obj = [{"object_type": "discovery_run", "object_id": "disc_101", "registry": "marketos", "relation": "produced"}]
    with patch("backend.workflows.orchestrator.execute_workflow_stage") as mock_exec:
        mock_exec.return_value = {"status": "completed", "output": {}, "produced_object_ids": mock_obj}
        resumed = resume_workflow(initial["workflow_id"], from_stage="import_evidence")

    assert resumed["status"] == "completed"
    assert resumed["errors"] == []
    assert not any("temporary unavailable" in act for act in resumed["final_output"]["operator_actions_required"])
    assert any(x["object_id"] == "disc_101" for x in resumed["produced_object_ids"])

    with patch("backend.workflows.orchestrator.execute_workflow_stage") as mock_exec:
        mock_exec.return_value = {"status": "completed", "output": {}, "produced_object_ids": mock_obj}
        replayed = replay_workflow_stage(initial["workflow_id"], "import_evidence")

    assert replayed["status"] == "completed"
    replayed_refs = [x for x in replayed["stages"][0]["produced_object_ids"]]
    assert all(x.get("relation") == "replay_of" for x in replayed_refs)
    # The mock returns one shared ref for every stage; only the replayed stage's ref is retagged.
    disc_refs = [(x["object_id"], x["relation"]) for x in replayed["produced_object_ids"] if x["object_id"] == "disc_101"]
    assert len(disc_refs) == len(set(disc_refs))
    assert disc_refs.count(("disc_101", "replay_of")) == 1


def test_run_workflow_with_resume_from_checkpoint_id():
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
            workspace_id="test-seed",
            workflow_type="import_discovery_cycle",
            payload={},
            resume_from_checkpoint_id=cp.checkpoint_id,
        )
    assert second["status"] == "completed"
    assert any("resumed_from_checkpoint" in w for w in second["warnings"])


def test_resume_blocks_checkpoint_owned_by_another_workflow_without_running_stages():
    registry = get_workflow_registry()
    with patch("backend.workflows.orchestrator.execute_workflow_stage") as mock_exec:
        mock_exec.return_value = {"status": "completed", "output": {}, "produced_object_ids": []}
        owner = run_workflow(
            workspace_id="checkpoint-owner-same-workspace",
            workflow_type="import_discovery_cycle",
            payload={},
            stop_after_stage="import_evidence",
        )
        target = run_workflow(
            workspace_id="checkpoint-owner-same-workspace",
            workflow_type="import_discovery_cycle",
            payload={},
            stop_after_stage="import_evidence",
        )
    checkpoint = registry.latest_checkpoint(owner["workflow_id"], "import_evidence")
    assert checkpoint is not None
    assert owner["workflow_id"] != target["workflow_id"]

    with patch("backend.workflows.orchestrator.execute_workflow_stage") as mock_exec:
        result = resume_workflow(target["workflow_id"], checkpoint_id=checkpoint.checkpoint_id)

    assert result["status"] == "blocked"
    assert result["blocked_reasons"] == ["checkpoint_workflow_mismatch"]
    mock_exec.assert_not_called()


def test_new_workflow_blocks_checkpoint_from_another_workspace_without_running_stages():
    registry = get_workflow_registry()
    with patch("backend.workflows.orchestrator.execute_workflow_stage") as mock_exec:
        mock_exec.return_value = {"status": "completed", "output": {}, "produced_object_ids": []}
        owner = run_workflow(
            workspace_id="checkpoint-owner-workspace-a",
            workflow_type="import_discovery_cycle",
            payload={},
            stop_after_stage="import_evidence",
        )
    checkpoint = registry.latest_checkpoint(owner["workflow_id"], "import_evidence")
    assert checkpoint is not None

    with patch("backend.workflows.orchestrator.execute_workflow_stage") as mock_exec:
        result = run_workflow(
            workspace_id="checkpoint-owner-workspace-b",
            workflow_type="import_discovery_cycle",
            payload={},
            resume_from_checkpoint_id=checkpoint.checkpoint_id,
        )

    assert result["status"] == "blocked"
    assert result["errors"] == ["resume_checkpoint_rejected:checkpoint_workspace_mismatch"]
    mock_exec.assert_not_called()


def test_new_workflow_blocks_orphan_checkpoint_without_running_stages():
    registry = get_workflow_registry()
    checkpoint = WorkflowCheckpoint(
        checkpoint_id="orphan-checkpoint-for-owner-validation-test",
        workflow_id="missing-workflow-owner-for-checkpoint-test",
        stage_name="import_evidence",
        stage_status="completed",
        checkpoint_type="after_stage",
    )
    registry.register_checkpoint(checkpoint)

    with patch("backend.workflows.orchestrator.execute_workflow_stage") as mock_exec:
        result = run_workflow(
            workspace_id="checkpoint-orphan-workspace",
            workflow_type="import_discovery_cycle",
            payload={},
            resume_from_checkpoint_id=checkpoint.checkpoint_id,
        )

    assert result["status"] == "blocked"
    assert result["errors"] == ["resume_checkpoint_rejected:checkpoint_owner_not_found"]
    mock_exec.assert_not_called()


def _event_types(workflow_id, stage_name=None, event_type=None):
    events = get_workflow_registry().list_timeline(workflow_id)
    if stage_name is not None:
        events = [e for e in events if e.stage_name == stage_name]
    if event_type is not None:
        events = [e for e in events if e.event_type == event_type]
    return [e.event_type for e in events]


def test_interrupt_restart_replay_is_idempotent_for_completed_work():
    """Interrupt after a completed stage, resume from its after_stage checkpoint,
    then replay that same completed work. Transitions and emitted stage/workflow
    events must not duplicate; produced refs and final status stay stable.
    """
    registry = get_workflow_registry()
    produced = [{"object_type": "evidence_import", "object_id": "imp_1", "registry": "marketos", "relation": "produced"}]

    with patch("backend.workflows.orchestrator.execute_workflow_stage") as mock_exec:
        mock_exec.return_value = {"status": "completed", "output": {"ok": True}, "produced_object_ids": produced}
        interrupted = run_workflow(
            workspace_id="test-interrupt-replay",
            workflow_type="import_discovery_cycle",
            payload={},
            stop_after_stage="import_evidence",
        )

    assert interrupted["status"] == "partial"
    import_stage = next(s for s in interrupted["stages"] if s["stage_name"] == "import_evidence")
    assert import_stage["status"] == "completed"
    cp = registry.latest_checkpoint(interrupted["workflow_id"], "import_evidence")
    assert cp is not None
    assert cp.checkpoint_type == "after_stage"
    assert cp.recoverable is True
    assert cp.replayable is True
    assert _event_types(interrupted["workflow_id"], "import_evidence", "stage_completed") == ["stage_completed"]
    assert _event_types(interrupted["workflow_id"], "", "workflow_partial") == ["workflow_partial"]
    completed_ids = [x["object_id"] for x in interrupted["produced_object_ids"]]
    assert completed_ids == ["imp_1"]

    with patch("backend.workflows.orchestrator.execute_workflow_stage") as mock_exec:
        mock_exec.return_value = {"status": "completed", "output": {}, "produced_object_ids": []}
        restarted = resume_workflow(interrupted["workflow_id"], checkpoint_id=cp.checkpoint_id)

    restarted_import = next(s for s in restarted["stages"] if s["stage_name"] == "import_evidence")
    assert restarted["workflow_id"] == interrupted["workflow_id"]
    assert restarted_import["status"] == "completed"
    assert restarted_import["retry_count"] == 0
    called_stages = [call.args[1].stage_name for call in mock_exec.call_args_list]
    assert "import_evidence" not in called_stages
    assert _event_types(interrupted["workflow_id"], "import_evidence", "stage_started") == ["stage_started"]
    assert _event_types(interrupted["workflow_id"], "import_evidence", "stage_completed") == ["stage_completed"]
    assert [x["object_id"] for x in restarted["produced_object_ids"] if x["object_id"] == "imp_1"] == ["imp_1"]

    with patch("backend.workflows.orchestrator.execute_workflow_stage") as mock_exec:
        mock_exec.return_value = {"status": "completed", "output": {"ok": True}, "produced_object_ids": produced}
        replayed = replay_workflow_stage(interrupted["workflow_id"], "import_evidence")

    assert replayed["status"] == restarted["status"]
    assert mock_exec.call_count == 0
    replayed_import = next(s for s in replayed["stages"] if s["stage_name"] == "import_evidence")
    assert replayed_import["status"] == "completed"
    assert _event_types(interrupted["workflow_id"], "import_evidence", "stage_completed") == ["stage_completed"]
    assert _event_types(interrupted["workflow_id"], "", "workflow_completed") == ["workflow_completed"]
    assert _event_types(interrupted["workflow_id"], "import_evidence", "replay_started") == ["replay_started"]
    assert _event_types(interrupted["workflow_id"], "import_evidence", "replay_completed") == ["replay_completed"]
    assert all(x.get("relation") == "replay_of" for x in replayed_import["produced_object_ids"])
    assert [x["object_id"] for x in replayed["produced_object_ids"] if x["object_id"] == "imp_1"] == ["imp_1"]

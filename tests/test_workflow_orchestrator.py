from backend.workflows.orchestrator import replay_workflow_stage, resume_workflow, run_workflow


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
    assert any(x["event_type"] == "replay_started" for x in replayed.get("obsidian", {}).get("timeline", {}).get("detail", {}).get("events", []) if isinstance(x, dict)) or replayed["status"] in {"completed", "partial"}

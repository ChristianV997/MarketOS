import json
from backend.workflows.workflow_models import WorkflowCheckpoint, WorkflowRun, WorkflowTimelineEvent
from backend.workflows.workflow_registry import WorkflowRegistry


def test_workflow_registry_survives_missing_and_corrupt_files(tmp_path):
    path = tmp_path / "workflow.json"
    registry = WorkflowRegistry(path)
    assert registry.list_workflows() == []
    path.write_text("{broken", encoding="utf-8")
    assert WorkflowRegistry(path).list_workflows() == []


def test_workflow_registry_persists_runs_checkpoints_and_timeline(tmp_path):
    registry = WorkflowRegistry(tmp_path / "workflow.json")
    run = WorkflowRun("w1", "ws", "custom_safe_cycle", "Title", "Objective")
    checkpoint = WorkflowCheckpoint("c1", "w1", "stage", "completed", "after_stage")
    event = WorkflowTimelineEvent("e1", "w1", "ws", "stage", "checkpoint_created", "saved")
    registry.register_workflow(run)
    registry.register_checkpoint(checkpoint)
    registry.register_timeline_event(event)
    reloaded = WorkflowRegistry(tmp_path / "workflow.json")
    assert reloaded.get_workflow("w1").workspace_id == "ws"
    assert reloaded.latest_checkpoint("w1").checkpoint_id == "c1"
    assert reloaded.list_timeline("w1")[0].event_id == "e1"

from backend.workflows.workflow_models import WorkflowCheckpoint, WorkflowRun, WorkflowStage, WorkflowTimelineEvent


def test_workflow_models_are_json_safe_and_document_status():
    stage = WorkflowStage("s1", "market_discovery", 1, status="completed")
    checkpoint = WorkflowCheckpoint("c1", "w1", "market_discovery", "completed", "after_stage")
    event = WorkflowTimelineEvent("e1", "w1", "default", "market_discovery", "stage_completed", "done")
    run = WorkflowRun("w1", "default", "custom_safe_cycle", "Test", "Inspect", stages=[stage], checkpoints=[checkpoint])
    assert WorkflowStage.from_dict(stage.to_dict()).status == "completed"
    assert WorkflowCheckpoint.from_dict(checkpoint.to_dict()).checkpoint_id == "c1"
    assert WorkflowTimelineEvent.from_dict(event.to_dict()).event_type == "stage_completed"
    assert "market_discovery" in run.to_markdown()
    assert "No live action" in run.to_markdown()

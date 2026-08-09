from backend.obsidian.sync import sync_workflow_run_note, sync_workflow_runbook_note, sync_workflow_timeline_note
from backend.obsidian.templates import render_workflow_run_note
from backend.workflows.runbook import get_workflow_runbook
from backend.workflows.workflow_models import WorkflowRun, WorkflowStage


def test_workflow_obsidian_sync_skips_without_vault(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    run = WorkflowRun("w-obsidian", "ws", "custom_safe_cycle", "Workflow", "Objective", stages=[WorkflowStage("s", "stage", 1)])
    assert sync_workflow_run_note(run)["status"] == "skipped"
    assert sync_workflow_timeline_note(run, [])["status"] == "skipped"
    assert sync_workflow_runbook_note(get_workflow_runbook("executive_intelligence_cycle"))["status"] == "skipped"


def test_workflow_obsidian_sync_writes_safe_notes(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    run = WorkflowRun("w-obsidian-write", "ws", "executive_intelligence_cycle", "Workflow", "Objective", stages=[WorkflowStage("s", "executive_intelligence", 1, status="completed")])
    assert sync_workflow_run_note(run)["status"] == "written"
    assert sync_workflow_timeline_note(run, [])["status"] == "written"
    assert "No live action" in render_workflow_run_note(run)
    assert not (tmp_path.parent / "escape.md").exists()

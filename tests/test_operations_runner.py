from backend.operations.operations_registry import OperationsRegistry
from backend.operations import operations_runner


def test_runner_creates_plan_artifacts_without_execution(monkeypatch, tmp_path):
    registry = OperationsRegistry(tmp_path / "operations.json")
    monkeypatch.setattr(operations_runner, "get_operations_registry", lambda: registry)
    result = operations_runner.create_operating_plan_cycle()
    assert result["plan"]["plan_id"]
    assert result["tasks"]
    assert result["calendar"]["calendar_id"]
    assert "planning references only" in " ".join(result["warnings"])
    updated = operations_runner.update_task_status(result["tasks"][0]["task_id"], "in_progress")
    assert updated["status"] == "completed"
    assert "does_not_execute" in updated["warnings"][0]

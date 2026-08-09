from backend.operations.operations_registry import OperationsRegistry
from backend.operations.task_models import OperatingPlan, OperatingTask


def test_registry_persists_and_filters(tmp_path):
    registry = OperationsRegistry(tmp_path / "operations.json")
    plan = OperatingPlan("p", "ws", "Plan", "objective", horizon="weekly")
    task = OperatingTask("t", "ws", "Task", "desc", metadata={"plan_id": "p"})
    registry.register_plan(plan); registry.register_task(task)
    loaded = OperationsRegistry(tmp_path / "operations.json")
    assert loaded.get_plan("p").workspace_id == "ws"
    assert loaded.list_tasks(plan_id="p")[0].task_id == "t"
    assert loaded.latest_plan("ws").plan_id == "p"

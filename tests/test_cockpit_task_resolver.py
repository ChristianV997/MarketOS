from backend.execution_cockpit.cockpit_registry import CockpitRegistry
from backend.execution_cockpit import task_resolver
from backend.operations.operations_registry import OperationsRegistry
from backend.operations.task_models import OperatingTask


def test_resolver_classifies_safe_manual_and_blocked(monkeypatch, tmp_path):
    operations = OperationsRegistry(tmp_path / "ops.json")
    cockpit = CockpitRegistry(tmp_path / "cockpit.json")
    operations.register_task(OperatingTask("t1", "default", "Validate", "validate", task_type="validation_sprint", safe_endpoint="/api/discovery/validation-sprints", safe_payload={"workspace_id": "default"}))
    operations.register_task(OperatingTask("t2", "default", "Import", "manual", task_type="evidence_acquisition", safe_payload={"foo": "bar"}))
    operations.register_task(OperatingTask("t3", "default", "Bad", "bad", task_type="validation_sprint", safe_endpoint="https://evil.invalid", safe_payload={"url": "https://evil.invalid"}))
    monkeypatch.setattr(task_resolver, "get_operations_registry", lambda: operations)
    monkeypatch.setattr(task_resolver, "get_cockpit_registry", lambda: cockpit)
    assert task_resolver.resolve_task_to_cockpit_action("t1").action_type == "run_validation_sprint"
    assert task_resolver.resolve_task_to_cockpit_action("t2").action_type == "advisory_manual"
    assert task_resolver.resolve_task_to_cockpit_action("t3").status == "blocked"

from backend.operations.task_models import OperatingPlan, OperatingTask, TaskPacket


def test_operating_models_are_json_safe_and_planning_only():
    task = OperatingTask("t1", "default", "Review", "Review evidence", checklist=["inspect"], status="bad")
    assert task.status == "blocked"
    plan = OperatingPlan("p1", "default", "Plan", "Objective", tasks=[task])
    packet = TaskPacket("pk1", "default", "p1", "t1", "Packet", "Do it", checklist=["inspect"], done_definition=["record"])
    assert OperatingPlan.from_dict(plan.to_dict()).tasks[0].task_id == "t1"
    assert "No task is automatically executed" in plan.to_markdown()
    assert "checklist" not in packet.to_markdown().lower() or "inspect" in packet.to_markdown()

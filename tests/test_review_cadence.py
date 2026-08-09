from backend.operations.review_cadence import build_progress_snapshot, build_review_cadence
from backend.operations.task_models import OperatingPlan, OperatingTask


def test_cadence_and_progress_include_blocker_review():
    tasks = [OperatingTask("t1", "default", "Task", "desc", due_day="day_1"), OperatingTask("t2", "default", "Blocked", "desc", due_day="backlog", status="blocked")]
    plan = OperatingPlan("p", "default", "Plan", "objective", tasks=tasks)
    cadence = build_review_cadence(plan)
    snapshot = build_progress_snapshot(plan, completed_task_ids=["t1"], blocked_task_ids=["t2"])
    assert any(x.checkpoint_type == "blocker_review" for x in cadence.checkpoints)
    assert "t2" in snapshot.blocked_task_ids
    assert snapshot.next_actions

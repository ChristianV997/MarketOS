from backend.operations.calendar_artifacts import build_operating_calendar
from backend.operations.task_models import OperatingPlan, OperatingTask


def test_calendar_is_local_and_blocked_tasks_are_backlog():
    plan = OperatingPlan("p", "default", "Plan", "objective", tasks=[OperatingTask("t", "default", "Task", "desc", estimated_hours=1, status="blocked")])
    calendar = build_operating_calendar(plan)
    assert calendar.blocks[0].day_label == "backlog"
    assert "LOCAL_ONLY" in calendar.to_ics_text()
    assert "external calendar" in calendar.to_markdown().lower()

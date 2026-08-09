def test_operations_modules_are_importable():
    from backend.operations.operations_runner import create_operating_plan_cycle
    from backend.operations.calendar_artifacts import OperatingCalendar
    assert callable(create_operating_plan_cycle)
    assert hasattr(OperatingCalendar, "to_ics_text")

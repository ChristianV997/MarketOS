from scripts.evaluate_medusa_sidecar import evaluate


def test_medusa_sidecar_evaluation_is_non_mutating_by_default():
    report = evaluate()
    assert report["status"] == "planned"
    assert report["executed"] is False
    assert "start" in report["commands"]


def test_medusa_sidecar_evaluation_requires_execution_and_teardown_together():
    assert evaluate(execute=True, teardown=False)["status"] == "blocked"
    assert evaluate(execute=False, teardown=True)["status"] == "blocked"

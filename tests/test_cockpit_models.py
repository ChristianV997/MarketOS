from backend.execution_cockpit.cockpit_models import CockpitAction, CockpitApproval, CockpitCheckpoint, CockpitExecution, CockpitRunSummary


def test_cockpit_models_serialize_and_show_safety():
    action = CockpitAction("a", "default", "bad", "Action", "desc")
    assert action.action_type == "blocked"
    assert CockpitAction.from_dict(action.to_dict()).action_id == "a"
    assert "No live external action" in action.to_markdown()
    assert CockpitApproval.from_dict(CockpitApproval("ap", "default", "a").to_dict()).approval_id == "ap"
    assert CockpitExecution.from_dict(CockpitExecution("e", "default", "a").to_dict()).execution_id == "e"
    assert CockpitCheckpoint.from_dict(CockpitCheckpoint("c", "default", "e", "a", "before_execution").to_dict()).checkpoint_id == "c"
    assert CockpitRunSummary.from_dict(CockpitRunSummary("s", "default", "p").to_dict()).summary_id == "s"

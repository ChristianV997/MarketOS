from backend.discovery.opportunity_pipeline import Opportunity
from backend.discovery.validation_service_plan import build_validation_service_plan, build_service_inputs_for_opportunity
from backend.discovery.validation_scorecard import build_validation_scorecard
from backend.discovery.validation_sprint import ValidationServiceResult, ValidationSprint
from backend.discovery.validation_sprint_runner import run_validation_sprint

def test_service_plan_is_dry_run_and_has_no_creative_growth():
    item=Opportunity("o","w","product_hypothesis","Desk organizer","Desk",stage="validation_ready")
    plan=build_validation_service_plan(item)
    assert "product_research" in plan and "customer_intelligence" in plan and "creative_growth" not in plan
    assert build_service_inputs_for_opportunity(item,"product_research")["dry_run"] is True

def test_scorecard_blocks_synthetic_evidence_from_advancing():
    item=Opportunity("o","w","product_hypothesis","Desk organizer","Desk",stage="validation_ready")
    results=[ValidationServiceResult("r","o","product_research","completed")]
    score=build_validation_scorecard(item,results,[type("E",(),{"provenance":{"not_real_market_data":True}})()])
    assert score.transition_recommendation != "launch_candidate"
    assert 0 <= score.validation_score <= 100

def test_empty_validation_sprint_fails_closed():
    result=run_validation_sprint(workspace_id="empty-validation-test",limit=1)
    assert result["status"] == "blocked"
    assert result["sprint"]["blocked_reasons"] == ["no_validation_targets"]

def test_sprint_serializes():
    sprint=ValidationSprint("s","w","t","o")
    assert ValidationSprint.from_dict(sprint.to_dict()).sprint_id == "s"

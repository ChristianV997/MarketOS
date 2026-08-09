from pathlib import Path
from backend.deliverables.package import DeliverablePackage,DeliverableSection
from backend.deliverables.decision_summary import build_executive_summary
from backend.deliverables.product_validation_sprint import build_product_validation_sprint_package
from backend.deliverables.renderer import write_deliverable_artifacts

def test_blocked_package_is_structured():
    p=build_product_validation_sprint_package("deliverable-test-no-sprint")
    assert p.status=="blocked" and p.executive_summary and "discovery" in p.next_actions[0].lower()
    assert "No live launch" in p.to_markdown()

def test_decision_summary_is_cautious_and_deterministic():
    result=build_executive_summary({"scorecards":[{"opportunity_id":"o","opportunity_name":"Desk","validation_score":80,"confidence":.8,"recommendation":"advance_to_launch_candidate","risk_flags":[],"missing_evidence":[]}]})
    assert len(result["advance"])==1 and result["limitations"]
    assert "profitability" not in result["summary"].lower()

def test_renderer_writes_markdown_and_html(tmp_path: Path):
    package=DeliverablePackage("package_test","w","product_validation_sprint","Test","Objective",sections=[DeliverableSection("s","Scope",1,"Local evidence only")],executive_summary="Recorded facts only")
    artifacts=write_deliverable_artifacts(package,str(tmp_path),["markdown","html"])
    assert len(artifacts)==2 and (tmp_path/"package_test.md").exists() and (tmp_path/"package_test.html").exists()
    assert "<script" not in (tmp_path/"package_test.html").read_text(encoding="utf-8").lower()

def test_package_round_trip():
    package=DeliverablePackage("p","w","product_validation_sprint","T","O",sections=[DeliverableSection("s","S",1,"C")])
    assert DeliverablePackage.from_dict(package.to_dict()).sections[0].title=="S"

from __future__ import annotations
from .creative_report import build_creative_intelligence_report
from .creative_registry import get_creative_registry
def run_creative_intelligence_cycle(workspace_id="default",product_name=None,category_name=None,opportunity_id=None):
 try:
  report=build_creative_intelligence_report(workspace_id,product_name,category_name,opportunity_id);reg=get_creative_registry();data={"buyer_psychology_map":reg.get_buyer_map(report.buyer_psychology_map_id).to_dict(),"angles":[reg.get_angle(x).to_dict() for x in report.angle_ids],"hooks":[reg.get_hook(x).to_dict() for x in report.hook_ids],"ugc_briefs":[reg.get_ugc_brief(x).to_dict() for x in report.ugc_brief_ids],"storyboards":[reg.get_storyboard(x).to_dict() for x in report.storyboard_ids],"landing_page_claim_map":reg.get_claim_map(report.landing_page_claim_map_id).to_dict(),"test_matrix":reg.get_test_matrix(report.test_matrix_id).to_dict(),"report":report.to_dict(),"status":"completed"}
  try:
   from backend.obsidian.sync import sync_creative_intelligence_report_note
   data["obsidian"]=sync_creative_intelligence_report_note(report)
  except Exception: data["obsidian"]={"status":"skipped"}
  return data
 except Exception as exc:return {"status":"partial","warnings":[str(exc)],"report":None}

from __future__ import annotations
import uuid
from .creative_models import CreativeTestMatrix
from .creative_registry import get_creative_registry

def build_creative_test_matrix(workspace_id,product_name,category_name,opportunity_id,angles,hooks,ugc_briefs,storyboards):
 variants=[]
 for a in angles[:6]:
  h=next((x for x in hooks if x.angle_id==a.angle_id),None)
  variants.append({"angle_id":a.angle_id,"hook_id":getattr(h,"hook_id",None),"format":"short_video","expected_learning":"Assess message clarity and evidence coverage in manual review.","required_evidence":["substantiated product claims"],"safety_risk":a.risk_level})
 m=CreativeTestMatrix("test_matrix_"+uuid.uuid4().hex[:16],workspace_id,product_name,category_name,opportunity_id,[{"type":"angle hypothesis","statement":"Different evidence-constrained drafts may clarify different buyer questions."},{"type":"proof hypothesis","statement":"Proof requirements may reveal the highest-value evidence gap."}],variants,[{"step":"dry_run_creative_review","execution":"local/manual only"},{"step":"manual_asset_collection","execution":"collect permissioned proof only"},{"step":"landing_page_claim_validation","execution":"local substantiation review"},{"step":"future_platform_test","execution":"manual, non-executed plan requiring separate approval"}],["message clarity","evidence completeness","objection coverage","claim substantiation"],["unsupported claims","compliance risk","evidence gaps","overpromising risk"],["Product-specific proof for any claim used","Permissioned social proof if later used"],["No live ad testing or performance prediction.","Metrics are review criteria until manually imported evidence exists."],metadata={"ugc_brief_count":len(ugc_briefs),"storyboard_count":len(storyboards)});get_creative_registry().register_test_matrix(m);return m

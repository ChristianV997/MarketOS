from __future__ import annotations
import uuid
from .buyer_psychology import build_buyer_psychology_map,_context
from .claim_safety import sanitize_creative_claim
from .creative_models import CreativeAngle
from .creative_registry import get_creative_registry

_TYPES=[("pain_solution","Problem-to-use-case draft"),("demonstration","Use-case demonstration draft"),("objection_handling","Evidence-first objection response"),("education","Buyer education draft"),("use_case","Specific use-case hypothesis"),("comparison","Decision criteria comparison draft"),("risk_reversal","Proof-first risk reduction draft")]
def generate_creative_angles(workspace_id="default",product_name=None,category_name=None,opportunity_id=None,max_angles=12):
    product,category,report,_,_,refs=_context(workspace_id,product_name,category_name,opportunity_id); buyer=build_buyer_psychology_map(workspace_id,product,category,opportunity_id); max_angles=min(max(int(max_angles),0),25); out=[]
    for typ,title in _TYPES[:max_angles]:
        premise=f"Draft hypothesis: show how {product} may fit a documented {category} use case without promising an outcome."
        checked=sanitize_creative_claim(premise,refs); conf=min(.75,(report.confidence_score if report else .2)); score=45+(report.creative_potential_score*.25 if report else 0)
        angle=CreativeAngle("angle_"+uuid.uuid4().hex[:16],workspace_id,product,category,opportunity_id or "",typ,title,checked["safe_text"],buyer.likely_buyer_segments[0]["segment"],buyer.desired_outcomes[0],buyer.objections[0],refs,"moderately_supported" if conf>=.6 else "weakly_supported" if conf>=.35 else "unsupported_hypothesis","low" if checked["status"]=="safe" else "medium",checked["blocked_reasons"], [checked["safe_text"]], ["short_video","static_ad","landing_page_section"],score,conf,checked["limitations"]+buyer.limitations,metadata={"buyer_map_id":buyer.map_id,"product_report_id":getattr(report,"report_id",None),"hypothesis_only":True});get_creative_registry().register_angle(angle);out.append(angle)
    return out

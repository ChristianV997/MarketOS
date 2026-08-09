from __future__ import annotations
import uuid
from .creative_models import UGCBrief,StoryboardOutline
from .creative_registry import get_creative_registry

def generate_ugc_briefs(workspace_id,product_name,category_name,opportunity_id,angles,max_briefs=8):
 out=[]
 for a in angles[:min(max(int(max_briefs),0),25)]:
  x=UGCBrief("ugc_"+uuid.uuid4().hex[:16],workspace_id,product_name,category_name,opportunity_id,a.angle_id,f"UGC draft: {a.title}","Creator casting hypothesis; do not imply actual ownership or experience.","A neutral, well-lit product-detail walkthrough.",["Frame this as a draft creator prompt.","Describe only documented product details.","Invite independent evaluation."],["Open with the decision question.","Show the relevant detail.","Show the proof requirement."],["Identify the use case.","Show the product detail.","State what evidence is still needed."],[a.safe_claims[0] if a.safe_claims else "Use evidence-constrained draft language."],["Do not claim personal results.","Do not invent a review or testimonial.","Do not promise an outcome."],["Disclose any creator relationship before publication."],a.evidence_basis,["No ad is launched; this is a local creator-instruction draft."]+a.limitations,metadata={"hypothesis_only":True});get_creative_registry().register_ugc_brief(x);out.append(x)
 return out

def generate_storyboards(angles,hooks,max_storyboards=12):
 out=[];by_angle={h.angle_id:h for h in hooks}
 for a in angles:
  h=by_angle.get(a.angle_id)
  if not h:continue
  for form in ("short_video","static_ad","image_carousel","landing_page_section"):
   if len(out)>=min(max(int(max_storyboards),0),50):return out
   x=StoryboardOutline("storyboard_"+uuid.uuid4().hex[:16],a.workspace_id,a.angle_id,h.hook_id,f"{form.replace('_',' ').title()} draft: {a.title}",form,[{"beat":1,"purpose":"Decision question","draft":h.text},{"beat":2,"purpose":"Documented detail","draft":"Show only verifiable product detail."},{"beat":3,"purpose":"Proof requirement","draft":"State what still requires substantiation."}],h.text and [h.text] or [],["Product-specific substantiation for any functional claim.","Permissioned proof for any testimonial/social proof."],"Review the evidence before using this draft.",["Draft only; no performance or outcome claim.","No ad was launched."],a.evidence_basis,metadata={"hypothesis_only":True});get_creative_registry().register_storyboard(x);out.append(x)
 return out

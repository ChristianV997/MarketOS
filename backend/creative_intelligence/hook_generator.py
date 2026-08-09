from __future__ import annotations
import uuid
from .claim_safety import sanitize_creative_claim
from .creative_models import CreativeHook
from .creative_registry import get_creative_registry

_HOOKS=[("question","What evidence would you want before choosing {product} for this use case?"),("demonstration","Watch the product details that matter for this use case."),("problem_callout","Still unsure which product details matter for this problem?"),("objection","Before you choose, ask what proof supports the claim."),("mistake","A common mistake: treating an unverified claim as proof."),("direct_benefit","Explore a clearer way to compare the relevant product details.")]
def generate_hooks_for_angles(angles,hooks_per_angle=5):
    cap=min(max(int(hooks_per_angle),0),10);out=[]
    for angle in angles:
      for typ,text in _HOOKS[:cap]:
        checked=sanitize_creative_claim(text.format(product=angle.product_name),angle.evidence_basis); hook=CreativeHook("hook_"+uuid.uuid4().hex[:16],angle.workspace_id,angle.angle_id,typ,checked["safe_text"],"Close-up of the product detail being evaluated; no unverified result overlay.","State the decision question, then show the documented detail.",checked["status"],checked["blocked_reasons"],angle.evidence_basis,angle.score,angle.confidence,checked["limitations"]+angle.limitations,metadata={"hypothesis_only":True});get_creative_registry().register_hook(hook);out.append(hook)
    return out

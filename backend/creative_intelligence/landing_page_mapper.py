from __future__ import annotations
import uuid
from .buyer_psychology import _context
from .angle_generator import generate_creative_angles
from .claim_safety import sanitize_creative_claim
from .creative_models import LandingPageClaimMap
from .creative_registry import get_creative_registry

def build_landing_page_claim_map(workspace_id="default",product_name=None,category_name=None,opportunity_id=None,angles=None):
 product,category,report,_,_,refs=_context(workspace_id,product_name,category_name,opportunity_id);angles=angles if angles is not None else generate_creative_angles(workspace_id,product,category,opportunity_id,4)
 claims=[];blocked=[]
 for a in angles[:4]:
  check=sanitize_creative_claim(a.premise,a.evidence_basis); row={"claim":check["safe_text"],"status":check["status"],"evidence_basis":a.evidence_basis,"required_evidence":check["required_evidence"]}
  (blocked if check["status"]=="blocked" else claims).append(row)
 m=LandingPageClaimMap("claim_map_"+uuid.uuid4().hex[:16],workspace_id,product,category,opportunity_id or "",claims,claims,[{"title":"Proof placeholder","content":"Add verified, permissioned product-specific proof here; do not invent it."}], [{"objection":"What supports this?","response":"Use documented product-specific evidence; otherwise label as a hypothesis."}], [{"question":"Will this guarantee an outcome?","answer":"No guarantee is made; validate product fit and claims first."}],blocked,["Product-specific claim substantiation","Verified price, material, supplier, and use-case evidence"],["All claims are drafts and must pass substantiation review.","No false scarcity, testimonials, or performance prediction."],metadata={"product_report_id":getattr(report,"report_id",None),"hypothesis_only":True});get_creative_registry().register_claim_map(m);return m

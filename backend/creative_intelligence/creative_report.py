from __future__ import annotations
import uuid
from .buyer_psychology import build_buyer_psychology_map,_context
from .angle_generator import generate_creative_angles
from .hook_generator import generate_hooks_for_angles
from .storyboard_generator import generate_ugc_briefs,generate_storyboards
from .landing_page_mapper import build_landing_page_claim_map
from .test_matrix import build_creative_test_matrix
from .creative_models import CreativeIntelligenceReport
from .creative_registry import get_creative_registry

def build_creative_intelligence_report(workspace_id="default",product_name=None,category_name=None,opportunity_id=None):
 product,category,product_report,_,_,_= _context(workspace_id,product_name,category_name,opportunity_id); buyer=build_buyer_psychology_map(workspace_id,product,category,opportunity_id); angles=generate_creative_angles(workspace_id,product,category,opportunity_id);hooks=generate_hooks_for_angles(angles);ugc=generate_ugc_briefs(workspace_id,product,category,opportunity_id or "",angles);story=generate_storyboards(angles,hooks);claims=build_landing_page_claim_map(workspace_id,product,category,opportunity_id,angles);matrix=build_creative_test_matrix(workspace_id,product,category,opportunity_id or "",angles,hooks,ugc,story)
 confidence=min(.8,(product_report.confidence_score if product_report else .15));missing=list(getattr(product_report,"missing_evidence",[]) or ["product-specific buyer, proof, and claim-substantiation evidence"]);blocked=[x.get("claim","") for x in claims.blocked_claims]
 r=CreativeIntelligenceReport("creative_report_"+uuid.uuid4().hex[:16],workspace_id,product,category,opportunity_id or "",f"Creative Intelligence: {product}",buyer.map_id,[x.angle_id for x in angles],[x.hook_id for x in hooks],[x.brief_id for x in ugc],[x.storyboard_id for x in story],claims.claim_map_id,matrix.matrix_id,"Evidence-constrained creative drafts prioritize buyer questions, proof requirements, and claim safety. No creative performance is predicted.",[{"angle_id":x.angle_id,"title":x.title,"score":x.score,"status":x.substantiation_level} for x in angles[:3]],[{"hook_id":x.hook_id,"text":x.text,"status":x.claim_safety_status} for x in hooks[:5]],[{"brief_id":x.brief_id,"title":x.title} for x in ugc[:3]],["Claims require product-specific substantiation before use."]+(["Commercial intelligence confidence is limited."] if confidence<.5 else []),blocked,missing,["Collect proof for the highest-priority claim gaps.","Review drafts manually; use only substantiated claims.","Use the local creative test matrix before considering any future manual test."],confidence,metadata={"product_report_id":getattr(product_report,"report_id",None),"hypothesis_only":True});get_creative_registry().register_report(r);return r

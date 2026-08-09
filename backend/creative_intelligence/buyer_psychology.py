from __future__ import annotations
import uuid
from .creative_models import BuyerPsychologyMap
from .creative_registry import get_creative_registry

def _context(workspace_id,product_name,category_name,opportunity_id):
    report=market=None; opportunity=None
    try:
        from backend.commercial_intelligence.intelligence_registry import get_commercial_intelligence_registry
        reg=get_commercial_intelligence_registry(); report=reg.latest_product_report(workspace_id,product_name,category_name,opportunity_id); market=reg.latest_market_report(workspace_id,category_name)
    except Exception: pass
    try:
        from backend.discovery.opportunity_registry import get_opportunity_registry
        opportunity=get_opportunity_registry().get_opportunity(opportunity_id) if opportunity_id else None
    except Exception: pass
    product=product_name or (report.product_name if report else None) or (opportunity.name if opportunity else None) or "Product archetype"
    category=category_name or (report.category_name if report else None) or (opportunity.category_name if opportunity else None) or "Unspecified category"
    refs=[]
    if report: refs.append({"registry":"commercial_intelligence","object_id":report.report_id,"relation":"product_intelligence"})
    if market: refs.append({"registry":"commercial_intelligence","object_id":market.report_id,"relation":"market_intelligence"})
    return product,category,report,market,opportunity,refs

def build_buyer_psychology_map(workspace_id="default",product_name=None,category_name=None,opportunity_id=None):
    product,category,report,market,_,refs=_context(workspace_id,product_name,category_name,opportunity_id)
    weak=not report or report.confidence_score<.5
    pain=(report.positioning.primary_pain_point if report and report.positioning else "Unverified buyer problem")
    buyer=(report.positioning.likely_buyer if report and report.positioning else "Buyer segment hypothesis requiring validation")
    m=BuyerPsychologyMap("buyer_map_"+uuid.uuid4().hex[:16],workspace_id,product,category,opportunity_id or "",likely_buyer_segments=[{"segment":buyer,"status":"hypothesis" if weak else "evidence-constrained inference","evidence_basis":refs}],primary_jobs_to_be_done=[f"Assess whether {product} fits the buyer's stated use case."],pain_points=[pain],desired_outcomes=["A clearer, safer way to evaluate the proposed use case."],anxieties=["Wasting money on an unsuitable product."],objections=["What proof supports this use case?","How does it differ from alternatives?"],buying_triggers=["A relevant, documented use case."],emotional_drivers=["Confidence in making an informed choice."],rational_drivers=["Clear product details, price, and proof."],trust_requirements=["Product-specific evidence before claims are used."],evidence_basis=refs,limitations=["Buyer psychology is hypothesis-led; direct customer evidence is limited."] if weak else [],metadata={"product_report_id":getattr(report,"report_id",None),"market_report_id":getattr(market,"report_id",None),"hypothesis_only":weak})
    get_creative_registry().register_buyer_map(m);return m

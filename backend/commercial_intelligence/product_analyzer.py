from __future__ import annotations
import uuid
from .evidence_features import extract_evidence_features
from .market_analyzer import analyze_market_category
from .product_models import ProductPositioning, ProductViabilityReport
from .scoring import score_product_viability
from .recommendations import build_product_validation_tests, build_recommended_imports_from_intelligence
from .intelligence_registry import get_commercial_intelligence_registry
def analyze_product_viability(workspace_id="default",product_name=None,category_name=None,opportunity_id=None,limit=500):
    features=extract_evidence_features(workspace_id,opportunity_id,category_name,product_name,limit); category=category_name or features.metadata.get("category") or "Unspecified category"; product=product_name or features.metadata.get("product_name") or f"{category} product archetype"; market=analyze_market_category(workspace_id,category,opportunity_id,limit); score=score_product_viability(features.features,market); missing=score["missing"]+[x for x in ("product_level_demand","supplier_offer","shipping_time") if x not in score["missing"]]; pos=ProductPositioning("positioning_"+uuid.uuid4().hex[:16],workspace_id,product,category,metadata={"hypothesis_only":True},differentiation_angles=["Solve a recorded pain point with a focused category-specific offer."],bundle_ideas=["Test a complementary bundle as a planning hypothesis."],upsell_ideas=["Test a low-risk accessory or replenishment hypothesis."],variant_ideas=["Test a size/use-case variant only after evidence supports it."],creative_angles=["Demonstrate the problem and proposed solution; creative angle is unvalidated."],limitations=score["limitations"]+(["buyer and product-level demand evidence is missing"] if "product_level_demand" in missing else [])); report=ProductViabilityReport("product_report_"+uuid.uuid4().hex[:16],workspace_id,product,category,f"Product Intelligence: {product}",score["score"],score["confidence"],score["demand"],score["differentiation"],score["margin"],score["supplier"],score["competition"],score["creative"],score["readiness"],["low differentiation" if score["differentiation"]<40 else "high saturation/competition risk" if score["competition"]>70 else "evidence remains incomplete"],["Recorded signals justify further testing" if score["score"]>=50 else "No strong evidence-backed reason to advance yet"],["margin/supplier evidence is weak or missing","product-level demand remains unverified"] if missing else [],missing,[],[],pos,metadata={"market_report_id":market.report_id,"feature_set_id":features.feature_set_id,"opportunity_id":opportunity_id,"hypothesis_only":True}); report.recommended_validation_tests=build_product_validation_tests(report); report.recommended_imports=build_recommended_imports_from_intelligence(report); get_commercial_intelligence_registry().register_product_report(report)
    if opportunity_id:
        try:
            from backend.discovery.opportunity_registry import get_opportunity_registry
            opportunity=get_opportunity_registry().get_opportunity(opportunity_id)
            if opportunity:
                opportunity.metadata["product_intelligence_report_id"]=report.report_id
                opportunity.metadata["product_intelligence_confidence"]=report.confidence_score
                opportunity.metadata["product_intelligence_advisory_only"]=True
                get_opportunity_registry().update_opportunity(opportunity)
        except Exception: pass
    try:
        from backend.obsidian.sync import sync_product_intelligence_note
        sync_product_intelligence_note(report)
    except Exception: pass
    return report

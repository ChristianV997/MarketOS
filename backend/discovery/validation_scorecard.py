from __future__ import annotations
import uuid
from .validation_sprint import ValidationScorecard

def build_validation_scorecard(opportunity, service_results, evidence_records=None, gaps=None, calibration_profiles=None):
    completed=[x for x in service_results if x.status=="completed"]; failed=[x for x in service_results if x.status in {"blocked","unavailable","failed"}]; score=50+min(25,len(completed)*8)-min(20,len(failed)*5); passed=[]; checks=[]; risks=[]; missing=[]
    for result in service_results:
        risks.extend(result.risk_flags); missing.extend(result.missing_evidence); checks.extend(result.recommendations)
        if result.status=="completed": passed.append(f"{result.service_name}_completed")
        else: checks.append(f"{result.service_name}_{result.status}")
    evidence_records=evidence_records or []; synthetic=bool(evidence_records) and all((getattr(x,"provenance",{}) or {}).get("not_real_market_data") is True for x in evidence_records)
    if synthetic: score-=20; risks.append("synthetic_only_evidence")
    if opportunity.opportunity_type=="product_hypothesis" and not any(k in (getattr(opportunity,"metadata",{}) or {}) for k in ("retail_price","supplier_cost","shipping_cost","price")): missing.append("price_or_cost_evidence"); score-=15
    critical=any("critical" in str(x).lower() for x in risks); score=max(0,min(100,score)); confidence=max(0,min(1,(len(completed)/max(1,len(service_results)))*.7 + min(len(evidence_records),5)/5*.3))
    if critical: recommendation,transition="reject","rejected"
    elif completed and score>=75 and confidence>=.65 and "product_research_completed" in passed and not synthetic: recommendation,transition="advance_to_launch_candidate","launch_candidate"
    elif missing: recommendation,transition="request_more_evidence","evidence_requested"
    else: recommendation,transition="keep_validating","validation_ready"
    return ValidationScorecard("scorecard_"+uuid.uuid4().hex[:16],opportunity.opportunity_id,opportunity.name,opportunity.category_name,score,confidence,recommendation,service_results,passed,checks,sorted(set(risks)),sorted(set(missing)),["Review missing evidence and rerun the sprint."],transition,{"planning_only":True})

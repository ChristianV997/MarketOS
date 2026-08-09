from __future__ import annotations
from typing import Any
from .opportunity_pipeline import Opportunity, STAGES, TRANSITIONS

MIN_EVIDENCE=2; MIN_CONFIDENCE=.55; MIN_SCORE=40
def _get(x,key,default=None): return getattr(x,key,default) if not isinstance(x,dict) else x.get(key,default)
def evaluate_opportunity_gates(opportunity: Opportunity, evidence_records=None, reports=None, gaps=None, calibration_profiles=None) -> dict[str,Any]:
    evidence_records, reports, gaps, calibration_profiles = evidence_records or [], reports or [], gaps or [], calibration_profiles or []
    related=lambda x: not _get(x,"entity_name","") or _get(x,"entity_name","").lower() in {opportunity.name.lower(),opportunity.category_name.lower()}
    evidence=[x for x in evidence_records if related(x) or _get(x,"evidence_id","") in opportunity.evidence_ids]
    signals={_get(x,"signal_type","") for x in evidence}; synthetic=bool(evidence) and all((_get(x,"provenance",{}) or {}).get("not_real_market_data") is True for x in evidence)
    matched_gaps=[x for x in gaps if _get(x,"gap_id","") in opportunity.gap_ids or str(_get(x,"entity_name","")).lower() in {opportunity.name.lower(),opportunity.category_name.lower()}]
    critical=any(_get(x,"severity","") in {"critical"} for x in matched_gaps) or any("critical" in str(x).lower() for x in opportunity.risk_flags)
    failed=[]; passed=[]; required=[]; target=opportunity.stage; status="hold"
    if opportunity.recommendation=="reject": return {"allowed_transitions":["rejected"],"recommended_transition":"rejected","current_stage":opportunity.stage,"target_stage":"rejected","gate_status":"reject","passed_gates":[],"failed_gates":["recommendation_reject"],"blocked_reasons":["opportunity_recommendation_is_reject"],"promotion_reasons":[],"required_next_evidence":[],"confidence":opportunity.confidence,"score":opportunity.score}
    if critical: failed.append("critical_risk_present")
    if opportunity.stage=="discovered":
        if opportunity.missing_evidence or opportunity.gap_ids or len(evidence)<MIN_EVIDENCE or opportunity.confidence<MIN_CONFIDENCE or synthetic: target="evidence_requested"; status="pass"; passed.append("worth_investigating_but_evidence_incomplete"); required=opportunity.missing_evidence or ["demand_proxy","competition_proxy"]
        else: target="evidence_enriched"; status="pass"; passed.append("minimum_evidence_present")
    elif opportunity.stage=="evidence_requested":
        if opportunity.acquisition_plan_ids and len(signals)>=2: target="evidence_enriched"; status="pass"; passed.append("independent_signals_and_acquisition_plan")
        else: required=["at_least_two_independent_signal_types","imported_evidence_linked_to_acquisition_plan"]; failed.extend(required)
    elif opportunity.stage=="evidence_enriched":
        needed={"demand_proxy","trend_proxy"} ; missing=needed-signals
        if not missing: passed.append("demand_or_trend_signal")
        else: failed.append("missing_demand_or_trend_evidence"); required.extend(sorted(missing))
        if "competition_proxy" in signals: passed.append("competition_signal")
        else: failed.append("missing_competition_evidence"); required.append("competition_proxy")
        if opportunity.opportunity_type=="product_hypothesis" and not ({"margin_proxy","supplier_proxy","price_signal"}&signals): failed.append("missing_product_cost_or_price_evidence"); required.append("margin_proxy_or_supplier_proxy_or_price_signal")
        if not failed and not critical and opportunity.recommendation in {"investigate","prioritize"}: target="validation_ready"; status="pass"
    elif opportunity.stage=="validation_ready":
        names={_get(x,"service_name","") for x in reports}; has_product="product_research" in names; has_unit="unit_economics" in names
        if has_product: passed.append("product_research_report")
        else: failed.append("missing_product_research_report")
        cost_needed=bool({"margin_proxy","supplier_proxy","price_signal"}&signals)
        if cost_needed and has_unit: passed.append("unit_economics_report")
        elif cost_needed: failed.append("missing_unit_economics_report")
        scorecard = None
        try:
            from .validation_sprint_registry import get_validation_sprint_registry
            scorecards = get_validation_sprint_registry().list_scorecards(opportunity_id=opportunity.opportunity_id, limit=1)
            scorecard = scorecards[0] if scorecards else None
        except Exception:
            scorecard = None
        if scorecard is not None:
            if _get(scorecard, "confidence", 0) < .65: failed.append("validation_scorecard_confidence_too_low")
            if _get(scorecard, "validation_score", 0) < 75: failed.append("validation_scorecard_score_too_low")
            if any("critical" in str(x).lower() for x in (_get(scorecard, "risk_flags", []) or [])): failed.append("validation_scorecard_critical_risk")
            if not failed: passed.append("validation_scorecard_gate")
        else:
            failed.append("missing_validation_scorecard")
        if not failed and not critical and not synthetic: target="launch_candidate"; status="pass"; passed.append("planning_only_validation_gate")
    if critical and target not in {"rejected"}: status="block"; target=opportunity.stage
    allowed=[x for x in TRANSITIONS.get(opportunity.stage,set()) if x==target or x=="rejected"]
    if target==opportunity.stage: allowed=[x for x in allowed if x!=opportunity.stage]
    return {"allowed_transitions":sorted(allowed),"recommended_transition":target if target!=opportunity.stage else None,"current_stage":opportunity.stage,"target_stage":target,"gate_status":status if not failed else ("block" if critical else "hold"),"passed_gates":passed,"failed_gates":sorted(set(failed)),"blocked_reasons":sorted(set(failed)),"promotion_reasons":passed,"required_next_evidence":sorted(set(required)),"confidence":opportunity.confidence,"score":opportunity.score}

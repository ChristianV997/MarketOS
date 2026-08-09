from __future__ import annotations
import uuid
from .evidence_features import extract_evidence_features
from .market_models import MarketAttractivenessReport, MarketSignalSummary
from .scoring import score_market_attractiveness
from .recommendations import build_market_research_questions
from .intelligence_registry import get_commercial_intelligence_registry
def _read(score): return "strong recorded signal" if score>=70 else "moderate recorded signal" if score>=40 else "limited or missing evidence"
def analyze_market_category(workspace_id="default",category_name=None,opportunity_id=None,limit=500):
    features=extract_evidence_features(workspace_id,opportunity_id,category_name,limit=limit); category=category_name or features.metadata.get("category") or "Unspecified category"; scored=score_market_attractiveness(features.features); coverage=scored["coverage"]; values={x.signal_type:sum(y.normalized_value for y in features.features if y.signal_type==x.signal_type)/max(1,sum(y.signal_type==x.signal_type for y in features.features)) for x in features.features}; summary=MarketSignalSummary("market_summary_"+uuid.uuid4().hex[:16],workspace_id,category,values.get("demand",0),values.get("trend",0),values.get("competition",0),values.get("competition",0),values.get("seasonality",0),values.get("price",0),values.get("supplier",0),values.get("creative",0),scored["confidence"],coverage,sorted([k for k,v in values.items() if v>=60]),sorted([k for k in ("demand","trend","competition","price","supplier","creative") if coverage.get(k,0)==0]),[],scored["limitations"],[{"feature_id":x.feature_id,"source_object_id":x.source_object_id} for x in features.features],{"evidence_constrained":True}); report=MarketAttractivenessReport("market_report_"+uuid.uuid4().hex[:16],workspace_id,category,f"Market Intelligence: {category}",scored["score"],scored["confidence"],"fragmented/unclear" if len(features.features)<3 else "observed signals require interpretation",_read(values.get("demand",0)),_read(values.get("trend",0)),_read(values.get("competition",0)),_read(100-values.get("competition",0)),_read(values.get("seasonality",0)),_read(values.get("price",0)),_read(values.get("supplier",0)),_read(values.get("creative",0)),"Customer/pain-point evidence is limited unless audience signals are recorded.",["high competition or saturation risk"] if values.get("competition",0)>70 else [],scored["missing"],[],[],summary,metadata={"feature_set_id":features.feature_set_id,"opportunity_id":opportunity_id,"evidence_constrained":True}); report.recommended_research_questions=build_market_research_questions(report); reg=get_commercial_intelligence_registry(); reg.register_feature_set(features); reg.register_market_report(report)
    try:
        from backend.obsidian.sync import sync_evidence_feature_set_note, sync_market_intelligence_note
        sync_evidence_feature_set_note(features); sync_market_intelligence_note(report)
    except Exception: pass
    return report

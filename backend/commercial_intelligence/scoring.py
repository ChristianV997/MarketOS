from __future__ import annotations
from .evidence_features import EvidenceFeature

def bounded_score(value, default=0.0):
    try: return max(0.0,min(float(value),100.0))
    except (TypeError,ValueError): return default
def score_evidence_coverage(features):
    expected={"demand","trend","competition","price","margin","supplier","creative","customer","seasonality"}; present={x.signal_type for x in features}; return {signal:(100.0 if signal in present else 0.0) for signal in sorted(expected)}
def _avg(features, signal):
    xs=[x for x in features if x.signal_type==signal]; return sum(x.normalized_value*x.confidence for x in xs)/max(1,len(xs)) if xs else 0.0
def _confidence(features):
    if not features:return 0.0
    value=sum(x.confidence for x in features)/len(features); diversity=min(1.0,len({x.source_type for x in features})/4); synthetic=any("synthetic" in " ".join(x.limitations) for x in features); return max(0.0,min(1.0,value*.7+diversity*.3-(.25 if synthetic else 0)))
def score_market_attractiveness(features):
    coverage=score_evidence_coverage(features); demand=_avg(features,"demand"); trend=_avg(features,"trend"); competition=_avg(features,"competition"); saturation=competition; price=_avg(features,"price"); supplier=_avg(features,"supplier"); creative=_avg(features,"creative"); confidence=_confidence(features); score=bounded_score(demand*.2+trend*.15+(100-saturation)*.18+price*.1+supplier*.1+creative*.07+confidence*100*.2); missing=[x for x,v in coverage.items() if v==0]; return {"score":score,"confidence":confidence,"coverage":coverage,"missing":missing,"rationale":["Scores are deterministic proxies over persisted evidence.","Competition and saturation are interpreted separately from demand."],"limitations":list(dict.fromkeys([x for f in features for x in f.limitations]+(["missing_evidence_limits_interpretation"] if missing else [])))}
def score_product_viability(features, category_report=None):
    market=score_market_attractiveness(features); demand=_avg(features,"demand") or _avg(features,"trend"); margin=_avg(features,"margin"); supplier=_avg(features,"supplier"); price=_avg(features,"price"); creative=_avg(features,"creative"); competition=_avg(features,"competition"); differentiation=bounded_score(100-competition*.65+creative*.25); readiness=bounded_score((demand*.3+margin*.25+supplier*.2+price*.1+differentiation*.15)); score=bounded_score(demand*.2+differentiation*.2+margin*.15+supplier*.15+(100-competition)*.15+creative*.1+readiness*.05); return {"score":score,"confidence":market["confidence"],"demand":demand,"differentiation":differentiation,"margin":margin,"supplier":supplier,"competition":competition,"creative":creative,"readiness":readiness,"missing":market["missing"],"limitations":market["limitations"]}

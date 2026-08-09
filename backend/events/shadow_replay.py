"""Conservative, fixture-only shadow evidence classifier; no feature flags."""
from __future__ import annotations

PROMOTE="PROMOTE";KEEP_SHADOW="KEEP_SHADOW";REWORK="REWORK";DELETE="DELETE"
def classify_shadow_evidence(payload:dict)->dict:
    sample=int(payload.get("sample_size",0) or 0); minimum=int(payload.get("minimum_sample_size",1) or 1); metric=float(payload.get("primary_metric_delta",0) or 0); safety=float(payload.get("safety_metric_delta",0) or 0); tolerated=float(payload.get("max_tolerated_regression",0) or 0); blocker=bool(payload.get("safety_blocker",False))
    reasons=[]
    if blocker:return {"classification":REWORK,"reasons":["safety_blocker"]}
    if sample<minimum:return {"classification":KEEP_SHADOW,"reasons":["insufficient_sample_size"]}
    if safety < -abs(tolerated):return {"classification":REWORK,"reasons":["safety_metric_regression"]}
    if metric < -abs(tolerated):return {"classification":DELETE,"reasons":["primary_metric_regression"]}
    if metric>=0 and safety>=-abs(tolerated):return {"classification":PROMOTE,"reasons":["fixture_thresholds_satisfied"]}
    return {"classification":KEEP_SHADOW,"reasons":["evidence_inconclusive"]}

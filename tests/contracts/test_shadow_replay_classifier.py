from backend.events.shadow_replay import KEEP_SHADOW,PROMOTE,REWORK,classify_shadow_evidence
def test_shadow_classifier_is_conservative_and_explainable():
    assert classify_shadow_evidence({})["classification"]==KEEP_SHADOW
    assert classify_shadow_evidence({"sample_size":20,"minimum_sample_size":20,"primary_metric_delta":0,"safety_metric_delta":0,"max_tolerated_regression":.01})["classification"]==PROMOTE
    assert classify_shadow_evidence({"sample_size":20,"minimum_sample_size":20,"safety_blocker":True})["classification"]==REWORK

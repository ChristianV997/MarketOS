from backend.evaluation.shadow_features.models import (
    KEEP_SHADOW,
    EvaluationMetric,
    EvidenceRequirement,
    SafetyMetric,
    ShadowFeatureEvaluation,
)


def test_models_are_json_safe_and_round_trip():
    requirement = EvidenceRequirement(10, ["input"], ["metric"])
    evaluation = ShadowFeatureEvaluation(
        feature_id="normalized_scoring", classification=KEEP_SHADOW, fixture_name="fixture.jsonl",
        sample_size=2, confidence_level="low",
        primary_metrics=[EvaluationMetric("metric", 1, 0, 1, 1, passed=True)],
        safety_metrics=[SafetyMetric("safety", 1, 1, 0, True)], blockers=[], warnings=[],
        evidence_event_ids=["event-1"], replay_hashes=["hash"], recommendation="collect more",
        rationale=["insufficient_sample_size"], requirement=requirement,
    )
    assert ShadowFeatureEvaluation.from_dict(evaluation.to_dict()) == evaluation

from pathlib import Path

from backend.contracts.events import Event
from backend.evaluation.shadow_features.evaluator import evaluate_shadow_feature
from backend.events.replay_certification import load_canonical_jsonl


ROOT = Path("tests/fixtures/shadow_evaluation")


def _evaluate(name: str):
    events = load_canonical_jsonl(ROOT / name)
    return evaluate_shadow_feature(events, events[0].aggregate_id, fixture_name=name)


def test_promote_requires_sample_and_safety_evidence():
    assert _evaluate("attribution_pass_candidate.jsonl").classification == "PROMOTE"
    assert _evaluate("capital_policy_risk_adjusted_improvement.jsonl").classification == "KEEP_SHADOW"


def test_domain_safety_blockers_prevent_promotion():
    assert "candidate_revenue_exceeds_order_ground_truth" in _evaluate("attribution_revenue_inflation_blocker.jsonl").blockers
    assert "budget_cap_exceeded" in _evaluate("capital_policy_cap_violation.jsonl").blockers
    assert "unbounded_score_term_dominance" in _evaluate("normalized_scoring_unbounded_dominance.jsonl").blockers
    assert "risk_cap_loosened_in_worse_context" in _evaluate("adaptive_risk_safety_blocker.jsonl").blockers
    assert "expansion_with_negative_landed_contribution" in _evaluate("supplier_geo_negative_margin_blocker.jsonl").blockers


def test_missing_required_evidence_and_live_authority_never_promote():
    insufficient = Event(
        event_id="missing-evidence", workspace_id="fixture", aggregate_type="shadow_evaluation",
        aggregate_id="capital_policy", event_type="shadow_feature_observation", schema_version=1,
        occurred_at=1.0, correlation_id="correlation", source="test",
        payload={"feature_id": "capital_policy", "sample_size": 99, "baseline_value": 1, "candidate_value": 2},
        metadata={"synthetic": True},
    )
    assert evaluate_shadow_feature([insufficient], "capital_policy").classification == "KEEP_SHADOW"
    unsafe = Event(
        event_id="live-authority", workspace_id="fixture", aggregate_type="advisory",
        aggregate_id="capital_policy", event_type="shadow_feature_observation", schema_version=1,
        occurred_at=1.0, correlation_id="correlation", source="test",
        payload={
            "feature_id": "capital_policy", "sample_size": 99, "baseline_value": 1,
            "candidate_value": 2, "observed_event_types": ["budget_recommendation", "risk_state", "contribution_profit_projection"],
            "live_authority": True,
        }, metadata={"synthetic": True},
    )
    evaluation = evaluate_shadow_feature([unsafe], "capital_policy")
    assert evaluation.classification == "REWORK"
    assert any("live_authority" in blocker for blocker in evaluation.blockers)

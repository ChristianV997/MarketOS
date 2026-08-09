"""Evidence requirements for the financially material shadow features."""
from __future__ import annotations

from dataclasses import dataclass

from .models import EvidenceRequirement

ATTRIBUTION_RECONCILIATION = "attribution_reconciliation"
CAPITAL_POLICY = "capital_policy"
NORMALIZED_SCORING = "normalized_scoring"
ADAPTIVE_RISK = "adaptive_risk"
SUPPLIER_GEO_ECONOMICS = "supplier_geo_economics"
CALIBRATION_REGIME_CONFIDENCE = "calibration_regime_confidence"

CORE_FEATURE_IDS = (
    ATTRIBUTION_RECONCILIATION,
    CAPITAL_POLICY,
    NORMALIZED_SCORING,
    ADAPTIVE_RISK,
    SUPPLIER_GEO_ECONOMICS,
    CALIBRATION_REGIME_CONFIDENCE,
)


@dataclass(frozen=True)
class ShadowFeaturePolicy:
    """Static mapping used by reports; it has no feature-flag authority."""

    feature_id: str
    flag_name: str
    owner_paths: tuple[str, ...]
    promotion_risk: str
    status: str


def feature_policies() -> dict[str, ShadowFeaturePolicy]:
    """Describe audited core and deferred flags without importing their owners."""
    policies = [
        ShadowFeaturePolicy(
            ATTRIBUTION_RECONCILIATION, "ATTRIBUTION_RECONCILE_LIVE",
            ("backend/metrics/attribution.py", "backend/metrics/profitability.py"),
            "Inflated recognized revenue or omitted refunds can corrupt profitability decisions.", "implemented",
        ),
        ShadowFeaturePolicy(
            CAPITAL_POLICY, "CAPITAL_POLICY_LIVE", ("backend/decision/capital_policy.py",),
            "Unsafe concentration, drawdown, or allocation to blocked opportunities can increase losses.", "implemented",
        ),
        ShadowFeaturePolicy(
            NORMALIZED_SCORING, "SCORING_NORMALIZE_LIVE", ("backend/decision/engine.py", "backend/decision/scoring.py"),
            "An unsupported dominant score term can reorder candidates without evidence.", "implemented",
        ),
        ShadowFeaturePolicy(
            ADAPTIVE_RISK, "RISK_ADAPTIVE_LIVE", ("backend/risk/config.py", "backend/risk/gate.py"),
            "Loosening a cap during worse volatility or concentration can bypass loss controls.", "implemented",
        ),
        ShadowFeaturePolicy(
            SUPPLIER_GEO_ECONOMICS, "GEO_ECONOMICS_LIVE", ("backend/validation/suppliers.py", "backend/economics/supplier_feedback.py"),
            "Raw-ROAS expansion can be negative after landed costs, returns, or reliability.", "implemented",
        ),
        ShadowFeaturePolicy(
            CALIBRATION_REGIME_CONFIDENCE, "CALIBRATION_HOLDOUT_LIVE / REGIME_CONFIDENCE_WEIGHTING_LIVE",
            ("backend/learning/calibration.py", "backend/decision/confidence.py"),
            "Same-window leakage or overconfidence can make decisions appear safer than they are.", "implemented",
        ),
        ShadowFeaturePolicy("supplier_risk_ranking", "SUPPLIER_RISK_RANKING_LIVE", ("backend/validation/suppliers.py",), "Supplier selection may trade cost for unproven reliability.", "deferred"),
        ShadowFeaturePolicy("supplier_feedback", "SUPPLIER_FEEDBACK_LIVE", ("backend/economics/supplier_feedback.py",), "Sparse observations can overfit supplier reliability.", "deferred"),
        ShadowFeaturePolicy("ab_test_validity", "PHASE7_AB_TEST_VALIDITY_LIVE", ("core/creative/selection.py",), "Small samples can discard viable creative candidates.", "deferred"),
        ShadowFeaturePolicy("fatigue_detection", "PHASE7_FATIGUE_DETECTION_LIVE", ("core/creative/selection.py",), "Short-window noise can rotate creative prematurely.", "deferred"),
        ShadowFeaturePolicy("urgency_scoring", "PHASE7_URGENCY_SCORING_LIVE", ("backend/runtime/state.py",), "Weak trend evidence can over-prioritize an opportunity.", "deferred"),
        ShadowFeaturePolicy("monte_carlo", "PHASE7_MONTE_CARLO_LIVE", ("simulation/engine.py",), "Simulation confidence intervals can be misread as operational certainty.", "deferred"),
        ShadowFeaturePolicy("organic_channel", "PHASE8_ORGANIC_CHANNEL_LIVE", ("core/portfolio.py",), "Estimated organic economics can distort capital allocation.", "deferred"),
        ShadowFeaturePolicy("affiliate_scaling", "PHASE8_AFFILIATE_SCALING_LIVE", ("backend/integrations/affiliate_networks.py",), "Scaling can imply external partner actions outside this harness.", "deferred"),
    ]
    return {item.feature_id: item for item in policies}


def evaluation_matrix() -> dict[str, EvidenceRequirement]:
    """Return fresh requirements so callers cannot mutate global policy."""
    return {
        ATTRIBUTION_RECONCILIATION: EvidenceRequirement(
            minimum_sample_size=20,
            required_event_types=["attribution_claim_observed", "order_created", "payment_captured", "refund_issued"],
            required_metric_names=["deduplicated_recognized_revenue_accuracy"],
            requires_financial_projection=True,
        ),
        CAPITAL_POLICY: EvidenceRequirement(
            minimum_sample_size=30,
            required_event_types=["budget_recommendation", "risk_state", "contribution_profit_projection"],
            required_metric_names=["risk_adjusted_contribution"],
            requires_financial_projection=True,
        ),
        NORMALIZED_SCORING: EvidenceRequirement(
            minimum_sample_size=30,
            required_event_types=["legacy_score_observed", "candidate_normalized_score", "candidate_outcome_observed"],
            required_metric_names=["ranking_calibration"],
        ),
        ADAPTIVE_RISK: EvidenceRequirement(
            minimum_sample_size=30,
            required_event_types=["risk_state", "spend_cap_observed", "risk_recommendation"],
            required_metric_names=["downside_exposure_reduction"],
            requires_financial_projection=True,
        ),
        SUPPLIER_GEO_ECONOMICS: EvidenceRequirement(
            minimum_sample_size=30,
            required_event_types=["supplier_cost_observed", "shipping_cost_observed", "geo_margin_observed", "supplier_reliability_observed"],
            required_metric_names=["landed_contribution_margin"],
            requires_financial_projection=True,
        ),
        CALIBRATION_REGIME_CONFIDENCE: EvidenceRequirement(
            minimum_sample_size=50,
            required_event_types=["prediction_observed", "realized_outcome", "calibration_window", "regime_signal"],
            required_metric_names=["out_of_sample_calibration"],
        ),
    }

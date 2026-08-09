import math
import os

TRANSITION_CONFIDENCE_DAMPING = 0.85
TRANSITION_EXPLORATION_MULTIPLIER = 1.3
TRANSITION_COOLDOWN_EXPLORATION_MULTIPLIER = 1.1
MIN_TRANSITION_EXPLORATION_BOOST = 0.05

# ── confidence blend/smoothing weights ────────────────────────────────────────
# No shadow-mode instrumentation exists yet to calibrate these against real
# reality-gap/calibration-error outcomes (see backend/validation/shadow_flag_report.py's
# seven flags — none cover this path), so these remain documented, tunable
# defaults rather than fabricated "data-driven" values. Each pair is
# constrained to sum to 1.0 (checked by tests/test_decision_confidence_weights.py)
# so the two terms stay a true weighted average.
#
# GAP_WEIGHT / ERROR_WEIGHT: how much the reality-gap term vs. the
# calibration-error term drives the instantaneous confidence estimate.
# Reality gap is weighted higher (0.6) because it reflects the most recent
# executed decision's outcome directly, while calibration error is a
# slower-moving, model-level signal.
CONFIDENCE_GAP_WEIGHT = float(os.getenv("CONFIDENCE_GAP_WEIGHT", "0.6"))
CONFIDENCE_ERROR_WEIGHT = float(os.getenv("CONFIDENCE_ERROR_WEIGHT", "0.4"))

# SMOOTHING_RETAIN / SMOOTHING_NEW: exponential-moving-average weights
# applied to the previous confidence value vs. the freshly-computed one,
# damping cycle-to-cycle oscillation in the exploration/scale-down behavior
# apply_confidence() derives from this score.
CONFIDENCE_SMOOTHING_RETAIN = float(os.getenv("CONFIDENCE_SMOOTHING_RETAIN", "0.8"))
CONFIDENCE_SMOOTHING_NEW = float(os.getenv("CONFIDENCE_SMOOTHING_NEW", "0.2"))


class ConfidenceEngine:
    def __init__(self):
        self.last_confidence = 1.0

    def compute(self, reality_gap: float | None, calibration_error: float | None):
        """
        Combine reality gap + calibration error into confidence score [0,1]
        Lower gap + lower error → higher confidence
        """
        if reality_gap is None and calibration_error is None:
            return 1.0

        gap = reality_gap if reality_gap is not None else 0.0
        err = calibration_error if calibration_error is not None else 0.0

        # normalize using soft exponential decay
        gap_term = math.exp(-gap)
        err_term = math.exp(-abs(err))

        confidence = CONFIDENCE_GAP_WEIGHT * gap_term + CONFIDENCE_ERROR_WEIGHT * err_term

        # smooth to avoid oscillations
        confidence = (
            CONFIDENCE_SMOOTHING_RETAIN * self.last_confidence
            + CONFIDENCE_SMOOTHING_NEW * confidence
        )
        self.last_confidence = confidence

        return max(0.05, min(1.0, confidence))


confidence_engine = ConfidenceEngine()


def apply_confidence(decision: dict, confidence: float, transition: bool = False, cooldown: int = 0):
    """Modify decision score and exploration based on confidence"""
    effective_confidence = confidence * TRANSITION_CONFIDENCE_DAMPING if transition else confidence

    # scale score
    decision["score"] *= effective_confidence

    # attach confidence for logging
    decision["confidence"] = effective_confidence

    # adaptive behavior
    if effective_confidence < 0.4:
        decision["exploration_boost"] = 0.3
        decision["scale_down"] = True
    elif effective_confidence < 0.7:
        decision["exploration_boost"] = 0.1
        decision["scale_down"] = False
    else:
        decision["exploration_boost"] = 0.0
        decision["scale_down"] = False

    # Intentionally compound these multipliers: immediate transition shock plus short cooldown persistence.
    if transition:
        if decision["exploration_boost"] == 0.0:
            decision["exploration_boost"] = MIN_TRANSITION_EXPLORATION_BOOST
        decision["exploration_boost"] *= TRANSITION_EXPLORATION_MULTIPLIER
    if cooldown > 0:
        decision["exploration_boost"] *= TRANSITION_COOLDOWN_EXPLORATION_MULTIPLIER

    decision["exploration_boost"] = min(1.0, decision["exploration_boost"])
    decision["transition_adjustment"] = {
        "occurred": transition,
        "cooldown": max(0, cooldown),
    }

    return decision

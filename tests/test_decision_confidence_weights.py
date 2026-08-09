"""Invariant tests for backend.decision.confidence's tunable weight
constants — these are documented defaults (no shadow-mode calibration data
exists yet for this path), so the guard here is that each weighted pair
stays a true weighted average, not that the specific values are "correct"."""
from backend.decision.confidence import (
    CONFIDENCE_GAP_WEIGHT,
    CONFIDENCE_ERROR_WEIGHT,
    CONFIDENCE_SMOOTHING_RETAIN,
    CONFIDENCE_SMOOTHING_NEW,
)


def test_confidence_blend_weights_sum_to_one():
    assert CONFIDENCE_GAP_WEIGHT + CONFIDENCE_ERROR_WEIGHT == 1.0


def test_confidence_smoothing_weights_sum_to_one():
    assert CONFIDENCE_SMOOTHING_RETAIN + CONFIDENCE_SMOOTHING_NEW == 1.0


def test_confidence_weights_are_non_negative():
    assert CONFIDENCE_GAP_WEIGHT >= 0
    assert CONFIDENCE_ERROR_WEIGHT >= 0
    assert CONFIDENCE_SMOOTHING_RETAIN >= 0
    assert CONFIDENCE_SMOOTHING_NEW >= 0

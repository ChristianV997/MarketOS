"""Deterministic, read-only evaluation of shadow features from canonical events."""

from .evaluator import build_shadow_evaluation_report, evaluate_all_shadow_features, evaluate_shadow_feature
from .matrix import CORE_FEATURE_IDS, evaluation_matrix

__all__ = [
    "CORE_FEATURE_IDS",
    "build_shadow_evaluation_report",
    "evaluate_all_shadow_features",
    "evaluate_shadow_feature",
    "evaluation_matrix",
]

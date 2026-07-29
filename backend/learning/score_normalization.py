"""Score normalization and term weighting for decision engine.

Replaces the unnormalized flat sum (corrected_pred + c_score + velocity_bonus +
bandit_w + regime_bonus - competition_penalty) with z-scored term weighting
and Bayesian precision weighting.

Tracks rolling distributions of each term over recent decisions and normalizes
them against their historical mean/std, preventing any single term from dominating
due to scale differences.
"""
from __future__ import annotations

from collections import deque
import numpy as np


class ScoringTermTracker:
    """Tracks rolling statistics of decision-scoring terms."""

    def __init__(self, max_history: int = 100):
        """
        Args:
            max_history: number of past decision cycles to track
        """
        self.max_history = max_history
        self._term_history = {
            "corrected_pred": deque(maxlen=max_history),
            "c_score": deque(maxlen=max_history),
            "velocity_bonus": deque(maxlen=max_history),
            "bandit_w": deque(maxlen=max_history),
            "regime_bonus": deque(maxlen=max_history),
            "competition_penalty": deque(maxlen=max_history),
        }

    def record_terms(self, terms: dict) -> None:
        """Record observed term values from a decision cycle.

        Args:
            terms: dict with keys matching term names in _term_history
        """
        for key in self._term_history:
            if key in terms:
                self._term_history[key].append(float(terms[key]))

    def get_stats(self, term_name: str) -> dict:
        """Return mean, std, and count for a term.

        Returns:
            dict with keys 'mean', 'std', 'count'
        """
        hist = self._term_history.get(term_name, deque())
        if not hist:
            return {"mean": 0.0, "std": 1.0, "count": 0}

        vals = list(hist)
        return {
            "mean": float(np.mean(vals)),
            "std": float(np.std(vals) or 1e-6),  # avoid division by zero
            "count": len(vals),
        }

    def normalize_z_score(self, term_name: str, value: float) -> float:
        """Z-score normalize a term against its rolling history.

        Z = (x - mean) / std

        Args:
            term_name: name of the term
            value: raw value to normalize

        Returns:
            z-scored value
        """
        stats = self.get_stats(term_name)
        if stats["count"] < 2:
            return 0.0  # insufficient history
        z = (value - stats["mean"]) / stats["std"]
        return float(z)

    def combine_normalized_terms(self, normalized_terms: dict, precisions: dict = None) -> float:
        """Combine normalized terms using inverse-variance (Bayesian precision) weighting.

        Score = Σ(precision_i * z_i) / Σ(precision_i)

        Args:
            normalized_terms: dict with z-scored term values
            precisions: dict with precision weights (1/variance) per term.
                       Defaults to 1.0 for all terms.

        Returns:
            combined normalized score
        """
        if not normalized_terms:
            return 0.0

        if precisions is None:
            precisions = {k: 1.0 for k in normalized_terms}

        weighted_sum = 0.0
        precision_sum = 0.0

        for term_name, z_val in normalized_terms.items():
            precision = precisions.get(term_name, 1.0)
            weighted_sum += precision * z_val
            precision_sum += precision

        if precision_sum <= 0:
            return 0.0

        return float(weighted_sum / precision_sum)


# Singleton tracker shared across backend
_scorer_tracker = ScoringTermTracker(max_history=100)


def record_decision_terms(terms: dict) -> None:
    """Record raw decision terms for normalization statistics."""
    _scorer_tracker.record_terms(terms)


def normalize_and_combine(raw_terms: dict, confidence: float = 1.0,
                         use_precision_weighting: bool = True) -> float:
    """Normalize terms and combine them into a final decision score [0, 1].

    Args:
        raw_terms: dict with raw (unnormalized) term values
        confidence: confidence level (1/width²) for precision weighting
        use_precision_weighting: if True, use 1/variance as precision weight

    Returns:
        normalized combined score bounded to [0, 1] via sigmoid
    """
    normalized = {}
    precisions = {}

    for term_name, value in raw_terms.items():
        z = _scorer_tracker.normalize_z_score(term_name, value)
        normalized[term_name] = z

        # Precision = 1/variance (confidence-adjusted for some terms)
        stats = _scorer_tracker.get_stats(term_name)
        variance = stats["std"] ** 2 or 1.0

        # For bandit term, apply confidence weighting (higher confidence = higher precision)
        if term_name == "bandit_w" and use_precision_weighting:
            precisions[term_name] = confidence / variance
        else:
            precisions[term_name] = 1.0 / variance

    combined = _scorer_tracker.combine_normalized_terms(normalized, precisions)

    # Transform unbounded z-score to [0, 1] via sigmoid: 1 / (1 + exp(-z))
    # Scaled by 2 to make the midpoint (z=0) → 0.5, z=±1 → [0.27, 0.73]
    sigmoid = 1.0 / (1.0 + np.exp(-combined))
    return float(sigmoid)


def get_scoring_stats() -> dict:
    """Return current statistics for all tracked terms (for monitoring)."""
    return {
        term: _scorer_tracker.get_stats(term)
        for term in _scorer_tracker._term_history
    }

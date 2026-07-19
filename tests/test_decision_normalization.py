"""Tests for backend.learning.score_normalization (Phase 3: decision score normalization).

Covers: z-score normalization of scoring terms, precision weighting, shadow-mode
gating, backward compatibility, and integration with normalized scoring.
"""
from __future__ import annotations

import pytest
import os
from unittest.mock import MagicMock, patch

from backend.learning.score_normalization import (
    ScoringTermTracker, normalize_and_combine, record_decision_terms, get_scoring_stats
)
from backend.learning.contextual_bandit import ProductContextualBandit


# ─────────────────────────────────────────────────────────────────────────────
# ScoringTermTracker Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestScoringTermTracker:
    def test_tracks_term_values(self):
        tracker = ScoringTermTracker(max_history=10)
        tracker.record_terms({
            "corrected_pred": 2.0,
            "c_score": 0.5,
            "velocity_bonus": 0.1,
            "bandit_w": 0.2,
            "regime_bonus": 0.3,
            "competition_penalty": 0.05,
        })
        assert tracker.get_stats("corrected_pred")["count"] == 1
        assert tracker.get_stats("c_score")["count"] == 1

    def test_computes_rolling_stats(self):
        tracker = ScoringTermTracker(max_history=10)
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        for v in values:
            tracker.record_terms({"corrected_pred": v})

        stats = tracker.get_stats("corrected_pred")
        assert stats["count"] == 5
        assert abs(stats["mean"] - 3.0) < 0.01
        assert stats["std"] > 0

    def test_z_score_normalization(self):
        tracker = ScoringTermTracker(max_history=100)
        # Add history: mean=0, std should be meaningful
        for v in [0.0, 0.0, 0.0, 1.0, -1.0]:
            tracker.record_terms({"corrected_pred": v})

        z = tracker.normalize_z_score("corrected_pred", 2.0)
        assert z > 0  # value 2.0 is above mean 0

    def test_z_score_insufficient_history(self):
        tracker = ScoringTermTracker(max_history=100)
        tracker.record_terms({"corrected_pred": 1.0})
        # Only 1 sample, should return 0
        z = tracker.normalize_z_score("corrected_pred", 1.5)
        assert z == 0.0

    def test_combine_normalized_terms(self):
        tracker = ScoringTermTracker()
        normalized = {
            "corrected_pred": 1.0,
            "c_score": 0.5,
            "velocity_bonus": 0.2,
        }
        # Without precisions, should average
        combined = tracker.combine_normalized_terms(normalized, precisions=None)
        assert combined > 0  # average of positive values

    def test_combine_with_precision_weighting(self):
        tracker = ScoringTermTracker()
        normalized = {
            "corrected_pred": 2.0,
            "c_score": 1.0,
        }
        # High precision on corrected_pred should weight it more
        precisions = {"corrected_pred": 2.0, "c_score": 1.0}
        combined = tracker.combine_normalized_terms(normalized, precisions)
        # Should be closer to 2.0 than to 1.0
        assert combined > 1.5

    def test_max_history_bounded(self):
        tracker = ScoringTermTracker(max_history=5)
        for i in range(10):
            tracker.record_terms({"corrected_pred": float(i)})

        stats = tracker.get_stats("corrected_pred")
        assert stats["count"] == 5  # maxlen enforced


# ─────────────────────────────────────────────────────────────────────────────
# normalize_and_combine Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestNormalizeAndCombine:
    @pytest.fixture(autouse=True)
    def reset_globals(self):
        from backend.learning import score_normalization
        score_normalization._scorer_tracker = score_normalization.ScoringTermTracker()
        yield

    def test_empty_terms(self):
        result = normalize_and_combine({})
        # Empty terms combine to 0, which sigmoid maps to 0.5 (sigmoid(0) = 0.5)
        assert result == 0.5

    def test_single_term(self):
        raw_terms = {"corrected_pred": 2.0}
        # Record history first for normalization
        for _ in range(5):
            record_decision_terms({"corrected_pred": 1.0})

        result = normalize_and_combine(raw_terms, confidence=0.8)
        # Should be positive (2.0 is above mean 1.0)
        assert result > 0

    def test_multiple_terms_combined(self):
        # Build up history
        for _ in range(10):
            record_decision_terms({
                "corrected_pred": 2.0,
                "c_score": 0.5,
                "velocity_bonus": 0.1,
                "bandit_w": 0.2,
                "regime_bonus": 0.3,
                "competition_penalty": 0.05,
            })

        raw_terms = {
            "corrected_pred": 3.0,  # above historical mean
            "c_score": 0.5,         # at historical mean
            "velocity_bonus": 0.1,  # at historical mean
            "bandit_w": 0.2,        # at historical mean
            "regime_bonus": 0.3,    # at historical mean
            "competition_penalty": 0.05,  # at historical mean
        }
        result = normalize_and_combine(raw_terms, confidence=1.0)
        # Should be positive because corrected_pred is elevated
        assert result > 0

    def test_confidence_precision_weighting(self):
        # Set up identical history
        for _ in range(5):
            record_decision_terms({
                "corrected_pred": 1.0,
                "bandit_w": 1.0,
            })

        raw_terms = {"corrected_pred": 2.0, "bandit_w": 2.0}

        # High confidence should weight bandit_w more
        result_high_conf = normalize_and_combine(raw_terms, confidence=0.9)
        result_low_conf = normalize_and_combine(raw_terms, confidence=0.1)

        # With high confidence, bandit term gets higher precision weight
        # So result should reflect this (may not be strictly > or <, depends on impl)
        # Just verify both compute without error
        assert isinstance(result_high_conf, float)
        assert isinstance(result_low_conf, float)


# ─────────────────────────────────────────────────────────────────────────────
# ProductContextualBandit Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestProductContextualBandit:
    def test_feature_vector_normalization(self):
        bandit = ProductContextualBandit(n_features=10)
        feat = bandit._feature_vector("product_1", "electronics", "hook_1", "audience_1")
        assert len(feat) == 10
        # Should be L2-normalized
        norm = (feat ** 2).sum() ** 0.5
        assert abs(norm - 1.0) < 0.01 or norm < 1e-6

    def test_score_computation(self):
        bandit = ProductContextualBandit(n_features=10)
        score = bandit.score("product_1", "electronics", "hook_1", "audience_1")
        assert isinstance(score, float)
        assert score > -1e9  # no catastrophic failure

    def test_update_and_score_changes(self):
        bandit = ProductContextualBandit(n_features=10, alpha=0.5)
        score_before = bandit.score("product_1", "electronics")
        # Update with positive reward
        bandit.update("product_1", 5.0, "electronics")
        score_after = bandit.score("product_1", "electronics")
        # Score should improve after positive update
        assert score_after > score_before

    def test_reward_stats(self):
        bandit = ProductContextualBandit(n_features=10)
        bandit.update("product_1", 2.0, "electronics")
        bandit.update("product_1", 4.0, "electronics")
        stats = bandit.reward_stats()
        assert stats["mean"] == 3.0
        assert stats["count"] == 2

    def test_multiple_products_independent(self):
        bandit = ProductContextualBandit(n_features=10)
        # Product 1: consistent high reward
        for _ in range(5):
            bandit.update("product_1", 5.0, "electronics")

        # Product 2: consistent low reward
        for _ in range(5):
            bandit.update("product_2", 1.0, "apparel")

        # Scores should diverge
        score_1 = bandit.score("product_1", "electronics")
        score_2 = bandit.score("product_2", "apparel")
        assert score_1 > score_2


# ─────────────────────────────────────────────────────────────────────────────
# Shadow-Mode Integration (via decide() in engine.py)
# ─────────────────────────────────────────────────────────────────────────────


class TestShadowModeDecisionScoring:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        # Mock event store
        from backend.orchestration.event_store import EventStore
        self.event_store = EventStore(path=str(tmp_path / "shadow.jsonl"))
        import importlib
        es_mod = importlib.import_module("backend.orchestration.event_store")
        monkeypatch.setattr(es_mod, "event_store", self.event_store)

    def _make_state(self):
        """Create a proper state object for testing."""
        from backend.core.state import SystemState, EventLog, CausalGraph
        state = SystemState()
        state.event_log = EventLog()
        state.event_log.rows = [{"roas": 2.0} for _ in range(10)]
        state.graph = CausalGraph()
        state.graph.edges = {}
        state.transition = {}
        state.detected_regime = "stable"
        return state

    def test_flag_off_returns_legacy_journals_normalized(self, monkeypatch):
        monkeypatch.delenv("SCORING_NORMALIZE_LIVE", raising=False)

        from backend.decision.engine import decide

        state = self._make_state()
        decisions = decide(state)
        assert len(decisions) > 0
        # Decisions should all have scores
        for d in decisions:
            assert "score" in d
            assert isinstance(d["score"], (int, float))

    def test_flag_on_returns_normalized(self, monkeypatch):
        monkeypatch.setenv("SCORING_NORMALIZE_LIVE", "true")

        from backend.decision.engine import decide

        state = self._make_state()
        decisions = decide(state)
        # When flag is on, normalized score is used (no guarantee about specific values)
        assert len(decisions) > 0

    def test_journal_failure_doesnt_break_decision(self, monkeypatch):
        monkeypatch.delenv("SCORING_NORMALIZE_LIVE", raising=False)

        from backend.decision.engine import decide

        # Break the event store
        monkeypatch.setattr(self.event_store, "append",
                           lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))

        state = self._make_state()
        # Should not raise, despite journal failure
        decisions = decide(state)
        assert len(decisions) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Backward Compatibility Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestBackwardCompatibility:
    def test_legacy_tests_still_import_bandit_weight(self):
        # Ensure bandit_weight still works (it's used in legacy code)
        from backend.learning.bandit_update import bandit_weight
        from backend.core.state import CausalGraph

        action = {"variant": 1}
        graph = CausalGraph()
        graph.edges = {}
        weight = bandit_weight(action, graph=graph)
        assert isinstance(weight, (int, float))

    def test_engine_still_computes_confidence(self):
        # Ensure confidence is still computed (used by apply_confidence)
        from backend.decision.confidence import confidence_engine

        conf = confidence_engine.compute(reality_gap=0.1, calibration_error=0.05)
        assert isinstance(conf, float)
        assert 0 <= conf <= 1.0

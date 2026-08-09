"""Tests for core.content.patterns — Phase 7 A/B testing validity improvements."""
from __future__ import annotations

import pytest

from core.content.patterns import PatternStore


class TestSampleSizeWeightedAverage:
    """Phase 7: sample-size-weighted running average replaces (prev+new)/2."""

    def test_first_observation_sets_score(self):
        store = PatternStore()
        store.update({"hook_scores": {"hook_1": 2.0}})
        assert store.get_observation_count("hook_1") == 1
        patterns = store.get_patterns()
        assert patterns["hook_scores"]["hook_1"] == 2.0

    def test_second_observation_weighted_by_count(self):
        store = PatternStore()
        store.update({"hook_scores": {"hook_1": 2.0}})
        store.update({"hook_scores": {"hook_1": 4.0}})
        # Expected: (1*2.0 + 4.0) / 2 = 3.0
        patterns = store.get_patterns()
        assert patterns["hook_scores"]["hook_1"] == pytest.approx(3.0, abs=0.01)
        assert store.get_observation_count("hook_1") == 2

    def test_many_observations_converge_to_true_mean(self):
        store = PatternStore()
        # Record 100 obs of value 5.0
        for _ in range(100):
            store.update({"hook_scores": {"hook_1": 5.0}})

        patterns = store.get_patterns()
        assert patterns["hook_scores"]["hook_1"] == pytest.approx(5.0, abs=0.01)
        assert store.get_observation_count("hook_1") == 100

    def test_old_average_resists_single_outlier(self):
        store = PatternStore()
        # Build up 50 observations at 2.0
        for _ in range(50):
            store.update({"hook_scores": {"hook_1": 2.0}})

        # Add one outlier at 10.0
        store.update({"hook_scores": {"hook_1": 10.0}})

        patterns = store.get_patterns()
        score = patterns["hook_scores"]["hook_1"]
        # (50*2.0 + 10.0) / 51 ≈ 2.16, not (2.0 + 10.0)/2 = 6.0
        assert score == pytest.approx(2.16, abs=0.01)
        assert score < 3.0  # Much closer to 2.0 than to 10.0

    def test_converges_to_new_regime_eventually(self):
        store = PatternStore()
        # 50 observations at 1.0
        for _ in range(50):
            store.update({"hook_scores": {"hook_1": 1.0}})

        # Now 50 observations at 3.0 (regime shift)
        for _ in range(50):
            store.update({"hook_scores": {"hook_1": 3.0}})

        patterns = store.get_patterns()
        score = patterns["hook_scores"]["hook_1"]
        # (50*1.0 + 50*3.0) / 100 = 2.0
        assert score == pytest.approx(2.0, abs=0.01)

    def test_angle_and_regime_scores_tracked_separately(self):
        store = PatternStore()
        store.update({
            "hook_scores": {"hook_1": 2.0},
            "angle_scores": {"angle_1": 3.0},
            "regime_scores": {"stable": 1.5},
        })
        assert store.get_observation_count("hook_1", "hook") == 1
        assert store.get_observation_count("angle_1", "angle") == 1
        assert store.get_observation_count("stable", "regime") == 1


class TestStatisticalValidity:
    """Phase 7: A/B testing validity gates (minimum sample size, significance)."""

    def test_insufficient_samples_not_valid(self):
        store = PatternStore()
        for _ in range(5):
            store.update({"hook_scores": {"hook_1": 2.0}})

        assert not store.is_statistically_valid("hook_1", category="hook", min_samples=20)

    def test_sufficient_samples_is_valid(self):
        store = PatternStore()
        for _ in range(25):
            store.update({"hook_scores": {"hook_1": 2.0}})

        assert store.is_statistically_valid("hook_1", category="hook", min_samples=20)

    def test_custom_min_samples_threshold(self):
        store = PatternStore()
        for _ in range(10):
            store.update({"hook_scores": {"hook_1": 2.0}})

        assert not store.is_statistically_valid("hook_1", min_samples=20)
        assert store.is_statistically_valid("hook_1", min_samples=5)

    def test_observation_count_getter(self):
        store = PatternStore()
        assert store.get_observation_count("hook_1") == 0

        for i in range(15):
            store.update({"hook_scores": {"hook_1": float(i)}})

        assert store.get_observation_count("hook_1") == 15

    def test_category_isolation(self):
        store = PatternStore()
        for _ in range(25):
            store.update({"hook_scores": {"hook_1": 2.0}})

        for _ in range(5):
            store.update({"angle_scores": {"angle_1": 3.0}})

        assert store.is_statistically_valid("hook_1", category="hook", min_samples=20)
        assert not store.is_statistically_valid("angle_1", category="angle", min_samples=20)


class TestPersistenceWithCounts:
    """Phase 7: snapshot/restore must preserve observation counts."""

    def test_snapshot_includes_counts(self):
        store = PatternStore()
        for _ in range(15):
            store.update({"hook_scores": {"hook_1": 2.0}})

        snapshot = store.snapshot()
        assert "hook_counts" in snapshot
        assert snapshot["hook_counts"]["hook_1"] == 15

    def test_restore_recovers_counts(self):
        store1 = PatternStore()
        for _ in range(15):
            store1.update({"hook_scores": {"hook_1": 2.0}})

        snapshot = store1.snapshot()

        store2 = PatternStore()
        store2.restore(snapshot)
        assert store2.get_observation_count("hook_1") == 15

    def test_backward_compat_missing_counts(self):
        """Old snapshots without counts should work (infer count=1 per score)."""
        store = PatternStore()
        old_snapshot = {
            "hook_scores": {"hook_1": 2.0, "hook_2": 3.0},
            "angle_scores": {},
            "regime_scores": {},
            # No counts present
        }
        store.restore(old_snapshot)

        # Should infer count=1 for each score
        assert store.get_observation_count("hook_1") == 1
        assert store.get_observation_count("hook_2") == 1

    def test_persist_and_restore_round_trip(self):
        import tempfile
        import os

        store1 = PatternStore()
        for i in range(20):
            store1.update({"hook_scores": {"hook_1": 2.0 + float(i % 5) * 0.1}})

        snapshot = store1.snapshot()

        store2 = PatternStore()
        store2.restore(snapshot)

        patterns1 = store1.get_patterns()
        patterns2 = store2.get_patterns()

        assert patterns1["hook_scores"]["hook_1"] == patterns2["hook_scores"]["hook_1"]
        assert store1.get_observation_count("hook_1") == store2.get_observation_count("hook_1")


class TestMultiplePatterns:
    """Multiple patterns updated together."""

    def test_update_multiple_hooks_independently(self):
        store = PatternStore()
        for _ in range(20):
            store.update({
                "hook_scores": {"hook_1": 2.0, "hook_2": 3.0},
            })

        assert store.get_observation_count("hook_1") == 20
        assert store.get_observation_count("hook_2") == 20
        patterns = store.get_patterns()
        assert patterns["hook_scores"]["hook_1"] == pytest.approx(2.0, abs=0.01)
        assert patterns["hook_scores"]["hook_2"] == pytest.approx(3.0, abs=0.01)

    def test_hooks_angles_regimes_all_tracked(self):
        store = PatternStore()
        for _ in range(15):
            store.update({
                "hook_scores": {"hook_1": 2.0},
                "angle_scores": {"angle_1": 3.0},
                "regime_scores": {"stable": 1.5},
            })

        assert store.is_statistically_valid("hook_1", "hook", min_samples=10)
        assert store.is_statistically_valid("angle_1", "angle", min_samples=10)
        assert store.is_statistically_valid("stable", "regime", min_samples=10)

    def test_mixed_valid_invalid_patterns(self):
        store = PatternStore()
        for _ in range(25):
            store.update({"hook_scores": {"hook_1": 2.0}})

        for _ in range(5):
            store.update({"hook_scores": {"hook_2": 3.0}})

        assert store.is_statistically_valid("hook_1", min_samples=20)
        assert not store.is_statistically_valid("hook_2", min_samples=20)

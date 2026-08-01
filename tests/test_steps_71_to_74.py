"""Tests for Steps 71–74.

Step 71 — Cross-Playbook Optimizer + Meta-Learning Layer
Step 72 (Master Drop) — Phase Controller + Resource Allocator + POD_001
Step 73 — Discovery: clustering, angles, products
Step 74 — Content feedback + memory log
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Step 71 — playbooks: performance
# ---------------------------------------------------------------------------

class TestPlaybookPerformance:
    def setup_method(self):
        from core.playbooks.performance import clear
        clear()

    def test_record_and_get_avg(self):
        from core.playbooks.performance import record, get_avg
        record("pb1", "US", "tiktok", {"ctr": 0.1, "roas": 2.0})
        record("pb1", "US", "tiktok", {"ctr": 0.2, "roas": 3.0})
        avg = get_avg("pb1", "US", "tiktok")
        assert avg is not None
        assert avg["ctr"] == pytest.approx(0.15)
        assert avg["roas"] == pytest.approx(2.5)

    def test_get_avg_no_data_returns_none(self):
        from core.playbooks.performance import get_avg
        assert get_avg("unknown", "US", "meta") is None

    def test_clear_removes_all(self):
        from core.playbooks.performance import record, get_avg, clear
        record("pb2", "MX", "tiktok", {"ctr": 0.05, "roas": 1.0})
        clear()
        assert get_avg("pb2", "MX", "tiktok") is None

    def test_missing_keys_default_to_zero(self):
        from core.playbooks.performance import record, get_avg
        record("pb3", "US", "tiktok", {})
        avg = get_avg("pb3", "US", "tiktok")
        assert avg == {"ctr": 0.0, "roas": 0.0}


# ---------------------------------------------------------------------------
# Step 71 — playbooks: selector
# ---------------------------------------------------------------------------

class TestPlaybookSelector:
    def setup_method(self):
        from core.playbooks.performance import clear
        clear()

    def test_select_returns_highest_roas(self):
        from core.playbooks.performance import record
        from core.playbooks.selector import select
        record("low", "US", "tiktok", {"ctr": 0.05, "roas": 1.0})
        record("high", "US", "tiktok", {"ctr": 0.1, "roas": 3.0})
        playbooks = [{"id": "low"}, {"id": "high"}]
        best = select(playbooks, "US", "tiktok")
        assert best["id"] == "high"

    def test_select_uses_exploration_score_when_no_data(self):
        from core.playbooks.selector import select
        playbooks = [{"id": "a"}, {"id": "b"}]
        result = select(playbooks, "US", "tiktok")
        assert result in playbooks

    def test_select_raises_on_empty(self):
        from core.playbooks.selector import select
        with pytest.raises(ValueError):
            select([], "US", "tiktok")

    def test_select_prefers_performance_over_exploration(self):
        from core.playbooks.performance import record
        from core.playbooks.selector import select
        # One playbook has known ROAS > exploration score (0.5)
        record("known", "US", "meta", {"ctr": 0.0, "roas": 2.0})
        playbooks = [{"id": "known"}, {"id": "unknown"}]
        result = select(playbooks, "US", "meta")
        assert result["id"] == "known"


# ---------------------------------------------------------------------------
# Step 71 — playbooks: bandit
# ---------------------------------------------------------------------------

class TestPlaybookBandit:
    def setup_method(self):
        from core.playbooks.performance import clear
        clear()

    def test_choose_returns_playbook(self):
        from core.playbooks.bandit import choose
        playbooks = [{"id": "x"}, {"id": "y"}]
        result = choose(playbooks, epsilon=0.0)
        assert result in playbooks

    def test_choose_explores_with_epsilon_one(self):
        from core.playbooks.bandit import choose
        playbooks = [{"id": "x"}, {"id": "y"}, {"id": "z"}]
        # With epsilon=1.0 always explores — result must still be a valid choice
        result = choose(playbooks, epsilon=1.0)
        assert result in playbooks

    def test_choose_raises_on_empty(self):
        from core.playbooks.bandit import choose
        with pytest.raises(ValueError):
            choose([])

    def test_choose_exploits_best(self):
        from core.playbooks.performance import record
        from core.playbooks.bandit import choose
        record("best", "US", "tiktok", {"ctr": 0.2, "roas": 4.0})
        record("worst", "US", "tiktok", {"ctr": 0.01, "roas": 0.5})
        playbooks = [{"id": "best"}, {"id": "worst"}]
        # With epsilon=0.0 always exploits
        result = choose(playbooks, geo="US", platform="tiktok", epsilon=0.0)
        assert result["id"] == "best"


# ---------------------------------------------------------------------------
# Step 71 — meta: insights
# ---------------------------------------------------------------------------

class TestMetaInsights:
    def test_detects_pattern(self):
        from core.meta.insights import detect_patterns
        history = [{"geo": "US", "angle": "satisfaction", "roas": 2.8}]
        insights = detect_patterns(history)
        assert any("satisfaction" in i and "US" in i for i in insights)

    def test_no_pattern_for_low_roas(self):
        from core.meta.insights import detect_patterns
        history = [{"geo": "US", "angle": "satisfaction", "roas": 1.0}]
        insights = detect_patterns(history)
        assert insights == []

    def test_includes_platform_when_present(self):
        from core.meta.insights import detect_patterns
        history = [{"geo": "US", "angle": "curiosity", "roas": 2.0, "platform": "tiktok"}]
        insights = detect_patterns(history)
        assert any("tiktok" in i for i in insights)

    def test_no_duplicate_insights(self):
        from core.meta.insights import detect_patterns
        history = [
            {"geo": "US", "angle": "satisfaction", "roas": 2.0},
            {"geo": "US", "angle": "satisfaction", "roas": 3.0},
        ]
        insights = detect_patterns(history)
        satisfaction_us = [i for i in insights if "satisfaction" in i and "US" in i]
        assert len(satisfaction_us) == 1

    def test_empty_history_returns_empty(self):
        from core.meta.insights import detect_patterns
        assert detect_patterns([]) == []


# NOTE: This branch's own core/system/phase_controller.py and
# core/system/resource_allocator.py (tested by the two classes formerly
# here — TestPhaseController, TestResourceAllocator) were superseded by
# main's more mature, thread-safe, env-configurable implementations during
# the branch merge (see docs/plan for this merge) — main's phase_controller
# is a singleton with drawdown-awareness, not the simple class these tests
# expected. Removed rather than adapted since the two APIs are unrelated.

# ---------------------------------------------------------------------------
# Step 72 Master Drop — POD_001
# ---------------------------------------------------------------------------

class TestPod001:
    def test_run_pod_empty_signals(self):
        from pods.pod_001 import run_pod
        result = run_pod(signals=[])
        assert "products" in result
        assert "creatives" in result
        assert isinstance(result["products"], list)
        assert isinstance(result["creatives"], list)

    def test_run_pod_with_signals(self):
        from pods.pod_001 import run_pod
        signals = [
            {"text": "satisfying clean gadget", "views": 1000, "likes": 100},
            {"text": "kitchen blender review", "views": 500, "likes": 50},
        ]
        result = run_pod(signals=signals)
        assert len(result["products"]) >= 1
        assert len(result["creatives"]) >= 1

    def test_run_pod_creatives_have_hook(self):
        from pods.pod_001 import run_pod
        signals = [{"text": "clean satisfying asmr", "views": 2000}]
        result = run_pod(signals=signals)
        for creative in result["creatives"]:
            assert "hook" in creative


# ---------------------------------------------------------------------------
# Step 73 — discovery: clustering
# ---------------------------------------------------------------------------

class TestDiscoveryClustering:
    def test_extract_niche_cleaning(self):
        from discovery.clustering import extract_niche
        assert extract_niche("this is a clean product") == "cleaning"

    def test_extract_niche_kitchen(self):
        from discovery.clustering import extract_niche
        assert extract_niche("best blender for kitchen") == "kitchen"

    def test_extract_niche_general_fallback(self):
        from discovery.clustering import extract_niche
        assert extract_niche("random unrelated text here") == "general"

    def test_cluster_groups_signals(self):
        from discovery.clustering import cluster
        signals = [
            {"text": "clean surface"},
            {"text": "kitchen recipe"},
            {"text": "kitchen blender"},
        ]
        result = cluster(signals)
        assert "cleaning" in result
        assert "kitchen" in result
        assert len(result["kitchen"]) == 2

    def test_cluster_empty_input(self):
        from discovery.clustering import cluster
        assert cluster([]) == {}


# ---------------------------------------------------------------------------
# Step 73 — discovery: angles
# ---------------------------------------------------------------------------

class TestDiscoveryAngles:
    def test_detects_satisfaction_angle(self):
        from discovery.angles import extract_angles
        angles = extract_angles({"text": "this is oddly satisfying"})
        assert "satisfaction" in angles

    def test_detects_problem_solution_angle(self):
        from discovery.angles import extract_angles
        angles = extract_angles({"text": "fix the problem fast"})
        assert "problem-solution" in angles

    def test_detects_transformation_angle(self):
        from discovery.angles import extract_angles
        angles = extract_angles("before and after transformation")
        assert "transformation" in angles

    def test_no_angle_returns_empty(self):
        from discovery.angles import extract_angles
        angles = extract_angles({"text": "unrelated content xyz"})
        assert angles == []

    def test_multiple_angles_detected(self):
        from discovery.angles import extract_angles
        angles = extract_angles({"text": "satisfying fix before easy"})
        assert "satisfaction" in angles
        assert "problem-solution" in angles


# ---------------------------------------------------------------------------
# Step 73 — discovery: products
# ---------------------------------------------------------------------------

class TestDiscoveryProducts:
    def test_generate_products_returns_list(self):
        from discovery.products import generate_products
        signals = [{"text": "clean satisfying product"}]
        products = generate_products(signals)
        assert isinstance(products, list)
        assert len(products) == 1

    def test_product_has_required_keys(self):
        from discovery.products import generate_products
        signals = [{"text": "kitchen blender easy recipe"}]
        products = generate_products(signals)
        for p in products:
            assert "niche" in p
            assert "name" in p
            assert "angles" in p

    def test_niche_assigned_correctly(self):
        from discovery.products import generate_products
        signals = [{"text": "satisfying clean gadget"}]
        products = generate_products(signals)
        assert products[0]["niche"] == "cleaning"

    def test_empty_signals(self):
        from discovery.products import generate_products
        assert generate_products([]) == []

    def test_angles_populated(self):
        from discovery.products import generate_products
        signals = [{"text": "satisfying clean product"}]
        products = generate_products(signals)
        assert "satisfaction" in products[0]["angles"]


# NOTE: This branch's own core/content/feedback.py (tested by the
# TestContentFeedback class formerly here) was superseded by main's
# existing content-feedback module (a different API — see
# orchestrator/main.py's `from core.content.feedback import batch_classify`)
# during the branch merge. Removed rather than adapted since the two APIs
# are unrelated.

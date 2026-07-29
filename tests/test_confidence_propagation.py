from backend.agents.allocator import StrategyAllocator
from backend.agents.self_healing_guard import GuardedSelfHealing
from backend.causal.graph import CausalGraph
from backend.learning.bandit_update import bandit_memory, bandit_weight


def test_allocator_uses_confidence_and_exploration_boost():
    allocator = StrategyAllocator()
    low_conf = allocator.allocate("exploratory", total_actions=10, confidence=0.3, exploration_boost=0.3)
    high_conf = allocator.allocate("exploratory", total_actions=10, confidence=0.9, exploration_boost=0.0)
    assert low_conf >= high_conf


def test_bandit_weight_changes_with_confidence():
    # .copy() preserves bandit_memory.history's actual type (an OrderedDict
    # of bounded deques) — dict(...) would coerce it to a plain dict,
    # permanently breaking the OrderedDict-only move_to_end() call in
    # BanditMemory.update() for every test that runs afterward in this
    # process once restored below.
    original = bandit_memory.history.copy()
    graph = CausalGraph()
    graph.add_edge("exploratory", "roas", 0.2)
    action = ("exploratory", "campaign-1")
    bandit_memory.update(action, 1.0)
    bandit_memory.update(action, 1.2)
    low = bandit_weight(action, graph, confidence=0.2)
    high = bandit_weight(action, graph, confidence=0.9)
    assert low != high
    bandit_memory.history = original


def test_self_healing_guard_requires_gap_and_low_confidence():
    guard = GuardedSelfHealing(gap_threshold=0.5, confidence_threshold=0.5)
    assert guard.should_heal(reality_gap=0.8, confidence=0.2) is True
    assert guard.should_heal(reality_gap=0.8, confidence=0.8) is False
    assert guard.should_heal(reality_gap=0.2, confidence=0.2) is False

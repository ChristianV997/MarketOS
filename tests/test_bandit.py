from backend.learning.bandit_update import BanditMemory
from backend.causal.graph import CausalGraph


def test_empty_stats():
    bm = BanditMemory()
    stats = bm.stats({"variant": 1})
    assert stats["mean"] == 0
    assert stats["var"] == 1


def test_update_and_stats():
    bm = BanditMemory()
    action = {"variant": 2}
    bm.update(action, 1.0)
    bm.update(action, 3.0)
    stats = bm.stats(action)
    assert stats["mean"] == 2.0
    assert stats["var"] == 1.0


def test_bandit_weight_grows_with_mean():
    from backend.learning.bandit_update import bandit_weight
    bm = BanditMemory()
    g = CausalGraph()
    action = {"variant": 3}
    bm.update(action, 2.0)
    bm.update(action, 2.0)
    import backend.learning.bandit_update as bu
    orig = bu.bandit_memory
    bu.bandit_memory = bm
    w = bandit_weight(action, g)
    bu.bandit_memory = orig
    assert w > 0


def test_differently_ordered_equal_dicts_share_one_bandit_key():
    """str(action) is dict-insertion-order-sensitive — two semantically
    identical action dicts built with keys in a different order must still
    land in the same bandit-memory bucket."""
    bm = BanditMemory()
    action_a = {"variant": "x", "phase": "SCALE"}
    action_b = {"phase": "SCALE", "variant": "x"}
    bm.update(action_a, 1.0)
    bm.update(action_b, 3.0)
    stats = bm.stats(action_a)
    assert stats["mean"] == 2.0
    assert len(bm.history) == 1

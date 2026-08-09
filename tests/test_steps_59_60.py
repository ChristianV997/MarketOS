"""Tests for Steps 59 and 60.

Step 59 — Multi-Step RL + Cross-Domain Transfer
Step 60 — World-Model Planning + Hierarchical RL
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Step 59 tests
# ---------------------------------------------------------------------------

class TestTrajectoryBuffer:
    def test_push_and_len(self):
        from core.rl.trajectory_buffer import TrajectoryBuffer
        buf = TrajectoryBuffer(maxlen=10)
        buf.push([{"state": {}, "action": "A", "reward": 1.0}])
        assert len(buf) == 1

    def test_push_empty_ignored(self):
        from core.rl.trajectory_buffer import TrajectoryBuffer
        buf = TrajectoryBuffer()
        buf.push([])
        assert len(buf) == 0

    def test_sample_returns_list(self):
        from core.rl.trajectory_buffer import TrajectoryBuffer
        buf = TrajectoryBuffer()
        for i in range(5):
            buf.push([{"state": {}, "action": "A", "reward": float(i)}])
        sample = buf.sample(3)
        assert isinstance(sample, list)
        assert len(sample) == 3

    def test_maxlen_eviction(self):
        from core.rl.trajectory_buffer import TrajectoryBuffer
        buf = TrajectoryBuffer(maxlen=3)
        for i in range(5):
            buf.push([{"state": {}, "action": "A", "reward": float(i)}])
        assert len(buf) == 3


class TestReturns:
    def test_discounted_returns_single(self):
        from core.rl.returns import discounted_returns
        result = discounted_returns([1.0], gamma=0.99)
        assert result == pytest.approx([1.0])

    def test_discounted_returns_multi(self):
        from core.rl.returns import discounted_returns
        # G_0 = 1 + 0.99 * 1 = 1.99, G_1 = 1
        result = discounted_returns([1.0, 1.0], gamma=0.99)
        assert len(result) == 2
        assert result[1] == pytest.approx(1.0)
        assert result[0] == pytest.approx(1.99)

    def test_trajectory_returns(self):
        from core.rl.returns import trajectory_returns
        traj = [{"reward": 1.0}, {"reward": 2.0}]
        annotated = trajectory_returns(traj, gamma=0.5)
        assert "return" in annotated[0]
        assert annotated[1]["return"] == pytest.approx(2.0)

    def test_empty_rewards(self):
        from core.rl.returns import discounted_returns
        assert discounted_returns([]) == []


class TestReward:
    def test_compute_reward_positive(self):
        from core.rl.reward import compute_reward
        r = compute_reward(profit=10.0, drawdown=2.0, stability=1.0)
        assert r == pytest.approx(10.0 * 0.6 - 2.0 * 0.3 + 1.0 * 0.1)

    def test_reward_from_state(self):
        from core.rl.reward import reward_from_state
        state = {"profit": 5.0, "drawdown": 1.0, "stability": 0.5}
        r = reward_from_state(state)
        assert r == pytest.approx(5.0 * 0.6 - 1.0 * 0.3 + 0.5 * 0.1)

    def test_reward_from_empty_state(self):
        from core.rl.reward import reward_from_state
        assert reward_from_state({}) == pytest.approx(0.0)


class TestSequenceLoop:
    def test_step_accumulates(self):
        from core.engine.sequence_loop import SequenceLoop
        loop = SequenceLoop(max_len=10)
        loop.step({}, "A", 1.0)
        assert loop.pending == 1

    def test_flush_empties_pending(self):
        from core.engine.sequence_loop import SequenceLoop
        loop = SequenceLoop(max_len=10)
        loop.step({}, "A", 1.0)
        loop.flush()
        assert loop.pending == 0

    def test_auto_flush_at_max_len(self):
        from core.engine.sequence_loop import SequenceLoop
        loop = SequenceLoop(max_len=3)
        for _ in range(3):
            loop.step({}, "A", 1.0)
        assert loop.pending == 0
        assert len(loop.buffer) == 1

    def test_flush_stores_in_buffer(self):
        from core.engine.sequence_loop import SequenceLoop
        loop = SequenceLoop(max_len=10)
        loop.step({"roas": 2.0}, "scale", 0.5)
        loop.flush()
        assert len(loop.buffer) == 1


class TestMeta:
    def test_embed_state_length(self):
        from core.meta.embedding_space import embed_state, _NUMERIC_KEYS
        state = {"roas": 2.0, "profit": 10.0}
        vec = embed_state(state)
        assert len(vec) == len(_NUMERIC_KEYS)

    def test_embed_state_values(self):
        from core.meta.embedding_space import embed_state
        state = {"roas": 3.0}
        vec = embed_state(state)
        assert vec[0] == pytest.approx(3.0)

    def test_cross_domain_memory_store_and_retrieve(self):
        from core.meta.cross_domain_memory import CrossDomainMemory
        mem = CrossDomainMemory()
        mem.store("tiktok", [1.0, 2.0], 0.8)
        assert len(mem) == 1
        entries = mem.get_all()
        assert entries[0]["domain"] == "tiktok"

    def test_cross_domain_memory_by_domain(self):
        from core.meta.cross_domain_memory import CrossDomainMemory
        mem = CrossDomainMemory()
        mem.store("tiktok", [1.0], 0.5)
        mem.store("meta", [2.0], 0.7)
        assert len(mem.by_domain("meta")) == 1

    def test_transfer_reward_no_similar(self):
        from core.meta.transfer import transfer_reward
        from core.meta.cross_domain_memory import CrossDomainMemory
        mem = CrossDomainMemory()
        assert transfer_reward(mem, [1.0, 0.0, 0.0]) == pytest.approx(0.0)

    def test_transfer_find_similar(self):
        from core.meta.transfer import find_similar
        from core.meta.cross_domain_memory import CrossDomainMemory
        mem = CrossDomainMemory()
        mem.store("tiktok", [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], 1.0)
        results = find_similar(mem, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], min_similarity=0.9)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Step 60 tests
# ---------------------------------------------------------------------------

class TestWorldModel:
    def test_predict_next_fallback(self):
        from core.world_model.model import WorldModel
        wm = WorldModel()
        state = {"roas": 2.0}
        predicted = wm.predict_next(state, "scale")
        assert predicted == state

    def test_train_and_predict(self):
        from core.world_model.model import WorldModel
        wm = WorldModel()
        next_s = {"roas": 3.0}
        wm.train([{"action": "scale", "next_state": next_s}])
        predicted = wm.predict_next({"roas": 2.0}, "scale")
        assert predicted == next_s

    def test_maxlen_trim(self):
        from core.world_model.model import WorldModel
        wm = WorldModel(maxlen=3)
        for i in range(5):
            wm.train([{"action": "A", "next_state": {"i": i}}])
        assert len(wm.memory) == 3


class TestPlanner:
    def test_simulate_horizon(self):
        from core.world_model.planner import simulate
        from core.world_model.model import WorldModel
        wm = WorldModel()
        wm.train([{"action": "scale", "next_state": {"roas": 3.0}}])
        traj = simulate(wm, {"roas": 2.0}, lambda s: "scale", horizon=3)
        assert len(traj) == 3

    def test_simulate_returns_tuples(self):
        from core.world_model.planner import simulate
        from core.world_model.model import WorldModel
        wm = WorldModel()
        traj = simulate(wm, {}, lambda s: "hold", horizon=2)
        for item in traj:
            assert isinstance(item, tuple)
            assert len(item) == 2


class TestMetaPolicy:
    def test_scale(self):
        from core.rl.meta_policy import MetaPolicy
        mp = MetaPolicy()
        assert mp.select({"roas": 3.0}) == "scale"

    def test_protect(self):
        from core.rl.meta_policy import MetaPolicy
        mp = MetaPolicy()
        assert mp.select({"roas": 0.8}) == "protect"

    def test_explore(self):
        from core.rl.meta_policy import MetaPolicy
        mp = MetaPolicy()
        assert mp.select({"roas": 1.5}) == "explore"

    def test_worker_policy(self):
        from core.rl.meta_policy import worker_policy
        assert worker_policy({}, "scale") == "increase_budget"
        assert worker_policy({}, "protect") == "reduce_budget"
        assert worker_policy({}, "explore") == "test_new_creative"

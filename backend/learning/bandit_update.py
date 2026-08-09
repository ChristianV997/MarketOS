import json
import os
from collections import OrderedDict, deque

import numpy as np

# Bounds mirroring sibling learning stores (CalibrationLog caps at 500,
# RegimeStrategyMemory caps at 100) — previously both the number of
# distinct action keys and each key's reward list grew forever, since
# action keys are near-unique str(dict) reprs. A long-running process
# would accumulate an ever-growing dict of ever-growing lists.
_MAX_ACTION_KEYS = int(os.getenv("BANDIT_MEMORY_MAX_KEYS", "1000"))
_MAX_REWARDS_PER_KEY = int(os.getenv("BANDIT_MEMORY_MAX_REWARDS_PER_KEY", "200"))


def _stable_key(action) -> str:
    """Canonical string key for an action, independent of dict insertion
    order — str(action) on a dict is order-sensitive, so two
    semantically-identical actions built with keys in a different order
    (e.g. {"variant": "a", "phase": "x"} vs {"phase": "x", "variant": "a"})
    would previously land in separate bandit-memory buckets instead of
    sharing one. Falls back to str() for values json.dumps can't handle.
    """
    try:
        return json.dumps(action, sort_keys=True, default=str)
    except TypeError:
        return str(action)


class BanditMemory:

    def __init__(self):
        # OrderedDict for LRU-style eviction of the oldest action key once
        # _MAX_ACTION_KEYS is exceeded.
        self.history: "OrderedDict[str, deque]" = OrderedDict()

    def _key(self, action):
        return _stable_key(action)

    def update(self, action, reward):
        k = self._key(action)
        if k not in self.history:
            if len(self.history) >= _MAX_ACTION_KEYS:
                self.history.popitem(last=False)  # evict oldest key
            self.history[k] = deque(maxlen=_MAX_REWARDS_PER_KEY)
        else:
            self.history.move_to_end(k)
        self.history[k].append(reward)

    def stats(self, action):
        k = self._key(action)
        vals = self.history.get(k, [])
        if len(vals) == 0:
            return {"mean": 0, "var": 1}
        return {
            "mean": float(np.mean(vals)),
            "var": float(np.var(vals))
        }


bandit_memory = BanditMemory()


def update_from_delayed(delayed_items):

    for item in delayed_items:
        action = item["decision"]
        outcome = item["outcome"]
        roas = outcome.get("roas", 0)

        bandit_memory.update(action, roas)



def bandit_weight(action, graph, confidence=1.0):

    stats = bandit_memory.stats(action)

    mean = stats["mean"]
    var = stats["var"]
    confidence = max(0.05, min(1.0, confidence))

    stability = 1 / (1 + var)

    causal_align = 0
    for (p, c), w in graph.edges.items():
        if p in action:
            causal_align += w

    exploration_bonus = (1.0 - confidence) * stability
    return confidence * mean + stability + causal_align + exploration_bonus

"""DEPRECATED — no production call sites. Capital/action allocation is
unified in backend.decision.capital_policy; this naive mean-reward share
is retained only for import/test compatibility and will be removed.
"""

class StrategyAllocator:

    def __init__(self):
        self.weights = {
            "conservative": 0.3,
            "aggressive": 0.4,
            "exploratory": 0.3
        }
        self.performance = {k: [] for k in self.weights}

    def update(self, strategy, reward):
        if strategy not in self.performance:
            return
        self.performance[strategy].append(reward)
        if len(self.performance[strategy]) > 50:
            self.performance[strategy] = self.performance[strategy][-50:]

        # recompute weights
        scores = {}
        total = 0
        for k, vals in self.performance.items():
            if len(vals) == 0:
                scores[k] = 1.0
            else:
                scores[k] = sum(vals)/len(vals)
            total += scores[k]

        if total > 0:
            for k in self.weights:
                self.weights[k] = scores[k]/total

    def allocate(self, strategy, total_actions, confidence=1.0, exploration_boost=0.0):
        confidence = max(0.05, min(1.0, confidence))
        base = self.weights.get(strategy, 0.3) * total_actions * confidence
        if strategy == "exploratory":
            base += exploration_boost * total_actions
        return max(1, int(base))

allocator = StrategyAllocator()

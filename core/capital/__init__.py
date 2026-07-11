"""core.capital — capital allocation engine.

This package contains the original CapitalEngine (pod-level) plus the new
softmax-based allocator introduced in Step 54.
"""
# Re-export the original CapitalEngine from the module-level contents
SCALE_ROAS_THRESHOLD = 2.5
KILL_ROAS_THRESHOLD = 1.5
SCALE_FACTOR = 1.5
MAX_BUDGET = 10_000.0


class CapitalEngine:
    """Controls money deployment across pods based on ROAS performance."""

    def __init__(
        self,
        scale_threshold: float = SCALE_ROAS_THRESHOLD,
        kill_threshold: float = KILL_ROAS_THRESHOLD,
        scale_factor: float = SCALE_FACTOR,
        max_budget: float = MAX_BUDGET,
    ):
        self.scale_threshold = scale_threshold
        self.kill_threshold = kill_threshold
        self.scale_factor = scale_factor
        self.max_budget = max_budget

    def evaluate(self, pod) -> str:
        """Return 'scale', 'kill', or 'hold' based on pod ROAS."""
        roas = pod.metrics.get("roas", 0.0)
        if roas > self.scale_threshold:
            return "scale"
        if roas < self.kill_threshold:
            return "kill"
        return "hold"

    def apply(self, pod) -> str:
        """Apply capital decision to pod — mutates budget/status in place."""
        decision = self.evaluate(pod)
        if decision == "scale":
            pod.budget = min(pod.budget * self.scale_factor, self.max_budget)
            pod.status = "scaling"
        elif decision == "kill":
            pod.status = "killed"
        return decision

    def allocate_budget(self, pods, total_budget: float) -> dict:
        """Distribute total_budget across non-killed pods, ROAS-weighted.

        Uses the softmax allocator (score = roas*0.6 + profit*0.3 - drawdown*0.1,
        clamped to 5–35% per pod) so winners get more capital; falls back to an
        even split only if the softmax path fails.
        """
        active = [p for p in pods if p.status != "killed"]
        if not active:
            return {}
        try:
            from core.capital.allocator import allocate
            strategies = [
                {
                    "roas":     p.metrics.get("roas", 0.0),
                    "profit":   p.metrics.get("revenue", 0.0) - p.metrics.get("spend", 0.0),
                    "drawdown": p.metrics.get("drawdown", 0.0),
                }
                for p in active
            ]
            amounts = allocate(strategies, total_budget)
            return {p.id: round(a, 4) for p, a in zip(active, amounts)}
        except Exception:
            per_pod = total_budget / len(active)
            return {p.id: round(per_pod, 4) for p in active}


capital_engine = CapitalEngine()

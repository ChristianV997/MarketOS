from collections import defaultdict, deque
from datetime import datetime, timedelta


def evaluate_hooks(results: list[dict]) -> dict[str, float]:
    """Return average ROAS per hook string from a list of result records.

    Each record must contain ``"hook"`` and ``"roas"`` keys.
    """
    scores: dict[str, list] = defaultdict(list)

    for r in results:
        hook = r.get("hook", "")
        roas = r.get("roas", 0.0)
        scores[hook].append(roas)

    return {h: sum(v) / len(v) for h, v in scores.items()}


class HookFatigueDetector:
    """Track rolling-window ROAS per hook to detect fatigue (declining trend).

    Phase 7: Replaces lifetime-average scoring with rolling window detection.
    Flags a hook as "fatigued" when recent ROAS trend drops ≥20% below historical.
    """

    def __init__(self, window_days: int = 30, fatigue_threshold: float = 0.20):
        """
        Args:
            window_days: Rolling window for recent vs historical (default 30d)
            fatigue_threshold: Trigger fatigue flag when trend_roas < historical_roas * (1-threshold)
        """
        self.window_days = window_days
        self.fatigue_threshold = fatigue_threshold
        # Store (timestamp, roas) tuples per hook
        self.hook_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))

    def record_roas(self, hook: str, roas: float, timestamp: datetime | None = None) -> None:
        """Record ROAS observation for a hook."""
        if timestamp is None:
            timestamp = datetime.utcnow()
        self.hook_history[hook].append((timestamp, roas))

    def get_recent_roas(self, hook: str, days: int = 7) -> float | None:
        """Average ROAS for hook in last N days."""
        if hook not in self.hook_history:
            return None
        cutoff = datetime.utcnow() - timedelta(days=days)
        recent = [r for t, r in self.hook_history[hook] if t >= cutoff]
        return sum(recent) / len(recent) if recent else None

    def get_historical_roas(self, hook: str, exclude_days: int = 7) -> float | None:
        """Average ROAS for hook, excluding last N days."""
        if hook not in self.hook_history:
            return None
        cutoff = datetime.utcnow() - timedelta(days=exclude_days)
        historical = [r for t, r in self.hook_history[hook] if t < cutoff]
        return sum(historical) / len(historical) if historical else None

    def is_fatigued(self, hook: str) -> bool:
        """Return True if recent ROAS has declined ≥fatigue_threshold vs historical."""
        recent = self.get_recent_roas(hook, days=7)
        historical = self.get_historical_roas(hook, exclude_days=7)
        if recent is None or historical is None:
            return False
        if historical == 0:
            return False
        decline_pct = (historical - recent) / historical
        return decline_pct >= self.fatigue_threshold

    def get_fatigue_metrics(self, hook: str) -> dict:
        """Return detailed fatigue analysis for a hook."""
        recent = self.get_recent_roas(hook, days=7) or 0.0
        historical = self.get_historical_roas(hook, exclude_days=7) or 0.0
        decline = max(0.0, (historical - recent) / (historical or 1.0))
        return {
            "hook": hook,
            "recent_roas_7d": round(recent, 4),
            "historical_roas": round(historical, 4),
            "decline_pct": round(decline * 100, 1),
            "is_fatigued": self.is_fatigued(hook),
            "observation_count": len(self.hook_history.get(hook, [])),
        }

    def get_fatigued_hooks(self) -> list[str]:
        """Return hooks currently flagged as fatigued."""
        return [h for h in self.hook_history.keys() if self.is_fatigued(h)]

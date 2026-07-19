from collections import defaultdict, deque
from datetime import datetime, timedelta


class SequenceOptimizer:
    """Phase 7: Track sequence ROAS with rolling-window fatigue detection.

    Replaces lifetime-average scoring with windowed comparison to detect
    sequence decay and flag for refresh.
    """

    def __init__(self, window_days: int = 30):
        self.window_days = window_days
        # Track (timestamp, roas) tuples per sequence
        self.sequence_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))

    def update(self, sequence_id: str, roas: float, timestamp: datetime | None = None) -> None:
        """Record ROAS observation for a sequence."""
        if timestamp is None:
            timestamp = datetime.utcnow()
        self.sequence_history[sequence_id].append((timestamp, roas))

    def best_sequences(self, k: int = 3) -> list[tuple[str, float]]:
        """Return top K sequences by lifetime average ROAS."""
        ranked = sorted(
            [
                (sid, sum(r for _, r in v) / len(v))
                for sid, v in self.sequence_history.items()
                if v
            ],
            key=lambda x: x[1],
            reverse=True,
        )
        return ranked[:k]

    def get_recent_roas(self, sequence_id: str, days: int = 7) -> float | None:
        """Average ROAS for sequence in last N days."""
        if sequence_id not in self.sequence_history:
            return None
        cutoff = datetime.utcnow() - timedelta(days=days)
        recent = [r for t, r in self.sequence_history[sequence_id] if t >= cutoff]
        return sum(recent) / len(recent) if recent else None

    def get_historical_roas(self, sequence_id: str, exclude_days: int = 7) -> float | None:
        """Average ROAS for sequence, excluding last N days."""
        if sequence_id not in self.sequence_history:
            return None
        cutoff = datetime.utcnow() - timedelta(days=exclude_days)
        historical = [r for t, r in self.sequence_history[sequence_id] if t < cutoff]
        return sum(historical) / len(historical) if historical else None

    def is_fatigued(self, sequence_id: str, threshold: float = 0.20) -> bool:
        """Return True if recent ROAS has declined ≥threshold vs historical."""
        recent = self.get_recent_roas(sequence_id, days=7)
        historical = self.get_historical_roas(sequence_id, exclude_days=7)
        if recent is None or historical is None:
            return False
        if historical == 0:
            return False
        decline_pct = (historical - recent) / historical
        return decline_pct >= threshold

    def get_fatigued_sequences(self, threshold: float = 0.20) -> list[str]:
        """Return sequence IDs currently flagged as fatigued."""
        return [s for s in self.sequence_history.keys() if self.is_fatigued(s, threshold=threshold)]


# Module-level singleton consumed by the live execution loop (Phase 7).
# Ad "angles" are treated as sequences: the only other content axis tracked
# alongside hooks in the live loop, and SequenceOptimizer's API is generic
# enough (arbitrary sequence_id -> ROAS) to apply to them directly.
sequence_fatigue_optimizer = SequenceOptimizer()

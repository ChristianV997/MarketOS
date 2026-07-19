"""backend.discovery.trend_history — lightweight time-series accumulator for velocity/saturation.

Tracks rolling windows of (timestamp, velocity, saturation) per product, enabling:
- Lifecycle detection (rising/peak/declining)
- Trend-based urgency scoring (velocity * (1 - saturation) * acceleration)
- Comparison of current velocity against historical baseline

This module is consumed by the unified urgency score in core/signals.py.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone


class TrendHistory:
    """Per-product rolling time-series of (timestamp, velocity, saturation)."""

    def __init__(self, max_history: int = 100):
        self.max_history = max_history
        # product_id -> deque of (ts_sec: float, velocity: float, saturation: float)
        self._history: dict[str, deque] = defaultdict(lambda: deque(maxlen=max_history))

    def record(self, product_id: str, velocity: float = 0.0, saturation: float = 0.0,
               ts: float | None = None) -> None:
        """Record one observation (velocity from trends, saturation from ad_intelligence)."""
        ts = ts or datetime.now(timezone.utc).timestamp()
        velocity = max(0.0, min(1.0, float(velocity)))  # clamp to [0, 1]
        saturation = max(0.0, min(1.0, float(saturation)))  # clamp to [0, 1]
        self._history[product_id].append((ts, velocity, saturation))

    def get_trend_stats(self, product_id: str) -> dict:
        """Compute rolling trend statistics.

        Returns:
          current_velocity: last observed velocity
          avg_velocity_recent: mean of last 7 observations
          avg_velocity_older: mean of observations before that
          saturation_trend: current - historical average
          acceleration: recent_velocity - older_velocity
          lifecycle: "rising" / "peak" / "declining" / "unknown"
        """
        hist = self._history.get(product_id, deque())
        if not hist:
            return {
                "current_velocity": 0.0,
                "avg_velocity_recent": 0.0,
                "avg_velocity_older": 0.0,
                "saturation_trend": 0.0,
                "acceleration": 0.0,
                "lifecycle": "unknown",
            }

        recent = list(hist)[-7:] if len(hist) >= 7 else list(hist)
        older = list(hist)[: max(0, len(hist) - 7)] if len(hist) > 7 else []

        recent_vels = [v for _, v, _ in recent]
        older_vels = [v for _, v, _ in older]

        current_velocity = recent_vels[-1] if recent_vels else 0.0
        avg_recent = sum(recent_vels) / len(recent_vels) if recent_vels else 0.0
        avg_older = sum(older_vels) / len(older_vels) if older_vels else avg_recent

        recent_sats = [s for _, _, s in recent]
        older_sats = [s for _, _, s in older]
        avg_recent_sat = sum(recent_sats) / len(recent_sats) if recent_sats else 0.0
        avg_older_sat = sum(older_sats) / len(older_sats) if older_sats else avg_recent_sat

        acceleration = avg_recent - avg_older

        # Lifecycle detection: based on velocity trend + saturation position
        if acceleration > 0.05:
            lifecycle = "rising"
        elif acceleration < -0.05:
            lifecycle = "declining"
        elif avg_recent > 0.5:
            lifecycle = "peak"
        else:
            lifecycle = "unknown"

        return {
            "current_velocity": round(current_velocity, 4),
            "avg_velocity_recent": round(avg_recent, 4),
            "avg_velocity_older": round(avg_older, 4),
            "saturation_trend": round(avg_recent_sat - avg_older_sat, 4),
            "acceleration": round(acceleration, 4),
            "lifecycle": lifecycle,
        }

    def clear(self, product_id: str) -> None:
        """Clear history for a product."""
        if product_id in self._history:
            self._history[product_id].clear()


# Module-level singleton
trend_history = TrendHistory()

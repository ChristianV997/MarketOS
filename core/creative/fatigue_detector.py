"""core.creative.fatigue_detector — rolling-window creative fatigue detection.

Replaces lifetime-average ROAS scoring with a window-based approach: a creative
that spiked early and decayed to zero is flagged as fatigued and recommended for
refresh, whereas a creative that's been steadily good maintains high score.

Fatigue is detected when:
  trend_roas (last 7 days) < historical_roas (days 8-30) by ≥20%

This signals creative decay and is passed to the sequence optimizer as a
refresh/rotation trigger.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone


class FatigueDetector:
    """Per-hook/angle rolling-window fatigue tracker.

    Bounded deque (max 30 rows per hook) stores (timestamp, roas) pairs.
    Rolling 7-day window (trend) is compared to historical 8–30-day window
    to detect declining ROAS (creative decay).
    """

    def __init__(self, window_days: int = 30, trend_days: int = 7, decay_threshold: float = 0.20):
        self.window_days = window_days
        self.trend_days = trend_days
        self.decay_threshold = decay_threshold  # 20% drop triggers fatigue flag

        # hook_id -> deque of (timestamp_sec: float, roas: float)
        self._hook_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=window_days))
        # angle_id -> deque of (timestamp_sec: float, roas: float)
        self._angle_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=window_days))

    def record_performance(self, hook_id: str = "", angle_id: str = "", roas: float = 0.0,
                          ts: float | None = None) -> None:
        """Record one performance observation (hook and/or angle)."""
        ts = ts or datetime.now(timezone.utc).timestamp()
        if hook_id:
            self._hook_history[hook_id].append((ts, roas))
        if angle_id:
            self._angle_history[angle_id].append((ts, roas))

    def is_fatigued(self, hook_id: str = "", angle_id: str = "") -> tuple[bool, dict]:
        """Check if hook or angle is fatigued (trend < historical by decay_threshold).

        Returns (is_fatigued: bool, details: dict) where details contains:
          - trend_roas: avg ROAS over last 7 days
          - historical_roas: avg ROAS over days 8-30
          - decay_pct: (historical - trend) / historical
          - days_of_data: count of observations
          - threshold_exceeded: whether decay_pct >= decay_threshold
        """
        history = self._hook_history.get(hook_id, deque()) if hook_id else self._angle_history.get(angle_id, deque())

        if not history or len(history) < 2:
            return False, {"days_of_data": len(history), "insufficient_data": True}

        now = datetime.now(timezone.utc).timestamp()
        trend_cutoff = now - self.trend_days * 86400
        historical_cutoff = now - self.window_days * 86400

        trend_roas_list = [roas for ts, roas in history if ts >= trend_cutoff]
        historical_roas_list = [roas for ts, roas in history if historical_cutoff <= ts < trend_cutoff]

        trend_roas = sum(trend_roas_list) / len(trend_roas_list) if trend_roas_list else 0.0
        historical_roas = sum(historical_roas_list) / len(historical_roas_list) if historical_roas_list else 0.0

        # Avoid division by zero
        if historical_roas == 0:
            decay_pct = 0.0
        else:
            decay_pct = max(0.0, (historical_roas - trend_roas) / historical_roas)

        # Round before the threshold comparison, not just for display — an
        # exact-percent decay (e.g. 2.0 -> 1.6, precisely 20%) can compute as
        # 0.19999999999999996 in IEEE-754 float64 (1.6 has no exact binary
        # representation), which silently fails a bare `>=` against 0.20.
        is_fatigued = round(decay_pct, 4) >= self.decay_threshold

        details = {
            "trend_roas": round(trend_roas, 4),
            "historical_roas": round(historical_roas, 4),
            "decay_pct": round(decay_pct, 4),
            "days_of_data": len(history),
            "threshold_exceeded": is_fatigued,
        }

        # Shadow-mode logging for validation (Phase 7a)
        try:
            from backend.orchestration.event_store import event_store, new_workflow_id
            event_store.append(
                new_workflow_id("fatigue"), "shadow_creative_fatigue",
                workflow="creative_fatigue", step="is_fatigued",
                data={
                    "hook_id": hook_id,
                    "angle_id": angle_id,
                    "is_fatigued": is_fatigued,
                    **details
                })
        except Exception:
            pass  # journaling must never break fatigue detection

        return is_fatigued, details

    def refresh_recommendation(self, hook_id: str = "", angle_id: str = "") -> tuple[bool, str]:
        """High-level recommendation: refresh this creative or not.

        Returns (should_refresh: bool, reason: str).
        """
        is_fatigued, details = self.is_fatigued(hook_id, angle_id)
        if not is_fatigued:
            return False, "performing_well"

        if details.get("insufficient_data"):
            return False, "insufficient_data"

        decay = details["decay_pct"]
        if decay >= 0.40:
            return True, f"severe_decay_{decay:.0%}"
        elif decay >= 0.20:
            return True, f"moderate_decay_{decay:.0%}"
        else:
            return False, "within_tolerance"


# Module-level singleton
fatigue_detector = FatigueDetector()

"""backend.orchestration.rate_mesh — cross-platform rate coordination.

The per-service sliding-window limiter (backend.integrations.rate_limiter)
keeps each platform inside its own quota, but knows nothing about system
load: when Meta returns 429s, every cycle still retries Meta at full rate
and hammers TikTok at full rate too. The mesh adds the cross-platform
layer:

  - throttle(platform) — record a platform-side throttle; starts an
    exponential per-platform penalty window (doubles per repeat, capped)
    and applies a one-shot *global* soft-brake so sibling platforms shed
    load for a short window instead of piling on.
  - acquire(platform)  — combines circuit-breaker health, penalty windows,
    the global brake, and the underlying sliding-window limiter into one
    yes/no the adapters consult before every outbound call.

Backoff state decays automatically: a clean acquire after the penalty
window resets the multiplier.
"""
from __future__ import annotations

import logging
import threading
import time

from backend.integrations.rate_limiter import rate_limiter as _window_limiter
from backend.orchestration.state_machine import health_registry

_log = logging.getLogger(__name__)


class RateMesh:
    def __init__(self, *, base_penalty_s: float = 5.0,
                 max_penalty_s: float = 300.0,
                 global_brake_s: float = 2.0):
        self.base_penalty_s = base_penalty_s
        self.max_penalty_s = max_penalty_s
        self.global_brake_s = global_brake_s
        self._penalty_until: dict[str, float] = {}
        self._penalty_mult: dict[str, int] = {}
        self._global_brake_until = 0.0
        self._lock = threading.Lock()

    # ── signals ──────────────────────────────────────────────────────────

    def throttle(self, platform: str) -> None:
        """A platform told us to slow down (429/quota error)."""
        with self._lock:
            mult = self._penalty_mult.get(platform, 0) + 1
            self._penalty_mult[platform] = mult
            penalty = min(self.base_penalty_s * (2 ** (mult - 1)),
                          self.max_penalty_s)
            self._penalty_until[platform] = time.time() + penalty
            # Soft global brake: siblings shed load briefly instead of
            # inheriting the freed-up capacity and tripping their own limits.
            self._global_brake_until = max(
                self._global_brake_until, time.time() + self.global_brake_s)
        _log.warning("mesh_throttle platform=%s penalty_s=%.1f", platform, penalty)
        health_registry.get(platform).record_failure(_RateLimitSignal())

    def success(self, platform: str) -> None:
        """Clean call — decay any penalty state for the platform."""
        with self._lock:
            if platform in self._penalty_until and \
                    time.time() >= self._penalty_until[platform]:
                self._penalty_until.pop(platform, None)
                self._penalty_mult.pop(platform, None)

    # ── gate ─────────────────────────────────────────────────────────────

    def acquire(self, platform: str, *, timeout: float = 10.0) -> bool:
        """May we call this platform now? Consults, in order:
        circuit breaker → penalty window → global brake → sliding window."""
        if not health_registry.get(platform).allow_request():
            return False
        now = time.time()
        with self._lock:
            until = self._penalty_until.get(platform, 0.0)
            brake = self._global_brake_until
        if now < until:
            return False
        if now < brake:
            time.sleep(min(brake - now, self.global_brake_s))
        return _window_limiter.acquire(platform, timeout=timeout)

    def status(self) -> dict:
        now = time.time()
        with self._lock:
            penalties = {p: round(t - now, 1)
                         for p, t in self._penalty_until.items() if t > now}
            brake = max(0.0, self._global_brake_until - now)
        return {
            "penalties_s": penalties,
            "global_brake_s": round(brake, 2),
            "windows": _window_limiter.status(),
            "health": health_registry.status(),
        }

    def reset(self) -> None:
        """Test helper."""
        with self._lock:
            self._penalty_until.clear()
            self._penalty_mult.clear()
            self._global_brake_until = 0.0


class _RateLimitSignal(Exception):
    """Marker exception so PlatformHealth classifies this as a 429."""
    status = 429

    def __init__(self) -> None:
        super().__init__("rate limited (mesh signal)")


rate_mesh = RateMesh()

__all__ = ["RateMesh", "rate_mesh"]

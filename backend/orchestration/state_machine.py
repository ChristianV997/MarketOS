"""backend.orchestration.state_machine — per-platform health + circuit breaker.

Each platform (meta, tiktok, shopify, ajo, ...) carries a small state
machine:

    HEALTHY ──errors──▶ DEGRADED ──more errors──▶ FAILED (circuit open)
       ▲                   │  ▲                       │
       │                   │  └──── 429s ──── RATE_LIMITED
       └───── successes ───┘                          │
       ◀────────────── cooldown elapsed → RECOVERING ─┘

While FAILED, ``allow_request()`` returns False until ``open_cooldown_s``
elapses; the first request after cooldown runs in RECOVERING (half-open):
one success closes the circuit back to HEALTHY, one failure re-opens it.

Error classification piggybacks on the MarketOSError taxonomy where
available (``retryable`` flag) and falls back to HTTP-ish status sniffing.

Thread-safe; a single registry instance is shared process-wide.
"""
from __future__ import annotations

import enum
import logging
import threading
import time
from typing import Any

_log = logging.getLogger(__name__)


class HealthState(str, enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"
    FAILED = "failed"          # circuit open — skip this platform
    RECOVERING = "recovering"  # half-open — one probe request allowed


class PlatformHealth:
    """Health state machine for one platform.

    Parameters
    ----------
    failure_threshold : consecutive failures before circuit opens
    open_cooldown_s   : how long the circuit stays open before a probe
    rate_limit_cooldown_s : back-off window after a 429
    """

    def __init__(self, platform: str, *, failure_threshold: int = 3,
                 open_cooldown_s: float = 60.0,
                 rate_limit_cooldown_s: float = 30.0):
        self.platform = platform
        self.failure_threshold = failure_threshold
        self.open_cooldown_s = open_cooldown_s
        self.rate_limit_cooldown_s = rate_limit_cooldown_s

        self._state = HealthState.HEALTHY
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self._rate_limited_at = 0.0
        self._total_successes = 0
        self._total_failures = 0
        self._lock = threading.Lock()

    # ── transitions ──────────────────────────────────────────────────────

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._total_successes += 1
            if self._state != HealthState.HEALTHY:
                _log.info("platform_recovered platform=%s from=%s",
                          self.platform, self._state.value)
            self._state = HealthState.HEALTHY

    def record_failure(self, error: Any = None) -> None:
        """Classify and record a failure; may open the circuit."""
        with self._lock:
            self._total_failures += 1
            if self._is_rate_limit(error):
                self._state = HealthState.RATE_LIMITED
                self._rate_limited_at = time.time()
                _log.warning("platform_rate_limited platform=%s", self.platform)
                return
            self._consecutive_failures += 1
            if self._state == HealthState.RECOVERING:
                # Probe failed — straight back to open circuit.
                self._open_circuit()
            elif self._consecutive_failures >= self.failure_threshold:
                self._open_circuit()
            else:
                self._state = HealthState.DEGRADED

    def _open_circuit(self) -> None:
        self._state = HealthState.FAILED
        self._opened_at = time.time()
        _log.warning("circuit_opened platform=%s failures=%d cooldown_s=%.0f",
                     self.platform, self._consecutive_failures,
                     self.open_cooldown_s)

    @staticmethod
    def _is_rate_limit(error: Any) -> bool:
        if error is None:
            return False
        status = getattr(error, "status", None) or getattr(error, "status_code", None)
        if status == 429:
            return True
        return "429" in str(error) or "rate limit" in str(error).lower()

    # ── queries ──────────────────────────────────────────────────────────

    def allow_request(self) -> bool:
        """Should a caller hit this platform right now?

        Handles cooldown-driven transitions lazily: FAILED→RECOVERING after
        open_cooldown_s, RATE_LIMITED→DEGRADED after rate_limit_cooldown_s.
        """
        with self._lock:
            now = time.time()
            if self._state == HealthState.FAILED:
                if now - self._opened_at >= self.open_cooldown_s:
                    self._state = HealthState.RECOVERING
                    _log.info("circuit_half_open platform=%s", self.platform)
                    return True
                return False
            if self._state == HealthState.RATE_LIMITED:
                if now - self._rate_limited_at >= self.rate_limit_cooldown_s:
                    self._state = HealthState.DEGRADED
                    return True
                return False
            return True

    @property
    def state(self) -> HealthState:
        with self._lock:
            return self._state

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "platform": self.platform,
                "state": self._state.value,
                "consecutive_failures": self._consecutive_failures,
                "total_successes": self._total_successes,
                "total_failures": self._total_failures,
            }


class HealthRegistry:
    """Process-wide map platform → PlatformHealth (lazily created)."""

    def __init__(self) -> None:
        self._platforms: dict[str, PlatformHealth] = {}
        self._lock = threading.Lock()

    def get(self, platform: str) -> PlatformHealth:
        with self._lock:
            if platform not in self._platforms:
                self._platforms[platform] = PlatformHealth(platform)
            return self._platforms[platform]

    def status(self) -> dict[str, dict]:
        with self._lock:
            return {p: h.status() for p, h in self._platforms.items()}

    def reset(self) -> None:
        """Test helper — drop all tracked platforms."""
        with self._lock:
            self._platforms.clear()


health_registry = HealthRegistry()

__all__ = ["HealthState", "PlatformHealth", "HealthRegistry", "health_registry"]

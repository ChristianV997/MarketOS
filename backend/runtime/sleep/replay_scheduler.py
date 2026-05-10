"""ReplayScheduler — orchestrates periodic cognitive sleep cycles.

Runs as a background daemon thread.  Wakes at configurable intervals to
trigger a ConsolidationEngine cycle.  Designed for consumer hardware:
one cycle at a time, no parallelism, configurable idle periods.

Env vars:
  SLEEP_CYCLE_INTERVAL_S  — seconds between cycles (default: 3600 = 1 hour)
  SLEEP_WINDOW_HOURS      — replay window per cycle (default: 24.0)
  SLEEP_WORKSPACE         — workspace to consolidate (default: default)
  SLEEP_ENABLED           — set "0" to disable (default: enabled)
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

_INTERVAL_S    = float(os.getenv("SLEEP_CYCLE_INTERVAL_S", "3600"))
_WINDOW_HOURS  = float(os.getenv("SLEEP_WINDOW_HOURS",     "24.0"))
_WORKSPACE     = os.getenv("SLEEP_WORKSPACE",               "default")
_ENABLED       = os.getenv("SLEEP_ENABLED", "1") != "0"


class ReplayScheduler:
    """Background scheduler for cognitive sleep cycles.

    Usage::

        scheduler = ReplayScheduler()
        scheduler.start()
        # ... runtime runs ...
        scheduler.stop()

    Or call ``run_now()`` to trigger an immediate cycle synchronously.
    """

    def __init__(
        self,
        interval_s:   float = _INTERVAL_S,
        window_hours: float = _WINDOW_HOURS,
        workspace:    str   = _WORKSPACE,
        enabled:      bool  = _ENABLED,
    ) -> None:
        self.interval_s   = interval_s
        self.window_hours = window_hours
        self.workspace    = workspace
        self.enabled      = enabled

        self._thread:        threading.Thread | None = None
        self._stop_event:    threading.Event         = threading.Event()
        self._lock:          threading.Lock          = threading.Lock()
        self._cycle_count:   int                     = 0
        self._last_cycle_ts: float                   = 0.0
        self._last_result:   Any                     = None

    # ── public control ────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self.enabled:
            log.info("ReplayScheduler: disabled (SLEEP_ENABLED=0)")
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="cognitive-sleep-scheduler",
                daemon=True,
            )
            self._thread.start()
            log.info(
                "ReplayScheduler: started (interval=%.0fs window=%.1fh workspace=%s)",
                self.interval_s, self.window_hours, self.workspace,
            )

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            if self._thread:
                self._thread.join(timeout=5.0)
                self._thread = None
        log.info("ReplayScheduler: stopped after %d cycles", self._cycle_count)

    def run_now(self) -> Any:
        """Trigger an immediate consolidation cycle synchronously."""
        return self._run_cycle()

    def status(self) -> dict[str, Any]:
        return {
            "enabled":       self.enabled,
            "running":       self.is_running(),
            "cycle_count":   self._cycle_count,
            "last_cycle_ts": self._last_cycle_ts,
            "interval_s":    self.interval_s,
            "workspace":     self.workspace,
        }

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def cycles_completed(self) -> int:
        return self._cycle_count

    @property
    def last_cycle_at(self) -> float:
        return self._last_cycle_ts

    # ── internals ─────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self._run_cycle()
            # Wait interval, but wake immediately if stop requested
            self._stop_event.wait(timeout=self.interval_s)

    def _run_cycle(self) -> Any:
        from .consolidation_engine import ConsolidationEngine
        engine = ConsolidationEngine(
            workspace=self.workspace,
            window_hours=self.window_hours,
        )
        try:
            result = engine.run_cycle()
            self._cycle_count  += 1
            self._last_cycle_ts = time.time()
            self._last_result   = result
            try:
                from backend.runtime.task_inventory import task_registry

                task_registry.heartbeat("sleep_scheduler", status="ok")
            except Exception:
                pass
            _emit_scheduler_tick(self._cycle_count, result)
            return result
        except Exception as exc:
            log.error("ReplayScheduler: cycle failed: %s", exc)
            try:
                from backend.runtime.task_inventory import task_registry

                task_registry.heartbeat("sleep_scheduler", status="error")
            except Exception:
                pass
            return None


def _emit_scheduler_tick(cycle_count: int, result: Any) -> None:
    try:
        from backend.events.log import append
        append(
            "sleep.scheduler.tick",
            payload={
                "cycle_count":     cycle_count,
                "compression_ratio": getattr(result, "compression_ratio", 0.0),
                "ok":              getattr(result, "ok", False),
                "duration_s":      getattr(result, "duration_s", 0.0),
            },
            source="replay_scheduler",
        )
    except Exception:
        pass


# ── module-level singleton ────────────────────────────────────────────────────

_scheduler: ReplayScheduler | None = None
_sched_lock = threading.Lock()


def get_scheduler() -> ReplayScheduler:
    global _scheduler
    if _scheduler is None:
        with _sched_lock:
            if _scheduler is None:
                _scheduler = ReplayScheduler()
    return _scheduler

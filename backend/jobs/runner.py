import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)


class JobMetrics:
    def __init__(self):
        self.counters = {
            "jobs_runs_total": 0,
            "jobs_failures_total": 0,
        }
        self.timings_ms: list[float] = []

    def record(self, status: str, duration_ms: float):
        self.counters["jobs_runs_total"] += 1
        if status == "failed":
            self.counters["jobs_failures_total"] += 1
        self.timings_ms.append(duration_ms)

    @property
    def snapshot(self) -> dict[str, Any]:
        return {
            **self.counters,
            "jobs_duration_ms": list(self.timings_ms),
        }


def is_retryable_error(error: Exception) -> bool:
    if hasattr(error, "retryable"):
        return bool(getattr(error, "retryable"))
    message = str(error).lower()
    if any(marker in message for marker in ("validation", "auth", "unauthorized", "forbidden", "invalid")):
        return False
    if isinstance(error, (TimeoutError, ConnectionError, OSError)):
        return True
    return any(marker in message for marker in ("timeout", "network", "temporar", "connection reset"))


class JobRegistry:
    def __init__(self, max_retries: int | None = None, metrics: JobMetrics | None = None):
        retries = int(os.getenv("JOB_MAX_RETRIES", "3")) if max_retries is None else max_retries
        self.max_retries = max(retries, 0)
        self.metrics = metrics or JobMetrics()
        self._handlers: dict[str, Callable[[], Any]] = {}
        self._window_runs: set[str] = set()

    def register(self, name: str, handler: Callable[[], Any]) -> None:
        self._handlers[name] = handler

    def _window(self, now: datetime, window: str) -> str:
        if window == "hour":
            return now.strftime("%Y%m%d%H")
        if window == "day":
            return now.strftime("%Y%m%d")
        return now.strftime("%Y%m%d%H%M")

    def _idempotency_key(self, job_name: str, now: datetime, window: str) -> str:
        date = now.strftime("%Y-%m-%d")
        return f"{job_name}:{date}:{self._window(now, window)}"

    def run(self, name: str, now: datetime | None = None, window: str = "hour") -> dict[str, Any]:
        if name not in self._handlers:
            raise KeyError(f"Unknown job: {name}")

        now = now or datetime.now(timezone.utc)
        started = datetime.now(timezone.utc)
        started_at = started.isoformat()
        key = self._idempotency_key(name, now, window)

        if key in self._window_runs:
            ended = datetime.now(timezone.utc)
            result = {
                "job": name,
                "status": "succeeded",
                "startedAt": started_at,
                "endedAt": ended.isoformat(),
                "durationMs": round((ended - started).total_seconds() * 1000, 2),
                "retryCount": 0,
                "idempotencyKey": key,
                "skipped": True,
            }
            self.metrics.record(result["status"], result["durationMs"])
            logger.info(result)
            return result

        retry_count = 0
        error_message = None
        status = "succeeded"
        payload: Any = None

        for attempt in range(self.max_retries + 1):
            try:
                payload = self._handlers[name]()
                break
            except Exception as err:  # pragma: no cover - covered by tests through behavior
                retry_count = attempt
                if attempt >= self.max_retries or not is_retryable_error(err):
                    status = "failed"
                    error_message = str(err)
                    break
                time.sleep(2 ** attempt)

        ended = datetime.now(timezone.utc)
        duration_ms = round((ended - started).total_seconds() * 1000, 2)

        result = {
            "job": name,
            "status": status,
            "startedAt": started_at,
            "endedAt": ended.isoformat(),
            "durationMs": duration_ms,
            "retryCount": retry_count,
            "idempotencyKey": key,
        }
        if error_message:
            result["error"] = error_message
        else:
            self._window_runs.add(key)
            if payload is not None:
                result["payload"] = payload

        self.metrics.record(status, duration_ms)
        logger.info(result)
        return result

    def run_all(self, now: datetime | None = None, window: str = "hour") -> list[dict[str, Any]]:
        return [self.run(name, now=now, window=window) for name in self._handlers]

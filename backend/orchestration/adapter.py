"""backend.orchestration.adapter — workflow-aware wrapper over integration clients.

PlatformAdapter adds three behaviors to any existing client module
(meta_ads_client, tiktok_ads, ...) without modifying it:

  1. gate every call through the RateMesh (circuit breaker + penalties +
     sliding window),
  2. feed success/failure back into the platform's health state machine
     (429s also notify the mesh so siblings back off),
  3. journal the call to the event store when a workflow_id is provided.

Usage:
    meta = PlatformAdapter("meta", meta_ads_client)
    cid = meta.call("create_campaign", name=..., daily_budget=...)

``call`` raises RetryableError when the mesh refuses (circuit open /
penalty window) so callers can distinguish "platform unavailable" from
"platform said no".
"""
from __future__ import annotations

import logging
from typing import Any

from backend.orchestration.event_store import event_store
from backend.orchestration.rate_mesh import rate_mesh
from backend.orchestration.state_machine import health_registry
from backend.patterns.errors import RetryableError

_log = logging.getLogger(__name__)


class PlatformAdapter:
    def __init__(self, platform: str, client: Any):
        self.platform = platform
        self.client = client
        self.health = health_registry.get(platform)

    def call(self, method: str, *args: Any, workflow_id: str | None = None,
             **kwargs: Any) -> Any:
        if not rate_mesh.acquire(self.platform):
            raise RetryableError(
                f"{self.platform} unavailable "
                f"(health={self.health.state.value})",
                service=self.platform)

        fn = getattr(self.client, method)
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            if _looks_throttled(exc):
                rate_mesh.throttle(self.platform)
            else:
                self.health.record_failure(exc)
            if workflow_id:
                event_store.append(workflow_id, "step_failed",
                                   step=f"{self.platform}.{method}",
                                   data={"error": str(exc)})
            raise

        self.health.record_success()
        rate_mesh.success(self.platform)
        if workflow_id:
            event_store.append(workflow_id, "step_completed",
                               step=f"{self.platform}.{method}",
                               data={"output": _summ(result)})
        return result

    def available(self) -> bool:
        return self.health.allow_request()


def _looks_throttled(exc: Exception) -> bool:
    status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    if status == 429:
        return True
    text = str(exc).lower()
    return "429" in text or "rate limit" in text or "too many requests" in text


def _summ(result: Any) -> Any:
    if isinstance(result, (str, int, float, bool, type(None))):
        return result
    if isinstance(result, dict):
        return {k: _summ(v) for k, v in list(result.items())[:20]}
    if isinstance(result, (list, tuple)):
        return [_summ(v) for v in list(result)[:20]]
    return str(result)


__all__ = ["PlatformAdapter"]

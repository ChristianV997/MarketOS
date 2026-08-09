"""PostHog AnalyticsProvider adapter — server-side event capture and query.

Implements the new backend.contracts.adapters.AnalyticsProvider Protocol.
Distinct from the existing frontend-only posthog-js client
(frontend/src/lib/posthog.ts, docs/oss/INVENTORY.yml's `posthog` entry) —
that client talks to PostHog Cloud directly from the browser and is
unaffected by this module. This adapter uses the optional `posthog` Python
SDK for capture and PostHog's HogQL query API (via httpx) for read
operations, both against PostHog Cloud. Dry-run by default.
"""
from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

from backend.contracts.adapters import AdapterHealth, AnalyticsProvider, SidecarContext

try:
    import posthog as _posthog_sdk
except ImportError:  # pragma: no cover
    _posthog_sdk = None

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


class PostHogAnalyticsAdapter:
    name = "posthog_backend"

    def __init__(self, project_api_key: str | None = None, *, personal_api_key: str | None = None,
                 host: str | None = None, timeout_s: float = 10.0, client: Any = None):
        self.project_api_key = project_api_key or os.getenv("POSTHOG_PROJECT_API_KEY", "")
        self.personal_api_key = personal_api_key or os.getenv("POSTHOG_PERSONAL_API_KEY", "")
        self.host = (host or os.getenv("POSTHOG_HOST", "https://us.i.posthog.com")).rstrip("/")
        self.timeout_s = timeout_s
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.project_api_key)

    def health(self) -> AdapterHealth:
        if not self.configured:
            return AdapterHealth(self.name, configured=False, reachable=False,
                                  detail="POSTHOG_PROJECT_API_KEY is unset")
        capabilities = ("event_capture",)
        reachable = _posthog_sdk is not None
        if self.personal_api_key and httpx is not None:
            capabilities = capabilities + ("query_events", "query_funnel")
        return AdapterHealth(
            self.name, configured=True, reachable=reachable, capabilities=capabilities,
            detail="" if reachable else "posthog Python SDK is not installed",
        )

    def capture_event(self, event: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        distinct_id = str(event.get("distinct_id", context.workspace_id))
        event_name = str(event.get("event", "service_run"))
        properties = dict(event.get("properties", {}))
        if context.dry_run:
            return {"dry_run": True, "distinct_id": distinct_id, "event": event_name, "properties": properties}
        if not (self.configured and _posthog_sdk is not None):
            return {"source": "unconfigured", "distinct_id": distinct_id, "event": event_name}
        _posthog_sdk.project_api_key = self.project_api_key
        _posthog_sdk.host = self.host
        _posthog_sdk.capture(distinct_id, event_name, properties)
        return {"dry_run": False, "distinct_id": distinct_id, "event": event_name, "accepted": True}

    def _query(self, hogql: str) -> Mapping[str, Any]:
        if not (self.personal_api_key and (httpx is not None or self._client is not None)):
            return {"source": "unconfigured", "query": hogql}
        client = self._client or httpx.Client(base_url=self.host, timeout=self.timeout_s)
        response = client.post(
            "/api/projects/@current/query/",
            headers={"Authorization": f"Bearer {self.personal_api_key}"},
            json={"query": {"kind": "HogQLQuery", "query": hogql}},
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"data": payload}

    def query_funnel(self, funnel: Mapping[str, Any]) -> Mapping[str, Any]:
        steps = funnel.get("steps", [])
        return self._query(f"-- funnel query, steps={steps}\nSELECT event, count() FROM events GROUP BY event")

    def query_events(self, *, event_name: str, limit: int = 50, since: str | None = None) -> Sequence[Mapping[str, Any]]:
        result = self._query(f"SELECT * FROM events WHERE event = '{event_name}' LIMIT {max(1, min(limit, 500))}")
        if result.get("source") == "unconfigured":
            return [result]
        rows = result.get("results", [])
        return rows if isinstance(rows, list) else []


analytics_provider_posthog: AnalyticsProvider = PostHogAnalyticsAdapter()

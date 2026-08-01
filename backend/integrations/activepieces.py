"""Activepieces CustomerAutomationProvider adapter.

Implements the new backend.contracts.adapters.CustomerAutomationProvider
Protocol — a customer-facing/product no-code workflow runtime, distinct
from backend.integrations.n8n's internal-only WorkflowAutomationProvider.
Dry-run by default.
"""
from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

from backend.contracts.adapters import AdapterHealth, CustomerAutomationProvider, SidecarContext

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


class ActivepiecesAutomationAdapter:
    name = "activepieces"

    def __init__(self, base_url: str | None = None, *, api_key: str | None = None,
                 timeout_s: float = 10.0, client: Any = None):
        self.base_url = (base_url or os.getenv("ACTIVEPIECES_BASE_URL", "")).rstrip("/")
        self.api_key = api_key or os.getenv("ACTIVEPIECES_API_KEY", "")
        self.timeout_s = timeout_s
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Activepieces is not configured; set ACTIVEPIECES_BASE_URL/API_KEY")
        if httpx is None and self._client is None:
            raise RuntimeError("httpx is required for the Activepieces adapter")
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["Authorization"] = f"Bearer {self.api_key}"
        client = self._client or httpx.Client(base_url=f"{self.base_url}/api/v1", timeout=self.timeout_s)
        response = client.request(method, path, headers=headers, **kwargs)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"data": payload}

    def health(self) -> AdapterHealth:
        if not self.configured:
            return AdapterHealth(self.name, configured=False, reachable=False,
                                  detail="ACTIVEPIECES_BASE_URL/API_KEY is unset")
        try:
            self._request("GET", "/flows", params={"limit": 1})
            return AdapterHealth(self.name, configured=True, reachable=True,
                                  capabilities=("workflow_automation", "connectors"))
        except Exception as exc:
            return AdapterHealth(self.name, configured=True, reachable=False, detail=str(exc))

    @staticmethod
    def _require_approved_mutation(context: SidecarContext, operation: str) -> None:
        if context.approval_state != "approved":
            raise PermissionError(f"Activepieces {operation} requires approved MarketOS context")
        context.require_live_idempotency()

    def trigger_workflow(self, workflow_id: str, payload: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        if context.dry_run:
            return {"id": f"dry-activepieces-run-{context.idempotency_key or workflow_id}", "dry_run": True,
                    "workflow_id": workflow_id, "payload": dict(payload)}
        self._require_approved_mutation(context, "workflow trigger")
        return self._request("POST", f"/webhooks/{workflow_id}", json=dict(payload))

    def get_workflow_status(self, run_id: str) -> Mapping[str, Any]:
        return self._request("GET", f"/flow-runs/{run_id}")

    def list_available_workflows(self) -> Sequence[Mapping[str, Any]]:
        payload = self._request("GET", "/flows")
        return payload.get("data", []) if isinstance(payload.get("data"), list) else []


customer_automation_provider_activepieces: CustomerAutomationProvider = ActivepiecesAutomationAdapter()

"""Narrow API boundary for internal-only n8n operational automations.

MarketOS owns commerce decisions; n8n is limited to notifications, CRM sync,
approval reminders, and exports. No n8n source is vendored or exposed as a
customer workflow engine.
"""
from __future__ import annotations

import os
import time
from typing import Any, Mapping

from backend.contracts.adapters import AdapterHealth, SidecarContext, WorkflowAutomationProvider

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


class N8nAutomationAdapter:
    name = "n8n"

    def __init__(self, base_url: str | None = None, *, token: str | None = None, client: Any = None):
        self.base_url = (base_url or os.getenv("N8N_BASE_URL", "")).rstrip("/")
        self.token = token or os.getenv("N8N_API_KEY", "")
        self.allowed_workflows = frozenset(filter(None, os.getenv("N8N_ALLOWED_WORKFLOWS", "alerts,crm_sync,approval_reminder,export").split(",")))
        self.path_template = os.getenv("N8N_WEBHOOK_PATH", "/webhook/{workflow}")
        self.max_retries = max(0, int(os.getenv("N8N_MAX_RETRIES", "2")))
        self.backoff_s = max(0.0, float(os.getenv("N8N_RETRY_BACKOFF_S", "0.25")))
        self._client = client

    def health(self) -> AdapterHealth:
        if not self.base_url:
            return AdapterHealth(self.name, configured=False, reachable=False, detail="N8N_BASE_URL is unset")
        return AdapterHealth(self.name, configured=True, reachable=True, capabilities=("internal_workflows", "notifications", "crm_sync"))

    def trigger(self, workflow: str, payload: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        workflow = str(workflow).strip()
        if workflow not in self.allowed_workflows:
            raise PermissionError(f"n8n workflow is not allowlisted: {workflow}")
        if context.dry_run:
            return {"id": f"dry-n8n-{context.idempotency_key or workflow}", "workflow": workflow, "status": "planned", "dry_run": True}
        if context.approval_state not in {"approved", "not_required"}:
            raise PermissionError("n8n automation requires approved MarketOS context")
        context.require_live_idempotency()
        if not self.base_url:
            raise RuntimeError("n8n is not configured")
        if httpx is None and self._client is None:
            raise RuntimeError("httpx is required for the n8n adapter")
        headers = context.to_headers()
        if self.token:
            headers["X-N8N-API-KEY"] = self.token
        client = self._client or httpx.Client(timeout=15.0)
        url = f"{self.base_url}{self.path_template.format(workflow=workflow)}"
        body = {"workflow": workflow, "payload": dict(payload), "context": context.__dict__}
        for attempt in range(self.max_retries + 1):
            try:
                response = client.post(url, json=body, headers=headers)
                status = int(getattr(response, "status_code", 200) or 200)
                if status >= 500 and attempt < self.max_retries:
                    time.sleep(self.backoff_s * (2 ** attempt))
                    continue
                response.raise_for_status()
                result = response.json()
                return result if isinstance(result, dict) else {"result": result, "workflow": workflow}
            except Exception:
                status = int(getattr(locals().get("response"), "status_code", 0) or 0)
                if status not in {0} and status < 500 or attempt >= self.max_retries:
                    raise
                time.sleep(self.backoff_s * (2 ** attempt))
        raise RuntimeError("n8n workflow exhausted retries")


automation_provider: WorkflowAutomationProvider = N8nAutomationAdapter()

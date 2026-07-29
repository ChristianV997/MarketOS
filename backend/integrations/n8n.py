"""Narrow API boundary for internal-only n8n operational automations.

MarketOS owns commerce decisions; n8n is limited to notifications, CRM sync,
approval reminders, and exports. No n8n source is vendored or exposed as a
customer workflow engine.
"""
from __future__ import annotations

import os
import time
from typing import Any, Mapping
from urllib.parse import urlparse

from backend.contracts.adapters import AdapterHealth, SidecarContext, WorkflowAutomationProvider

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


class N8nAutomationAdapter:
    name = "n8n"

    def __init__(self, base_url: str | None = None, *, token: str | None = None, client: Any = None):
        self.base_url = (base_url or os.getenv("N8N_BASE_URL", "")).rstrip("/")
        # Webhook routes are not authenticated by n8n's instance API key.
        # The receiving n8n workflow must validate this dedicated shared token
        # (for example with Header Auth) before doing any operational work.
        self.webhook_token = token or os.getenv("N8N_WEBHOOK_TOKEN", "")
        self.api_key = os.getenv("N8N_API_KEY", "")
        self.allowed_workflows = frozenset(filter(None, os.getenv("N8N_ALLOWED_WORKFLOWS", "alerts,crm_sync,approval_reminder,export").split(",")))
        self.allowed_hosts = frozenset(
            host.strip().lower().lstrip(".")
            for host in os.getenv("N8N_ALLOWED_HOSTS", "").split(",")
            if host.strip()
        )
        self.path_template = os.getenv("N8N_WEBHOOK_PATH", "/webhook/{workflow}")
        self.health_path = os.getenv("N8N_HEALTH_PATH", "/healthz")
        self.max_retries = max(0, int(os.getenv("N8N_MAX_RETRIES", "2")))
        self.backoff_s = max(0.0, float(os.getenv("N8N_RETRY_BACKOFF_S", "0.25")))
        self._client = client

    def _base_host_is_allowed(self) -> bool:
        hostname = (urlparse(self.base_url).hostname or "").lower()
        return bool(hostname and self.allowed_hosts and any(hostname == host or hostname.endswith("." + host) for host in self.allowed_hosts))

    def _live_configuration_error(self) -> str:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            return "N8N_BASE_URL must be an http(s) URL without embedded credentials"
        if not self._base_host_is_allowed():
            return "N8N_BASE_URL host is not allowlisted by N8N_ALLOWED_HOSTS"
        if not self.webhook_token:
            return "N8N_WEBHOOK_TOKEN is required for live internal webhook triggers"
        return ""

    def health(self) -> AdapterHealth:
        if not self.base_url:
            return AdapterHealth(self.name, configured=False, reachable=False, detail="N8N_BASE_URL is unset")
        error = self._live_configuration_error()
        if error:
            return AdapterHealth(self.name, configured=False, reachable=False, detail=error)
        if httpx is None and self._client is None:
            return AdapterHealth(self.name, configured=True, reachable=False, detail="httpx is required for n8n health probes")
        client = self._client or httpx.Client(timeout=2.0)
        owns_client = self._client is None
        try:
            response = client.get(f"{self.base_url}{self.health_path}")
            reachable = bool(getattr(response, "is_success", int(getattr(response, "status_code", 500)) < 400))
            return AdapterHealth(
                self.name,
                configured=True,
                reachable=reachable,
                capabilities=("internal_workflows", "notifications", "crm_sync") if reachable else (),
                detail="n8n internal health endpoint ready" if reachable else f"n8n health endpoint returned {getattr(response, 'status_code', 'unknown')}",
            )
        except Exception as exc:
            return AdapterHealth(self.name, configured=True, reachable=False, detail=f"n8n health probe failed: {exc}")
        finally:
            if owns_client:
                client.close()

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
        error = self._live_configuration_error()
        if error:
            raise PermissionError(error)
        if httpx is None and self._client is None:
            raise RuntimeError("httpx is required for the n8n adapter")
        headers = context.to_headers()
        headers["X-MarketOS-Automation-Token"] = self.webhook_token
        if self.api_key:
            headers["X-N8N-API-KEY"] = self.api_key
        client = self._client or httpx.Client(timeout=15.0)
        owns_client = self._client is None
        url = f"{self.base_url}{self.path_template.format(workflow=workflow)}"
        body = {
            "workflow": workflow,
            "payload": dict(payload),
            "context": {
                "workspace_id": context.workspace_id,
                "run_id": context.run_id,
                "artifact_id": context.artifact_id,
                "parent_ids": list(context.parent_ids),
                "idempotency_key": context.idempotency_key,
                "dry_run": context.dry_run,
                "approval_state": context.approval_state,
            },
        }
        try:
            for attempt in range(self.max_retries + 1):
                response = None
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
                    status = int(getattr(response, "status_code", 0) or 0)
                    # Only transport failures and 5xx responses are retried.
                    if (status and status < 500) or attempt >= self.max_retries:
                        raise
                    time.sleep(self.backoff_s * (2 ** attempt))
            raise RuntimeError("n8n workflow exhausted retries")
        finally:
            if owns_client:
                client.close()


automation_provider: WorkflowAutomationProvider = N8nAutomationAdapter()

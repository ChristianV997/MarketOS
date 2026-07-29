"""Permissioned boundary for optional Browser Use workflows."""
from __future__ import annotations

import asyncio
import os
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import urlparse

from backend.contracts.adapters import AdapterHealth, BrowserWorkflowProvider, SidecarContext


WorkflowRunner = Callable[[str, Mapping[str, Any], SidecarContext], Awaitable[Mapping[str, Any]]]


class BrowserUseWorker:
    """Run approved browser workflows through one injected runner.

    The runner is injected to keep Browser Use optional and to make every
    browser action testable without launching a real browser.
    """

    name = "browser-use"

    def __init__(self, runner: WorkflowRunner | None = None, *, allowed_workflows: set[str] | None = None, allowed_domains: set[str] | None = None, timeout_s: float = 120.0, max_actions: int = 50, require_trace: bool = True):
        self.runner = runner
        self.allowed_workflows = allowed_workflows or {"supplier_research", "product_import_review"}
        self.allowed_domains = allowed_domains or set(filter(None, os.getenv("BROWSER_USE_ALLOWED_DOMAINS", "").split(",")))
        self.timeout_s = timeout_s
        self.max_actions = max_actions
        self.require_trace = require_trace

    def health(self) -> AdapterHealth:
        if self.runner is None:
            return AdapterHealth(self.name, configured=False, reachable=False, detail="no permissioned workflow runner configured")
        return AdapterHealth(self.name, configured=True, reachable=True, capabilities=tuple(sorted(self.allowed_workflows)))

    async def execute(self, workflow: str, payload: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        if workflow not in self.allowed_workflows:
            raise PermissionError(f"browser workflow is not allowlisted: {workflow}")
        url = payload.get("url")
        if url and self.allowed_domains:
            hostname = (urlparse(str(url)).hostname or "").lower()
            if not any(hostname == domain.strip().lower().lstrip(".") or hostname.endswith("." + domain.strip().lower().lstrip(".")) for domain in self.allowed_domains):
                raise PermissionError(f"browser domain is not allowlisted: {hostname}")
        if context.approval_state not in {"approved", "not_required"}:
            raise PermissionError("browser workflow requires MarketOS approval")
        if context.dry_run:
            return {"workflow": workflow, "status": "planned", "dry_run": True, "payload": dict(payload)}
        if self.runner is None:
            raise RuntimeError("Browser Use runner is not configured")
        result = await asyncio.wait_for(self.runner(workflow, payload, context), timeout=self.timeout_s)
        actions = result.get("actions") if isinstance(result, Mapping) else None
        if isinstance(actions, list) and len(actions) > self.max_actions:
            raise RuntimeError("browser workflow exceeded the configured action limit")
        if self.require_trace and isinstance(result, Mapping) and not (result.get("trace_id") or result.get("trace") or result.get("actions")):
            raise RuntimeError("browser workflow result must include an execution trace")
        return result


browser_use_worker: BrowserWorkflowProvider = BrowserUseWorker()

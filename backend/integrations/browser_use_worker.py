"""Permissioned boundary for optional Browser Use workflows."""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping

from backend.contracts.adapters import AdapterHealth, BrowserWorkflowProvider, SidecarContext


WorkflowRunner = Callable[[str, Mapping[str, Any], SidecarContext], Awaitable[Mapping[str, Any]]]


class BrowserUseWorker:
    """Run approved browser workflows through one injected runner.

    The runner is injected to keep Browser Use optional and to make every
    browser action testable without launching a real browser.
    """

    name = "browser-use"

    def __init__(self, runner: WorkflowRunner | None = None, *, allowed_workflows: set[str] | None = None):
        self.runner = runner
        self.allowed_workflows = allowed_workflows or {"supplier_research", "product_import_review"}

    def health(self) -> AdapterHealth:
        if self.runner is None:
            return AdapterHealth(self.name, configured=False, reachable=False, detail="no permissioned workflow runner configured")
        return AdapterHealth(self.name, configured=True, reachable=True, capabilities=tuple(sorted(self.allowed_workflows)))

    async def execute(self, workflow: str, payload: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        if workflow not in self.allowed_workflows:
            raise PermissionError(f"browser workflow is not allowlisted: {workflow}")
        if context.approval_state not in {"approved", "not_required"}:
            raise PermissionError("browser workflow requires MarketOS approval")
        if context.dry_run:
            return {"workflow": workflow, "status": "planned", "dry_run": True, "payload": dict(payload)}
        if self.runner is None:
            raise RuntimeError("Browser Use runner is not configured")
        return await self.runner(workflow, payload, context)


browser_use_worker: BrowserWorkflowProvider = BrowserUseWorker()

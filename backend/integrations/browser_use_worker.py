"""Permissioned boundary for optional Browser Use workflows."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import urlparse

from backend.contracts.adapters import AdapterHealth, BrowserWorkflowProvider, SidecarContext


WorkflowRunner = Callable[[str, Mapping[str, Any], SidecarContext], Awaitable[Mapping[str, Any]]]


_TRACE_SECRET_KEYS = {"authorization", "cookie", "cookies", "password", "secret", "token", "api_key", "access_token"}


def _trace_value(value: Any, *, depth: int = 0) -> Any:
    """Return a small, JSON-safe audit representation of Browser Use history.

    Browser history can contain rendered page data, cookies, and screenshots.
    It is useful for an operator to see which actions ran, but none of those
    heavyweight or sensitive artifacts belong in an API response by default.
    """
    if depth > 4:
        return "<truncated>"
    if hasattr(value, "model_dump"):
        try:
            value = value.model_dump()
        except Exception:  # pragma: no cover - optional dependency shapes
            value = str(value)
    elif hasattr(value, "to_dict"):
        try:
            value = value.to_dict()
        except Exception:  # pragma: no cover - optional dependency shapes
            value = str(value)
    if isinstance(value, Mapping):
        return {
            str(key): ("<redacted>" if str(key).lower() in _TRACE_SECRET_KEYS else _trace_value(item, depth=depth + 1))
            for key, item in list(value.items())[:20]
        }
    if isinstance(value, (list, tuple)):
        return [_trace_value(item, depth=depth + 1) for item in value[:10]]
    if isinstance(value, str):
        # Screenshots commonly arrive as data URLs; retain only an indication
        # that one existed rather than returning a potentially huge image.
        if value.startswith("data:image/"):
            return "<screenshot captured>"
        return value[:1000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:1000]


def _history_trace(history: Any) -> Mapping[str, Any]:
    """Extract a version-tolerant, bounded action trace from Browser Use."""
    steps = getattr(history, "history", None)
    if steps is None and isinstance(history, Mapping):
        steps = history.get("history") or history.get("actions")
    if not isinstance(steps, (list, tuple)):
        steps = []
    return {
        "action_count": len(steps),
        "steps": [_trace_value(step) for step in steps[:50]],
        "truncated": len(steps) > 50,
    }


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
        if not context.dry_run and not self.allowed_domains:
            raise PermissionError("live browser workflows require BROWSER_USE_ALLOWED_DOMAINS")
        if not context.dry_run and not url:
            raise ValueError("live browser workflows require an explicit allowlisted URL")
        if url and self.allowed_domains:
            hostname = (urlparse(str(url)).hostname or "").lower()
            if not any(hostname == domain.strip().lower().lstrip(".") or hostname.endswith("." + domain.strip().lower().lstrip(".")) for domain in self.allowed_domains):
                raise PermissionError(f"browser domain is not allowlisted: {hostname}")
        if not context.dry_run and context.approval_state != "approved":
            raise PermissionError("browser workflow requires MarketOS approval")
        if context.dry_run:
            return {"workflow": workflow, "status": "planned", "dry_run": True, "payload": dict(payload)}
        context.require_live_idempotency()
        if self.runner is None:
            raise RuntimeError("Browser Use runner is not configured")
        result = await asyncio.wait_for(self.runner(workflow, payload, context), timeout=self.timeout_s)
        actions = result.get("actions") if isinstance(result, Mapping) else None
        action_count = result.get("action_count") if isinstance(result, Mapping) else None
        if isinstance(actions, list) and len(actions) > self.max_actions:
            raise RuntimeError("browser workflow exceeded the configured action limit")
        if isinstance(action_count, int) and action_count > self.max_actions:
            raise RuntimeError("browser workflow exceeded the configured action limit")
        if self.require_trace and isinstance(result, Mapping) and not (result.get("trace_id") or result.get("trace") or result.get("actions")):
            raise RuntimeError("browser workflow result must include an execution trace")
        return result


browser_use_worker: BrowserWorkflowProvider = BrowserUseWorker()


def build_browser_use_runner() -> WorkflowRunner:
    """Create the optional Browser Use runner lazily.

    The dependency is deliberately imported only when the worker is enabled;
    the API process remains usable without the optional browser profile.
    """
    try:
        from browser_use.beta import Agent, BrowserProfile, ChatBrowserUse
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Browser Use is not installed; install the reviewed optional worker profile") from exc

    async def _run(workflow: str, payload: Mapping[str, Any], context: SidecarContext) -> Mapping[str, Any]:
        task = {
            "supplier_research": "Research the supplier/product page and return structured product facts.",
            "product_import_review": "Review the proposed product import and report any blocking issues.",
        }.get(workflow, workflow)
        task = f"{task}\nInput JSON: {json.dumps(dict(payload), sort_keys=True)}\nDo not purchase, publish, or change account settings."
        profile = BrowserProfile(
            headless=os.getenv("BROWSER_USE_HEADLESS", "true").lower() == "true",
            allowed_domains=sorted({d.strip() for d in os.getenv("BROWSER_USE_ALLOWED_DOMAINS", "").split(",") if d.strip()}),
        )
        agent = Agent(task=task, llm=ChatBrowserUse(model=os.getenv("BROWSER_USE_MODEL", "bu-2-0")), browser_profile=profile)
        history = await agent.run()
        final = history.final_result() if hasattr(history, "final_result") else str(history)
        trace_id = hashlib.sha256(f"{context.run_id}:{context.artifact_id}:{workflow}".encode()).hexdigest()[:24]
        trace = _history_trace(history)
        return {
            "workflow": workflow,
            "status": "completed",
            "result": final,
            "trace_id": trace_id,
            "trace": trace,
            "action_count": trace["action_count"],
        }

    return _run


if os.getenv("BROWSER_USE_ENABLED", "false").lower() == "true":
    browser_use_worker = BrowserUseWorker(runner=build_browser_use_runner())

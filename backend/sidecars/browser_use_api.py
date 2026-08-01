"""HTTP boundary for the optional Browser Use worker.

This service is intended for a private Docker network only.  It receives the
same canonical MarketOS context as any other sidecar, then independently
applies the browser workflow allowlist, domain allowlist, approval, timeout,
idempotency, and trace requirements before invoking Browser Use.
"""
from __future__ import annotations

import hmac
import importlib.util
import os
from typing import Any, Mapping

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from backend.contracts.adapters import SidecarContext
from backend.integrations.browser_use_worker import BrowserUseWorker, build_browser_use_runner


class ContextPayload(BaseModel):
    workspace_id: str = "default"
    run_id: str = ""
    artifact_id: str = ""
    parent_ids: list[str] = Field(default_factory=list)
    idempotency_key: str = ""
    dry_run: bool = True
    approval_state: str = "not_required"

    def to_context(self) -> SidecarContext:
        return SidecarContext(
            workspace_id=self.workspace_id,
            run_id=self.run_id,
            artifact_id=self.artifact_id,
            parent_ids=tuple(self.parent_ids),
            idempotency_key=self.idempotency_key,
            dry_run=self.dry_run,
            approval_state=self.approval_state,
        )


class BrowserExecutionRequest(BaseModel):
    workflow: str
    payload: dict[str, Any] = Field(default_factory=dict)
    context: ContextPayload = Field(default_factory=ContextPayload)


def _worker_token() -> str:
    return os.getenv("BROWSER_USE_WORKER_TOKEN", "")


def _authorize(authorization: str | None) -> None:
    expected = _worker_token()
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid browser worker credentials")


def _new_worker() -> BrowserUseWorker:
    """Build a service-local runner so API and browser dependencies stay apart."""
    async def _run(workflow: str, payload: Mapping[str, Any], context: SidecarContext) -> Mapping[str, Any]:
        # Keep dry-run handling dependency-free; Browser Use itself is loaded
        # only after the outer worker has admitted a live execution.
        return await build_browser_use_runner()(workflow, payload, context)

    return BrowserUseWorker(runner=_run)


app = FastAPI(title="MarketOS Browser Use Worker", version="1.0")


@app.get("/health")
def health() -> Mapping[str, Any]:
    # Do not import or launch the optional browser process for a liveness probe.
    dependency_available = importlib.util.find_spec("browser_use") is not None
    configured = bool(_worker_token()) and dependency_available
    return {
        "service": "browser-use-worker",
        "configured": configured,
        "ready": configured,
        "detail": "worker token and browser dependency configured" if configured else "worker token or browser-use dependency is missing",
    }


@app.post("/execute")
async def execute(request: BrowserExecutionRequest, authorization: str | None = Header(default=None)) -> Mapping[str, Any]:
    _authorize(authorization)
    try:
        worker = _new_worker()
        return await worker.execute(request.workflow, request.payload, context=request.context.to_context())
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

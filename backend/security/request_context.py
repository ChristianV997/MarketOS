"""ASGI request correlation middleware with safe response headers."""
from __future__ import annotations

import re
import os
import time
import uuid
from typing import Any

from backend.security.safe_logging import log_request_end, log_request_start
from backend.observability.phase1_telemetry import set_request_sentry_context


_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def _request_id(headers: list[tuple[bytes, bytes]]) -> str:
    for key, value in headers:
        if key.lower() == b"x-request-id":
            candidate = value.decode("ascii", "ignore")
            if _SAFE_REQUEST_ID.fullmatch(candidate):
                return candidate
    return uuid.uuid4().hex


def _route_family(path: str) -> str:
    if path.startswith("/api/events"):
        return "event_read"
    if path.startswith("/api/commerce-mvp/public-run"):
        return "public_commerce_run"
    return "other"


class RequestContextMiddleware:
    """Add correlation headers and summary-only request logs."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        request_id = _request_id(scope.get("headers", []))
        path = str(scope.get("path", ""))
        method = str(scope.get("method", "GET"))
        family = _route_family(path)
        started = time.perf_counter()
        scope["marketos_request_id"] = request_id
        status_code = 500
        set_request_sentry_context(
            request_id=request_id,
            method=method,
            path=path,
            mvp_mode=os.getenv("MARKETOS_MVP_MODE", "0") == "1",
            read_only=family in {"event_read", "public_commerce_run"},
        )
        log_request_start(request_id=request_id, method=method, path=path, route_family=family)

        async def send_with_headers(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 500))
                headers = list(message.get("headers", []))
                names = {key.lower() for key, _ in headers}
                if b"x-request-id" not in names:
                    headers.append((b"x-request-id", request_id.encode("ascii")))
                if b"x-marketos-mvp-mode" not in names:
                    headers.append((b"x-marketos-mvp-mode", b"true"))
                if family in {"event_read", "public_commerce_run"} and b"x-marketos-read-only" not in names:
                    headers.append((b"x-marketos-read-only", b"true"))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            log_request_end(request_id=request_id, method=method, path=path, status_code=status_code, duration_ms=(time.perf_counter() - started) * 1000, route_family=family, read_only=family in {"event_read", "public_commerce_run"})


__all__ = ["RequestContextMiddleware"]

"""api.ws — operator-gated WebSocket live event stream.

Transport: a browser cannot set ``Authorization`` on a WebSocket handshake, so the
client offers the bearer token as a subprotocol::

    new WebSocket(url, ["marketos.events.v1", "bearer.<token>"])

Exactly one ``bearer.`` entry is read, and the token must use RFC 7230 token
characters (browsers refuse other subprotocol values). Only ``marketos.events.v1``
is echoed on accept, so the token is never reflected. Query strings, cookies and
other headers are never read for identity.

The gate runs before ``accept()``. The connection is accepted only when the server
verifies a principal holding ``event_stream:read`` in its sole internal workspace
(``backend.identity.http``). Every other case, including unconfigured identity
providers, closes with 1008 and sends no envelope.

Once the gate passes, ``backend.ws.stream.ws_stream`` handles replay, heartbeat and
broker consumption.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any

from fastapi import WebSocket, status
from starlette.concurrency import run_in_threadpool

from backend.identity.http import (
    get_token_verifier,
    get_workspace_repository,
    require_principal,
    require_workspace_permission,
)
from backend.identity.repository import OWNER_TYPE
from backend.identity.roles import EVENT_STREAM_READ
from backend.ws.stream import ws_stream

EVENTS_PROTOCOL = "marketos.events.v1"
_BEARER_PREFIX = "bearer."

_log = logging.getLogger("marketos.ws")
_operator_gate = require_workspace_permission(OWNER_TYPE, EVENT_STREAM_READ)


def _offered_protocols(ws: WebSocket) -> list[str]:
    raw = ws.headers.get("sec-websocket-protocol", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _offered_bearer_token(offered: list[str]) -> str | None:
    tokens = [item[len(_BEARER_PREFIX):] for item in offered if item.startswith(_BEARER_PREFIX)]
    return tokens[0] if len(tokens) == 1 else None


async def _provide(ws: WebSocket, dependency: Any) -> Any:
    """Resolve a provider as FastAPI would, honouring ``app.dependency_overrides``.

    ``Depends`` would let an unconfigured provider's HTTP 503 escape during dependency
    solving, and Starlette cannot turn that into a websocket close. Resolving here keeps
    every refusal a 1008 close. Providers must return their object directly (not yield it).
    """
    provider = ws.app.dependency_overrides.get(dependency, dependency)
    if inspect.iscoroutinefunction(provider):
        return await provider()
    return await run_in_threadpool(provider)


async def _is_operator(ws: WebSocket) -> bool:
    offered = _offered_protocols(ws)
    token = _offered_bearer_token(offered)
    if token is None or EVENTS_PROTOCOL not in offered:
        return False
    try:
        verifier = await _provide(ws, get_token_verifier)
        repository = await _provide(ws, get_workspace_repository)
        principal = await run_in_threadpool(require_principal, authorization=f"Bearer {token}", verifier=verifier)
        await run_in_threadpool(_operator_gate, principal=principal, repository=repository)
    except Exception as exc:
        _log.info("ws_refused reason=%s", getattr(exc, "status_code", type(exc).__name__))
        return False
    return True


async def event_stream(ws: WebSocket) -> None:  # noqa: D401
    if not await _is_operator(ws):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await ws_stream.handle(ws, subprotocol=EVENTS_PROTOCOL)

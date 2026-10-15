"""backend.ws.stream — workspace-scoped WebSocket stream.

Delivery is scoped to the server-resolved workspace of each connection:

- Replay is not offered to scoped sessions. The replay stores are global and cannot
  yet filter by workspace, so reading them would expose other workspaces' events.
- A live envelope reaches the socket only when its server-set ``workspace_id`` equals
  the session's workspace. Untagged and foreign envelopes are dropped.
- A missing or malformed scope is refused with 1008 before ``accept()``.

Heartbeat frames carry only a timestamp and are sent to every accepted session.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from backend.identity.workspaces import WORKSPACE_ID_PATTERN, WorkspaceAccess

_log = logging.getLogger(__name__)

_HEARTBEAT_S = 30.0
_IDLE_SLEEP_S = 0.1
_POLICY_VIOLATION = 1008
SCOPE_KEY = "workspace_id"


def _scope_workspace_id(access: Any) -> str | None:
    """Return the server-resolved workspace id, or ``None`` when the scope is absent or malformed."""
    if not isinstance(access, WorkspaceAccess):
        return None
    workspace_id = access.workspace_id
    if not isinstance(workspace_id, str) or WORKSPACE_ID_PATTERN.fullmatch(workspace_id) is None:
        return None
    return workspace_id


def _envelope_workspace_id(env: Any) -> str | None:
    payload = getattr(env, "payload", None)
    if not isinstance(payload, dict):
        return None
    value = payload.get(SCOPE_KEY)
    return value if isinstance(value, str) else None


class WebSocketStream:
    """One WebSocket session, delivering only envelopes in its workspace scope."""

    def __init__(
        self,
        heartbeat_s: float = _HEARTBEAT_S,
        idle_sleep_s: float = _IDLE_SLEEP_S,
    ):
        self._heartbeat_s = heartbeat_s
        self._idle_sleep_s = idle_sleep_s

    async def handle(self, ws: Any, *, subprotocol: str | None = None, access: Any = None) -> None:
        """Accept a scoped session and stream its workspace's live events until disconnect.

        ``access`` must be the ``WorkspaceAccess`` the server resolved for the verified
        principal. Anything else is refused with 1008 before ``accept()``. No client
        value is read here: the workspace comes only from ``access``.
        """
        scope = _scope_workspace_id(access)
        if scope is None:
            await ws.close(code=_POLICY_VIOLATION)
            return

        from backend.pubsub.broker import broker

        try:
            await ws.accept(subprotocol=subprotocol)
        except Exception:
            return

        last_hb = time.time()

        while True:
            try:
                envelopes = await asyncio.to_thread(
                    broker.consume,
                    "ws",
                    "ws_consumer",
                )
            except Exception as exc:
                _log.warning("ws_consume_error error=%s", exc)
                await asyncio.sleep(self._idle_sleep_s)
                continue

            for env in envelopes:
                if _envelope_workspace_id(env) != scope:
                    continue
                try:
                    await ws.send_text(env.envelope_json())
                except Exception:
                    return

            now = time.time()

            if now - last_hb >= self._heartbeat_s:
                try:
                    await ws.send_text(json.dumps({
                        "type": "heartbeat",
                        "ts": now,
                    }))
                    last_hb = now
                except Exception:
                    return

            if not envelopes:
                await asyncio.sleep(self._idle_sleep_s)


ws_stream = WebSocketStream()

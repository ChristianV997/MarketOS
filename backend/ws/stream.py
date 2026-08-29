"""backend.ws.stream — reconnect-safe WebSocket stream.

Features
--------
- Replay on reconnect using the durable replay store.
- Deterministic event envelopes with sequence_id + replay_hash.
- Heartbeat frames for long-lived command-center sessions.
- Compatibility with legacy payload-only frontend consumers.
- Client disconnect ends the handler so TestClient and process teardown stay bounded.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

_log = logging.getLogger(__name__)

_HEARTBEAT_S = 30.0
_IDLE_SLEEP_S = 0.1
_REPLAY_N = 30


class WebSocketStream:
    """Manages a single WebSocket connection with replay + heartbeat."""

    def __init__(
        self,
        heartbeat_s: float = _HEARTBEAT_S,
        idle_sleep_s: float = _IDLE_SLEEP_S,
        replay_n: int = _REPLAY_N,
    ):
        self._heartbeat_s = heartbeat_s
        self._idle_sleep_s = idle_sleep_s
        self._replay_n = replay_n

    async def handle(self, ws: Any) -> None:
        """Accept a WebSocket connection and stream events until disconnect."""
        from backend.pubsub.broker import broker

        try:
            await ws.accept()
        except Exception:
            return

        replay_payloads = self._load_replay_payloads(broker)

        for payload_json in replay_payloads:
            try:
                await ws.send_text(payload_json)
            except Exception:
                return

        last_hb = time.time()

        while True:
            incoming = await self._receive_or_idle(ws)
            if incoming is False:
                return
            if isinstance(incoming, dict):
                incoming_type = incoming.get("type")
                if incoming_type in {"websocket.disconnect", "websocket.close"}:
                    return

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

            if not envelopes and incoming is None:
                await asyncio.sleep(0)

    async def _receive_or_idle(self, ws: Any):
        """Wait briefly for a client frame so disconnect can end the loop."""
        try:
            return await asyncio.wait_for(ws.receive(), timeout=self._idle_sleep_s)
        except TimeoutError:
            return None
        except Exception:
            return False

    def _load_replay_payloads(self, broker: Any) -> list[str]:
        """Return recent event envelopes for websocket hydration."""

        try:
            from backend.runtime.replay_store import runtime_replay_store

            rows = runtime_replay_store.recent(n=self._replay_n)

            if rows:
                return [
                    json.dumps(row, default=str)
                    for row in rows
                ]

        except Exception:
            pass

        return [
            env.envelope_json()
            for env in broker.replay.recent(n=self._replay_n)
        ]


ws_stream = WebSocketStream()

"""backend.ws.stream — reconnect-safe WebSocket stream.

Features
--------
- Replay on reconnect using the durable replay store.
- Deterministic event envelopes with sequence_id + replay_hash.
- Heartbeat frames for long-lived command-center sessions.
- Compatibility with legacy payload-only frontend consumers.
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

    async def handle(self, ws: Any, *, subprotocol: str | None = None) -> None:
        """Accept a WebSocket connection and stream events until disconnect.

        Accepts unconditionally. The caller (``api.ws.event_stream``) must verify
        the connection's identity before calling this.
        """
        from backend.pubsub.broker import broker

        try:
            await ws.accept(subprotocol=subprotocol)
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

            if not envelopes:
                await asyncio.sleep(self._idle_sleep_s)

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

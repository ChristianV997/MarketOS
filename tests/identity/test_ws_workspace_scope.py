"""Workspace scope for the operator WebSocket stream (#475 remediation).

A verified operator is scoped to the one internal workspace the server resolved for
that principal. Replay is never read for a scoped session, and live delivery is
limited to envelopes whose server-set ``workspace_id`` matches. Fakes only: an
in-memory broker, recording replay stores, and an in-memory membership repository.
No real broker, credentials, or network.
"""
from __future__ import annotations

import asyncio
import importlib
import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

import api.ws as api_ws
from api.ws import EVENTS_PROTOCOL, event_stream
from backend.identity.http import get_token_verifier, get_workspace_repository
from backend.identity.principal import VerifiedPrincipal
from backend.identity.roles import CLIENT_VIEWER, INTERNAL_OPERATOR
from backend.identity.workspaces import WorkspaceAccess
from backend.ws.stream import WebSocketStream

ISSUER = "https://issuer.fixture"
WS_A = "ws-internal-a"
WS_B = "ws-internal-b"
WS_CLIENT = "ws-client-fixture"
POLICY_VIOLATION = 1008

# The package re-exports a ``broker`` object that shadows the submodule, so the
# modules are imported by name rather than with ``import ... as``.
broker_module = importlib.import_module("backend.pubsub.broker")
replay_module = importlib.import_module("backend.runtime.replay_store")

OPERATOR = VerifiedPrincipal(ISSUER, "user_scope_operator")
VIEWER = VerifiedPrincipal(ISSUER, "user_scope_viewer")
CLIENT_ONLY = VerifiedPrincipal(ISSUER, "user_scope_client")
MULTI = VerifiedPrincipal(ISSUER, "user_scope_multi")
TOKENS = {
    "tok-operator": OPERATOR,
    "tok-viewer": VIEWER,
    "tok-client": CLIENT_ONLY,
    "tok-multi": MULTI,
}


def _membership(principal: VerifiedPrincipal, workspace_id: str, workspace_type: str, role: str) -> WorkspaceAccess:
    return WorkspaceAccess(
        issuer=principal.issuer,
        subject=principal.subject,
        workspace_id=workspace_id,
        workspace_type=workspace_type,
        display_name=workspace_id,
        role=role,
    )


MEMBERSHIPS = (
    _membership(OPERATOR, WS_A, "internal", INTERNAL_OPERATOR),
    _membership(VIEWER, WS_A, "internal", CLIENT_VIEWER),
    _membership(CLIENT_ONLY, WS_CLIENT, "client_service", INTERNAL_OPERATOR),
    _membership(MULTI, WS_A, "internal", INTERNAL_OPERATOR),
    _membership(MULTI, WS_B, "internal", INTERNAL_OPERATOR),
)


def _access(workspace_id: Any, *, role: str = INTERNAL_OPERATOR) -> WorkspaceAccess:
    return WorkspaceAccess(
        issuer=ISSUER,
        subject="user_scope_operator",
        workspace_id=workspace_id,
        workspace_type="internal",
        display_name="fixture",
        role=role,
    )


class FakeVerifier:
    def verify(self, token: str) -> VerifiedPrincipal:
        if token not in TOKENS:
            raise ValueError("unknown fixture token")
        return TOKENS[token]


class FakeRepository:
    def memberships_for(self, principal: VerifiedPrincipal) -> tuple[WorkspaceAccess, ...]:
        return tuple(m for m in MEMBERSHIPS if m.issuer == principal.issuer and m.subject == principal.subject)


@dataclass(frozen=True)
class FakeEnvelope:
    payload: dict

    def envelope_json(self) -> str:
        return json.dumps(self.payload, sort_keys=True)


def _event(event_id: str, workspace_id: str | None = None) -> FakeEnvelope:
    payload: dict[str, Any] = {"event_id": event_id, "type": "runtime.snapshot"}
    if workspace_id is not None:
        payload["workspace_id"] = workspace_id
    return FakeEnvelope(payload)


class FakeReplay:
    def __init__(self, rows: list[dict] | None = None):
        self.recent_calls = 0
        self._rows = list(rows or [])

    def recent(self, n: int = 50) -> list[dict]:
        self.recent_calls += 1
        return list(self._rows)


class FakeBroker:
    def __init__(self, batches: list[list[FakeEnvelope]]):
        self._batches = [list(batch) for batch in batches]
        self.consume_calls = 0
        self.replay = FakeReplay()

    def consume(self, topic: str = "ws", consumer_name: str = "ws_consumer", limit: int = 1000) -> list[FakeEnvelope]:
        self.consume_calls += 1
        return self._batches.pop(0) if self._batches else []


class FakeWebSocket:
    """Records accept and close, and stops the stream after ``limit`` sends."""

    def __init__(
        self,
        subprotocols: tuple[str, ...] = (),
        *,
        limit: int | None = None,
        query_params: dict | None = None,
        dependency_overrides: dict | None = None,
    ):
        self.app = SimpleNamespace(dependency_overrides=dict(dependency_overrides or {}))
        self.headers = {"sec-websocket-protocol": ", ".join(subprotocols)} if subprotocols else {}
        self.query_params = dict(query_params or {})
        self.accept_calls = 0
        self.accepted_subprotocol = None
        self.close_codes: list[int] = []
        self.sent: list[str] = []
        self._limit = limit

    async def accept(self, subprotocol: str | None = None) -> None:
        self.accept_calls += 1
        self.accepted_subprotocol = subprotocol

    async def close(self, code: int = 1000) -> None:
        self.close_codes.append(code)

    async def send_text(self, text: str) -> None:
        self.sent.append(text)
        if self._limit is not None and len(self.sent) >= self._limit:
            raise ConnectionError("fixture stop")


def _frames(ws: FakeWebSocket) -> list[dict]:
    return [json.loads(text) for text in ws.sent]


def _event_ids(ws: FakeWebSocket) -> list[str]:
    return [frame["event_id"] for frame in _frames(ws) if frame.get("type") != "heartbeat"]


def _overrides() -> dict:
    return {get_token_verifier: FakeVerifier, get_workspace_repository: FakeRepository}


@pytest.fixture
def install(monkeypatch):
    """Install a fake broker and a recording runtime replay store. Returns the fakes."""

    def _install(batches: list[list[FakeEnvelope]] | None = None, replay_rows: list[dict] | None = None):
        broker = FakeBroker(batches or [])
        runtime_store = FakeReplay(replay_rows)
        broker.replay = FakeReplay(replay_rows)
        monkeypatch.setattr(broker_module, "broker", broker)
        monkeypatch.setattr(replay_module, "runtime_replay_store", runtime_store)
        return broker, runtime_store

    return _install


@pytest.fixture
def fast_stream(monkeypatch):
    """Heartbeat on every loop and no idle sleep, so every session terminates in the tests."""
    fast = WebSocketStream(heartbeat_s=0, idle_sleep_s=0)
    monkeypatch.setattr(api_ws, "ws_stream", fast)
    return fast


def _run(coro) -> None:
    asyncio.run(coro)


def _assert_refused_before_accept(ws: FakeWebSocket, broker: FakeBroker, runtime_store: FakeReplay) -> None:
    assert ws.accept_calls == 0
    assert ws.close_codes == [POLICY_VIOLATION]
    assert ws.sent == []
    assert broker.consume_calls == 0
    assert runtime_store.recent_calls == 0
    assert broker.replay.recent_calls == 0


# Stream boundary: the scope carried in from the gate.

def test_absent_scope_is_refused_before_accept(install):
    broker, runtime_store = install(batches=[[_event("a1", WS_A)]])
    ws = FakeWebSocket(limit=5)

    _run(WebSocketStream(heartbeat_s=0, idle_sleep_s=0).handle(ws, subprotocol=EVENTS_PROTOCOL, access=None))

    _assert_refused_before_accept(ws, broker, runtime_store)


@pytest.mark.parametrize(
    "access",
    [
        {"workspace_id": WS_A},
        WS_A,
        SimpleNamespace(workspace_id=WS_A),
        _access("ws A with spaces"),
        _access(""),
        _access("../escape"),
        _access("x" * 129),
        _access(None),
    ],
    ids=["dict", "bare_string", "namespace", "space", "empty", "traversal", "overlong", "none_id"],
)
def test_malformed_scope_cannot_subscribe(install, access):
    broker, runtime_store = install(batches=[[_event("a1", WS_A)]])
    ws = FakeWebSocket(limit=5)

    _run(WebSocketStream(heartbeat_s=0, idle_sleep_s=0).handle(ws, subprotocol=EVENTS_PROTOCOL, access=access))

    _assert_refused_before_accept(ws, broker, runtime_store)


def test_scoped_session_never_reads_global_replay(install):
    broker, runtime_store = install(
        batches=[],
        replay_rows=[{"event_id": "replay-a", "workspace_id": WS_A}, {"event_id": "replay-b", "workspace_id": WS_B}],
    )
    ws = FakeWebSocket(limit=1)

    _run(WebSocketStream(heartbeat_s=0, idle_sleep_s=0).handle(ws, subprotocol=EVENTS_PROTOCOL, access=_access(WS_A)))

    assert ws.accept_calls == 1
    assert runtime_store.recent_calls == 0
    assert broker.replay.recent_calls == 0
    assert _event_ids(ws) == []
    assert [frame["type"] for frame in _frames(ws)] == ["heartbeat"]


def test_live_delivery_is_limited_to_session_workspace(install):
    batch = [_event("a1", WS_A), _event("b1", WS_B), _event("untagged"), _event("a2", WS_A)]
    broker, runtime_store = install(batches=[batch])
    ws = FakeWebSocket(limit=3)

    _run(WebSocketStream(heartbeat_s=0, idle_sleep_s=0).handle(ws, subprotocol=EVENTS_PROTOCOL, access=_access(WS_A)))

    assert _event_ids(ws) == ["a1", "a2"]
    assert "b1" not in "".join(ws.sent)
    assert "untagged" not in "".join(ws.sent)
    assert runtime_store.recent_calls == 0
    assert broker.replay.recent_calls == 0


def test_other_workspace_session_receives_only_its_own_events(install):
    batch = [_event("a1", WS_A), _event("b1", WS_B), _event("untagged"), _event("a2", WS_A)]
    install(batches=[batch])
    ws = FakeWebSocket(limit=2)

    _run(WebSocketStream(heartbeat_s=0, idle_sleep_s=0).handle(ws, subprotocol=EVENTS_PROTOCOL, access=_access(WS_B)))

    assert _event_ids(ws) == ["b1"]
    assert "a1" not in "".join(ws.sent)
    assert "a2" not in "".join(ws.sent)


def test_untagged_events_are_never_delivered(install):
    install(batches=[[_event("untagged-1"), _event("untagged-2")]])
    ws = FakeWebSocket(limit=1)

    _run(WebSocketStream(heartbeat_s=0, idle_sleep_s=0).handle(ws, subprotocol=EVENTS_PROTOCOL, access=_access(WS_A)))

    assert _event_ids(ws) == []


# Route boundary: the gate passes its resolved access into the stream.

def test_verified_operator_is_scoped_to_its_own_workspace(install, fast_stream):
    broker, runtime_store = install(batches=[[_event("a1", WS_A), _event("b1", WS_B)]])
    ws = FakeWebSocket(
        (EVENTS_PROTOCOL, "bearer.tok-operator"),
        limit=2,
        dependency_overrides=_overrides(),
    )

    _run(event_stream(ws))

    assert ws.accept_calls == 1
    assert ws.accepted_subprotocol == EVENTS_PROTOCOL
    assert _event_ids(ws) == ["a1"]
    assert "b1" not in "".join(ws.sent)
    assert broker.consume_calls >= 1
    assert runtime_store.recent_calls == 0
    assert broker.replay.recent_calls == 0


def test_query_string_workspace_does_not_change_scope(install, fast_stream):
    broker, runtime_store = install(batches=[[_event("b1", WS_B)]])
    ws = FakeWebSocket(
        (EVENTS_PROTOCOL, "bearer.tok-operator"),
        limit=1,
        query_params={"workspace_id": WS_B},
        dependency_overrides=_overrides(),
    )

    _run(event_stream(ws))

    assert ws.accept_calls == 1
    assert _event_ids(ws) == []
    assert runtime_store.recent_calls == 0
    assert broker.replay.recent_calls == 0


@pytest.mark.parametrize(
    "subprotocols",
    [
        (EVENTS_PROTOCOL, "bearer.tok-viewer"),
        (EVENTS_PROTOCOL, "bearer.tok-client"),
        (EVENTS_PROTOCOL, "bearer.tok-unknown"),
        (EVENTS_PROTOCOL,),
        (EVENTS_PROTOCOL, "bearer.tok-operator", "bearer.tok-operator"),
        ("bearer.tok-operator",),
        (),
        (EVENTS_PROTOCOL, "bearer.tok-multi"),
    ],
    ids=[
        "client_viewer_internal",
        "client_only_operator",
        "unknown_token",
        "no_bearer",
        "duplicate_bearer",
        "no_events_protocol",
        "no_protocols",
        "ambiguous_internal_membership",
    ],
)
def test_unauthorized_socket_is_rejected_before_accept(install, fast_stream, subprotocols):
    broker, runtime_store = install(batches=[[_event("a1", WS_A)]])
    ws = FakeWebSocket(subprotocols, limit=5, dependency_overrides=_overrides())

    _run(event_stream(ws))

    _assert_refused_before_accept(ws, broker, runtime_store)


def test_unconfigured_identity_provider_is_rejected_before_accept(install, fast_stream):
    broker, runtime_store = install(batches=[[_event("a1", WS_A)]])
    ws = FakeWebSocket(
        (EVENTS_PROTOCOL, "bearer.tok-operator"),
        limit=5,
        dependency_overrides={get_workspace_repository: FakeRepository},
    )

    _run(event_stream(ws))

    _assert_refused_before_accept(ws, broker, runtime_store)

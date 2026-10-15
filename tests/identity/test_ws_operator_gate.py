"""Operator gate on the mounted ``/ws`` live event stream.

The production app is used so the tests cover the route as deployed. Identity providers
are fakes, the workspace store is SQLite running the repository's portable SQL (see
``conftest.py``), and the broker and replay store are recorders with synthetic payloads.
No network, credential or real event is involved.
"""
from __future__ import annotations

import importlib
import json

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.ws import EVENTS_PROTOCOL
from backend.identity.errors import IdentityError
from backend.identity.http import get_token_verifier, get_workspace_repository
from backend.identity.principal import VerifiedPrincipal
from backend.identity.roles import CLIENT_VIEWER, INTERNAL_OPERATOR

from .conftest import CLIENT_ACME, ISSUER, OWNER_ALICE

OPERATOR = VerifiedPrincipal(ISSUER, "user_ws_operator")
VIEWER = VerifiedPrincipal(ISSUER, "user_ws_viewer")  # client_viewer in the internal workspace
CLIENT_ONLY = VerifiedPrincipal(ISSUER, "user_ws_client_only")  # client_viewer in a client workspace only
TOKENS = {"tok-operator": OPERATOR, "tok-viewer": VIEWER, "tok-client": CLIENT_ONLY}

REPLAY = {
    "type": "runtime.snapshot", "event_id": "replay-1", "sequence_id": 1,
    "source": "synthetic", "ts": 1.0, "payload": {"cycle": 1},
}
LIVE = {
    "type": "cycle.completed", "event_id": "live-1", "sequence_id": 2,
    "source": "synthetic", "ts": 2.0, "payload": {"cycle": 2},
    "workspace_id": OWNER_ALICE,  # server-set scope; the operator's own internal workspace
}


class FakeVerifier:
    def verify(self, token: str) -> VerifiedPrincipal:
        try:
            return TOKENS[token]
        except KeyError:
            raise IdentityError() from None


class BrokenRepository:
    def __getattr__(self, name: str):
        raise RuntimeError("store unavailable")


class RecorderBroker:
    def __init__(self, *live: object) -> None:
        self._pending = list(live)
        self.consume_calls = 0

    def consume(self, topic: str = "ws", consumer_name: str = "ws_consumer", limit: int = 1000) -> list[object]:
        self.consume_calls += 1
        pending, self._pending = self._pending, []
        return pending


class SyntheticEnvelope:
    def __init__(self, body: dict) -> None:
        self._text = json.dumps(body)
        self.payload = body  # mirrors EventEnvelope.payload, which carries the server-set scope

    def envelope_json(self) -> str:
        return self._text


class FakeReplayStore:
    def __init__(self, *rows: dict) -> None:
        self._rows = list(rows)
        self.recent_calls = 0

    def recent(self, n: int = 50, event_type: str | None = None) -> list[dict]:
        self.recent_calls += 1
        return list(self._rows)


@pytest.fixture
def app():
    from backend.api import app as production_app  # the route as mounted, not a copy

    return production_app


@pytest.fixture
def overrides(app):
    installed: list[object] = []

    def install(dependency: object, provider: object) -> None:
        app.dependency_overrides[dependency] = provider
        installed.append(dependency)

    yield install
    for dependency in installed:
        app.dependency_overrides.pop(dependency, None)


@pytest.fixture
def store(repo):
    repo.create_workspace(OWNER_ALICE, "internal", "Alice Owner Workspace")
    repo.create_workspace(CLIENT_ACME, "client_service", "Acme Corp")
    repo.add_member(OWNER_ALICE, OPERATOR.issuer, OPERATOR.subject, INTERNAL_OPERATOR)
    repo.add_member(OWNER_ALICE, VIEWER.issuer, VIEWER.subject, CLIENT_VIEWER)
    repo.add_member(CLIENT_ACME, CLIENT_ONLY.issuer, CLIENT_ONLY.subject, CLIENT_VIEWER)
    return repo


@pytest.fixture
def wired(overrides, store):
    overrides(get_token_verifier, lambda: FakeVerifier())
    overrides(get_workspace_repository, lambda: store)


@pytest.fixture
def broker_and_replay(monkeypatch):
    # Patch the modules themselves: ``backend.pubsub`` re-exports a ``broker`` name that shadows
    # the submodule, so a dotted-string target would resolve to the instance instead.
    broker_module = importlib.import_module("backend.pubsub.broker")
    replay_module = importlib.import_module("backend.runtime.replay_store")
    broker = RecorderBroker(SyntheticEnvelope(LIVE))
    replay = FakeReplayStore(REPLAY)
    monkeypatch.setattr(broker_module, "broker", broker)
    monkeypatch.setattr(replay_module, "runtime_replay_store", replay)
    return broker, replay


def _connect(app, *, subprotocols=None, path="/ws", headers=None):
    extra = {"headers": headers} if headers is not None else {}
    return TestClient(app).websocket_connect(path, subprotocols=subprotocols, **extra)


def assert_refused(app, broker_and_replay, **connect) -> None:
    """The handshake is refused with 1008 and nothing reaches the broker or the replay store."""
    broker, replay = broker_and_replay
    with pytest.raises(WebSocketDisconnect) as refusal:
        with _connect(app, **connect) as ws:
            ws.receive_text()
    assert refusal.value.code == status.WS_1008_POLICY_VIOLATION
    assert broker.consume_calls == 0
    assert replay.recent_calls == 0


def test_anonymous_connection_is_refused_before_accept(app, wired, broker_and_replay):
    assert_refused(app, broker_and_replay)


def test_authorization_header_is_not_identity(app, wired, broker_and_replay):
    assert_refused(app, broker_and_replay, headers={"Authorization": "Bearer tok-operator"})


def test_query_string_token_is_not_identity(app, wired, broker_and_replay):
    assert_refused(app, broker_and_replay, path="/ws?token=tok-operator")


def test_unknown_token_is_refused(app, wired, broker_and_replay):
    assert_refused(app, broker_and_replay, subprotocols=[EVENTS_PROTOCOL, "bearer.tok-unknown"])


def test_token_without_events_protocol_is_refused(app, wired, broker_and_replay):
    assert_refused(app, broker_and_replay, subprotocols=["bearer.tok-operator"])


def test_client_viewer_in_internal_workspace_is_refused(app, wired, broker_and_replay):
    assert_refused(app, broker_and_replay, subprotocols=[EVENTS_PROTOCOL, "bearer.tok-viewer"])


def test_client_viewer_in_client_workspace_only_is_refused(app, wired, broker_and_replay):
    assert_refused(app, broker_and_replay, subprotocols=[EVENTS_PROTOCOL, "bearer.tok-client"])


def test_unconfigured_identity_provider_is_refused(app, broker_and_replay):
    assert get_token_verifier not in app.dependency_overrides
    assert_refused(app, broker_and_replay, subprotocols=[EVENTS_PROTOCOL, "bearer.tok-operator"])


def test_storage_failure_is_refused(app, overrides, broker_and_replay):
    overrides(get_token_verifier, lambda: FakeVerifier())
    overrides(get_workspace_repository, lambda: BrokenRepository())
    assert_refused(app, broker_and_replay, subprotocols=[EVENTS_PROTOCOL, "bearer.tok-operator"])


def test_operator_receives_its_workspace_live_envelope_without_replay(app, wired, broker_and_replay):
    broker, replay = broker_and_replay
    with _connect(app, subprotocols=[EVENTS_PROTOCOL, "bearer.tok-operator"]) as ws:
        assert ws.accepted_subprotocol == EVENTS_PROTOCOL
        assert ws.receive_text() == json.dumps(LIVE)
    assert replay.recent_calls == 0
    assert broker.consume_calls >= 1

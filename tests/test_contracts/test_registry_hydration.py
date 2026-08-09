"""Tests for backend.contracts.registry.ArtifactRegistry's replay-hydration
path, and the underlying backend.runtime.replay_store.get_replay_store()
fix it depends on.

Regression coverage: get_replay_store() was imported by backend.events.log
(and 6 other callers) but never defined, and RuntimeReplayStore had no
tail() method — so backend.events.log.append()/tail() silently no-op'd
(ImportError swallowed by a bare except) and ArtifactRegistry's durable
log + hydrate_from_replay() always restored 0 artifacts regardless of
what was ever registered. These tests prove the round trip now works.
"""
import logging

import pytest

from backend.contracts.base import BaseArtifact
from backend.contracts.registry import ArtifactRegistry
from backend.runtime.replay_store import RuntimeReplayStore, get_replay_store, runtime_replay_store


def test_get_replay_store_returns_the_module_singleton():
    assert get_replay_store() is runtime_replay_store


def test_replay_store_tail_aliases_recent():
    store = RuntimeReplayStore(db_path=":memory:")
    from backend.pubsub.broker import EventEnvelope
    store.append(EventEnvelope(event_id="e1", type="x", ts=1.0, source="t", payload={"a": 1}))
    store.append(EventEnvelope(event_id="e2", type="x", ts=2.0, source="t", payload={"a": 2}))

    tailed = store.tail(10)
    recent = store.recent(10)
    assert [e["event_id"] for e in tailed] == [e["event_id"] for e in recent]
    assert len(tailed) == 2


def test_artifact_registry_register_and_hydrate_from_replay_round_trip(monkeypatch):
    from backend.runtime.replay_store import RuntimeReplayStore
    import backend.runtime.replay_store as replay_store_module

    fresh_store = RuntimeReplayStore(db_path=":memory:")
    monkeypatch.setattr(replay_store_module, "runtime_replay_store", fresh_store)
    monkeypatch.setattr(replay_store_module, "get_replay_store", lambda: fresh_store)

    registry = ArtifactRegistry()
    artifact = BaseArtifact(artifact_type="base", workspace="ws-hydration-test")
    registry.register(artifact)

    restored = ArtifactRegistry()
    count = restored.hydrate_from_replay()
    assert count >= 1
    assert restored.get(artifact.artifact_id) is not None
    assert restored.get(artifact.artifact_id).workspace == "ws-hydration-test"


def test_hydrate_from_replay_logs_warning_when_truncated(monkeypatch, caplog):
    def fake_tail(n, *args, **kwargs):
        return [{"payload": {"artifact_id": f"a-{i}", "artifact_type": "base"},
                  "type": "artifact.base.registered"} for i in range(n)]

    monkeypatch.setattr("backend.events.log.tail", fake_tail)

    registry = ArtifactRegistry()
    with caplog.at_level(logging.WARNING):
        count = registry.hydrate_from_replay(limit=3)

    assert count == 3
    assert any("hydration_may_be_truncated" in r.message for r in caplog.records)


def test_hydrate_from_replay_no_warning_when_under_limit(monkeypatch, caplog):
    def fake_tail(n, *args, **kwargs):
        return [{"payload": {"artifact_id": "a-1", "artifact_type": "base"},
                  "type": "artifact.base.registered"}]

    monkeypatch.setattr("backend.events.log.tail", fake_tail)

    registry = ArtifactRegistry()
    with caplog.at_level(logging.WARNING):
        registry.hydrate_from_replay(limit=5000)

    assert not any("hydration_may_be_truncated" in r.message for r in caplog.records)


def test_hydrate_from_replay_respects_artifact_replay_limit_env(monkeypatch):
    monkeypatch.setenv("ARTIFACT_REPLAY_LIMIT", "42")
    import importlib
    import backend.contracts.registry as registry_module
    importlib.reload(registry_module)
    try:
        assert registry_module._DEFAULT_REPLAY_LIMIT == 42
    finally:
        monkeypatch.delenv("ARTIFACT_REPLAY_LIMIT", raising=False)
        importlib.reload(registry_module)

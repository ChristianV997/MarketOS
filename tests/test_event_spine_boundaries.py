"""Boundary tests for the canonical event spine.

Scope: backend/contracts/events.py (canonical envelope), backend/events/
repository.py (append-only repository foundation), and backend/events/
adapters/legacy.py (read-only legacy importers) — the target destination
named in ARCHITECTURE_CONTRACT.md's event-spine migration entry.

This file does not duplicate tests/contracts/test_architecture_boundaries.py
(which already enforces the single-`event_store`-module rule and the
finite legacy-appender allowlist for the *old* event_store.py/log.py
surfaces). It targets the *new* canonical Event/EventRepository surface
instead: schema validation, append-only behavior, and that no second
class shaped like EventRepository has been introduced elsewhere.
"""
from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest

from backend.contracts.events import Event, InvalidCanonicalEvent
from backend.events.adapters.legacy import LegacyRuntimeReplayAdapter, LegacyWorkflowEventStoreAdapter
from backend.events.repository import EventRepository, InMemoryEventRepository, JsonlEventRepository

ROOT = Path(__file__).resolve().parent.parent


def _event(**overrides) -> Event:
    fields = {
        "event_id": "evt-1",
        "workspace_id": "ws-1",
        "aggregate_type": "experiment",
        "aggregate_id": "exp-1",
        "event_type": "experiment.created",
        "schema_version": 1,
        "occurred_at": 1_700_000_000.0,
        "source": "test",
    }
    fields.update(overrides)
    return Event(**fields)


# --- Canonical event schema validation -------------------------------------

def test_canonical_event_rejects_missing_required_fields():
    with pytest.raises(InvalidCanonicalEvent):
        _event(event_id="")
    with pytest.raises(InvalidCanonicalEvent):
        _event(aggregate_type="   ")
    with pytest.raises(InvalidCanonicalEvent):
        _event(source="")


def test_canonical_event_rejects_invalid_schema_version():
    with pytest.raises(InvalidCanonicalEvent):
        _event(schema_version=0)
    with pytest.raises(InvalidCanonicalEvent):
        _event(schema_version=-1)


def test_canonical_event_rejects_non_finite_occurred_at():
    with pytest.raises(InvalidCanonicalEvent):
        _event(occurred_at=math.inf)
    with pytest.raises(InvalidCanonicalEvent):
        _event(occurred_at=math.nan)


def test_canonical_event_rejects_non_dict_payload_or_metadata():
    with pytest.raises(InvalidCanonicalEvent):
        _event(payload=["not", "a", "dict"])
    with pytest.raises(InvalidCanonicalEvent):
        _event(metadata="also not a dict")


def test_canonical_event_json_safe_sanitizes_non_finite_payload_values():
    event = _event(payload={"score": math.inf, "ratio": math.nan, "count": 3})
    assert event.payload["score"] is None
    assert event.payload["ratio"] is None
    assert event.payload["count"] == 3


def test_canonical_event_from_dict_round_trip_is_lossless():
    original = _event(payload={"a": 1}, metadata={"b": 2})
    restored = Event.from_dict(original.to_dict())
    assert restored == original
    assert restored.replay_hash() == original.replay_hash()


def test_canonical_event_from_dict_rejects_non_dict_input():
    with pytest.raises(InvalidCanonicalEvent):
        Event.from_dict("not a dict")


def test_canonical_event_replay_hash_is_deterministic():
    a = _event()
    b = _event()
    assert a.replay_hash() == b.replay_hash()
    c = _event(event_id="evt-2")
    assert c.replay_hash() != a.replay_hash()


# --- Append-only event repository behavior ----------------------------------

def test_event_repository_protocol_exposes_no_mutation_methods():
    """EventRepository must stay append-only: no update/delete/remove."""
    protocol_methods = {name for name in vars(EventRepository) if not name.startswith("_")}
    assert protocol_methods == {"append", "append_many", "get", "stream", "replay", "tail"}
    for concrete in (InMemoryEventRepository, JsonlEventRepository):
        for forbidden in ("update", "delete", "remove", "overwrite", "truncate"):
            assert not hasattr(concrete, forbidden), f"{concrete.__name__} must not expose {forbidden}()"


def test_event_repository_append_is_idempotent_by_event_id():
    repo = InMemoryEventRepository()
    first = repo.append(_event())
    second = repo.append(_event())
    assert first.appended is True
    assert second.appended is False
    assert second.idempotent is True
    assert len(list(repo.stream())) == 1


def test_event_repository_preserves_append_order():
    repo = InMemoryEventRepository()
    repo.append(_event(event_id="evt-a", occurred_at=100.0))
    repo.append(_event(event_id="evt-b", occurred_at=50.0))
    repo.append(_event(event_id="evt-c", occurred_at=200.0))
    assert [item.event_id for item in repo.stream()] == ["evt-a", "evt-b", "evt-c"]
    assert [item.event_id for item in repo.tail(2)] == ["evt-b", "evt-c"]


def test_event_repository_get_returns_none_for_unknown_id():
    repo = InMemoryEventRepository()
    repo.append(_event())
    assert repo.get("does-not-exist") is None


def test_event_repository_replay_filters_by_occurred_at_window():
    repo = InMemoryEventRepository()
    repo.append(_event(event_id="evt-a", occurred_at=100.0))
    repo.append(_event(event_id="evt-b", occurred_at=200.0))
    repo.append(_event(event_id="evt-c", occurred_at=300.0))
    windowed = repo.replay(since=150.0, until=250.0)
    assert [item.event_id for item in windowed] == ["evt-b"]


def test_jsonl_repository_skips_malformed_lines_on_load(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(
        _event(event_id="evt-good").canonical_json() + "\n"
        + "not json at all\n"
        + '{"event_id": "evt-missing-fields"}\n',
        encoding="utf-8",
    )
    repo = JsonlEventRepository(path)
    assert [item.event_id for item in repo.stream()] == ["evt-good"]


def test_jsonl_repository_append_persists_and_reloads(tmp_path):
    path = tmp_path / "events.jsonl"
    repo = JsonlEventRepository(path)
    repo.append(_event(event_id="evt-x"))
    reloaded = JsonlEventRepository(path)
    assert [item.event_id for item in reloaded.stream()] == ["evt-x"]


# --- Legacy importer read-only behavior --------------------------------------

class _FakeWorkflowStore:
    def _iter_events(self):
        return iter([{"workflow_id": "wf-1", "event": "step.done", "event_id": "wf-evt-1", "ts": 1.0, "data": {}}])


class _FakeReplayStore:
    def tail(self, n, event_type=None):
        return [{"event_id": "replay-1", "ts": 2.0, "type": "runtime.step", "payload": {}}]


def test_legacy_workflow_adapter_is_marked_read_only():
    assert LegacyWorkflowEventStoreAdapter.read_only is True
    assert LegacyRuntimeReplayAdapter.read_only is True


def test_legacy_workflow_adapter_append_is_rejected():
    adapter = LegacyWorkflowEventStoreAdapter(store=_FakeWorkflowStore())
    with pytest.raises(NotImplementedError):
        adapter.append(_event())


def test_legacy_runtime_adapter_append_is_rejected():
    adapter = LegacyRuntimeReplayAdapter(store=_FakeReplayStore())
    with pytest.raises(NotImplementedError):
        adapter.append(_event())


def test_legacy_workflow_adapter_stream_normalizes_into_canonical_events():
    adapter = LegacyWorkflowEventStoreAdapter(store=_FakeWorkflowStore())
    events = adapter.stream(limit=10)
    assert len(events) == 1
    assert isinstance(events[0], Event)
    assert events[0].source == "legacy.workflow_event_store"


def test_legacy_runtime_adapter_tail_normalizes_into_canonical_events():
    adapter = LegacyRuntimeReplayAdapter(store=_FakeReplayStore())
    events = adapter.tail(10)
    assert len(events) == 1
    assert isinstance(events[0], Event)
    assert events[0].source == "legacy.runtime_replay"


# --- Rejection of a second event-store authority ----------------------------

def test_only_backend_events_repository_defines_a_class_named_event_repository():
    """Complementary to test_event_store_locations_and_legacy_appenders_are_
    controlled (which governs the legacy event_store.py/eventstore.py naming
    pattern): this guards the *new* canonical EventRepository class name
    itself against a second, competing definition anywhere in production
    code."""
    ignored = {".git", ".venv", ".venv312", "venv", "env", "node_modules", "__pycache__", "build", "dist", "artifacts", "state", "htmlcov", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    offenders = []
    for root_name in ("api", "backend", "core", "marketos", "orchestrator", "services"):
        root = ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in ignored for part in path.relative_to(ROOT).parts):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == "EventRepository":
                    offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == ["backend/events/repository.py"], (
        f"exactly one EventRepository class is allowed; found: {offenders}"
    )

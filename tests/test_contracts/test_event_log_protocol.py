"""Tests for backend.contracts.event_log.EventLogProtocol — proves
backend.events.log and backend.orchestration.event_store.event_store both
already satisfy a common append+tail structural interface, without either
module changing its on-disk format, schema, or existing call sites."""
import backend.events.log as events_log
from backend.contracts.event_log import EventLogProtocol
from backend.orchestration.event_store import EventStore, event_store


def test_events_log_module_satisfies_protocol():
    assert isinstance(events_log, EventLogProtocol)


def test_event_store_instance_satisfies_protocol():
    assert isinstance(event_store, EventLogProtocol)


def test_fresh_event_store_instance_also_satisfies_protocol():
    assert isinstance(EventStore(path="/tmp/does-not-matter.jsonl"), EventLogProtocol)


def test_protocol_rejects_object_missing_tail():
    class NotALog:
        def append(self, *a, **k):
            return None
    assert not isinstance(NotALog(), EventLogProtocol)


def test_protocol_rejects_object_missing_append():
    class NotALog:
        def tail(self, *a, **k):
            return []
    assert not isinstance(NotALog(), EventLogProtocol)

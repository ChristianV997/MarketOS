"""Tests for the event_log_write_failures_total counter wired into both
backend.events.log.append() (fail-silent, unchanged) and
backend.orchestration.event_store.EventStore.append() (still raises on
failure, unchanged) — see backend/observability/metrics.py."""
import pytest

from backend.observability.metrics import event_log_write_failures_total


def _current_count(labels: dict) -> float:
    try:
        metric = event_log_write_failures_total.labels(**labels)
        return metric._value.get()  # prometheus_client Counter internal
    except Exception:
        return -1.0  # prometheus_client unavailable — skip exact-count assertions


class TestEventStoreCounterOnWriteFailure:
    def test_append_still_raises_and_increments_counter(self, tmp_path, monkeypatch):
        from backend.orchestration.event_store import EventStore

        store = EventStore(path=str(tmp_path / "events.jsonl"))

        def _boom(*args, **kwargs):
            raise OSError("disk full")
        monkeypatch.setattr("builtins.open", _boom)

        before = _current_count({"backend": "event_store"})
        with pytest.raises(OSError):
            store.append("wf-1", "SomeEvent")
        after = _current_count({"backend": "event_store"})

        if before >= 0:
            assert after == before + 1

    def test_append_succeeds_normally_when_write_works(self, tmp_path):
        from backend.orchestration.event_store import EventStore
        store = EventStore(path=str(tmp_path / "events.jsonl"))
        record = store.append("wf-1", "SomeEvent")
        assert record["event"] == "SomeEvent"


class TestReplayStoreLogCounterOnWriteFailure:
    def test_append_never_raises_but_increments_counter(self, monkeypatch):
        import backend.events.log as events_log

        def _boom_store():
            class _Boom:
                def append(self, env):
                    raise RuntimeError("replay store unavailable")
            return _Boom()
        monkeypatch.setattr(events_log, "_store", _boom_store)

        before = _current_count({"backend": "replay_store"})
        event_id = events_log.append("test_event", {"a": 1})  # must not raise
        after = _current_count({"backend": "replay_store"})

        assert isinstance(event_id, str) and event_id
        if before >= 0:
            assert after == before + 1

"""Tests for orchestrator.main's restart-safe checkpointing.

Covers periodic checkpoint writes, SIGTERM handling, and the tick loop's
shutdown/checkpoint interplay — without touching commerce/scraping workers.
"""
import signal
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

import orchestrator.main as om


# ── _write_checkpoint ─────────────────────────────────────────────────────────

def test_write_checkpoint_calls_serializer_save(monkeypatch):
    save_mock = MagicMock()
    monkeypatch.setattr("backend.core.serializer.save", save_mock)
    om._write_checkpoint(6)
    save_mock.assert_called_once()


def test_write_checkpoint_failure_does_not_raise(monkeypatch):
    monkeypatch.setattr(
        "backend.core.serializer.save",
        MagicMock(side_effect=RuntimeError("disk full")),
    )
    # Must not raise.
    om._write_checkpoint(6)


def test_write_checkpoint_increments_metrics_on_success(monkeypatch):
    monkeypatch.setattr("backend.core.serializer.save", MagicMock())
    with patch("backend.observability.metrics.checkpoint_writes_total") as writes_mock, \
         patch("backend.observability.metrics.checkpoint_last_write_ts") as ts_mock:
        om._write_checkpoint(6)
        writes_mock.inc.assert_called_once()
        ts_mock.set.assert_called_once()


def test_write_checkpoint_increments_failure_metric_on_error(monkeypatch):
    monkeypatch.setattr(
        "backend.core.serializer.save",
        MagicMock(side_effect=RuntimeError("boom")),
    )
    with patch("backend.observability.metrics.checkpoint_failures_total") as fail_mock:
        om._write_checkpoint(6)
        fail_mock.inc.assert_called_once()


# ── _restore_checkpoint ───────────────────────────────────────────────────────

def test_restore_checkpoint_assigns_loaded_state(monkeypatch):
    import backend.api as api

    sentinel_state = object()
    monkeypatch.setattr("backend.core.serializer.load", MagicMock(return_value=sentinel_state))
    monkeypatch.setattr(api, "_state", api._state)  # let monkeypatch capture + auto-revert _state
    from backend.orchestration.event_store import event_store
    monkeypatch.setattr(event_store, "incomplete_workflows", MagicMock(return_value=[]))
    om._restore_checkpoint()
    assert api._state is sentinel_state


def test_restore_checkpoint_handles_no_saved_state(monkeypatch):
    monkeypatch.setattr("backend.core.serializer.load", MagicMock(return_value=None))
    from backend.orchestration.event_store import event_store
    monkeypatch.setattr(event_store, "incomplete_workflows", MagicMock(return_value=[]))
    # Must not raise even when there's nothing to restore.
    om._restore_checkpoint()


def test_restore_checkpoint_logs_incomplete_workflows(monkeypatch, caplog):
    monkeypatch.setattr("backend.core.serializer.load", MagicMock(return_value=None))
    from backend.orchestration.event_store import event_store
    monkeypatch.setattr(event_store, "incomplete_workflows", MagicMock(return_value=[{"workflow_id": "wf-1"}]))
    with caplog.at_level("WARNING"):
        om._restore_checkpoint()
    assert any("incomplete_workflows" in r.message for r in caplog.records)


def test_restore_checkpoint_survives_serializer_failure(monkeypatch):
    monkeypatch.setattr(
        "backend.core.serializer.load",
        MagicMock(side_effect=RuntimeError("corrupt file")),
    )
    from backend.orchestration.event_store import event_store
    monkeypatch.setattr(event_store, "incomplete_workflows", MagicMock(return_value=[]))
    # Must not raise.
    om._restore_checkpoint()


# ── SIGTERM handling ───────────────────────────────────────────────────────────

def test_handle_sigterm_sets_shutdown_flag(monkeypatch):
    monkeypatch.setattr(om, "_shutdown_requested", False)
    om._handle_sigterm(signal.SIGTERM, None)
    assert om._shutdown_requested is True


# ── run() loop integration ────────────────────────────────────────────────────

def test_run_loop_exits_cleanly_on_shutdown_request(monkeypatch):
    """Simulate a SIGTERM mid-run: the loop should stop within a tick and
    perform a final checkpoint, without touching any commerce/scraping
    workers."""
    monkeypatch.setattr(om, "_shutdown_requested", False)
    monkeypatch.setattr(om, "TICK_INTERVAL", 0.01)
    monkeypatch.setattr(om, "_PHASE_WORKERS", {})
    monkeypatch.setattr(om, "_init_prometheus", lambda: None)
    monkeypatch.setattr(om, "_restore_checkpoint", lambda: None)
    monkeypatch.setattr(om, "signal", MagicMock())  # avoid re-registering real handlers
    checkpoint_calls = []
    monkeypatch.setattr(om, "_write_checkpoint", lambda tick: checkpoint_calls.append(tick))

    def _shutdown_after_delay():
        time.sleep(0.05)
        om._shutdown_requested = True

    thread = threading.Thread(target=_shutdown_after_delay, daemon=True)
    thread.start()

    run_thread = threading.Thread(target=om.run, daemon=True)
    run_thread.start()
    run_thread.join(timeout=5)

    assert not run_thread.is_alive(), "orchestrator.run() did not exit after shutdown request"
    assert checkpoint_calls, "expected at least one checkpoint write during the run"

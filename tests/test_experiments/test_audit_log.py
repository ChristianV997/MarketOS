"""Tests for backend.experiments.audit_log."""
from backend.experiments.audit_log import log_transition, transitions_for
from backend.experiments.envelope import CommercialRunEnvelope
from backend.orchestration.event_store import event_store


def test_log_transition_appends_ref_and_event():
    env = CommercialRunEnvelope(service_name="product_research", workspace_id="ws-1")
    wid = log_transition(env, "experiment_created")

    assert wid in env.audit_log_refs
    events = event_store.events_for(wid)
    assert any(e["event"] == "experiment_created" for e in events)
    assert events[0]["data"]["experiment_id"] == env.experiment_id
    assert events[0]["data"]["workspace_id"] == "ws-1"


def test_transitions_for_recovers_all_logged_events():
    env = CommercialRunEnvelope(service_name="product_research", workspace_id="ws-1")
    log_transition(env, "experiment_created")
    env.mark_running()
    log_transition(env, "experiment_running")
    env.mark_completed({"ok": True})
    log_transition(env, "experiment_completed")

    events = transitions_for(env)
    event_names = [e["event"] for e in events]
    assert "experiment_created" in event_names
    assert "experiment_running" in event_names
    assert "experiment_completed" in event_names


def test_log_transition_never_raises_when_event_store_append_fails(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("disk full")
    monkeypatch.setattr(event_store, "append", _boom)

    env = CommercialRunEnvelope(service_name="x", workspace_id="ws-1")
    wid = log_transition(env, "experiment_created")  # must not raise

    assert isinstance(wid, str) and wid
    assert wid not in env.audit_log_refs  # failed write never gets recorded as a ref


def test_transitions_for_never_raises_on_missing_refs():
    env = CommercialRunEnvelope(service_name="x", workspace_id="ws-1")
    env.audit_log_refs.append("nonexistent_workflow_id")
    assert transitions_for(env) == []

"""Tests for backend.experiments.envelope.CommercialRunEnvelope."""
import json

from backend.experiments.envelope import ARTIFACT_TYPE, CommercialRunEnvelope


def test_serializes_to_json_safe_dict():
    env = CommercialRunEnvelope(service_name="product_research", workspace_id="ws-1")
    d = env.to_dict()
    json.dumps(d)  # must not raise
    assert d["artifact_type"] == ARTIFACT_TYPE
    assert d["experiment_id"] == env.artifact_id
    assert d["workspace_id"] == "ws-1"
    assert d["status"] == "created"


def test_workspace_field_defaults_to_workspace_id():
    env = CommercialRunEnvelope(service_name="x", workspace_id="ws-42")
    assert env.workspace == "ws-42"


def test_mark_running_sets_status_and_started_at():
    env = CommercialRunEnvelope(service_name="x", workspace_id="ws-1")
    assert env.started_at is None
    env.mark_running()
    assert env.status == "running"
    assert env.started_at is not None


def test_mark_completed_sets_status_outputs_finished_at():
    env = CommercialRunEnvelope(service_name="x", workspace_id="ws-1")
    env.mark_running()
    env.mark_completed({"result": "ok"})
    assert env.status == "completed"
    assert env.outputs == {"result": "ok"}
    assert env.finished_at is not None


def test_mark_blocked_sets_status_and_reasons():
    env = CommercialRunEnvelope(service_name="x", workspace_id="ws-1")
    env.mark_blocked(["no credentials"])
    assert env.status == "blocked"
    assert env.blocked_reasons == ["no credentials"]
    assert env.finished_at is not None


def test_from_dict_round_trip_preserves_domain_fields():
    env = CommercialRunEnvelope(service_name="unit_economics", workspace_id="ws-9", proposed_spend=42.0)
    env.mark_running()
    restored = CommercialRunEnvelope.from_dict(env.to_dict())
    assert restored.to_dict() == env.to_dict()
    assert isinstance(restored, CommercialRunEnvelope)


def test_two_envelopes_get_distinct_experiment_ids():
    a = CommercialRunEnvelope(service_name="x", workspace_id="ws-1")
    b = CommercialRunEnvelope(service_name="x", workspace_id="ws-1")
    assert a.experiment_id != b.experiment_id

import math
import pytest
from backend.contracts.events import Event, InvalidCanonicalEvent

def _event(**changes):
    data=dict(event_id="event-1",workspace_id="workspace",aggregate_type="workflow",aggregate_id="wf-1",event_type="workflow.started",schema_version=1,occurred_at=10.5,source="test",payload={"value":float("nan")},metadata={})
    data.update(changes);return Event(**data)

def test_round_trip_is_json_safe_and_deterministic():
    event=_event(); restored=Event.from_dict(event.to_dict())
    assert restored==event and event.payload["value"] is None
    assert event.canonical_json()==restored.canonical_json()
    assert event.replay_hash()==restored.replay_hash()

def test_required_fields_and_timestamps_are_validated():
    with pytest.raises(InvalidCanonicalEvent): _event(event_type="")
    with pytest.raises(InvalidCanonicalEvent): _event(occurred_at=math.inf)

def test_legacy_workflow_and_pubsub_compatibility_helpers():
    workflow=Event.from_workflow_record({"workflow_id":"wf-1","event":"step_completed","ts":1,"workflow":"demo","step":"x","data":{"ok":True}})
    assert workflow.aggregate_id=="wf-1" and workflow.metadata["legacy_record"] is True
    from backend.pubsub.broker import EventEnvelope
    pubsub=Event.from_pubsub_envelope(EventEnvelope("p1","tick",2,"broker",{"workspace_id":"w","a":1}))
    assert pubsub.workspace_id=="w" and pubsub.payload=={"a":1}

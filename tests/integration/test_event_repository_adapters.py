from backend.contracts.events import Event
from backend.events.adapters.legacy import LegacyRuntimeReplayAdapter,LegacyWorkflowEventStoreAdapter
from backend.events.repository import JsonlEventRepository

def _event(i): return Event(f"e{i}",None,"workflow",f"wf{i}","step",1,float(i),source="test",payload={"i":i})

def test_jsonl_round_trip_order_and_torn_line(tmp_path):
    path=tmp_path/"events.jsonl"; repo=JsonlEventRepository(path);repo.append_many([_event(1),_event(2)])
    with path.open("a",encoding="utf-8") as handle: handle.write('{"broken"')
    loaded=JsonlEventRepository(path)
    assert [x.event_id for x in loaded.stream()]==["e1","e2"]
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3

def test_legacy_workflow_adapter_normalizes_without_writing():
    class Store:
        def _iter_events(self): return iter([{"workflow_id":"wf","event":"workflow_started","ts":1,"data":{"safe":True}}])
    adapter=LegacyWorkflowEventStoreAdapter(Store());event=adapter.stream()[0]
    assert event.aggregate_type=="workflow" and adapter.read_only

def test_legacy_replay_adapter_normalizes_without_external_service():
    class Store:
        def tail(self,n,event_type=None): return [{"event_id":"r1","type":"tick","ts":1,"source":"test","payload":"{\"x\": 1}"}]
    event=LegacyRuntimeReplayAdapter(Store()).tail()[0]
    assert event.payload=={"x":1}

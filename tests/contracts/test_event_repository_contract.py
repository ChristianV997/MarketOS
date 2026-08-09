from backend.contracts.events import Event
from backend.events.repository import InMemoryEventRepository

def _event(i, ts=None): return Event(f"e-{i}","w","test","a",f"type-{i%2}",1,float(i if ts is None else ts),source="test",payload={"i":i})

def test_in_memory_append_get_tail_stream_and_replay_are_deterministic():
    repo=InMemoryEventRepository(); results=repo.append_many([_event(1),_event(2),_event(3)])
    assert [x.appended for x in results]==[True,True,True]
    assert repo.append(_event(2)).idempotent is True
    assert repo.get("e-2").payload["i"]==2
    assert [x.event_id for x in repo.tail(2)]==["e-2","e-3"]
    assert [x.event_id for x in repo.stream(event_type="type-1")]==["e-1","e-3"]
    assert [x.event_id for x in repo.replay(since=2,until=2)]==["e-2"]

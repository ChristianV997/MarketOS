"""Tests for backend.orchestration.event_store's in-process index — the
perf fix behind backend.ledger.projections no longer re-scanning the
whole event log on every call."""
import uuid

from backend.orchestration.event_store import EventStore


def test_events_of_type_returns_same_result_as_before_indexing(tmp_path):
    store = EventStore(path=str(tmp_path / "events.jsonl"))
    store.append("wf-1", "OrderCreated", data={"workspace_id": "ws-a", "order_id": "o-1"})
    store.append("wf-2", "OrderCreated", data={"workspace_id": "ws-b", "order_id": "o-2"})
    store.append("wf-3", "PaymentCaptured", data={"workspace_id": "ws-a", "order_id": "o-1"})

    all_orders = store.events_of_type("OrderCreated")
    assert len(all_orders) == 2
    assert {e["data"]["order_id"] for e in all_orders} == {"o-1", "o-2"}


def test_events_of_type_workspace_filter():
    store = EventStore()
    ws = f"ws-index-{uuid.uuid4().hex[:8]}"
    store.append("wf-a", "OrderCreated", data={"workspace_id": ws, "order_id": "o-1"})
    store.append("wf-b", "OrderCreated", data={"workspace_id": "some-other-ws", "order_id": "o-2"})

    scoped = store.events_of_type("OrderCreated", workspace_id=ws)
    assert len(scoped) == 1
    assert scoped[0]["data"]["order_id"] == "o-1"


def test_index_picks_up_new_appends_without_rebuild(tmp_path):
    store = EventStore(path=str(tmp_path / "events.jsonl"))
    store.append("wf-1", "OrderCreated", data={"workspace_id": "ws-a"})
    first = store.events_of_type("OrderCreated")
    assert len(first) == 1

    store.append("wf-2", "OrderCreated", data={"workspace_id": "ws-a"})
    second = store.events_of_type("OrderCreated")
    assert len(second) == 2


def test_index_rebuilds_when_file_changed_by_another_writer(tmp_path):
    path = str(tmp_path / "events.jsonl")
    store = EventStore(path=path)
    store.append("wf-1", "OrderCreated", data={"workspace_id": "ws-a"})
    store.events_of_type("OrderCreated")  # build the index

    # Simulate a second process appending directly to the file.
    other = EventStore(path=path)
    other.append("wf-2", "OrderCreated", data={"workspace_id": "ws-b"})

    # The first store's index must notice the file changed and rebuild.
    refreshed = store.events_of_type("OrderCreated")
    assert len(refreshed) == 2


def test_events_of_type_limit_still_works(tmp_path):
    store = EventStore(path=str(tmp_path / "events.jsonl"))
    for i in range(5):
        store.append(f"wf-{i}", "OrderCreated", data={"workspace_id": "ws-a", "n": i})

    last_two = store.events_of_type("OrderCreated", limit=2)
    assert [e["data"]["n"] for e in last_two] == [3, 4]

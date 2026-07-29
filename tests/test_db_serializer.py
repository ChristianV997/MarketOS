"""Tests for DuckDB state persistence."""
import os
import random
import tempfile
import pytest

from backend.core.state import SystemState
from backend.execution.loop import run_cycle
from backend.core.db_serializer import save, load, query


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_state.db")


def _run_n(n=15):
    # The simulated environment is intentionally stochastic, but serializer
    # assertions should not depend on a random run producing a high-ROAS row.
    random_state = random.getstate()
    random.seed(0)
    try:
        state = SystemState()
        for _ in range(n):
            state = run_cycle(state)
        return state
    finally:
        random.setstate(random_state)


def test_save_creates_file(db_path):
    state = _run_n(5)
    save(state, db_path)
    assert os.path.exists(db_path)
    assert os.path.getsize(db_path) > 0


def test_roundtrip_scalar_fields(db_path):
    state = _run_n(10)
    save(state, db_path)

    loaded = load(db_path)
    assert loaded is not None
    assert loaded.total_cycles == state.total_cycles
    assert abs(loaded.capital - state.capital) < 0.01
    assert loaded.detected_regime == state.detected_regime


def test_roundtrip_event_log(db_path):
    state = _run_n(15)
    n_events = len(state.event_log.rows)
    save(state, db_path)

    loaded = load(db_path)
    assert len(loaded.event_log.rows) == n_events
    # Key fields present
    assert "roas" in loaded.event_log.rows[0]


def test_event_log_append_only(db_path):
    """Second save appends only new events — no duplicates."""
    state = _run_n(10)
    save(state, db_path)
    first_db_count = len(query(db_path, "SELECT * FROM event_log"))
    assert first_db_count == len(state.event_log.rows)

    events_before = len(state.event_log.rows)
    for _ in range(5):
        state = run_cycle(state)
    new_events = len(state.event_log.rows) - events_before

    save(state, db_path)
    second_db_count = len(query(db_path, "SELECT * FROM event_log"))

    assert second_db_count == first_db_count + new_events


def test_roundtrip_graph_edges(db_path):
    state = _run_n(20)
    save(state, db_path)

    loaded = load(db_path)
    assert len(loaded.graph.edges) == len(state.graph.edges)
    for (p, c), w in state.graph.edges.items():
        assert abs(loaded.graph.edges[(p, c)] - w) < 1e-6


def test_roundtrip_memory(db_path):
    state = _run_n(15)
    save(state, db_path)

    loaded = load(db_path)
    assert len(loaded.memory) == len(state.memory)


def test_load_nonexistent_returns_none(db_path):
    result = load(db_path)
    assert result is None


def test_query_helper(db_path):
    state = _run_n(12)
    save(state, db_path)

    rows = query(db_path, "SELECT roas FROM event_log WHERE roas > 0.5")
    assert len(rows) > 0
    assert all(r[0] > 0.5 for r in rows)


def test_serializer_router_uses_db(db_path):
    """serializer.save/load routes .db extension to DuckDB."""
    from backend.core.serializer import save as s_save, load as s_load
    state = _run_n(5)
    s_save(state, db_path)
    loaded = s_load(db_path)
    assert loaded is not None
    assert loaded.total_cycles == state.total_cycles


def test_serializer_router_uses_json(tmp_path):
    """serializer.save/load routes .json extension to legacy JSON."""
    import json as _json
    from backend.core.serializer import save as s_save, load as s_load

    json_path = str(tmp_path / "state.json")
    state = _run_n(5)
    s_save(state, json_path)

    assert os.path.exists(json_path)
    with open(json_path) as f:
        d = _json.load(f)
    assert "capital" in d

    loaded = s_load(json_path)
    assert loaded is not None
    assert loaded.total_cycles == state.total_cycles

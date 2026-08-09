"""Tests for hierarchical memory (episodic, semantic, procedural)."""
import time
import pytest

from backend.memory.episodic   import EpisodicStore, Episode
from backend.memory.semantic   import SemanticStore, SemanticUnit
from backend.memory.procedural import ProceduralStore, Procedure


# ── EpisodicStore ─────────────────────────────────────────────────────────────

def test_episodic_record_and_tail():
    store = EpisodicStore()
    store.record_event("decision.logged", {"product": "earbuds", "roas": 2.1})
    episodes = store.tail(10)
    assert len(episodes) == 1
    assert episodes[0].event_type == "decision.logged"


def test_episodic_count():
    store = EpisodicStore()
    assert store.count() == 0
    store.record_event("test.event", {})
    assert store.count() == 1


def test_episodic_by_type():
    store = EpisodicStore()
    store.record_event("type_a", {"x": 1})
    store.record_event("type_a", {"x": 2})
    store.record_event("type_b", {"y": 3})
    assert len(store.by_type("type_a")) == 2
    assert len(store.by_type("type_b")) == 1
    assert len(store.by_type("type_c")) == 0


def test_episodic_by_workspace():
    store = EpisodicStore()
    store.record_event("ev", {}, workspace="prod")
    store.record_event("ev", {}, workspace="prod")
    store.record_event("ev", {}, workspace="test")
    assert len(store.by_workspace("prod")) == 2
    assert len(store.by_workspace("test")) == 1


def test_episodic_window(monkeypatch):
    import backend.memory.episodic.store as store_mod

    store = EpisodicStore()
    t0 = time.time()
    monkeypatch.setattr(store_mod.time, "time", lambda: t0)
    store.record_event("early", {})
    t1 = t0 + 0.01
    monkeypatch.setattr(store_mod.time, "time", lambda: t1)
    store.record_event("late", {})
    window = store.window(t0, t1)
    assert all(t0 <= e.ts <= t1 for e in window)


def test_episodic_maxsize():
    store = EpisodicStore(max_episodes=3)
    for i in range(5):
        store.record_event(f"ev_{i}", {})
    # deque maxlen enforces the cap
    assert store.count() == 3


def test_episodic_record_returns_id():
    store = EpisodicStore()
    eid   = store.record_event("test", {"key": "value"})
    assert isinstance(eid, str)
    assert len(eid) == 12


# ── SemanticStore ─────────────────────────────────────────────────────────────

def test_semantic_upsert_and_get():
    store = SemanticStore()
    unit  = SemanticUnit(
        unit_id="u1", label="morning_hooks", domain="hook",
        embedding=[0.1] * 384, cluster_members=["hook A", "hook B"], score=0.8,
    )
    store.upsert(unit)
    retrieved = store.get_by_label("hook", "morning_hooks")
    assert retrieved is not None
    assert retrieved.score == 0.8


def test_semantic_domain_units():
    store = SemanticStore()
    store.upsert(SemanticUnit("u2", "cluster_a", "hook",   [], []))
    store.upsert(SemanticUnit("u3", "cluster_b", "hook",   [], []))
    store.upsert(SemanticUnit("u4", "cluster_c", "signal", [], []))
    assert len(store.domain_units("hook"))   == 2
    assert len(store.domain_units("signal")) == 1


def test_semantic_top_by_score():
    store = SemanticStore()
    for i, score in enumerate([0.3, 0.9, 0.6, 0.1]):
        store.upsert(SemanticUnit(f"su{i}", f"unit_{i}", "hook", [], [], score=score))
    top = store.top_by_score("hook", k=2)
    assert top[0].score >= top[1].score
    assert top[0].score == 0.9


def test_semantic_generation():
    store = SemanticStore()
    assert store.generation() == 0
    g = store.bump_generation()
    assert g == 1
    assert store.generation() == 1


def test_semantic_count():
    store = SemanticStore()
    assert store.count() == 0
    store.upsert(SemanticUnit("s1", "x", "hook", [], []))
    assert store.count() == 1
    assert store.count("hook") == 1
    assert store.count("angle") == 0


def test_semantic_snapshot():
    store = SemanticStore()
    store.upsert(SemanticUnit("snap1", "snap_unit", "angle", [0.5] * 4, []))
    snap = store.snapshot()
    assert "generation" in snap
    assert "angle" in snap["domains"]


# ── ProceduralStore ───────────────────────────────────────────────────────────

def test_procedural_create_and_get():
    store = ProceduralStore()
    proc  = store.create(
        name="scale_campaign",
        domain="campaign",
        steps=[{"action": "launch"}, {"action": "monitor"}],
        avg_roas=2.5,
    )
    retrieved = store.get(proc.procedure_id)
    assert retrieved is not None
    assert retrieved.name == "scale_campaign"


def test_procedural_success_rate():
    store = ProceduralStore()
    proc  = store.create("test_proc", "campaign", [])
    assert proc.success_rate == 0.0
    store.record_outcome(proc.procedure_id, success=True,  roas=3.0)
    store.record_outcome(proc.procedure_id, success=True,  roas=4.0)
    store.record_outcome(proc.procedure_id, success=False, roas=0.0)
    assert abs(proc.success_rate - 2/3) < 1e-6


def test_procedural_best_for_domain():
    store = ProceduralStore()
    low   = store.create("low",  "campaign", [], avg_roas=0.5)
    high  = store.create("high", "campaign", [], avg_roas=4.0)
    store.record_outcome(low.procedure_id,  success=True)
    store.record_outcome(high.procedure_id, success=True)
    best = store.best_for_domain("campaign", k=1)
    assert best[0].procedure_id == high.procedure_id


def test_procedural_count():
    store = ProceduralStore()
    assert store.count() == 0
    store.create("p1", "campaign", [])
    store.create("p2", "signal",   [])
    assert store.count() == 2
    assert store.count("campaign") == 1


def test_procedural_snapshot():
    store = ProceduralStore()
    store.create("snap_proc", "workflow", [{"step": "execute"}])
    snap = store.snapshot()
    assert isinstance(snap, list)
    assert any(p["name"] == "snap_proc" for p in snap)

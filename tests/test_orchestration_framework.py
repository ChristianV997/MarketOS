"""Tests for backend.orchestration — workflow engine, health state machine,
event store, rate mesh, transaction coordinator, and platform adapter.

Covers the five failure scenarios the framework exists to solve:
  1. cross-platform partial failure (atomic rollback vs best-effort keep)
  2. circuit breaker skips a failing platform, recovers via half-open probe
  3. throttle on one platform triggers peer backoff, not thundering herd
  4. dependency DAG stops stale-data cascade (skip downstream on failure)
  5. crash mid-workflow is visible via incomplete_workflows() + replayable
"""
from __future__ import annotations

import threading

import pytest

from backend.orchestration.event_store import EventStore, new_workflow_id
from backend.orchestration.state_machine import (
    HealthState, PlatformHealth, HealthRegistry)
from backend.orchestration.workflow import Step, Workflow
from backend.orchestration.transaction import LaunchTransaction
from backend.orchestration.rate_mesh import RateMesh
import importlib

adapter_mod = importlib.import_module("backend.orchestration.adapter")
rate_mesh_mod = importlib.import_module("backend.orchestration.rate_mesh")
sm_mod = importlib.import_module("backend.orchestration.state_machine")
tx_mod = importlib.import_module("backend.orchestration.transaction")
from backend.orchestration.adapter import PlatformAdapter
from backend.patterns.errors import RetryableError


@pytest.fixture()
def store(tmp_path):
    return EventStore(path=str(tmp_path / "events.jsonl"))


@pytest.fixture(autouse=True)
def _fresh_health(monkeypatch):
    """Isolate the process-wide health registry per test."""
    reg = HealthRegistry()
    monkeypatch.setattr(sm_mod, "health_registry", reg)
    monkeypatch.setattr(tx_mod, "health_registry", reg)
    monkeypatch.setattr(rate_mesh_mod, "health_registry", reg)
    monkeypatch.setattr(adapter_mod, "health_registry", reg)
    yield reg


# ─────────────────────────────────────────────────────────────────────────────
# State machine / circuit breaker
# ─────────────────────────────────────────────────────────────────────────────


class TestPlatformHealth:
    def test_starts_healthy(self):
        h = PlatformHealth("meta")
        assert h.state == HealthState.HEALTHY
        assert h.allow_request()

    def test_degrades_then_opens_circuit(self):
        h = PlatformHealth("meta", failure_threshold=3)
        h.record_failure(Exception("boom"))
        assert h.state == HealthState.DEGRADED
        h.record_failure(Exception("boom"))
        h.record_failure(Exception("boom"))
        assert h.state == HealthState.FAILED
        assert not h.allow_request()

    def test_success_resets(self):
        h = PlatformHealth("meta", failure_threshold=3)
        h.record_failure(Exception("x"))
        h.record_success()
        assert h.state == HealthState.HEALTHY

    def test_rate_limit_classified(self):
        h = PlatformHealth("meta")

        class E(Exception):
            status = 429
        h.record_failure(E("too many"))
        assert h.state == HealthState.RATE_LIMITED
        assert not h.allow_request()

    def test_rate_limit_cooldown_reopens(self):
        h = PlatformHealth("meta", rate_limit_cooldown_s=0.0)
        h.record_failure(Exception("429 too many requests"))
        assert h.allow_request()          # cooldown of 0 → immediately allowed
        assert h.state == HealthState.DEGRADED

    def test_half_open_probe_success_closes(self):
        h = PlatformHealth("meta", failure_threshold=1, open_cooldown_s=0.0)
        h.record_failure(Exception("fatal"))
        assert h.state == HealthState.FAILED
        assert h.allow_request()          # cooldown elapsed → half-open probe
        assert h.state == HealthState.RECOVERING
        h.record_success()
        assert h.state == HealthState.HEALTHY

    def test_half_open_probe_failure_reopens(self):
        h = PlatformHealth("meta", failure_threshold=1, open_cooldown_s=0.0)
        h.record_failure(Exception("fatal"))
        h.allow_request()                 # half-open
        h.record_failure(Exception("still down"))
        assert h.state == HealthState.FAILED


# ─────────────────────────────────────────────────────────────────────────────
# Event store
# ─────────────────────────────────────────────────────────────────────────────


class TestEventStore:
    def test_append_and_read_back(self, store):
        wid = new_workflow_id()
        store.append(wid, "workflow_started", workflow="t")
        store.append(wid, "workflow_completed", workflow="t")
        events = store.events_for(wid)
        assert [e["event"] for e in events] == [
            "workflow_started", "workflow_completed"]

    def test_incomplete_workflow_detected(self, store):
        done = new_workflow_id()
        store.append(done, "workflow_started", workflow="a")
        store.append(done, "workflow_completed", workflow="a")
        crashed = new_workflow_id()
        store.append(crashed, "workflow_started", workflow="b")
        store.append(crashed, "step_completed", workflow="b", step="s1")
        # process "dies" here — no terminal event

        incomplete = store.incomplete_workflows()
        assert [w["workflow_id"] for w in incomplete] == [crashed]
        assert incomplete[0]["completed_steps"] == ["s1"]

    def test_torn_tail_line_ignored(self, store):
        wid = new_workflow_id()
        store.append(wid, "workflow_started", workflow="t")
        with open(store.path, "a") as fh:
            fh.write('{"ts": 1, "workflow_id": "torn", "ev')   # crash mid-write
        assert store.events_for(wid)          # earlier events still readable
        assert store.events_for("torn") == []

    def test_find_launch_event_pairs_prediction(self, store):
        wid = new_workflow_id()
        store.append(wid, "step_completed", workflow="launch", step="launch_tiktok",
                     data={"output": {"campaign_id": "camp_42",
                                      "predicted_roas": 1.8}})
        ev = store.find_launch_event("camp_42")
        assert ev is not None
        assert ev["data"]["output"]["predicted_roas"] == 1.8
        assert store.find_launch_event("nope") is None


# ─────────────────────────────────────────────────────────────────────────────
# Workflow engine + DAG
# ─────────────────────────────────────────────────────────────────────────────


class TestWorkflow:
    def test_happy_path_threads_context(self, store):
        wf = Workflow("t", [
            Step("a", lambda ctx: 2),
            Step("b", lambda ctx: ctx["a"] * 10, depends_on=("a",)),
        ], store=store)
        res = wf.run()
        assert res.status == "ok"
        assert res.steps["b"].output == 20

    def test_dependency_failure_skips_downstream(self, store):
        """Gap 4: stale-data cascade — downstream must NOT run."""
        ran = []

        def boom(ctx):
            raise RuntimeError("metrics down")

        wf = Workflow("t", [
            Step("fetch_metrics", boom, required=False, fallback=None),
            Step("scale", lambda ctx: ran.append(1) or "scaled",
                 depends_on=("fetch_metrics",), required=False),
        ], store=store)
        res = wf.run()
        assert res.status == "ok"                 # both optional
        assert ran == []                          # scale never executed
        assert res.steps["scale"].status == "skipped"
        assert "dependency_fetch_metrics_failed" in res.steps["scale"].reason

    def test_required_failure_fails_workflow_and_compensates(self, store):
        undone = []
        wf = Workflow("t", [
            Step("a", lambda ctx: "resource",
                 compensate=lambda ctx, out: undone.append(out)),
            Step("b", lambda ctx: (_ for _ in ()).throw(RuntimeError("no"))),
        ], store=store)
        res = wf.run()
        assert res.status == "failed"
        assert undone == ["resource"]
        assert res.compensated == ["a"]
        events = [e["event"] for e in store.events_for(res.workflow_id)]
        assert "step_compensated" in events
        assert events[-1] == "workflow_failed"

    def test_validation_gate_skips(self, store):
        wf = Workflow("t", [
            Step("a", lambda ctx: {"fresh": False}),
            Step("b", lambda ctx: "ran", depends_on=("a",), required=False,
                 validate=lambda ctx: ctx["a"]["fresh"]),
        ], store=store)
        res = wf.run()
        assert res.steps["b"].status == "skipped"
        assert res.steps["b"].reason == "validation_failed"

    def test_forward_dependency_rejected(self, store):
        with pytest.raises(ValueError):
            Workflow("t", [Step("a", lambda ctx: 1, depends_on=("b",)),
                           Step("b", lambda ctx: 2)], store=store)

    def test_every_run_reaches_terminal_event(self, store):
        wf = Workflow("t", [Step("a", lambda ctx: 1)], store=store)
        res = wf.run()
        assert store.incomplete_workflows() == []
        last = store.events_for(res.workflow_id)[-1]
        assert last["event"] == "workflow_completed"


# ─────────────────────────────────────────────────────────────────────────────
# Rate mesh
# ─────────────────────────────────────────────────────────────────────────────


class TestRateMesh:
    def test_throttle_blocks_platform(self):
        mesh = RateMesh(base_penalty_s=60.0, global_brake_s=0.0)
        mesh.throttle("meta")
        assert not mesh.acquire("meta")

    def test_throttle_penalty_grows_exponentially(self):
        mesh = RateMesh(base_penalty_s=5.0, global_brake_s=0.0)
        mesh.throttle("meta")
        first = mesh.status()["penalties_s"]["meta"]
        mesh.throttle("meta")
        second = mesh.status()["penalties_s"]["meta"]
        assert second > first

    def test_sibling_platform_still_allowed_after_brake(self):
        mesh = RateMesh(base_penalty_s=60.0, global_brake_s=0.0)
        mesh.throttle("meta")
        assert mesh.acquire("tiktok")     # brief brake at most; never blocked

    def test_circuit_open_blocks_via_mesh(self, _fresh_health):
        mesh = RateMesh()
        h = _fresh_health.get("meta")
        for _ in range(h.failure_threshold):
            h.record_failure(Exception("down"))
        assert not mesh.acquire("meta")


# ─────────────────────────────────────────────────────────────────────────────
# Platform adapter
# ─────────────────────────────────────────────────────────────────────────────


class _FakeClient:
    def __init__(self, fail_with: Exception | None = None):
        self.fail_with = fail_with
        self.calls = []

    def create_campaign(self, **kw):
        self.calls.append(kw)
        if self.fail_with:
            raise self.fail_with
        return "camp_1"


class TestPlatformAdapter:
    def test_success_records_health(self, _fresh_health):
        a = PlatformAdapter("fake", _FakeClient())
        assert a.call("create_campaign", name="x") == "camp_1"
        assert _fresh_health.get("fake").status()["total_successes"] == 1

    def test_throttled_error_notifies_mesh(self, _fresh_health, monkeypatch):
        throttled = []
        monkeypatch.setattr(adapter_mod.rate_mesh, "throttle",
                            lambda p: throttled.append(p))

        class E(Exception):
            status = 429
        a = PlatformAdapter("fake", _FakeClient(fail_with=E("slow down")))
        with pytest.raises(E):
            a.call("create_campaign", name="x")
        assert throttled == ["fake"]

    def test_open_circuit_raises_retryable(self, _fresh_health):
        h = _fresh_health.get("fake")
        for _ in range(h.failure_threshold):
            h.record_failure(Exception("down"))
        a = PlatformAdapter("fake", _FakeClient())
        with pytest.raises(RetryableError):
            a.call("create_campaign", name="x")
        assert a.client.calls == []       # client never touched


# ─────────────────────────────────────────────────────────────────────────────
# Launch transaction
# ─────────────────────────────────────────────────────────────────────────────


def _mk_launcher(status="live", campaign_id="c1", budget=None):
    def launch(product, page_url, b, copy):
        res = {"platform": None, "status": status, "campaign_id": campaign_id,
               "budget": budget if budget is not None else b}
        return res
    return launch


BUILD = {"product": "widget", "page": {"url": "https://x"}, "ad_copy": {}}


class TestLaunchTransaction:
    def _tx(self, store, monkeypatch, launchers, pausers=None, atomic=False):
        monkeypatch.setattr(
            "backend.orchestration.transaction.event_store", store)
        return LaunchTransaction(atomic=atomic, launchers=launchers,
                                 pausers=pausers or {})

    def test_both_live(self, store, monkeypatch):
        tx = self._tx(store, monkeypatch, {
            "tiktok": _mk_launcher(campaign_id="tt1"),
            "meta": _mk_launcher(campaign_id="m1"),
        })
        res = tx.execute(BUILD, budget_daily=100)
        assert res.status == "ok"
        assert res.total_budget == pytest.approx(100.0)
        assert store.incomplete_workflows() == []

    def test_partial_best_effort_keeps_winner(self, store, monkeypatch):
        """Gap 1, default semantics: TikTok live + Meta failed → keep TikTok."""
        tx = self._tx(store, monkeypatch, {
            "tiktok": _mk_launcher(campaign_id="tt1"),
            "meta": _mk_launcher(status="error", campaign_id=""),
        })
        res = tx.execute(BUILD)
        assert res.status == "partial"
        assert res.compensated == []

    def test_partial_atomic_pauses_winner(self, store, monkeypatch):
        """Gap 1, atomic semantics: sibling failure pauses the live campaign."""
        paused = []
        tx = self._tx(store, monkeypatch, {
            "tiktok": _mk_launcher(campaign_id="tt1"),
            "meta": _mk_launcher(status="error", campaign_id=""),
        }, pausers={"tiktok": lambda cid: paused.append(cid) or True},
           atomic=True)
        res = tx.execute(BUILD)
        assert res.status == "failed"
        assert paused == ["tt1"]
        assert res.compensated == ["tt1"]
        events = [e["event"] for e in store.events_for(res.workflow_id)]
        assert "step_compensated" in events

    def test_unhealthy_platform_budget_reallocated(self, store, monkeypatch,
                                                   _fresh_health):
        """Gap 2: unhealthy Meta is skipped, its budget flows to TikTok."""
        h = _fresh_health.get("meta")
        for _ in range(h.failure_threshold):
            h.record_failure(Exception("down"))

        seen = {}

        def launcher(product, page_url, b, copy):
            seen["budget"] = b
            return {"platform": "tiktok", "status": "live",
                    "campaign_id": "tt1", "budget": b}

        tx = self._tx(store, monkeypatch,
                      {"tiktok": launcher, "meta": _mk_launcher()})
        res = tx.execute(BUILD, budget_daily=100)
        assert res.status == "partial"
        assert res.skipped_platforms == ["meta"]
        assert seen["budget"] == pytest.approx(100.0)   # full budget, not 55

    def test_atomic_fails_fast_on_unhealthy(self, store, monkeypatch,
                                            _fresh_health):
        h = _fresh_health.get("meta")
        for _ in range(h.failure_threshold):
            h.record_failure(Exception("down"))
        called = []
        tx = self._tx(store, monkeypatch, {
            "tiktok": lambda *a: called.append(1),
            "meta": _mk_launcher(),
        }, atomic=True)
        res = tx.execute(BUILD)
        assert res.status == "failed"
        assert called == []                # no money moved

    def test_all_failed(self, store, monkeypatch):
        tx = self._tx(store, monkeypatch, {
            "tiktok": _mk_launcher(status="error"),
            "meta": _mk_launcher(status="error"),
        })
        res = tx.execute(BUILD)
        assert res.status == "failed"
        last = store.events_for(res.workflow_id)[-1]
        assert last["event"] == "workflow_failed"

    def test_launcher_exception_contained(self, store, monkeypatch):
        def boom(*a):
            raise RuntimeError("api exploded")
        tx = self._tx(store, monkeypatch, {
            "tiktok": boom, "meta": _mk_launcher(campaign_id="m1")})
        res = tx.execute(BUILD)
        assert res.status == "partial"

    def test_concurrent_transactions_serialized(self, store, monkeypatch):
        """Isolation: two threads launching at once never interleave phases."""
        order = []
        lock_probe = threading.Lock()

        def launcher(product, page_url, b, copy):
            with lock_probe:
                order.append("start")
            with lock_probe:
                order.append("end")
            return {"platform": "tiktok", "status": "live",
                    "campaign_id": "x", "budget": b}

        tx = self._tx(store, monkeypatch, {"tiktok": launcher})
        threads = [threading.Thread(
            target=lambda: tx.execute(BUILD, platforms=("tiktok",)))
            for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert order == ["start", "end", "start", "end"]


# ─────────────────────────────────────────────────────────────────────────────
# launch_product_tx wrapper
# ─────────────────────────────────────────────────────────────────────────────


class TestLaunchProductTx:
    def test_dry_run_end_to_end(self, monkeypatch, tmp_path):
        """Full path through real (dry-run) integration clients."""
        monkeypatch.setenv("TIKTOK_DRY_RUN", "true")
        monkeypatch.setenv("META_DRY_RUN", "true")
        store = EventStore(path=str(tmp_path / "e2e.jsonl"))
        monkeypatch.setattr(
            "backend.orchestration.transaction.event_store", store)

        from backend.launch.orchestrator import launch_product_tx
        res = launch_product_tx(BUILD, budget_daily=50)
        assert res["status"] == "ok"
        assert res["live_count"] == 2
        assert res["workflow_id"].startswith("launch_tx")
        assert store.incomplete_workflows() == []

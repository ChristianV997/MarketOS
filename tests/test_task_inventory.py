"""Tests for backend.runtime.task_inventory."""
import time


def test_registry_has_all_kinds():
    from backend.runtime.task_inventory import task_registry
    tasks = task_registry.all()
    kinds = {t["kind"] for t in tasks}
    assert "thread" in kinds
    assert "loop" in kinds
    assert "scheduler" in kinds
    assert "ws" in kinds
    assert "queue" in kinds
    assert "state_writer" in kinds


def test_registry_covers_key_tasks():
    from backend.runtime.task_inventory import task_registry
    names = {t["name"] for t in task_registry.all()}
    expected = {
        "background_runner",
        "research_runner",
        "orchestrator_tick",
        "signal_ingestion_worker",
        "execution_cycle_worker",
        "feedback_collection_worker",
        "scaling_worker",
        "ingestion_scheduler",
        "redis_stream_upos_events",
        "ws_event_stream",
        "sw_event_log",
        "sw_serializer_duckdb",
        "sw_decision_trace",
        "sw_pattern_store",
        "sw_playbook_memory",
    }
    assert expected.issubset(names), f"Missing: {expected - names}"


def test_heartbeat_updates_timestamp():
    from backend.runtime.task_inventory import task_registry
    before = time.time()
    task_registry.heartbeat("background_runner", status="ok")
    tasks = {t["name"]: t for t in task_registry.all()}
    rec = tasks["background_runner"]
    assert rec["last_run_ts"] >= before
    assert rec["last_status"] == "ok"
    assert rec["run_count"] >= 1


def test_heartbeat_auto_creates_unknown_task():
    from backend.runtime.task_inventory import TaskRegistry
    reg = TaskRegistry()
    reg.heartbeat("auto_task", status="ok")
    names = {t["name"] for t in reg.all()}
    assert "auto_task" in names


def test_active_flag_true_after_heartbeat():
    from backend.runtime.task_inventory import TaskRegistry
    reg = TaskRegistry()
    reg.register("myloop", kind="loop", description="test", interval_s=60)
    reg.heartbeat("myloop")
    rec = next(t for t in reg.all() if t["name"] == "myloop")
    assert rec["active"] is True


def test_active_flag_false_before_heartbeat():
    from backend.runtime.task_inventory import TaskRegistry
    reg = TaskRegistry()
    reg.register("coldloop", kind="loop", description="test", interval_s=60)
    rec = next(t for t in reg.all() if t["name"] == "coldloop")
    assert rec["active"] is False


def test_configured_false_when_env_missing():
    from backend.runtime.task_inventory import TaskRegistry
    import os
    reg = TaskRegistry()
    reg.register("guarded", kind="scheduler", description="test", env_required="FAKE_ENV_XYZ_NEVER_SET")
    rec = next(t for t in reg.all() if t["name"] == "guarded")
    assert rec["configured"] is False


def test_configured_true_when_no_env_required():
    from backend.runtime.task_inventory import TaskRegistry
    reg = TaskRegistry()
    reg.register("free", kind="thread", description="test")
    rec = next(t for t in reg.all() if t["name"] == "free")
    assert rec["configured"] is True


def test_summary_shape():
    from backend.runtime.task_inventory import task_registry
    s = task_registry.summary()
    assert "total" in s
    assert "active" in s
    assert "by_kind" in s
    assert s["total"] >= 15


def test_to_stream_type():
    from backend.runtime.task_inventory import task_registry
    snap = task_registry.to_stream()
    assert snap["type"] == "task_inventory"
    assert "tasks" in snap
    assert "summary" in snap


def test_live_threads_returns_list():
    from backend.runtime.task_inventory import task_registry
    threads = task_registry.live_threads()
    assert isinstance(threads, list)


def test_next_run_ts_computed():
    from backend.runtime.task_inventory import TaskRegistry
    reg = TaskRegistry()
    reg.register("timer", kind="loop", description="test", interval_s=30)
    reg.heartbeat("timer")
    rec = next(t for t in reg.all() if t["name"] == "timer")
    assert rec["next_run_ts"] is not None
    assert rec["next_run_ts"] > rec["last_run_ts"]

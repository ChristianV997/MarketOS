from datetime import datetime, timezone

from backend.jobs.runner import JobRegistry
from backend.jobs.scheduler import IngestionScheduler


def test_scheduler_triggers_registered_job_on_tick():
    calls = []
    registry = JobRegistry(max_retries=0)
    registry.register("ingestion", lambda: calls.append("ran"))

    scheduler = IngestionScheduler(registry, cron="0 * * * *", feature_flag="true")
    now = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)

    result = scheduler.tick(now=now)

    assert len(result) == 1
    assert calls == ["ran"]


def test_scheduler_respects_feature_flag_but_allows_manual_trigger():
    calls = []
    registry = JobRegistry(max_retries=0)
    registry.register("ingestion", lambda: calls.append("ran"))

    scheduler = IngestionScheduler(registry, cron="0 * * * *", feature_flag="false")
    now = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)

    assert scheduler.tick(now=now) == []
    assert scheduler.trigger_now(now=now)
    assert calls == ["ran"]


def test_retry_only_for_retryable_errors(monkeypatch):
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("backend.jobs.runner.time.sleep", fake_sleep)

    retry_attempts = {"count": 0}

    def flaky_job():
        retry_attempts["count"] += 1
        if retry_attempts["count"] < 3:
            raise TimeoutError("network timeout")

    registry = JobRegistry(max_retries=3)
    registry.register("flaky", flaky_job)
    success = registry.run("flaky")

    assert success["status"] == "succeeded"
    assert retry_attempts["count"] == 3
    assert sleeps == [1, 2]

    auth_attempts = {"count": 0}

    def auth_job():
        auth_attempts["count"] += 1
        raise ValueError("auth failed")

    registry.register("auth", auth_job)
    failed = registry.run("auth")

    assert failed["status"] == "failed"
    assert auth_attempts["count"] == 1


def test_idempotency_guard_blocks_duplicate_runs_in_same_window():
    calls = {"count": 0}

    def job():
        calls["count"] += 1

    registry = JobRegistry(max_retries=0)
    registry.register("ingestion", job)

    now = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    first = registry.run("ingestion", now=now, window="hour")
    second = registry.run("ingestion", now=now, window="hour")

    assert first["status"] == "succeeded"
    assert second["status"] == "succeeded"
    assert second["skipped"] is True
    assert calls["count"] == 1


def test_job_result_structure_for_success_and_failure():
    registry = JobRegistry(max_retries=0)
    registry.register("ok", lambda: None)

    def fail_job():
        raise ValueError("validation failed")

    registry.register("bad", fail_job)

    success = registry.run("ok")
    failed = registry.run("bad")

    expected_keys = {"job", "status", "startedAt", "endedAt", "durationMs", "retryCount", "idempotencyKey"}

    assert expected_keys.issubset(success.keys())
    assert success["status"] == "succeeded"

    assert expected_keys.issubset(failed.keys())
    assert failed["status"] == "failed"
    assert failed["error"] == "validation failed"


def test_job_result_preserves_structured_handler_payload():
    registry = JobRegistry(max_retries=0)
    registry.register("research.sources.v1", lambda: {"status": "partial", "sources": {"reddit": "failed"}})

    result = registry.run("research.sources.v1")

    assert result["status"] == "succeeded"
    assert result["payload"]["status"] == "partial"
    assert result["payload"]["sources"]["reddit"] == "failed"

import time

import pytest

from backend.jobs.runner import JobRegistry
from backend.research import (
    EvidenceEnvelope,
    SwarmJobSpec,
    SwarmJobStore,
    SwarmRunner,
    SwarmValidationError,
    TrendRecordStore,
    canonical_json,
    sha256_json,
    swarm_readiness,
)
from backend.research.swarm import register_swarm_job


def _spec(**overrides):
    values = {
        "query": "compare research tools",
        "objective": "collect attributable market evidence",
        "runtime": "hermes",
        "sources": ("agent_reach",),
        "job_id": "job-1",
    }
    values.update(overrides)
    return SwarmJobSpec.create(**values)


def _payload(spec, *, records=None):
    return {
        "schema": "MarketOS.ResearchEvidence.v1",
        "job_id": spec.job_id,
        "runtime": spec.runtime,
        "status": "succeeded",
        "records": records or [{
            "evidence_id": "ev-1",
            "topic": "research tools",
            "intent": "research",
            "velocity": 0.4,
            "competition": None,
            "source": "agent_reach",
            "freshness_ts": "2026-08-02T00:00:00+00:00",
            "confidence": 0.8,
            "raw": {"title": "Research tools"},
            "source_url": "https://example.com/research-tools",
            "retrieved_at": "2026-08-02T00:00:00+00:00",
            "provider": "agent-reach",
        }],
        "rejected": [],
        "telemetry": {"fixture": True},
    }


def test_canonical_hash_is_stable_and_rejects_nonfinite_values():
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert sha256_json({"a": 2, "b": 1}) == sha256_json({"b": 1, "a": 2})
    with pytest.raises(SwarmValidationError):
        canonical_json({"value": float("nan")})


def test_job_spec_rejects_unknown_runtime_and_sensor():
    with pytest.raises(SwarmValidationError):
        _spec(runtime="unknown")
    with pytest.raises(SwarmValidationError):
        _spec(sources=("unknown",))
    with pytest.raises(SwarmValidationError):
        _spec(dry_run=False)


def test_envelope_requires_attributable_finite_evidence():
    spec = _spec()
    envelope = EvidenceEnvelope.from_mapping(_payload(spec), spec)
    assert envelope.envelope_hash == sha256_json(envelope.to_dict())
    assert envelope.records[0].to_research_record(job_id=spec.job_id, runtime=spec.runtime)["raw"]["_marketos_evidence"]["source_url"] == "https://example.com/research-tools"

    invalid = _payload(spec)
    invalid["records"][0]["source_url"] = "not-a-url"
    with pytest.raises(SwarmValidationError):
        EvidenceEnvelope.from_mapping(invalid, spec)

    invalid = _payload(spec)
    invalid["records"][0]["content_sha256"] = "0" * 64
    with pytest.raises(SwarmValidationError):
        EvidenceEnvelope.from_mapping(invalid, spec)

    allowlisted = _spec(dry_run=False, allowed_domains=("example.com",))
    assert EvidenceEnvelope.from_mapping(_payload(allowlisted), allowlisted).records
    invalid = _payload(allowlisted)
    invalid["records"][0]["source_url"] = "https://other.example/research-tools"
    with pytest.raises(SwarmValidationError):
        EvidenceEnvelope.from_mapping(invalid, allowlisted)


def test_job_store_is_idempotent_and_claims_once(tmp_path):
    store = SwarmJobStore(path=str(tmp_path / "research.db"))
    spec = _spec()
    first = store.enqueue(spec)
    second = store.enqueue(spec)
    assert first["job_id"] == second["job_id"]
    assert len(store.claim_pending()) == 1
    assert store.claim_pending() == []
    assert store.get(spec.job_id)["status"] == "running"


def test_runner_validates_then_persists_typed_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("FF_RESEARCH_SWARM_ENABLED", "true")
    monkeypatch.setenv("FF_RESEARCH_SWARM_HERMES", "true")
    monkeypatch.setenv("FF_RESEARCH_SENSOR_AGENT_REACH", "true")
    db = str(tmp_path / "research.db")
    job_store = SwarmJobStore(path=db)
    trend_store = TrendRecordStore(path=db)
    spec = _spec()
    job_store.enqueue(spec)

    runner = SwarmRunner(
        job_store=job_store,
        trend_store=trend_store,
        runtimes={"hermes": lambda payload: _payload(spec)},
    )
    result = runner.run_pending()
    assert result["status"] == "succeeded"
    assert result["completed"] == 1
    stored = trend_store.findTopN(1)[0]
    assert stored["source"] == "agent_reach"
    assert stored["raw"]["_marketos_evidence"]["job_id"] == spec.job_id
    assert job_store.get(spec.job_id)["status"] == "succeeded"
    public = job_store.list_public(1)[0]
    assert public["result"]["record_count"] == 1
    assert "research tools" not in str(public)


def test_runner_fails_closed_when_runtime_or_sensor_flag_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("FF_RESEARCH_SWARM_ENABLED", "true")
    monkeypatch.setenv("FF_RESEARCH_SWARM_HERMES", "true")
    monkeypatch.delenv("FF_RESEARCH_SENSOR_AGENT_REACH", raising=False)
    db = str(tmp_path / "research.db")
    jobs = SwarmJobStore(path=db)
    trend = TrendRecordStore(path=db)
    spec = _spec()
    jobs.enqueue(spec)
    runner = SwarmRunner(job_store=jobs, trend_store=trend, runtimes={"hermes": lambda _: _payload(spec)})
    result = runner.run_pending()
    assert result["status"] == "failed"
    assert jobs.get(spec.job_id)["error_type"] == "validation_error"
    assert trend.findTopN(1) == []


def test_runner_timeout_is_recorded_and_does_not_persist(tmp_path, monkeypatch):
    monkeypatch.setenv("FF_RESEARCH_SWARM_ENABLED", "true")
    monkeypatch.setenv("FF_RESEARCH_SWARM_HERMES", "true")
    monkeypatch.setenv("FF_RESEARCH_SENSOR_AGENT_REACH", "true")
    db = str(tmp_path / "research.db")
    jobs = SwarmJobStore(path=db)
    trend = TrendRecordStore(path=db)
    spec = _spec(max_duration_s=0.01)
    jobs.enqueue(spec)

    def slow(_):
        time.sleep(0.1)
        return _payload(spec)

    result = SwarmRunner(job_store=jobs, trend_store=trend, runtimes={"hermes": slow}).run_pending()
    assert result["failed"] == 1
    assert jobs.get(spec.job_id)["error_type"] == "timeout"
    assert trend.findTopN(1) == []


def test_disabled_scheduler_job_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.delenv("FF_RESEARCH_SWARM_ENABLED", raising=False)
    db = str(tmp_path / "research.db")
    registry = JobRegistry(max_retries=0)
    register_swarm_job(registry, job_store=SwarmJobStore(path=db), trend_store=TrendRecordStore(path=db))
    result = registry.run("research.swarm.v1")
    assert result["status"] == "succeeded"
    assert result["payload"]["status"] == "skipped"


def test_readiness_is_safe_and_reports_unregistered_runtimes(monkeypatch):
    monkeypatch.setenv("FF_RESEARCH_SWARM_ENABLED", "true")
    monkeypatch.setenv("FF_RESEARCH_SWARM_HERMES", "true")
    payload = swarm_readiness(runtime_names=())
    hermes = next(item for item in payload["runtimes"] if item["name"] == "hermes")
    assert hermes["status"] == "unavailable"
    assert hermes["runner_registered"] is False
    assert "credential" not in str(payload).lower()

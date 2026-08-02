"""Governed research-swarm jobs and typed evidence envelopes.

The module deliberately contains no third-party agent dependency. Runtimes are
registered by an adapter/sidecar and must return the versioned envelope shape
validated here before evidence can reach the canonical research store.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import sqlite3
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.parse import urlparse

from backend.research.trend_store import TrendRecordStore, validate_research_record
from backend.research import metrics as research_metrics

logger = logging.getLogger(__name__)

SCHEMA = "MarketOS.ResearchEvidence.v1"
RUNTIME_NAMES = ("hermes", "deerflow")
SENSOR_NAMES = ("agent_reach", "exa")
_TRUE = {"1", "true", "yes", "on"}


class SwarmValidationError(ValueError):
    """Raised when a job or evidence envelope cannot be accepted safely."""


def _flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in _TRUE


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as err:
        raise SwarmValidationError(f"value is not finite JSON: {err}") from err


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _bounded_string(value: Any, field_name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise SwarmValidationError(f"{field_name} must be a non-empty string of at most {maximum} characters")
    return value.strip()


@dataclass(frozen=True)
class SwarmJobSpec:
    job_id: str
    query: str
    objective: str
    runtime: str
    sources: tuple[str, ...] = ()
    max_duration_s: float = 60.0
    max_records: int = 50
    max_bytes: int = 512_000
    allowed_domains: tuple[str, ...] = ()
    dry_run: bool = True
    requested_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def create(
        cls,
        *,
        query: str,
        objective: str,
        runtime: str,
        job_id: str | None = None,
        sources: Sequence[str] = (),
        max_duration_s: float | None = None,
        max_records: int | None = None,
        max_bytes: int | None = None,
        allowed_domains: Sequence[str] = (),
        dry_run: bool = True,
    ) -> "SwarmJobSpec":
        spec = cls(
            job_id=job_id or str(uuid.uuid4()),
            query=query,
            objective=objective,
            runtime=runtime,
            sources=tuple(sources),
            max_duration_s=max_duration_s if max_duration_s is not None else _float_env("RESEARCH_SWARM_MAX_DURATION_SECONDS", 60.0),
            max_records=max_records if max_records is not None else _int_env("RESEARCH_SWARM_MAX_RECORDS", 50),
            max_bytes=max_bytes if max_bytes is not None else _int_env("RESEARCH_SWARM_MAX_BYTES", 512_000),
            allowed_domains=tuple(allowed_domains),
            dry_run=dry_run,
        )
        spec.validate()
        return spec

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SwarmJobSpec":
        spec = cls(
            job_id=str(payload.get("job_id", "")),
            query=payload.get("query", ""),
            objective=payload.get("objective", ""),
            runtime=payload.get("runtime", ""),
            sources=tuple(payload.get("sources") or ()),
            max_duration_s=payload.get("max_duration_s", 60.0),
            max_records=payload.get("max_records", 50),
            max_bytes=payload.get("max_bytes", 512_000),
            allowed_domains=tuple(payload.get("allowed_domains") or ()),
            dry_run=bool(payload.get("dry_run", True)),
            requested_at=str(payload.get("requested_at") or datetime.now(timezone.utc).isoformat()),
        )
        spec.validate()
        return spec

    def validate(self) -> None:
        _bounded_string(self.job_id, "job_id", 128)
        _bounded_string(self.query, "query", 2_000)
        _bounded_string(self.objective, "objective", 2_000)
        if self.runtime not in RUNTIME_NAMES:
            raise SwarmValidationError(f"runtime must be one of {RUNTIME_NAMES}")
        if not self.sources:
            raise SwarmValidationError("at least one research sensor is required")
        unknown = sorted(set(self.sources) - set(SENSOR_NAMES))
        if unknown:
            raise SwarmValidationError(f"unknown research sensors: {unknown}")
        if len(set(self.sources)) != len(self.sources):
            raise SwarmValidationError("sources must not contain duplicates")
        if not isinstance(self.dry_run, bool):
            raise SwarmValidationError("dry_run must be boolean")
        if isinstance(self.max_duration_s, bool) or not math.isfinite(float(self.max_duration_s)) or not 0.001 <= float(self.max_duration_s) <= 900:
            raise SwarmValidationError("max_duration_s must be finite and between 0.001 and 900")
        if isinstance(self.max_records, bool) or not 1 <= int(self.max_records) <= 1_000:
            raise SwarmValidationError("max_records must be between 1 and 1000")
        if isinstance(self.max_bytes, bool) or not 1_024 <= int(self.max_bytes) <= 10_000_000:
            raise SwarmValidationError("max_bytes must be between 1024 and 10000000")
        if not self.dry_run and not self.allowed_domains:
            raise SwarmValidationError("live jobs require an explicit allowed_domains list")
        for domain in self.allowed_domains:
            _bounded_string(domain, "allowed_domains item", 253)
            if "/" in domain or " " in domain:
                raise SwarmValidationError("allowed domains must be hostnames, not URLs")
        try:
            datetime.fromisoformat(self.requested_at.replace("Z", "+00:00"))
        except ValueError as err:
            raise SwarmValidationError("requested_at must be an ISO timestamp") from err

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "query": self.query,
            "objective": self.objective,
            "runtime": self.runtime,
            "sources": list(self.sources),
            "max_duration_s": float(self.max_duration_s),
            "max_records": int(self.max_records),
            "max_bytes": int(self.max_bytes),
            "allowed_domains": list(self.allowed_domains),
            "dry_run": self.dry_run,
            "requested_at": self.requested_at,
        }


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    topic: str
    intent: str
    velocity: float
    competition: float | None
    source: str
    freshness_ts: str
    confidence: float
    raw: dict[str, Any]
    source_url: str
    retrieved_at: str
    provider: str
    content_sha256: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any], *, runtime: str) -> "EvidenceRecord":
        raw = payload.get("raw")
        if not isinstance(raw, dict):
            raise SwarmValidationError("evidence.raw must be an object")
        source_url = _bounded_string(payload.get("source_url"), "source_url", 2_048)
        parsed = urlparse(source_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise SwarmValidationError("source_url must be an http(s) URL")
        retrieved_at = _bounded_string(payload.get("retrieved_at"), "retrieved_at", 80)
        try:
            datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
        except ValueError as err:
            raise SwarmValidationError("retrieved_at must be an ISO timestamp") from err
        provider = _bounded_string(payload.get("provider", runtime), "provider", 120)
        evidence_id = _bounded_string(payload.get("evidence_id") or sha256_json({"url": source_url, "raw": raw}), "evidence_id", 128)
        computed_hash = sha256_json(raw)
        supplied_hash = payload.get("content_sha256")
        if supplied_hash is not None and str(supplied_hash) != computed_hash:
            raise SwarmValidationError("content_sha256 does not match evidence.raw")
        record = cls(
            evidence_id=evidence_id,
            topic=payload.get("topic", ""),
            intent=payload.get("intent", "unknown"),
            velocity=payload.get("velocity", 0.0),
            competition=payload.get("competition"),
            source=payload.get("source", ""),
            freshness_ts=payload.get("freshness_ts", retrieved_at),
            confidence=payload.get("confidence", 0.0),
            raw=raw,
            source_url=source_url,
            retrieved_at=retrieved_at,
            provider=provider,
            content_sha256=computed_hash,
        )
        record.validate(runtime=runtime)
        return record

    def validate(self, *, runtime: str) -> None:
        canonical = {
            "topic": self.topic,
            "intent": self.intent,
            "velocity": self.velocity,
            "competition": self.competition,
            "source": self.source,
            "freshness_ts": self.freshness_ts,
            "confidence": self.confidence,
            "raw": self.raw,
        }
        validate_research_record(canonical)
        if self.source not in SENSOR_NAMES:
            raise SwarmValidationError("evidence source is not a registered sensor")
        if len(self.content_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in self.content_sha256.lower()):
            raise SwarmValidationError("content_sha256 must be a SHA-256 hex digest")
        if runtime not in RUNTIME_NAMES:
            raise SwarmValidationError("evidence runtime is not registered")
        canonical_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "topic": self.topic,
            "intent": self.intent,
            "velocity": float(self.velocity),
            "competition": self.competition,
            "source": self.source,
            "freshness_ts": self.freshness_ts,
            "confidence": float(self.confidence),
            "raw": self.raw,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at,
            "provider": self.provider,
            "content_sha256": self.content_sha256,
        }

    def to_research_record(self, *, job_id: str, runtime: str) -> dict[str, Any]:
        raw = dict(self.raw)
        raw["_marketos_evidence"] = {
            "schema": SCHEMA,
            "job_id": job_id,
            "evidence_id": self.evidence_id,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at,
            "provider": self.provider,
            "runtime": runtime,
            "content_sha256": self.content_sha256,
        }
        return {
            "topic": self.topic,
            "intent": self.intent,
            "velocity": float(self.velocity),
            "competition": self.competition,
            "source": self.source,
            "freshness_ts": self.freshness_ts,
            "confidence": float(self.confidence),
            "raw": raw,
        }


@dataclass(frozen=True)
class EvidenceEnvelope:
    job_id: str
    runtime: str
    status: str
    records: tuple[EvidenceRecord, ...] = ()
    rejected: tuple[dict[str, Any], ...] = ()
    telemetry: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any], spec: SwarmJobSpec) -> "EvidenceEnvelope":
        if payload.get("schema", SCHEMA) != SCHEMA:
            raise SwarmValidationError(f"evidence schema must be {SCHEMA}")
        if str(payload.get("job_id")) != spec.job_id:
            raise SwarmValidationError("evidence job_id does not match the queued job")
        runtime = str(payload.get("runtime", spec.runtime))
        status = str(payload.get("status", "succeeded"))
        if status not in {"succeeded", "partial", "skipped"}:
            raise SwarmValidationError("evidence status is invalid")
        records = tuple(EvidenceRecord.from_mapping(item, runtime=runtime) for item in (payload.get("records") or ()))
        rejected = tuple(dict(item) for item in (payload.get("rejected") or ()))
        envelope = cls(job_id=spec.job_id, runtime=runtime, status=status, records=records, rejected=rejected, telemetry=dict(payload.get("telemetry") or {}))
        envelope.validate(spec)
        return envelope

    def validate(self, spec: SwarmJobSpec) -> None:
        if self.runtime != spec.runtime:
            raise SwarmValidationError("evidence runtime does not match the job")
        if len(self.records) > spec.max_records:
            raise SwarmValidationError("evidence record limit exceeded")
        for record in self.records:
            record.validate(runtime=self.runtime)
            if record.source not in spec.sources:
                raise SwarmValidationError(f"evidence source {record.source!r} was not requested by the job")
            if spec.allowed_domains:
                hostname = (urlparse(record.source_url).hostname or "").lower()
                allowed = {
                    domain.strip().lower().lstrip(".")
                    for domain in spec.allowed_domains
                }
                if not any(hostname == domain or hostname.endswith("." + domain) for domain in allowed):
                    raise SwarmValidationError(f"evidence domain is not allowlisted: {hostname}")
        payload = self.to_dict()
        if len(canonical_json(payload).encode("utf-8")) > spec.max_bytes:
            raise SwarmValidationError("evidence byte limit exceeded")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "job_id": self.job_id,
            "runtime": self.runtime,
            "status": self.status,
            "records": [record.to_dict() for record in self.records],
            "rejected": [dict(item) for item in self.rejected],
            "telemetry": dict(self.telemetry),
        }

    @property
    def envelope_hash(self) -> str:
        return sha256_json(self.to_dict())


class SwarmRuntime(Protocol):
    def __call__(self, spec: Mapping[str, Any]) -> Mapping[str, Any]: ...


class SwarmJobStore:
    """SQLite queue and immutable result history for bounded swarm jobs."""

    def __init__(self, path: str = "backend/state/research.db") -> None:
        self.path = path
        self._ensure_schema()

    @contextmanager
    def _connect(self):
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS research_swarm_jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    runtime TEXT NOT NULL,
                    spec TEXT NOT NULL,
                    result TEXT,
                    error_type TEXT,
                    error_message TEXT,
                    requested_at TEXT NOT NULL,
                    started_at TEXT,
                    ended_at TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_research_swarm_status ON research_swarm_jobs (status, requested_at)")

    def enqueue(self, spec: SwarmJobSpec) -> dict[str, Any]:
        spec.validate()
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO research_swarm_jobs
                (job_id, status, runtime, spec, requested_at, created_at)
                VALUES (?, 'queued', ?, ?, ?, ?)
                """,
                (spec.job_id, spec.runtime, canonical_json(spec.to_dict()), spec.requested_at, now),
            )
        return self.get(spec.job_id) or {}

    def claim_pending(self, limit: int = 10) -> list[SwarmJobSpec]:
        limit = max(1, min(int(limit), 100))
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT job_id, spec FROM research_swarm_jobs WHERE status = 'queued' ORDER BY requested_at LIMIT ?",
                (limit,),
            ).fetchall()
            specs: list[SwarmJobSpec] = []
            for row in rows:
                spec = SwarmJobSpec.from_mapping(json.loads(row["spec"]))
                changed = conn.execute(
                    "UPDATE research_swarm_jobs SET status = 'running', started_at = ? WHERE job_id = ? AND status = 'queued'",
                    (now, spec.job_id),
                ).rowcount
                if changed:
                    specs.append(spec)
            return specs

    def complete(self, job_id: str, envelope: EvidenceEnvelope) -> None:
        now = datetime.now(timezone.utc).isoformat()
        payload = {**envelope.to_dict(), "envelope_hash": envelope.envelope_hash}
        with self._connect() as conn:
            conn.execute(
                "UPDATE research_swarm_jobs SET status = ?, result = ?, ended_at = ? WHERE job_id = ? AND status = 'running'",
                (envelope.status, canonical_json(payload), now, job_id),
            )

    def fail(self, job_id: str, error: Exception, *, error_type: str = "runtime_error") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE research_swarm_jobs SET status = 'failed', error_type = ?, error_message = ?, ended_at = ? WHERE job_id = ? AND status = 'running'",
                (error_type, str(error)[:2_000], now, job_id),
            )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM research_swarm_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._decode(row) if row else None

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM research_swarm_jobs ORDER BY requested_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._decode(row) for row in rows]

    def list_public(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return operational metadata without query/result payloads."""
        return [self._public(item) for item in self.list(limit)]

    @staticmethod
    def _public(item: Mapping[str, Any]) -> dict[str, Any]:
        result = item.get("result") or {}
        return {
            "job_id": item.get("job_id"),
            "status": item.get("status"),
            "runtime": item.get("runtime"),
            "requested_at": item.get("requested_at"),
            "started_at": item.get("started_at"),
            "ended_at": item.get("ended_at"),
            "error_type": item.get("error_type"),
            "result": {
                "schema": result.get("schema"),
                "status": result.get("status"),
                "record_count": len(result.get("records") or []),
                "rejected_count": len(result.get("rejected") or []),
                "envelope_hash": result.get("envelope_hash"),
            } if result else None,
        }

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["spec"] = json.loads(item["spec"])
        if item.get("result"):
            item["result"] = json.loads(item["result"])
        return item


def swarm_readiness(*, runtime_names: Sequence[str] = ()) -> dict[str, Any]:
    registered = set(runtime_names)
    global_enabled = _flag("FF_RESEARCH_SWARM_ENABLED")
    runtimes = []
    for name in RUNTIME_NAMES:
        flag_name = f"FF_RESEARCH_SWARM_{name.upper()}"
        enabled = _flag(flag_name)
        status = "disabled" if not global_enabled or not enabled else ("ready" if name in registered else "unavailable")
        runtimes.append({"name": name, "flag_env": flag_name, "enabled": status == "ready", "status": status, "runner_registered": name in registered})
    sensors = []
    for name in SENSOR_NAMES:
        flag_name = f"FF_RESEARCH_SENSOR_{name.upper()}"
        enabled = _flag(flag_name)
        sensors.append({"name": name, "flag_env": flag_name, "enabled": global_enabled and enabled, "status": "ready" if global_enabled and enabled else "disabled"})
    return {
        "global_enabled": global_enabled,
        "runtimes": runtimes,
        "sensors": sensors,
        "execution_policy": {
            "max_workers": max(1, min(_int_env("RESEARCH_SWARM_MAX_WORKERS", 2), 8)),
            "max_batch": max(1, min(_int_env("RESEARCH_SWARM_MAX_BATCH", 4), 100)),
            "default_timeout_seconds": max(0.001, min(_float_env("RESEARCH_SWARM_MAX_DURATION_SECONDS", 60.0), 900.0)),
            "dry_run_default": True,
        },
    }


class SwarmRunner:
    def __init__(
        self,
        *,
        job_store: SwarmJobStore,
        trend_store: TrendRecordStore,
        runtimes: Mapping[str, SwarmRuntime] | None = None,
    ) -> None:
        self.job_store = job_store
        self.trend_store = trend_store
        self.runtimes = dict(runtimes or {})

    def enqueue(self, spec: SwarmJobSpec) -> dict[str, Any]:
        return self.job_store.enqueue(spec)

    def run_pending(self) -> dict[str, Any]:
        readiness = swarm_readiness(runtime_names=tuple(self.runtimes))
        if not readiness["global_enabled"]:
            return {"status": "skipped", "reason": "feature_flag_disabled", "queued": 0, "completed": 0}
        specs = self.job_store.claim_pending(readiness["execution_policy"]["max_batch"])
        if not specs:
            return {"status": "succeeded", "reason": "no_queued_jobs", "queued": 0, "completed": 0}
        workers = min(readiness["execution_policy"]["max_workers"], len(specs))
        started = time.monotonic()
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="marketos-swarm")
        futures: dict[Future[EvidenceEnvelope], SwarmJobSpec] = {
            executor.submit(self._run_one, spec): spec for spec in specs
        }
        completed = 0
        failed = 0
        try:
            done, pending = wait(futures, timeout=max(float(spec.max_duration_s) for spec in specs))
            for future in done:
                spec = futures[future]
                try:
                    envelope = future.result()
                    if envelope.records:
                        self.trend_store.append_many([
                            record.to_research_record(job_id=spec.job_id, runtime=spec.runtime)
                            for record in envelope.records
                        ])
                    self.job_store.complete(spec.job_id, envelope)
                    research_metrics.record_swarm_job(spec.runtime, envelope.status)
                    research_metrics.record_swarm_records(spec.runtime, persisted=len(envelope.records))
                    completed += 1
                except Exception as err:
                    self.job_store.fail(spec.job_id, err, error_type="validation_error" if isinstance(err, SwarmValidationError) else "runtime_error")
                    research_metrics.record_swarm_job(spec.runtime, "failed")
                    research_metrics.record_swarm_records(spec.runtime, rejected=1)
                    failed += 1
            for future in pending:
                spec = futures[future]
                future.cancel()
                self.job_store.fail(spec.job_id, TimeoutError("swarm job timeout"), error_type="timeout")
                research_metrics.record_swarm_job(spec.runtime, "timeout")
                failed += 1
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return {
            "status": "succeeded" if failed == 0 else ("partial" if completed else "failed"),
            "queued": len(specs),
            "completed": completed,
            "failed": failed,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
        }

    def _run_one(self, spec: SwarmJobSpec) -> EvidenceEnvelope:
        if not _flag(f"FF_RESEARCH_SWARM_{spec.runtime.upper()}"):
            return EvidenceEnvelope(job_id=spec.job_id, runtime=spec.runtime, status="skipped", telemetry={"reason": "runtime_flag_disabled"})
        disabled_sensors = [
            source for source in spec.sources
            if not _flag(f"FF_RESEARCH_SENSOR_{source.upper()}")
        ]
        if disabled_sensors:
            raise SwarmValidationError(f"research sensors are disabled: {disabled_sensors}")
        runtime = self.runtimes.get(spec.runtime)
        if runtime is None:
            raise SwarmValidationError(f"runtime {spec.runtime!r} is not registered")
        payload = runtime(spec.to_dict())
        if not isinstance(payload, Mapping):
            raise SwarmValidationError("runtime must return a mapping")
        return EvidenceEnvelope.from_mapping(payload, spec)


def register_swarm_job(
    job_registry: Any,
    *,
    job_store: SwarmJobStore | None = None,
    trend_store: TrendRecordStore | None = None,
    runtimes: Mapping[str, SwarmRuntime] | None = None,
) -> None:
    record_store = trend_store or TrendRecordStore(path=os.getenv("RESEARCH_DB_PATH", "backend/state/research.db"))
    queue = job_store or SwarmJobStore(path=record_store.path)
    runner = SwarmRunner(job_store=queue, trend_store=record_store, runtimes=runtimes)

    def run_job() -> dict[str, Any]:
        result = runner.run_pending()
        logger.info({"job": "research.swarm.v1", **result})
        return result

    job_registry.register("research.swarm.v1", run_job)

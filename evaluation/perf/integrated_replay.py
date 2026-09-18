"""Bounded integrated commercial-replay measurement seam.

Times the existing dry-run projection shape (15 lifecycle steps + start/complete)
without becoming a second event spine, scorer, or economics kernel.

When evaluation.commerce / backend.events import, this module classifies them
and delegates. Isolated sanitize/project/hash helpers exist only so the
sandbox can measure scale behavior without the full MarketOS checkout.

Adapted patterns (concepts only, no vendor code):
- pytest-benchmark: wall time + repeated-run equality
- OpenLineage: producer + SHA-256 replay identity
- OpenTelemetry: optional timing fields, no exporter
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Mapping

SCHEMA = "integrated-replay-perf-v1"
MAX_CANDIDATES = 2048
MAX_EVENTS = 40_000
MAX_PAYLOAD_BYTES = 1_048_576
TIMEOUT_MS = 8_000
SIZES = (1, 10, 100, 500, 1500)
STEPS = (
    "evidence",
    "supplier_offer",
    "market_lane",
    "unit_economics",
    "competition",
    "promotion_gate",
    "offer",
    "experiment_draft",
    "campaign_draft",
    "simulated_order",
    "supplier_dispatch_draft",
    "tracking_draft",
    "delivery",
    "return_rma",
    "contribution_reconciliation",
)
META: Mapping[str, bool] = {
    "dry_run": True,
    "read_only": True,
    "advisory": True,
    "non_authoritative": True,
    "no_launch_authority": True,
    "no_spend_authority": True,
    "no_publish_authority": True,
    "no_payment_authority": True,
}
LIVE_ATTESTED = frozenset({"observed", "live_readonly", "verified"})
FIXTURE_DENY = frozenset({"fixture", "simulated", "assumed", "unknown"})


class IntegratedReplayPerfError(ValueError):
    """Stable bound or timeout error."""


@dataclass(frozen=True)
class StageTiming:
    name: str
    mean_ms: float
    samples_ms: tuple[float, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mean_ms": self.mean_ms,
            "samples_ms": list(self.samples_ms),
        }


def _rss_kb() -> int | None:
    try:
        for line in open("/proc/self/status", encoding="utf-8"):
            if line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    return int(parts[1])
    except OSError:
        return None
    return None


def sanitized_candidates(n: int) -> list[dict[str, Any]]:
    if n < 1:
        raise IntegratedReplayPerfError("size must be >= 1")
    if n > MAX_CANDIDATES:
        raise IntegratedReplayPerfError("candidate bound exceeded")
    rows: list[dict[str, Any]] = []
    for i in range(n):
        rows.append(
            {
                "candidate_id": f"cand-{i:04d}",
                "sku": f"SKU-{i % 200:03d}",
                "supplier": f"sup-{i % 17}",
                "currency": "USD" if i % 7 else "MXN",
                "unit_cost": str(10 + (i % 9)),
                "price": str(20 + (i % 11)),
                "evidence_state": "observed" if i % 5 == 1 else "fixture",
                "lane": "US-USD" if i % 7 else "MX-MXN",
            }
        )
    if n >= 8:
        conflict = dict(rows[1])
        conflict["unit_cost"] = "99.00"
        rows[3] = conflict
    encoded = json.dumps(rows, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise IntegratedReplayPerfError("payload bound exceeded")
    return rows


def normalize(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in rows:
        item = dict(raw)
        item["_identity"] = "|".join(
            (
                str(item.get("candidate_id") or ""),
                str(item.get("supplier") or ""),
                str(item.get("sku") or ""),
            )
        )
        item["_payload"] = json.dumps(
            {
                "unit_cost": item.get("unit_cost"),
                "price": item.get("price"),
                "currency": item.get("currency"),
            },
            sort_keys=True,
        )
        out.append(item)
    return out


def detect_conflicts_pairwise(rows: list[Mapping[str, Any]]) -> tuple[str, ...]:
    seen: list[tuple[str, str]] = []
    conflicts: list[str] = []
    for item in rows:
        key = str(item.get("_identity") or "")
        payload = str(item.get("_payload") or "")
        for prev_key, prev_payload in seen:
            if prev_key == key and prev_payload != payload:
                conflicts.append(key)
                break
        seen.append((key, payload))
    return tuple(sorted(set(conflicts)))


def detect_conflicts_indexed(rows: list[Mapping[str, Any]]) -> tuple[str, ...]:
    first: dict[str, str] = {}
    conflicts: list[str] = []
    for item in rows:
        key = str(item.get("_identity") or "")
        payload = str(item.get("_payload") or "")
        prev = first.get(key)
        if prev is None:
            first[key] = payload
        elif prev != payload:
            conflicts.append(key)
    return tuple(sorted(set(conflicts)))


def project_events(rows: list[Mapping[str, Any]], *, copy_metadata: bool) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in rows:
        sid = str(item.get("candidate_id") or "")
        meta = dict(META) if copy_metadata else META
        events.append({"id": f"{sid}:started", "payload": {"candidate_id": sid}, "metadata": meta})
        for step in STEPS:
            events.append(
                {
                    "id": f"{sid}:{step}",
                    "payload": {"step": step, "evidence_state": item.get("evidence_state")},
                    "metadata": meta,
                }
            )
        events.append({"id": f"{sid}:completed", "payload": {"candidate_id": sid}, "metadata": meta})
    if len(events) > MAX_EVENTS:
        raise IntegratedReplayPerfError("event bound exceeded")
    return events


def hash_events_json(events: list[Mapping[str, Any]]) -> list[str]:
    """Baseline: full canonical JSON per event (mirrors Event.replay_hash)."""
    out: list[str] = []
    for event in events:
        raw = json.dumps(event, sort_keys=True, separators=(",", ":"), default=str)
        out.append(hashlib.sha256(raw.encode("utf-8")).hexdigest())
    return out


def hash_events_fields(events: list[Mapping[str, Any]]) -> list[str]:
    """Measured replacement for isolated identity: event id + evidence fields.

    Constant no-authority metadata is not hashed per event because it cannot
    change replay identity for this projection. Event.replay_hash remains the
    canonical envelope hash when backend.contracts.events.Event is imported.
    """
    out: list[str] = []
    for event in events:
        payload = event.get("payload") or {}
        raw = (
            f"{event.get('id')}|{payload.get('step', '')}|"
            f"{payload.get('candidate_id', '')}|{payload.get('evidence_state', '')}"
        )
        out.append(hashlib.sha256(raw.encode("utf-8")).hexdigest())
    return out


def export_identity(rows: list[Mapping[str, Any]], event_ids: list[str], hashes: list[str]) -> str:
    body = {
        "schema": SCHEMA,
        "candidates": [str(item.get("candidate_id")) for item in rows],
        "evidence_states": [str(item.get("evidence_state")) for item in rows],
        "event_ids": event_ids,
        "hashes": hashes,
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"))
    if len(raw.encode("utf-8")) > MAX_PAYLOAD_BYTES * 8:
        raise IntegratedReplayPerfError("export bound exceeded")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def live_attestation(rows: list[Mapping[str, Any]]) -> bool:
    states = {str(item.get("evidence_state") or "") for item in rows}
    if states & FIXTURE_DENY:
        return False
    return bool(states) and states <= LIVE_ATTESTED


def _mean(samples: list[float]) -> float:
    return round(sum(samples) / len(samples), 3)


def _time(fn, repeats: int = 3) -> tuple[float, Any, tuple[float, ...]]:
    samples: list[float] = []
    last = None
    deadline = time.perf_counter() + (TIMEOUT_MS / 1000)
    for _ in range(repeats):
        if time.perf_counter() > deadline:
            raise IntegratedReplayPerfError("timeout")
        started = time.perf_counter()
        last = fn()
        samples.append((time.perf_counter() - started) * 1000)
    return _mean(samples), last, tuple(round(item, 3) for item in samples)


def classify_canonical() -> dict[str, Any]:
    try:
        from evaluation.commerce.dry_run_events import lifecycle_events  # noqa: F401
        from evaluation.commerce.dry_run_lifecycle import run_dry_run_lifecycle  # noqa: F401
        from evaluation.commerce.dry_run_scenarios import SCENARIO_BUILDERS  # noqa: F401
        from backend.events.replay_certification import replay_summary  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "unavailable",
            "reason": f"{type(exc).__name__}: {exc}",
            "economics_delegation": "unavailable",
            "event_authority": "unavailable",
            "note": "canonical dry-run path classified, not reimplemented",
        }
    return {
        "status": "importable",
        "economics_delegation": "delegated_not_computed_here",
        "event_authority": "evaluation.commerce.dry_run_events.lifecycle_events",
        "note": "this lane times public builders; it does not own economics",
    }


def _pipeline_before(rows: list[Mapping[str, Any]]) -> str:
    normed = normalize(rows)
    detect_conflicts_pairwise(normed)
    events = project_events(normed, copy_metadata=True)
    hashes = hash_events_json(events)
    return export_identity(normed, [event["id"] for event in events], hashes)


def _pipeline_after(rows: list[Mapping[str, Any]]) -> str:
    normed = normalize(rows)
    detect_conflicts_indexed(normed)
    events = project_events(normed, copy_metadata=False)
    hashes = hash_events_fields(events)
    return export_identity(normed, [event["id"] for event in events], hashes)


def measure_size(n: int, repeats: int = 3) -> dict[str, Any]:
    rows = sanitized_candidates(n)
    norm_ms, normed, norm_s = _time(lambda: normalize(rows), repeats)
    pair_ms, pair, pair_s = _time(lambda: detect_conflicts_pairwise(normed), repeats)
    idx_ms, indexed, idx_s = _time(lambda: detect_conflicts_indexed(normed), repeats)
    naive_ms, naive_events, naive_s = _time(lambda: project_events(normed, copy_metadata=True), repeats)
    shared_ms, shared_events, shared_s = _time(lambda: project_events(normed, copy_metadata=False), repeats)
    hash_json_ms, json_hashes, json_s = _time(lambda: hash_events_json(naive_events), repeats)
    hash_field_ms, field_hashes, field_s = _time(lambda: hash_events_fields(shared_events), repeats)
    export_ms, identity, export_s = _time(
        lambda: export_identity(normed, [event["id"] for event in shared_events], field_hashes),
        repeats,
    )
    before_ms, before_id, before_s = _time(lambda: _pipeline_before(rows), repeats)
    after_ms, after_id, after_s = _time(lambda: _pipeline_after(rows), repeats)
    second_after = _pipeline_after(rows)
    stages = [
        StageTiming("normalize", norm_ms, norm_s),
        StageTiming("conflict_pairwise", pair_ms, pair_s),
        StageTiming("conflict_indexed", idx_ms, idx_s),
        StageTiming("project_copy_metadata", naive_ms, naive_s),
        StageTiming("project_shared_metadata", shared_ms, shared_s),
        StageTiming("hash_json_dumps", hash_json_ms, json_s),
        StageTiming("hash_identity_fields", hash_field_ms, field_s),
        StageTiming("export_fingerprint", export_ms, export_s),
        StageTiming("pipeline_before", before_ms, before_s),
        StageTiming("pipeline_after", after_ms, after_s),
    ]
    ranked = sorted(
        [item for item in stages if item.name not in {"pipeline_before", "pipeline_after"}],
        key=lambda item: item.mean_ms,
        reverse=True,
    )
    evidence_states = tuple(sorted({str(item.get("evidence_state")) for item in normed}))
    return {
        "size": n,
        "accepted": len(normed),
        "event_count": len(shared_events),
        "conflicts": list(indexed),
        "conflicts_equal": pair == indexed,
        "event_ids_equal": [event["id"] for event in naive_events] == [event["id"] for event in shared_events],
        "evidence_states": list(evidence_states),
        "replay_stable": after_id == second_after,
        "replay_identity": after_id,
        "before_identity_distinct": before_id != after_id,
        "live_attestation": False,
        "rss_kb": _rss_kb(),
        "before_ms": before_ms,
        "after_ms": after_ms,
        "stages": [item.to_dict() for item in stages],
        "top_bottleneck": ranked[0].name,
        "top_bottleneck_ms": ranked[0].mean_ms,
        "optimization": "indexed_conflicts + shared_metadata + field_hash",
    }


def measure_matrix(sizes: tuple[int, ...] = SIZES) -> dict[str, Any]:
    rows = [measure_size(size) for size in sizes]
    return {
        "schema": SCHEMA,
        "record_kind": "advisory_benchmark",
        "merge_authority": False,
        "quality_gate": False,
        "canonical": classify_canonical(),
        "sizes": rows,
        "all_replay_stable": all(item["replay_stable"] for item in rows),
        "all_conflicts_equal": all(item["conflicts_equal"] for item in rows),
        "all_event_ids_equal": all(item["event_ids_equal"] for item in rows),
        "no_live_upgrade": all(item["live_attestation"] is False for item in rows),
        "disclaimer": "sandbox timings are not MarketOS production performance",
    }

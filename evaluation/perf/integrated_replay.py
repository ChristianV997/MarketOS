"""Canonical replay performance arbitration for PR #274.

This module does not own commercial replay. #279 owns the fixture replay
CLI (`scripts/run_commercial_replay_integration.py` + five scenario
builders + `lifecycle_events` + `Event.replay_hash`). #280 owns the
benchmark laboratory and must not be imported or copied here.

When MarketOS commerce imports are available this seam:

- drives the five public dry-run builders twice;
- projects events only through `evaluation.commerce.dry_run_events.lifecycle_events`;
- uses `Event.replay_hash()` as the identity;
- certifies sequence and live-authority through `replay_summary`;
- records wall time and optional RSS.

When those imports are missing the seam classifies the path as
unavailable. Isolated dict projection / field-hash helpers remain only
so this sandbox can prove they are *not* the canonical identity.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Mapping

SCHEMA = "integrated-replay-arbitration-v2"
MAX_CANDIDATES = 2048
MAX_EVENTS = 40_000
TIMEOUT_MS = 8_000
CANONICAL_BUILDERS = (
    "hydroponics_positive_candidate",
    "smart_pet_support_burden_candidate",
    "solar_4g_security_blocked_candidate",
    "commodity_electronics_rejected_candidate",
    "high_ticket_deferred_candidate",
)
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
LIVE_ATTESTED = frozenset({"observed", "live_readonly", "verified"})
FIXTURE_DENY = frozenset({"fixture", "simulated", "assumed", "unknown", "missing"})
AUTHORITIES = {
    "replay_cli": "#279 scripts/run_commercial_replay_integration.py",
    "event_projection": "evaluation.commerce.dry_run_events.lifecycle_events",
    "event_hash": "backend.contracts.events.Event.replay_hash",
    "certification": "backend.events.replay_certification.replay_summary",
    "economics": "backend.economics.kernel / evaluation.commerce.dry_run_lifecycle",
    "laboratory": "#280 scripts/benchmarks/benchmark_commercial_replay_lab.py",
}


class IntegratedReplayPerfError(ValueError):
    """Stable bound, timeout, or conformance error."""


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


def classify_canonical() -> dict[str, Any]:
    missing: list[str] = []
    imported: dict[str, str] = {}
    try:
        from evaluation.commerce.dry_run_events import lifecycle_events  # noqa: F401

        imported["lifecycle_events"] = "evaluation.commerce.dry_run_events.lifecycle_events"
    except Exception as exc:  # noqa: BLE001
        missing.append(f"lifecycle_events:{type(exc).__name__}: {exc}")
    try:
        from evaluation.commerce.dry_run_lifecycle import run_dry_run_lifecycle  # noqa: F401

        imported["run_dry_run_lifecycle"] = "evaluation.commerce.dry_run_lifecycle.run_dry_run_lifecycle"
    except Exception as exc:  # noqa: BLE001
        missing.append(f"run_dry_run_lifecycle:{type(exc).__name__}: {exc}")
    try:
        from evaluation.commerce.dry_run_scenarios import SCENARIO_BUILDERS  # noqa: F401

        imported["SCENARIO_BUILDERS"] = "evaluation.commerce.dry_run_scenarios.SCENARIO_BUILDERS"
    except Exception as exc:  # noqa: BLE001
        missing.append(f"SCENARIO_BUILDERS:{type(exc).__name__}: {exc}")
    try:
        from backend.contracts.events import Event  # noqa: F401

        imported["Event"] = "backend.contracts.events.Event"
    except Exception as exc:  # noqa: BLE001
        missing.append(f"Event:{type(exc).__name__}: {exc}")
    try:
        from backend.events.replay_certification import replay_summary  # noqa: F401

        imported["replay_summary"] = "backend.events.replay_certification.replay_summary"
    except Exception as exc:  # noqa: BLE001
        missing.append(f"replay_summary:{type(exc).__name__}: {exc}")
    status = "importable" if not missing else "unavailable"
    return {
        "status": status,
        "imported": imported,
        "missing": missing,
        "authorities": dict(AUTHORITIES),
        "event_authority": AUTHORITIES["event_projection"],
        "hash_authority": AUTHORITIES["event_hash"],
        "laboratory_owner": AUTHORITIES["laboratory"],
        "this_module_authority": False,
        "economics_delegation": "delegated_not_computed_here" if not missing else "unavailable",
        "note": (
            "times public builders; does not own economics, events, or the #280 lab"
            if not missing
            else "canonical dry-run path classified, not reimplemented"
        ),
    }


def live_attestation(rows: list[Mapping[str, Any]]) -> bool:
    states = {str(item.get("evidence_state") or "") for item in rows}
    if states & FIXTURE_DENY:
        return False
    return bool(states) and states <= LIVE_ATTESTED


def _time(fn, repeats: int = 2) -> tuple[float, Any]:
    samples: list[float] = []
    last = None
    deadline = time.perf_counter() + (TIMEOUT_MS / 1000)
    for _ in range(repeats):
        if time.perf_counter() > deadline:
            raise IntegratedReplayPerfError("timeout")
        started = time.perf_counter()
        last = fn()
        samples.append((time.perf_counter() - started) * 1000)
    return round(sum(samples) / len(samples), 3), last


def _evidence_state(report: Any) -> str:
    if getattr(report, "steps", None):
        detail = report.steps[0].detail or {}
        return str(detail.get("evidence_state") or "unknown")
    return str(getattr(report, "evidence_state", "unknown") or "unknown")


def measure_canonical_scenarios() -> dict[str, Any]:
    """Drive the five public builders through the canonical Event path."""
    classification = classify_canonical()
    if classification["status"] != "importable":
        return {
            "status": "unavailable",
            "schema": SCHEMA,
            "canonical": classification,
            "scenarios": [],
            "all_replay_stable": False,
            "all_sequences_clean": False,
            "no_live_upgrade": True,
            "event_hash_authority": AUTHORITIES["event_hash"],
            "field_hash_rejected_as_identity": True,
            "reason": classification["missing"],
        }

    from backend.events.replay_certification import replay_summary
    from evaluation.commerce.dry_run_events import lifecycle_events
    from evaluation.commerce.dry_run_lifecycle import run_dry_run_lifecycle
    from evaluation.commerce.dry_run_scenarios import SCENARIO_BUILDERS

    builders = {builder.__name__: builder for builder in SCENARIO_BUILDERS}
    rows: list[dict[str, Any]] = []
    for name in CANONICAL_BUILDERS:
        builder = builders.get(name)
        if builder is None:
            raise IntegratedReplayPerfError(f"missing canonical builder: {name}")

        def _run(current=builder, label=name):
            report = run_dry_run_lifecycle(current())
            events = lifecycle_events(report, workspace_id=f"ws-{label}", occurred_at=0.0)
            return report, events

        mean_ms, pair = _time(_run, repeats=2)
        first_report, first_events = pair
        second_report, second_events = _run()
        first_ids = [event.event_id for event in first_events]
        second_ids = [event.event_id for event in second_events]
        first_hashes = [event.replay_hash() for event in first_events]
        second_hashes = [event.replay_hash() for event in second_events]
        summary = replay_summary(first_events)
        evidence = _evidence_state(first_report)
        if live_attestation([{"evidence_state": evidence}]):
            raise IntegratedReplayPerfError("fixture states cannot upgrade to live attestation")
        if first_report.live_actions_taken:
            raise IntegratedReplayPerfError("canonical dry-run took a live action")
        rows.append(
            {
                "scenario": name,
                "scenario_id": first_report.scenario_id,
                "candidate_id": first_report.candidate_id,
                "achievable_stage": first_report.achievable_stage,
                "promoted_to_launch": first_report.promoted_to_launch,
                "evidence_state": evidence,
                "event_count": len(first_events),
                "event_ids": first_ids,
                "event_ids_equal": first_ids == second_ids,
                "replay_hashes_equal": first_hashes == second_hashes,
                "report_equal": first_report.to_dict() == second_report.to_dict(),
                "sequence_issues": list(summary.get("sequence_issues") or []),
                "live_authority_violations": list(summary.get("live_authority_violations") or []),
                "live_actions_taken": first_report.live_actions_taken,
                "live_attestation": False,
                "hash_authority": "Event.replay_hash",
                "wall_ms": mean_ms,
                "rss_kb": _rss_kb(),
            }
        )
    return {
        "status": "actual",
        "schema": SCHEMA,
        "canonical": classification,
        "scenarios": rows,
        "all_replay_stable": all(item["replay_hashes_equal"] and item["event_ids_equal"] for item in rows),
        "all_sequences_clean": all(not item["sequence_issues"] for item in rows),
        "no_live_upgrade": all(item["live_attestation"] is False for item in rows),
        "no_live_authority": all(not item["live_authority_violations"] for item in rows),
        "event_hash_authority": AUTHORITIES["event_hash"],
        "field_hash_rejected_as_identity": True,
        "covered_builders": list(CANONICAL_BUILDERS),
    }


def sanitized_candidates(n: int) -> list[dict[str, Any]]:
    """Sandbox-only rows. Not a commercial scenario and not a second spine."""
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
                "evidence_state": "fixture",
            }
        )
    return rows


def project_event_ids(rows: list[Mapping[str, Any]]) -> list[str]:
    events: list[str] = []
    for item in rows:
        sid = str(item.get("candidate_id") or "")
        events.append(f"{sid}:started")
        events.extend(f"{sid}:{step}" for step in STEPS)
        events.append(f"{sid}:completed")
    if len(events) > MAX_EVENTS:
        raise IntegratedReplayPerfError("event bound exceeded")
    return events


def isolated_field_fingerprint(event_ids: list[str], evidence_states: list[str]) -> str:
    """Rejected identity. Kept to prove it is not Event.replay_hash."""
    raw = json.dumps({"ids": event_ids, "evidence": evidence_states}, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def reject_field_hash_as_canonical() -> dict[str, Any]:
    """Document that the prior isolated optimization must not replace Event.replay_hash."""
    classification = classify_canonical()
    rows = sanitized_candidates(4)
    ids = project_event_ids(rows)
    isolated = isolated_field_fingerprint(ids, [str(item["evidence_state"]) for item in rows])
    event_hashes = None
    hashes_equal = False
    if classification["status"] == "importable":
        from evaluation.commerce.dry_run_events import lifecycle_events
        from evaluation.commerce.dry_run_lifecycle import run_dry_run_lifecycle
        from evaluation.commerce.dry_run_scenarios import hydroponics_positive_candidate

        events = lifecycle_events(
            run_dry_run_lifecycle(hydroponics_positive_candidate()),
            workspace_id="ws-arbitration",
            occurred_at=0.0,
        )
        event_hashes = [event.replay_hash() for event in events]
        hashes_equal = event_hashes == [isolated] * len(event_hashes)
    return {
        "field_hash_is_canonical": False,
        "field_fingerprint": isolated,
        "event_replay_hashes": event_hashes,
        "hashes_equal_to_event_replay_hash": hashes_equal,
        "canonical": classification,
        "verdict": "Event.replay_hash remains the only replay identity",
    }


def isolated_scale_note() -> dict[str, Any]:
    """Historical sandbox measurement. Not a production result and not #280."""
    return {
        "classification": "sandbox_facsimile_not_canonical",
        "production_path": False,
        "duplicates_280_laboratory": False,
        "recorded_before_ms_1500": 205.353,
        "recorded_after_ms_1500": 56.375,
        "recorded_bottleneck": "isolated json.dumps of synthetic envelopes",
        "survives_event_replay_hash": False,
        "reason": (
            "the isolated after-path hashed event-id fields instead of "
            "Event.canonical_json; Event.__post_init__ still copies metadata"
        ),
        "evidence_classification": "fixture",
    }


def arbitrate() -> dict[str, Any]:
    canonical = measure_canonical_scenarios()
    identity = reject_field_hash_as_canonical()
    return {
        "schema": SCHEMA,
        "record_kind": "replay_performance_arbitration",
        "merge_authority": False,
        "quality_gate": False,
        "canonical_path": AUTHORITIES["replay_cli"],
        "laboratory_path": AUTHORITIES["laboratory"],
        "this_pr": "#274",
        "measures_real_commercial_replay": canonical.get("status") == "actual",
        "optimization_changes_event_replay_hash": False,
        "second_replay_path": False,
        "canonical": canonical,
        "identity_arbitration": identity,
        "isolated_scale_note": isolated_scale_note(),
        "verdict": {
            "canonical_owner": "#279",
            "laboratory_owner": "#280",
            "this_lane": "conformance and timing of the #279 Event path",
            "production_optimization_applied": False,
            "reason": (
                "changing Event.replay_hash or dry_run_events metadata sharing "
                "would alter canonical envelope hashes; #280 already owns the "
                "certification micro-optimization on advisory json.dumps"
            ),
        },
        "disclaimer": "sandbox timings are not MarketOS production performance",
    }

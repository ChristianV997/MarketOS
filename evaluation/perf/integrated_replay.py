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


def _percentile(samples: list[float], pct: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, int(round((pct / 100) * (len(ordered) - 1)))))
    return round(ordered[index], 3)


def _time(fn, repeats: int = 2) -> tuple[float, Any, list[float]]:
    samples: list[float] = []
    last = None
    deadline = time.perf_counter() + (TIMEOUT_MS / 1000)
    for _ in range(repeats):
        if time.perf_counter() > deadline:
            raise IntegratedReplayPerfError("timeout")
        started = time.perf_counter()
        last = fn()
        samples.append((time.perf_counter() - started) * 1000)
    return round(sum(samples) / len(samples), 3), last, [round(item, 3) for item in samples]


def _evidence_state(report: Any) -> str:
    if getattr(report, "steps", None):
        detail = report.steps[0].detail or {}
        return str(detail.get("evidence_state") or "unknown")
    return str(getattr(report, "evidence_state", "unknown") or "unknown")

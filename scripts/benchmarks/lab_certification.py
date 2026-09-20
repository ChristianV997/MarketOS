"""Lab-owned certification helpers for PR #280.

Does not own replay (#279) or conformance (#274). Does not change
Event.replay_hash. Safe to import without running builders.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

COMMERCE_LIFECYCLE_EVENT_COUNT = 17
FULFILLMENT_EVENT_COUNT = 20
CLI_CONCAT_EVENT_COUNT = 37
MIN_SAMPLES_FOR_TAIL = 20


def aggregate_replay_hash(hashes: list[str]) -> str:
    return hashlib.sha256("".join(hashes).encode("utf-8")).hexdigest()


def classify_event_scope(event_count: int) -> str:
    if event_count == COMMERCE_LIFECYCLE_EVENT_COUNT:
        return "commerce_lifecycle"
    if event_count == CLI_CONCAT_EVENT_COUNT:
        return "cli_concat_commerce_plus_fulfillment"
    return "unexpected"


def field_hash_negative_control(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return "field-hash:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def unavailable_import_must_not_certify(status: str, all_invariants_satisfied: bool) -> bool:
    if status in {"unmerged_dependency", "unavailable"}:
        return all_invariants_satisfied is False
    return True


def evidence_state_must_not_escalate(evidence_state: str) -> bool:
    return evidence_state != "live_readonly"


def percentile_guard(samples: list[float], p: float = 0.95) -> float:
    if not samples:
        raise ValueError("invalid sample shape")
    if len(samples) < MIN_SAMPLES_FOR_TAIL and p >= 0.95:
        return max(samples)
    ordered = sorted(samples)
    idx = min(max(int(round(p * (len(ordered) - 1))), 0), len(ordered) - 1)
    return ordered[idx]

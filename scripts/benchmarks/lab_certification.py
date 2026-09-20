"""Lab-owned certification helpers for PR #280.

Does not own replay (#279) or conformance (#274). Does not change
Event.replay_hash. Safe to import without running builders.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from evaluation.commerce.dry_run_lifecycle import LIFECYCLE_STEPS

COMMERCE_LIFECYCLE_EVENT_COUNT = 1 + len(LIFECYCLE_STEPS) + 1
FULFILLMENT_EVENT_COUNT = 20
CLI_CONCAT_EVENT_COUNT = 37
MIN_SAMPLES_FOR_TAIL = 20
MIN_LAB_MODULE_BYTES = 50000
PR279_CONCAT_MARKER = "tuple((*commerce_events, *fulfillment_events))"
THIRTEEN_INVARIANT_KEYS = (
    "all_event_ids_identical",
    "all_ordering_identical",
    "monotonic_timestamps",
    "all_hash_sequences_identical",
    "all_replay_hashes_identical",
    "no_sequence_violations",
    "no_live_authority_violations",
    "live_actions_taken_false",
    "live_attestation_false",
    "governor_simulated",
    "approval_ledger_simulated",
    "trustos_export_sanitized",
    "no_mutations",
)
PUBLISHED_COMMERCE_AGGREGATE_HASHES = {
    "hydroponics_positive_candidate": "6fb5335152136dd144dce4f9409c9556b73586e2000909d341642b322e448043",
    "smart_pet_support_burden_candidate": "454324ce4704c1e2c962c966e72a93f3bdc21179cd55db2f8d65441b772095ac",
    "solar_4g_security_blocked_candidate": "44ea844bac5e4822416ca71cb9ebf59af8b3c46b4a1ceb01a56a86cae538f3e9",
    "commodity_electronics_rejected_candidate": "b19c522f0ecc954a268a7369634f1013f49f2b9f2387250fc396805416131aa4",
    "high_ticket_deferred_candidate": "f9d709c9366b35985f15cbf0018e741a530f5250567a335a7407d471d37c13fe",
}


def aggregate_replay_hash(hashes: list[str]) -> str:
    return hashlib.sha256("".join(hashes).encode("utf-8")).hexdigest()


def classify_event_scope(event_count: int) -> str:
    if event_count == COMMERCE_LIFECYCLE_EVENT_COUNT:
        return "commerce_lifecycle"
    if event_count == FULFILLMENT_EVENT_COUNT:
        return "fulfillment_only"
    if event_count == CLI_CONCAT_EVENT_COUNT:
        return "cli_concat_commerce_plus_fulfillment"
    return "unexpected"


def field_hash_negative_control(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return "field-hash:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def unavailable_import_must_not_certify(status: str, all_invariants_satisfied: bool) -> bool:
    if status in {"unmerged_dependency", "unavailable", "commerce_only_cli_not_pr279", "truncated_or_wrong_scope"}:
        return all_invariants_satisfied is False
    return True


def evidence_state_must_not_escalate(evidence_state: str) -> bool:
    return evidence_state not in {"live_readonly", "live", "actual_executed"}


def classify_evidence(evidence_state: str) -> str:
    """Map builder evidence_state onto lab classification. Never rewrite observed to fixture."""
    state = (evidence_state or "unknown").strip().lower()
    if state in {"live_readonly", "live", "actual_executed"}:
        raise ValueError(f"evidence escalation refused: {evidence_state}")
    if state in {"observed", "fixture", "assumed", "unknown"}:
        return state
    return "unknown"


def percentile_guard(samples: list[float], p: float = 0.95) -> float:
    if not samples:
        raise ValueError("invalid sample shape")
    if len(samples) < MIN_SAMPLES_FOR_TAIL and p >= 0.95:
        return max(samples)
    ordered = sorted(samples)
    idx = min(max(int(round(p * (len(ordered) - 1))), 0), len(ordered) - 1)
    return ordered[idx]


def verify_event_count_negative_control(event_count: int, expected_scope: str = "commerce_lifecycle") -> bool:
    """Verifies that an event count strictly matches the expected scope."""
    actual_scope = classify_event_scope(event_count)
    return actual_scope == expected_scope


def verify_altered_sequence_negative_control(original_hashes: list[str], altered_hashes: list[str]) -> bool:
    """Proves that any alteration to event hash sequence changes the aggregate hash."""
    if original_hashes == altered_hashes:
        return False
    return aggregate_replay_hash(original_hashes) != aggregate_replay_hash(altered_hashes)


def verify_module_not_truncated(content: str | bytes) -> bool:
    """Verifies that module text is the complete restored laboratory and not a placeholder."""
    text = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else content
    if "PLACEHOLDER" in text or "LAB_RESTORE_REQUIRED = True" in text:
        return False
    lines = text.splitlines()
    required = (
        "ScenarioReplayLaboratory",
        "class SensitivityMatrixLaboratory",
        "class StatisticalComparisonLaboratory",
        "generate_laboratory_report",
        "percentile_guard",
        "commerce_only_cli_not_pr279",
    )
    return len(lines) >= 900 and all(token in text for token in required)


def inspect_replay_cli_source(path: str | Path) -> dict[str, Any]:
    """Read-only inspection of the replay CLI. Concatenation is #279-owned."""
    p = Path(path)
    if not p.exists():
        return {
            "status": "unavailable",
            "is_pr279_concat": False,
            "has_fulfillment_runner": False,
            "bytes": 0,
            "path": str(p),
        }
    raw = p.read_bytes()
    text = raw.decode("utf-8")
    return {
        "status": "available",
        "is_pr279_concat": PR279_CONCAT_MARKER in text,
        "has_fulfillment_runner": "run_fulfillment_risk_dry_run" in text,
        "bytes": len(raw),
        "path": str(p),
    }


def fail_closed_pr279_certification(
    status: str,
    note: str,
    *,
    cli_inspection: dict[str, Any] | None = None,
    rows_evaluated: int = 0,
) -> dict[str, Any]:
    return {
        "status": status,
        "authority": "scripts.run_commercial_replay_integration",
        "mode": "not_pr279_concat",
        "result": "not_certified",
        "note": note,
        "rows_evaluated": rows_evaluated,
        "all_replay_equal": False,
        "all_launch_blocked": True,
        "invariant_checks": {key: False for key in THIRTEEN_INVARIANT_KEYS},
        "all_invariants_satisfied": False,
        "scenario_invariants": [],
        "cli_inspection": cli_inspection or {},
    }

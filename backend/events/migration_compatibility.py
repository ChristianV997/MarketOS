"""Read-only parity checks between legacy pilot records and canonical mirrors."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from backend.contracts.events import Event

from .migration_pilot import LEGACY_EVENT_TYPE, PILOT_NAME, build_shadow_mode_decision_event


@dataclass(frozen=True)
class DualWriteCompatibilityReport:
    pilot_name: str
    legacy_count: int
    canonical_count: int
    parity: bool
    mismatches: list[str]
    legacy_fields_preserved: bool
    canonical_non_authoritative: bool
    ordering_preserved: bool
    replay_hashes: list[str]
    migration_blockers: list[str]
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pilot_name": self.pilot_name,
            "legacy_count": self.legacy_count,
            "canonical_count": self.canonical_count,
            "parity": self.parity,
            "mismatches": self.mismatches,
            "legacy_fields_preserved": self.legacy_fields_preserved,
            "canonical_non_authoritative": self.canonical_non_authoritative,
            "ordering_preserved": self.ordering_preserved,
            "replay_hashes": self.replay_hashes,
            "migration_blockers": self.migration_blockers,
            "recommendation": self.recommendation,
        }


def normalize_legacy_and_canonical(legacy_record: dict[str, Any], canonical_event: Event | None = None) -> tuple[Event, Event]:
    expected = build_shadow_mode_decision_event(legacy_record)
    return expected, canonical_event or expected


def assert_canonical_non_authoritative(event: Event) -> list[str]:
    required = {
        "migration_pilot": True,
        "dual_write": True,
        "dry_run": True,
        "non_authoritative": True,
        "legacy_event_type": LEGACY_EVENT_TYPE,
    }
    return [f"metadata_mismatch:{key}" for key, value in required.items() if event.metadata.get(key) != value]


def assert_legacy_fields_preserved(legacy_record: dict[str, Any], event: Event) -> list[str]:
    mismatches: list[str] = []
    data = dict(legacy_record.get("data") or {})
    if legacy_record.get("event") != event.event_type:
        mismatches.append("event_type")
    if data != event.payload:
        mismatches.append("payload")
    if str(legacy_record.get("workflow_id") or "") != str(event.correlation_id or ""):
        mismatches.append("correlation_id")
    if str(legacy_record.get("workflow_id") or "") != str(event.causation_id or ""):
        mismatches.append("causation_id")
    if data.get("workspace_id") is not None and str(data["workspace_id"]) != event.workspace_id:
        mismatches.append("workspace_id")
    if data.get("shadow_id") is not None and str(data["shadow_id"]) != event.aggregate_id:
        mismatches.append("aggregate_id")
    return mismatches


def compare_legacy_record_to_canonical_event(legacy_record: dict[str, Any], event: Event) -> list[str]:
    expected, actual = normalize_legacy_and_canonical(legacy_record, event)
    mismatches = assert_legacy_fields_preserved(legacy_record, actual)
    for field in ("event_id", "aggregate_type", "event_type", "occurred_at", "source"):
        if getattr(expected, field) != getattr(actual, field):
            mismatches.append(field)
    mismatches.extend(assert_canonical_non_authoritative(actual))
    return sorted(set(mismatches))


def validate_legacy_pilot_record(record: dict[str, Any]) -> list[str]:
    """Reject ambiguous inputs before claiming parity for a legacy write."""
    issues: list[str] = []
    if record.get("event") != LEGACY_EVENT_TYPE:
        issues.append("legacy_event_type")
    if not str(record.get("workflow_id") or ""):
        issues.append("legacy_workflow_id")
    if not isinstance(record.get("data"), dict):
        issues.append("legacy_data")
    try:
        float(record.get("ts"))
    except (TypeError, ValueError):
        issues.append("legacy_timestamp")
    return issues


def validate_dual_write_order(legacy_records: Sequence[dict[str, Any]], canonical_events: Sequence[Event]) -> list[str]:
    """The mirror must be one-for-one and preserve legacy record order."""
    issues: list[str] = []
    for index, record in enumerate(legacy_records):
        issues.extend(f"legacy_{index}:{issue}" for issue in validate_legacy_pilot_record(record))
        if index >= len(canonical_events):
            continue
        expected = build_shadow_mode_decision_event(record)
        actual = canonical_events[index]
        if expected.event_id != actual.event_id:
            issues.append(f"ordering_event_id:{index}")
        if expected.occurred_at != actual.occurred_at:
            issues.append(f"ordering_timestamp:{index}")
    return sorted(set(issues))


def summarize_dual_write_parity(legacy_records: Sequence[dict[str, Any]], canonical_events: Sequence[Event]) -> DualWriteCompatibilityReport:
    records = [record for record in legacy_records if record.get("event") == LEGACY_EVENT_TYPE]
    events = [event for event in canonical_events if event.event_type == LEGACY_EVENT_TYPE]
    mismatches: list[str] = []
    for index, record in enumerate(records):
        if index >= len(events):
            mismatches.append(f"missing_canonical_event:{index}")
        else:
            mismatches.extend(f"event_{index}:{value}" for value in compare_legacy_record_to_canonical_event(record, events[index]))
    if len(events) > len(records):
        mismatches.append("unexpected_extra_canonical_events")
    ordering_issues = validate_dual_write_order(records, events)
    mismatches.extend(ordering_issues)
    blockers = sorted(set(mismatches))
    parity = not blockers and len(records) == len(events)
    return DualWriteCompatibilityReport(
        pilot_name=PILOT_NAME,
        legacy_count=len(records), canonical_count=len(events), parity=parity,
        mismatches=blockers, legacy_fields_preserved=not any("payload" in value or "correlation" in value or "causation" in value for value in blockers),
        canonical_non_authoritative=not any("metadata_mismatch" in value for value in blockers),
        ordering_preserved=not ordering_issues,
        replay_hashes=[event.replay_hash() for event in events], migration_blockers=blockers,
        recommendation="consider_next_non_live_pilot" if parity else "retain_legacy_authority_and_resolve_parity_mismatches",
    )


def build_dual_write_compatibility_report(legacy_records: Sequence[dict[str, Any]], canonical_events: Sequence[Event]) -> DualWriteCompatibilityReport:
    return summarize_dual_write_parity(legacy_records, canonical_events)

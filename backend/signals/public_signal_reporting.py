"""Deterministic audit reports for advisory public-signal batches."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from backend.contracts.events import Event
from backend.events.replay_certification import hash_sequence, validate_event_sequence

from .public_signal_models import PublicSignal, PublicSignalIngestionResult
from .public_sources import public_signal_event


REQUIRED_EVENT_METADATA = {
    "dry_run": True,
    "advisory": True,
    "no_credentials": True,
    "public_source": True,
    "non_authoritative": True,
    "no_launch_authority": True,
    "no_spend_authority": True,
}


@dataclass(frozen=True)
class PublicSignalAuditReport:
    source: str
    query: str
    ingestion_status: str
    signal_count: int
    unique_signal_count: int
    source_url_count: int
    publishers: list[str]
    cache_status: str
    network_used: bool
    evidence_limitations: list[str]
    event_count: int
    event_validation_issues: list[str]
    authority_violations: list[str]
    replay_hashes: list[str]
    advisory_only: bool
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def signal_limitations(signals: Sequence[PublicSignal]) -> list[str]:
    limitations: set[str] = set()
    for signal in signals:
        for item in signal.quality.get("limitations", []):
            limitations.add(str(item))
    limitations.add("public signals are advisory observations and require corroboration")
    return sorted(limitations)


def validate_public_signal_events(events: Sequence[Event]) -> list[str]:
    issues: list[str] = []
    for event in events:
        if event.event_type != "public_signal_observed":
            issues.append(f"unexpected_event_type:{event.event_id}")
        if event.aggregate_type != "public_signal":
            issues.append(f"unexpected_aggregate_type:{event.event_id}")
        if event.payload.get("signal_id") != event.aggregate_id:
            issues.append(f"aggregate_payload_mismatch:{event.event_id}")
        for key, expected in REQUIRED_EVENT_METADATA.items():
            if event.metadata.get(key) != expected:
                issues.append(f"metadata_mismatch:{key}:{event.event_id}")
        if event.metadata.get("live_authority") is True:
            issues.append(f"live_authority:{event.event_id}")
    return sorted(set(issues))


def build_public_signal_audit(
    result: PublicSignalIngestionResult,
    *,
    workspace_id: str = "public-signal-dry-run",
    events: Sequence[Event] | None = None,
) -> PublicSignalAuditReport:
    """Build a read-only batch certificate even when no event was persisted."""
    signal_events = list(events) if events is not None else [
        public_signal_event(signal, workspace_id, cache_status=result.cache_status)
        for signal in result.signals
    ]
    validation = validate_event_sequence(signal_events) + validate_public_signal_events(signal_events)
    authorities = [issue for issue in validation if "authority" in issue]
    publishers = sorted({str(signal.attribution.get("publisher", "")) for signal in result.signals if signal.attribution.get("publisher")})
    identifiers = {signal.signal_id for signal in result.signals}
    urls = {signal.evidence_url for signal in result.signals if signal.evidence_url}
    next_actions = [
        "Treat observations as advisory evidence; do not infer commercial outcomes from one source.",
        "Corroborate relevant observations with approved local evidence or another audited source.",
    ]
    if result.status in {"blocked", "degraded"}:
        next_actions.insert(0, "Use fixtures, an existing cache, or explicitly authorize a bounded public read.")
    return PublicSignalAuditReport(
        source=result.source, query=result.query, ingestion_status=result.status,
        signal_count=len(result.signals), unique_signal_count=len(identifiers), source_url_count=len(urls),
        publishers=publishers, cache_status=result.cache_status, network_used=result.network_used,
        evidence_limitations=signal_limitations(result.signals), event_count=len(signal_events),
        event_validation_issues=sorted(set(validation)), authority_violations=authorities,
        replay_hashes=hash_sequence(signal_events), advisory_only=not authorities and not validation,
        next_actions=next_actions,
    )


def audit_to_json(audit: PublicSignalAuditReport) -> str:
    return json.dumps(audit.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def audit_to_markdown(audit: PublicSignalAuditReport) -> str:
    limitations = "\n".join(f"- {item}" for item in audit.evidence_limitations)
    hashes = "\n".join(f"- `{item}`" for item in audit.replay_hashes) or "- none"
    issues = ", ".join(audit.event_validation_issues) or "none"
    return "\n".join([
        "# Public Signal Audit", "",
        "This report is advisory-only and grants no launch, spend, publishing, provider, or commerce authority.", "",
        f"- Source: `{audit.source}`", f"- Query: `{audit.query}`", f"- Ingestion status: `{audit.ingestion_status}`",
        f"- Signals: {audit.signal_count} ({audit.unique_signal_count} unique)", f"- Cache: `{audit.cache_status}`",
        f"- Network used: `{audit.network_used}`", f"- Canonical event validation issues: {issues}", "",
        "## Evidence limitations", "", limitations, "", "## Replay hashes", "", hashes, "",
        "## Next actions", "", *[f"- {item}" for item in audit.next_actions], "",
    ])

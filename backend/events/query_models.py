"""JSON-safe, read-only models for canonical event operator views."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any

@dataclass(frozen=True)
class EventQuery:
    workspace_id: str | None = None; event_type: str | None = None; aggregate_type: str | None = None; aggregate_id: str | None = None; correlation_id: str | None = None; source: str | None = None
    limit: int = 100; offset: int = 0; since: float | None = None; until: float | None = None; sort: str = "asc"
    def __post_init__(self):
        if self.sort not in {"asc", "desc"}: raise ValueError("sort must be asc or desc")
        if self.limit < 0 or self.limit > 500: raise ValueError("limit must be between 0 and 500")
        if self.offset < 0: raise ValueError("offset must be non-negative")
    def to_dict(self) -> dict[str, Any]: return asdict(self)

@dataclass(frozen=True)
class EventRecordView:
    event_id: str; workspace_id: str | None; event_type: str; aggregate_type: str; aggregate_id: str; occurred_at: float; source: str; correlation_id: str | None; causation_id: str | None; replay_hash: str; payload_summary: dict[str, Any]; metadata_summary: dict[str, Any]; dry_run: bool; advisory: bool; read_only: bool; pii_redacted: bool; authority_flags: tuple[str, ...]
    def to_dict(self) -> dict[str, Any]:
        value = asdict(self); value["authority_flags"] = list(self.authority_flags); return value

@dataclass(frozen=True)
class EventTimeline:
    workspace_id: str | None; events: tuple[EventRecordView, ...]; event_type_counts: dict[str, int]; aggregate_type_counts: dict[str, int]; first_occurred_at: float | None; last_occurred_at: float | None; warnings: tuple[str, ...] = ()
    def to_dict(self) -> dict[str, Any]:
        value = asdict(self); value["events"] = [item.to_dict() for item in self.events]; value["warnings"] = list(self.warnings); return value

@dataclass(frozen=True)
class CommerceRunSummary:
    workspace_id: str | None; run_id: str; query: str; status: str; candidate_count: int; selected_candidate: str | None; economics_present: bool; creative_packet_present: bool; landing_page_packet_present: bool; store_draft_packet_present: bool; approval_packet_present: bool; vendor_recommendations_present: bool; event_count: int; warnings: tuple[str, ...]; blockers: tuple[str, ...]
    def to_dict(self) -> dict[str, Any]:
        value = asdict(self); value["warnings"] = list(self.warnings); value["blockers"] = list(self.blockers); return value

@dataclass(frozen=True)
class ShopifyImportSummary:
    workspace_id: str | None; batch_id: str; product_count: int; variant_count: int; collection_count: int; order_count: int; line_item_count: int; customer_count: int; pii_redacted: bool; observed_revenue_total: float; average_order_value: float; event_count: int; warnings: tuple[str, ...]
    def to_dict(self) -> dict[str, Any]:
        value = asdict(self); value["warnings"] = list(self.warnings); return value

@dataclass(frozen=True)
class OpportunityRankingSummary:
    """Decoded opportunity_scoring_events() output for one Commerce MVP run —
    unlike EventRecordView.payload_summary (key names/counts only, for the
    generic timeline), this carries each candidate's actual composite
    score/confidence/dimension breakdown/reasons/risks/unknowns so an
    operator can see *why* a candidate ranked where it did without a
    second, opaque query engine."""
    workspace_id: str | None; run_id: str; query: str; top_candidate_id: str | None
    candidate_count: int; scores: tuple[dict[str, Any], ...]; event_count: int
    def to_dict(self) -> dict[str, Any]:
        value = asdict(self); value["scores"] = [dict(item) for item in self.scores]; return value

__all__ = ["CommerceRunSummary", "EventQuery", "EventRecordView", "EventTimeline", "OpportunityRankingSummary", "ShopifyImportSummary"]

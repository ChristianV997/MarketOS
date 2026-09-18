"""JSON-safe artifacts for the non-mutating Commerce MVP packet."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool, float)): return value
    if isinstance(value, dict): return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_safe(v) for v in value]
    if hasattr(value, "to_dict"): return value.to_dict()
    return str(value)


class _Packet:
    def to_dict(self) -> dict[str, Any]: return _safe(asdict(self))


@dataclass(frozen=True)
class OpportunityCandidate(_Packet):
    candidate_id: str; workspace_id: str; query: str; product_name: str; category_name: str
    evidence_signal_ids: tuple[str, ...]; evidence_titles: tuple[str, ...]; source_urls: tuple[str, ...]
    source_count: int; source_local_score: float; recency_score: float; evidence_strength: str; confidence_level: str
    assumptions: tuple[str, ...]; unknowns: tuple[str, ...]; cannot_claim: tuple[str, ...]; recommended_next_action: str


@dataclass(frozen=True)
class UnitEconomicsSummary(_Packet):
    candidate_id: str; assumed_price: float; assumed_unit_cost: float; assumed_shipping_cost: float
    assumed_payment_fee: float; assumed_return_rate: float; assumed_cac: float; gross_margin: float
    contribution_margin: float; break_even_cac: float; warnings: tuple[str, ...]; assumptions: tuple[str, ...]; source: str
    canonical_economics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CreativePacket(_Packet):
    candidate_id: str; buyer_angles: tuple[str, ...]; hooks: tuple[str, ...]; ugc_brief: tuple[str, ...]
    storyboard_outline: tuple[str, ...]; claim_safety_notes: tuple[str, ...]; blocked_claims: tuple[str, ...]
    allowed_claims: tuple[str, ...]; recommended_vendor_targets: tuple[str, ...]


@dataclass(frozen=True)
class LandingPagePacket(_Packet):
    candidate_id: str; target_builder: str; hero: str; offer: str; benefits: tuple[str, ...]
    proof_sections: tuple[str, ...]; faq: tuple[str, ...]; objection_handling: tuple[str, ...]; cta: str
    compliance_notes: tuple[str, ...]; asset_requirements: tuple[str, ...]; manual_publish_checklist: tuple[str, ...]


@dataclass(frozen=True)
class StoreDraftPacket(_Packet):
    candidate_id: str; target_platform: str; product_title: str; product_description: str; collection_suggestion: str
    variant_placeholders: tuple[str, ...]; image_requirements: tuple[str, ...]; pricing_assumptions: tuple[str, ...]
    inventory_unknowns: tuple[str, ...]; supplier_unknowns: tuple[str, ...]; manual_store_setup_checklist: tuple[str, ...]
    forbidden_actions: tuple[str, ...]


@dataclass(frozen=True)
class ManualApprovalPacket(_Packet):
    approval_id: str; candidate_id: str; required_reviews: tuple[str, ...]; approval_items: tuple[str, ...]
    forbidden_without_approval: tuple[str, ...]; recommended_saas_tools: tuple[dict[str, Any], ...]
    export_artifacts: tuple[str, ...]; next_manual_steps: tuple[str, ...]; risk_notes: tuple[str, ...]


@dataclass(frozen=True)
class CommerceMvpRun(_Packet):
    run_id: str; workspace_id: str; query: str; started_at: float; completed_at: float; mode: str; status: str
    signal_batch: tuple[dict[str, Any], ...]; opportunity_candidates: tuple[OpportunityCandidate, ...]
    selected_candidate: OpportunityCandidate | None; unit_economics_summary: UnitEconomicsSummary | None
    creative_packet: CreativePacket | None; landing_page_packet: LandingPagePacket | None; store_draft_packet: StoreDraftPacket | None
    vendor_recommendations: tuple[dict[str, Any], ...]; approval_packet: ManualApprovalPacket | None
    canonical_event_ids: tuple[str, ...]; warnings: tuple[str, ...] = (); blockers: tuple[str, ...] = (); metadata: dict[str, Any] = field(default_factory=dict)

    def to_markdown(self) -> str:
        candidate = self.selected_candidate
        lines = ["# Commerce MVP packet", "", f"- Run: `{self.run_id}`", f"- Mode: `{self.mode}`", f"- Status: `{self.status}`", "", "## Safety", "", "- Advisory and dry-run only. No provider, store, ad, payment, fulfillment, or publishing action was executed."]
        if candidate:
            lines += ["", "## Candidate", "", f"- Product hypothesis: **{candidate.product_name}**", f"- Evidence signals: {candidate.source_count}", f"- Confidence: {candidate.confidence_level}", "", "## Required human review", ""]
            lines += [f"- {item}" for item in (self.approval_packet.required_reviews if self.approval_packet else ())]
        return "\n".join(lines) + "\n"


__all__ = ["CommerceMvpRun", "CreativePacket", "LandingPagePacket", "ManualApprovalPacket", "OpportunityCandidate", "StoreDraftPacket", "UnitEconomicsSummary"]

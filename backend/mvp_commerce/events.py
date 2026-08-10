"""Canonical advisory events for the Commerce MVP packet."""
from __future__ import annotations
import hashlib
from typing import Any
from backend.contracts.events import Event

_EVENTS = ("commerce_mvp_run_started", "commerce_mvp_signal_batch_selected", "commerce_mvp_opportunity_candidate_created", "commerce_mvp_candidate_selected", "commerce_mvp_unit_economics_estimated", "commerce_mvp_creative_packet_created", "commerce_mvp_landing_page_packet_created", "commerce_mvp_store_draft_packet_created", "commerce_mvp_vendor_recommendations_attached", "commerce_mvp_manual_approval_packet_created", "commerce_mvp_run_completed")

def commerce_mvp_events(run: Any) -> list[Event]:
    payloads = [
        ("commerce_mvp_run_started", "commerce_mvp_run", run.run_id, {"query": run.query, "mode": run.mode}),
        ("commerce_mvp_signal_batch_selected", "commerce_mvp_run", run.run_id, {"signal_ids": [item["signal_id"] for item in run.signal_batch]}),
        *[("commerce_mvp_opportunity_candidate_created", "opportunity_candidate", item.candidate_id, item.to_dict()) for item in run.opportunity_candidates],
        ("commerce_mvp_candidate_selected", "opportunity_candidate", run.selected_candidate.candidate_id, run.selected_candidate.to_dict()) if run.selected_candidate else None,
        ("commerce_mvp_unit_economics_estimated", "commerce_mvp_run", run.run_id, run.unit_economics_summary.to_dict()) if run.unit_economics_summary else None,
        ("commerce_mvp_creative_packet_created", "commerce_mvp_run", run.run_id, run.creative_packet.to_dict()) if run.creative_packet else None,
        ("commerce_mvp_landing_page_packet_created", "commerce_mvp_run", run.run_id, run.landing_page_packet.to_dict()) if run.landing_page_packet else None,
        ("commerce_mvp_store_draft_packet_created", "commerce_mvp_run", run.run_id, run.store_draft_packet.to_dict()) if run.store_draft_packet else None,
        ("commerce_mvp_vendor_recommendations_attached", "commerce_mvp_run", run.run_id, {"recommendations": list(run.vendor_recommendations)}),
        ("commerce_mvp_manual_approval_packet_created", "commerce_mvp_run", run.run_id, run.approval_packet.to_dict()) if run.approval_packet else None,
        ("commerce_mvp_run_completed", "commerce_mvp_run", run.run_id, {"status": run.status, "warnings": list(run.warnings), "blockers": list(run.blockers)}),
    ]
    values: list[Event] = []
    for index, item in enumerate(row for row in payloads if row is not None):
        event_type, aggregate_type, aggregate_id, payload = item
        event_id = "commerce-mvp-event-" + hashlib.sha256(f"{run.run_id}:{index}:{event_type}:{aggregate_id}".encode()).hexdigest()[:20]
        values.append(Event(event_id, run.workspace_id, aggregate_type, aggregate_id, event_type, 1, run.started_at + index / 1000, correlation_id=run.run_id, source="backend.mvp_commerce", payload=payload,
            metadata={"dry_run": True, "advisory": True, "non_authoritative": True, "manual_approval_required": True, "no_launch_authority": True, "no_spend_authority": True, "no_publish_authority": True, "no_store_mutation_authority": True, "no_payment_authority": True, "no_fulfillment_authority": True}))
    return values

__all__ = ["commerce_mvp_events", "_EVENTS"]

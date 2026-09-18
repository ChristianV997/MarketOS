"""Canonical event projection for the dry-run commerce lifecycle.

Follows the exact convention ``evaluation.commerce.service.evaluation_events``
already uses to map a report onto ``backend.contracts.events.Event`` records
(one event per step, deterministic ``occurred_at`` offsets, a shared
``correlation_id``, and an explicit no-live-authority metadata block). This
is not a new event spine — it is a projection into the one canonical
``Event`` envelope every other MarketOS evaluation module already writes to,
which is what lets ``backend.events.replay_certification`` (hash sequencing,
sequence validation, live-authority scanning) work on it unmodified.
"""
from __future__ import annotations

from backend.contracts.events import Event

from .dry_run_lifecycle import DryRunLifecycleReport

_NO_AUTHORITY_METADATA = {
    "dry_run": True,
    "read_only": True,
    "advisory": True,
    "non_authoritative": True,
    "manual_approval_required": True,
    "no_launch_authority": True,
    "no_spend_authority": True,
    "no_publish_authority": True,
    "no_store_mutation_authority": True,
    "no_inventory_mutation_authority": True,
    "no_payment_authority": True,
    "no_refund_authority": True,
    "no_fulfillment_authority": True,
    "no_customer_message_authority": True,
    "no_supplier_dispatch_authority": True,
}


def lifecycle_events(
    report: DryRunLifecycleReport,
    *,
    workspace_id: str,
    occurred_at: float = 0.0,
) -> list[Event]:
    """Project one ``DryRunLifecycleReport`` onto canonical, replay-safe events.

    Every event's ``aggregate_type`` is ``"commerce_dry_run"`` (a plain data
    label, not a new event subsystem — the same pattern as this codebase's
    existing ``"commerce_evaluation"``/``"ranked_opportunity"``/etc. labels),
    scoped by ``correlation_id=report.scenario_id`` so
    ``backend.events.replay_certification.replay_summary`` can validate
    ordering, hash the sequence, and flag any live-authority language across
    the whole run.
    """
    events: list[Event] = [
        Event(
            f"{report.scenario_id}:started",
            workspace_id,
            "commerce_dry_run",
            report.candidate_id,
            "commerce_dry_run_started",
            1,
            occurred_at,
            correlation_id=report.scenario_id,
            source="evaluation.commerce.dry_run_lifecycle",
            payload={"scenario_id": report.scenario_id, "candidate_id": report.candidate_id},
            metadata=dict(_NO_AUTHORITY_METADATA),
        )
    ]
    for index, step in enumerate(report.steps, start=1):
        events.append(
            Event(
                f"{report.scenario_id}:{step.step}",
                workspace_id,
                "commerce_dry_run",
                report.candidate_id,
                f"commerce_dry_run_step_{step.step}",
                1,
                occurred_at + index / 1000,
                causation_id=events[-1].event_id,
                correlation_id=report.scenario_id,
                source="evaluation.commerce.dry_run_lifecycle",
                payload=step.to_dict(),
                metadata=dict(_NO_AUTHORITY_METADATA),
            )
        )
    events.append(
        Event(
            f"{report.scenario_id}:completed",
            workspace_id,
            "commerce_dry_run",
            report.candidate_id,
            "commerce_dry_run_completed",
            1,
            occurred_at + (len(report.steps) + 1) / 1000,
            causation_id=events[-1].event_id,
            correlation_id=report.scenario_id,
            source="evaluation.commerce.dry_run_lifecycle",
            payload={
                "achievable_stage": report.achievable_stage,
                "promoted_to_launch": report.promoted_to_launch,
                "blockers": list(report.promotion.blockers),
            },
            metadata=dict(_NO_AUTHORITY_METADATA),
        )
    )
    return events


__all__ = ["lifecycle_events"]

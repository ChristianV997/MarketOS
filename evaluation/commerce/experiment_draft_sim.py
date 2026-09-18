"""Dry-run simulator. Never claims real performance or live action."""
from __future__ import annotations

from typing import Any

from evaluation.commerce.experiment_draft_models import ExperimentDraft, SimulationReport
from evaluation.commerce.experiment_draft_types import FIXTURE_STATES, replay_hash


def simulate_experiment_draft(draft: ExperimentDraft) -> SimulationReport:
    blocked = list(draft.blocked_reasons)
    if draft.approval_state not in {"approved_for_simulation"} and draft.lifecycle_state not in {"approved_for_simulation", "simulated"}:
        blocked.append("approval_absent_for_simulation")
    _ = draft.evidence_state in FIXTURE_STATES
    classification = "blocked"
    state = draft.lifecycle_state
    if not blocked and draft.lifecycle_state in {"approved_for_simulation", "draft_ready", "proposed", "human_review", "simulated"}:
        classification = "simulated_hold"
        state = "simulated"
    elif blocked and draft.lifecycle_state == "rejected":
        classification = "rejected"
    elif blocked:
        classification = "blocked"
        state = "human_review" if state not in {"rejected", "unavailable"} else state
    stop_eval = "invalid_missing_stop_condition" if "missing_stop_condition" in draft.blocked_reasons else "not_triggered_no_live_traffic"
    next_action = "keep_offline_and_review_with_operator" if classification == "simulated_hold" else draft.next_human_action
    payload = {"experiment_id": draft.experiment_id, "classification": classification, "blocked": blocked, "replay_hash": draft.replay_hash}
    return SimulationReport(
        schema="MarketOS.ExperimentDraftSimulation.v1",
        experiment_id=draft.experiment_id,
        classification=classification,
        lifecycle_state=state,
        input_valid=not draft.blocked_reasons,
        scenario_assumptions=draft.assumptions,
        metric_definitions={
            "success_metric": draft.success_metric,
            "guardrails": ",".join(draft.guardrail_metrics),
            "stop_condition": draft.stop_condition,
            "definition": "planning thresholds only; not observed performance",
        },
        stop_condition_evaluation=stop_eval,
        blocked_reasons=tuple(dict.fromkeys(blocked)),
        next_action=next_action,
        replay_hash=replay_hash(payload),
        live_action_allowed=False,
        planning_currency=draft.planning.currency,
    )


def client_safe_report(draft: ExperimentDraft, simulation: SimulationReport | None = None) -> dict[str, Any]:
    payload = {
        "schema": "MarketOS.ClientExperimentDraft.v1",
        "record_kind": "planning_record",
        "experiment_id": draft.experiment_id,
        "product_id": draft.product_id,
        "offer_id": draft.offer_id,
        "market_lane": draft.market_lane,
        "channel": draft.channel,
        "hypothesis": draft.hypothesis,
        "budget_cap": draft.budget_cap,
        "budget_currency": draft.budget_currency,
        "time_window": draft.time_window,
        "success_metric": draft.success_metric,
        "guardrail_metrics": list(draft.guardrail_metrics),
        "stop_condition": draft.stop_condition,
        "lifecycle_state": draft.lifecycle_state,
        "confidence": draft.confidence,
        "next_human_action": draft.next_human_action,
        "live_action_allowed": False,
        "planning_currency": draft.planning.currency,
        "planning_evidence_state": draft.planning.evidence_state,
    }
    if simulation is not None:
        payload["simulation_classification"] = simulation.classification
        payload["simulation_next_action"] = simulation.next_action
    return payload

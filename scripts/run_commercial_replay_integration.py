#!/usr/bin/env python3
"""Bounded commercial replay + performance integration runner.

Drives existing public builders. Does not score products, replace
scripts/benchmark_commerce_cycle.py, copy backend.economics.kernel,
or import evaluation.perf.commerce_engine as a production path.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
import platform
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            .decode("utf-8")
            .strip()
        )
    except Exception:  # noqa: BLE001
        return "unavailable"


def _base_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "merge-base", "HEAD", "origin/main"],
                cwd=ROOT,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            .decode("utf-8")
            .strip()
        )
    except Exception:  # noqa: BLE001
        return "unavailable"


def _classify_import_error(exc: BaseException) -> dict[str, Any]:
    return {
        "result": "unavailable",
        "evidence_classification": "unavailable",
        "reason": f"{type(exc).__name__}: {exc}",
    }


_REPLAY_INPUTS: tuple[tuple[str, str], ...] = (
    ("hydroponics_promising.json", "hydroponics_positive_candidate"),
    ("smart_pet_support_risk.json", "smart_pet_support_burden_candidate"),
    ("solar_4g_blocked.json", "solar_4g_security_blocked_candidate"),
    ("commodity_electronics_rejected.json", "commodity_electronics_rejected_candidate"),
    ("walking_pad_deferred.json", "high_ticket_deferred_candidate"),
)

EVIDENCE_CLASS_VOCABULARY: tuple[str, ...] = (
    "actual_executed",
    "fixture",
    "manual_import",
    "derived",
    "simulated_or_planned",
    "unavailable",
    "ci_unavailable",
)


def _canonical_fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _supplier_evidence_class(offer: dict[str, Any] | None) -> str:
    if offer is None:
        return "unavailable"
    evidence = offer.get("evidence")
    if not isinstance(evidence, dict):
        return "unavailable"
    state = evidence.get("state")
    if state == "fixture":
        return "fixture"
    if state == "manual":
        return "manual_import"
    if state == "derived":
        return "derived"
    return "unavailable"


def _compliance_evaluation(destination_country: Any) -> dict[str, Any]:
    """Ask the existing TrustOS overlay; unknown product facts stay blocked."""
    countries = {
        "mexico": "mexico",
        "mx": "mexico",
        "united states": "united_states",
        "united_states": "united_states",
        "usa": "united_states",
        "canada": "canada",
    }
    market = countries.get(str(destination_country).strip().casefold(), "unknown")
    try:
        from evaluation.trustos.mexico_product_compliance import (
            MexicoProductCompliancePacket,
            evaluate_mexico_product_compliance,
        )

        decision = evaluate_mexico_product_compliance(
            MexicoProductCompliancePacket(
                market=market,
                product_family="unknown_family",
                sku_model_exact="",
            )
        )
        gate_satisfaction = decision.promotion_gate_satisfaction()
        satisfied = gate_satisfaction.get("compliance") is True
        blockers = sorted(set(decision.blockers))
        if not satisfied and not blockers:
            blockers = ["compliance_evidence_required"]
        return {
            "status": "satisfied" if satisfied else "needs_evidence",
            "gate_satisfaction": {"compliance": satisfied},
            "blockers": blockers,
            "evidence_classification": "derived" if satisfied else "unavailable",
            "live_lookup_performed": False,
        }
    except Exception:  # noqa: BLE001 - missing/broken authority fails closed
        return {
            "status": "unavailable",
            "gate_satisfaction": {"compliance": False},
            "blockers": ["compliance_evaluator_unavailable"],
            "evidence_classification": "unavailable",
            "live_lookup_performed": False,
        }


def _scenario_evidence_classes(
    offer: dict[str, Any] | None,
    *,
    missing_cost_inputs: tuple[str, ...] = (),
    research_evidence_state: str = "fixture",
    compliance_evidence_class: str = "unavailable",
) -> dict[str, str]:
    """Classify each evidence boundary without changing existing status fields."""
    research_state_class = {
        "fixture": "fixture",
        "manual": "manual_import",
        "derived": "derived",
    }.get(research_evidence_state, "unavailable")
    return {
        "runner": "actual_executed",
        "research_input": research_state_class,
        "supplier_evidence": _supplier_evidence_class(offer),
        "economics": "unavailable" if missing_cost_inputs else "derived",
        "economics_calculation": "actual_executed",
        "compliance": compliance_evidence_class,
        "commerce_lifecycle": "simulated_or_planned",
        "fulfillment_lifecycle": "simulated_or_planned",
        "governor": "simulated_or_planned",
        "approval_ledger": "simulated_or_planned",
        "trustos_export": "actual_executed",
        "external_validation": "unavailable",
        "ci": "ci_unavailable",
    }


def _missing_supplier_cost_inputs(
    offer: dict[str, Any] | None,
    shipping_value: Any,
) -> tuple[str, ...]:
    """Treat absent amounts as unknown while preserving explicitly supplied zero."""
    missing: list[str] = []
    price_value = offer.get("price", {}).get("amount") if offer is not None else None
    unknown_tokens = {"", "unknown", "unavailable", "n/a", "none", "missing"}
    if offer is None or price_value is None or (
        isinstance(price_value, str) and price_value.strip().lower() in unknown_tokens
    ):
        missing.append("product_cost")
    if offer is None or shipping_value is None or (
        isinstance(shipping_value, str) and shipping_value.strip().lower() in unknown_tokens
    ):
        missing.append("supplier_shipping")
    return tuple(missing)


def _mark_missing_cost_economics_unavailable(report: Any, missing_cost_inputs: tuple[str, ...]) -> Any:
    """Do not publish kernel arithmetic that used missing supplier costs as zero."""
    missing_inputs = set(report.economics.missing_inputs)
    missing_inputs.update(missing_cost_inputs)

    packet = dict(report.commerce_packet)
    assumptions = dict(packet.get("assumptions", {}))
    for name, value in tuple(assumptions.items()):
        if isinstance(value, dict) and value.get("source") == "missing":
            missing_inputs.add(name)
            assumptions.pop(name)
    packet["assumptions"] = assumptions
    missing = sorted(missing_inputs)
    unavailable = {
        "status": "unavailable",
        "currency": report.economics.currency,
        "evidence_state": "missing",
        "missing_inputs": missing,
        "reason": "supplier_offer_evidence_missing",
    }
    packet["economics"] = unavailable

    steps = tuple(
        replace(
            step,
            status="unavailable",
            detail={
                **unavailable,
                "calculation_execution": "actual_executed",
            },
        )
        if step.step == "unit_economics"
        else step
        for step in report.steps
    )
    return replace(report, steps=steps, commerce_packet=packet)


def _commerce_cli_projection(report: Any) -> dict[str, Any]:
    """Keep the existing report/packet fields without duplicating internals."""
    return {
        "scenario_id": report.scenario_id,
        "candidate_id": report.candidate_id,
        "achievable_stage": report.achievable_stage,
        "promoted_to_launch": report.promoted_to_launch,
        "steps": [step.to_dict() for step in report.steps],
        "promotion": report.promotion.to_dict(),
        "commerce_packet": dict(report.commerce_packet),
        "dry_run": report.dry_run,
        "live_actions_taken": report.live_actions_taken,
    }


def _fulfillment_cli_projection(
    report: Any,
    *,
    missing_cost_inputs: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Expose the existing fulfillment state projection, not raw internals."""
    reserve_classifications = set(report.reserve_classifications)
    reserve_classifications.update(f"unknown_cost:{name}" for name in missing_cost_inputs)
    return {
        "schema": "MarketOS.FulfillmentRiskDryRun.v1",
        "scenario_id": report.scenario_id,
        "order_id": report.order_id,
        "candidate_id": report.candidate_id,
        "workspace_id": report.workspace_id,
        "current_state": report.current_state,
        "state_path": list(report.state_path),
        "status": report.status,
        "blockers": list(report.blockers),
        "warnings": list(report.warnings),
        "next_human_action": report.next_human_action,
        "evidence_state": report.evidence_state,
        "evidence_refs": [item.to_dict() for item in report.evidence_refs],
        "sla_risks": list(report.sla_risks),
        "reserve_classifications": sorted(reserve_classifications),
        "risk_flags": list(report.risk_flags),
        "port_observations": [item.to_dict() for item in report.port_observations],
        "event_ids": [item.event_id for item in report.events],
        "event_replay_hashes": [item.replay_hash() for item in report.events],
        "dry_run": report.dry_run,
        "live_action_allowed": report.live_action_allowed,
        "provider_calls": report.provider_calls,
        "credentials_used": report.credentials_used,
        "external_mutations": report.external_mutations,
        "database_writes": report.database_writes,
    }


def _approval_ledger_cli_projection(report: Any) -> dict[str, Any]:
    """Expose the canonical offline approval boundary without raw records."""
    payload = report.to_dict()
    return {
        "report_version": report.report_version,
        "approval_count": report.approval_count,
        "pending_count": report.pending_count,
        "blocked_count": report.blocked_count,
        "simulation_count": len(report.simulations),
        "simulation_results": [
            {
                "action": item.action,
                "result": item.result,
                "can_be_approved_now": item.can_be_approved_now,
            }
            for item in report.simulations
        ],
        "safety_summary": payload["safety_summary"],
        "external_action_authorized": False,
    }


def _research_evidence(report: dict[str, Any], offer: dict[str, Any], lane: dict[str, Any]):
    from backend.economics.kernel import EVIDENCE_STATES, EvidenceRef

    evidence = offer["evidence"]
    confidence = evidence.get("confidence")
    source_state = evidence.get("state")
    kernel_state = "assumed" if source_state == "manual" else source_state
    if kernel_state not in EVIDENCE_STATES:
        kernel_state = "unknown"
    return EvidenceRef(
        evidence["reference_id"],
        source_type=evidence["source"],
        origin=lane["origin_country"],
        destination=lane["destination_country"],
        captured_at=evidence["captured_at"],
        valid_until=evidence.get("expires_at") or "",
        extraction_method=evidence["extraction_method"],
        evidence_state=kernel_state,
        confidence=None if confidence in (None, "unknown") else Decimal(str(confidence)),
        warnings=tuple(evidence.get("warnings", ())),
    )


def _research_lane(lane: dict[str, Any], evidence):
    from backend.economics.kernel import MarketLane

    return MarketLane(
        lane_id=f"mx-{lane['destination_country'].lower()}-{lane['warehouse'].lower().replace(' ', '-')}",
        origin=lane["origin_country"],
        ship_from=lane["ship_from_country"],
        warehouse=lane["warehouse"],
        destination_country=lane["destination_country"],
        destination_region=lane["destination_state_region"],
        currency=lane["currency"],
        return_destination=lane["return_destination"],
        delivery_promise=lane["delivery_promise"],
        support_language="es-MX",
        marketplace_permissions=tuple(lane.get("marketplace_eligibility", ())),
        compliance=tuple(lane.get("compliance_requirements", ())),
        evidence_refs=(evidence,),
    )


def _replay_scenario(
    *,
    fixture_name: str,
    builder_name: str,
    workspace_id: str,
    registry_path: str,
    research_manifest: dict[str, Any] | None = None,
    manifest_base_dir: Path | None = None,
    operator_confirmations: tuple[tuple[str, str, str], ...] = (),
) -> dict[str, Any]:
    from backend.contracts.events import Event
    from backend.economics.kernel import EvidenceRef, Money
    from backend.events.replay_certification import replay_summary
    from backend.events.repository import InMemoryEventRepository
    from backend.workspaces.client_workspace import ClientWorkspace
    from backend.workspaces.registry import WorkspaceRegistry
    from evaluation.commerce.dry_run_events import lifecycle_events
    from evaluation.commerce.dry_run_lifecycle import run_dry_run_lifecycle
    from evaluation.commerce.dry_run_scenarios import (
        commodity_electronics_rejected_candidate,
        high_ticket_deferred_candidate,
        hydroponics_positive_candidate,
        smart_pet_support_burden_candidate,
        solar_4g_security_blocked_candidate,
    )
    from evaluation.commerce.fulfillment_risk_lifecycle import (
        FixtureFulfillmentAdapter,
        build_named_scenario,
        run_fulfillment_risk_dry_run,
    )
    from evaluation.companyos.resource_execution_governor import (
        ExecutionDecisionRequest,
        evaluate_execution_request,
    )
    from evaluation.companyos.approval_ledger import build_approval_ledger, simulate_action
    from evaluation.trustos.client_workspace_isolation import export_client_evidence
    from scripts.research_to_decision import build_research_to_decision, load_manifest

    builders: dict[str, Callable[[], Any]] = {
        "commodity_electronics_rejected_candidate": commodity_electronics_rejected_candidate,
        "high_ticket_deferred_candidate": high_ticket_deferred_candidate,
        "hydroponics_positive_candidate": hydroponics_positive_candidate,
        "smart_pet_support_burden_candidate": smart_pet_support_burden_candidate,
        "solar_4g_security_blocked_candidate": solar_4g_security_blocked_candidate,
    }
    fixture_dir = ROOT / "tests" / "fixtures" / "research_to_decision"
    if research_manifest is None:
        manifest, manifest_base_dir = load_manifest(fixture_dir / fixture_name)
    else:
        manifest = research_manifest
    builder_parameters = inspect.signature(build_research_to_decision).parameters
    operator_contract_available = "operator_confirmed_supplier_documents" in builder_parameters
    if research_manifest is not None and not operator_contract_available:
        raise RuntimeError("operator attestation contract unavailable")
    research_kwargs: dict[str, Any] = {}
    if operator_contract_available:
        research_kwargs["operator_confirmed_supplier_documents"] = operator_confirmations
    research = build_research_to_decision(
        manifest,
        base_dir=manifest_base_dir or fixture_dir,
        **research_kwargs,
    )
    candidate_id = manifest["candidates"][0]["candidate_id"]
    audit = next(item for item in research["appendix"]["candidate_audit"] if item["candidate_id"] == candidate_id)
    offer = next(
        (
            item
            for item in research["appendix"]["supplier_offers"]
            if item["candidate_id"] == candidate_id
            and item.get("status") == "accepted"
        ),
        None,
    )
    if _supplier_evidence_class(offer) == "unavailable":
        offer = None
    if offer is not None:
        evidence = _research_evidence(research, offer, research["appendix"]["market_lane"])
    else:
        evidence = EvidenceRef(
            f"fixture:{candidate_id}:supplier-missing",
            source_type="fixture",
            origin=research["appendix"]["market_lane"]["origin_country"],
            destination=research["appendix"]["market_lane"]["destination_country"],
            captured_at=manifest["captured_at"],
            extraction_method="fixture",
            evidence_state="missing",
        )
    lane = _research_lane(research["appendix"]["market_lane"], evidence)
    supplier_evidence_state = (
        offer.get("evidence", {}).get("state")
        if offer is not None and offer.get("evidence", {}).get("state") in {"fixture", "manual", "derived"}
        else "missing"
    )
    compliance = _compliance_evaluation(
        research["appendix"]["market_lane"].get("destination_country")
    )
    template = builders[builder_name]()
    price_value = manifest["candidates"][0].get("target_sell_price") or (offer["price"]["amount"] if offer else "0")
    product_cost_value = offer["price"]["amount"] if offer else "0"
    shipping_value = offer["shipping"]["cost"] if offer else None
    missing_cost_inputs = _missing_supplier_cost_inputs(offer, shipping_value)
    money_evidence_state = "assumed" if supplier_evidence_state == "manual" else supplier_evidence_state
    money_source = {
        "fixture": "fixture",
        "manual": "manual",
        "derived": "derived",
        "missing": "missing",
    }[supplier_evidence_state]
    product_cost_missing = "product_cost" in missing_cost_inputs
    product_cost = Money(
        str("0" if product_cost_missing else product_cost_value), lane.currency,
        source="missing" if product_cost_missing else money_source,
        provenance="missing" if product_cost_missing else money_source,
        evidence_ref=evidence,
        evidence_state="missing" if product_cost_missing else money_evidence_state,
    )
    price = Money(
        str(price_value), lane.currency, source=money_source, provenance=money_source,
        evidence_ref=evidence, evidence_state=money_evidence_state,
    )
    assumptions = replace(
        template.assumptions,
        supplier_shipping=(
            Money(
                str(shipping_value), lane.currency, source=money_source, provenance=money_source,
                evidence_ref=evidence, evidence_state=money_evidence_state,
            )
            if "supplier_shipping" not in missing_cost_inputs
            else None
        ),
        payment_fee_fixed=Money("0", lane.currency, source=money_source, provenance=money_source, evidence_state=money_evidence_state, evidence_ref=evidence),
        cac=Money("0", lane.currency, source=money_source, provenance=money_source, evidence_state=money_evidence_state, evidence_ref=evidence),
        evidence_refs=(evidence,),
    )
    supplier_offer = template.supplier_offer if offer is not None else None
    if supplier_offer is not None and offer is not None:
        supplier_offer = replace(
            supplier_offer,
            supplier_id=offer["supplier"],
            offer_id=offer["offer_id"],
            supplier_sku=offer["exact_sku"],
            variant_id=offer["variant"],
            evidence_ref=evidence,
        )
    gate_satisfaction = dict(template.gate_satisfaction)
    if missing_cost_inputs:
        gate_satisfaction["economics"] = False
    gate_satisfaction.update(compliance["gate_satisfaction"])
    scenario = replace(
        template,
        candidate_id=candidate_id,
        workspace_id=workspace_id,
        price=price,
        product_cost=product_cost,
        lane=lane,
        assumptions=assumptions,
        supplier_offer=supplier_offer,
        evidence_state=supplier_evidence_state,
        gate_satisfaction=gate_satisfaction,
    )
    commerce = run_dry_run_lifecycle(scenario)
    if missing_cost_inputs:
        commerce = _mark_missing_cost_economics_unavailable(commerce, missing_cost_inputs)
    commerce_events = lifecycle_events(commerce, workspace_id=workspace_id, occurred_at=0.0)

    fulfillment_template = build_named_scenario("customer_return_merchant_paid")
    fulfillment = replace(
        fulfillment_template,
        scenario_id=f"{commerce.scenario_id}:fulfillment",
        order_id=f"order:{commerce.scenario_id}",
        candidate_id=candidate_id,
        workspace_id=workspace_id,
        lane=lane,
        price=price,
        product_cost=product_cost,
        assumptions=assumptions,
        supplier_offer=supplier_offer,
        evidence_refs=(evidence,),
        evidence_state="fixture",
        responsibilities=replace(
            fulfillment_template.responsibilities,
            evidence_refs=(evidence,),
            return_destination=lane.return_destination,
            delivery_promise=lane.delivery_promise,
        ),
    )
    fulfillment_report = run_fulfillment_risk_dry_run(
        fulfillment,
        adapter=FixtureFulfillmentAdapter.complete(),
        occurred_at=1.0,
    )
    fulfillment_events = tuple(fulfillment_report.events)
    events: tuple[Event, ...] = tuple((*commerce_events, *fulfillment_events))
    repository = InMemoryEventRepository()
    first_append = repository.append_many(events)
    second_append = repository.append_many(events)
    summary = replay_summary(list(repository.stream()))

    governor = evaluate_execution_request(
        ExecutionDecisionRequest(
            request_id=f"{commerce.scenario_id}:launch",
            action_type="launch_ad_experiment",
            domain="ads_content",
            owner_department="marketing",
            workspace_id=workspace_id,
            requested_amount=0.0,
            hypothesis="fixture-only commercial replay",
            success_metric="no_live_action",
            kill_threshold=1.0,
            approval_state="not_requested",
        )
    )
    approval_ledger = build_approval_ledger(
        generated_at="offline-deterministic",
        simulations=(simulate_action("launch_ad"),),
    )
    registry = WorkspaceRegistry(registry_path)
    workspace = registry.register(
        ClientWorkspace(
            workspace_id=workspace_id,
            name="commercial-replay-fixture",
            workspace_type="client_service",
        )
    )
    blockers = sorted(
        set(audit["hard_gates"])
        | set(commerce.promotion.blockers)
        | set(fulfillment_report.blockers)
        | set(compliance["blockers"])
    )
    evidence_required = sorted(
        set(audit["missing_evidence"])
        | set(compliance["blockers"])
        | {"human_review_before_external_action"}
    )
    supplier_class = _supplier_evidence_class(offer)
    provenance_scheme = {
        "fixture": "fixture",
        "manual_import": "manual",
        "derived": "derived",
        "unavailable": "offline",
    }[supplier_class]
    export = export_client_evidence(
        workspace=workspace,
        registry=registry,
        provenance=f"{provenance_scheme}://commercial-replay/{commerce.scenario_id}",
        # TrustOS uses its own bounded export status vocabulary; the source
        # fixture state remains explicit in the surrounding result.
        evidence_state="requires_review",
        payload={
            "workspace_id": workspace.workspace_id,
            "status": "blocked" if blockers else "draft",
            "blockers": blockers,
            "evidence_required": evidence_required,
            "approvals_required": ["human_review", "approval_ledger_before_external_action"],
            "next_actions": ["review_fixture_evidence", "keep_external_actions_disabled"],
        },
    )
    event_replay_hashes = list(summary["hash_sequence"])
    result = {
        "scenario": commerce.scenario_id,
        "candidate_id": candidate_id,
        "supplier_evidence_state": supplier_evidence_state,
        "compliance": compliance,
        "evidence_classes": _scenario_evidence_classes(
            offer,
            missing_cost_inputs=missing_cost_inputs,
            research_evidence_state=research["appendix"]["market_lane"].get("evidence_state", "unknown"),
            compliance_evidence_class=compliance["evidence_classification"],
        ),
        "supplier_offer": {
            "offer_id": offer["offer_id"],
            "exact_sku": offer["exact_sku"],
            "status": offer["status"],
        } if offer is not None else None,
        "research": {
            "replay_fingerprint": research["appendix"]["replay_fingerprint"],
            "market_lane": research["appendix"]["market_lane"],
            "freshness": audit["freshness"],
            "promotion_state": audit["promotion_lifecycle"][-1]["next_state"],
            "supplier_documented": any(
                item["next_state"] == "supplier_documented"
                for item in audit["promotion_lifecycle"]
            ),
            "blockers": list(audit["hard_gates"]),
        },
        "commerce": _commerce_cli_projection(commerce),
        "fulfillment": _fulfillment_cli_projection(
            fulfillment_report,
            missing_cost_inputs=missing_cost_inputs,
        ),
        "governor": governor.to_dict(),
        "approval_ledger": _approval_ledger_cli_projection(approval_ledger),
        "client_export": export.to_dict(),
        # These are lifecycle events, not financial-ledger observations. The
        # canonical summary defaults empty ledger aggregates to numeric zero;
        # omit that unsupported projection rather than imply observed zeroes.
        "event_summary": {
            key: value for key, value in summary.items() if key != "ledger"
        },
        "event_ids": [event.event_id for event in events],
        "event_replay_hashes": event_replay_hashes,
        # Derive this only from canonical event replay hashes; packet-level
        # fingerprinting remains the CLI's existing authority.
        "replay_hash": _canonical_fingerprint(event_replay_hashes),
        "event_count": len(events),
        "first_append_count": sum(item.appended for item in first_append),
        "second_append_idempotent_count": sum(item.idempotent for item in second_append),
        "launch_authorized": False,
        "external_mutations": False,
        "provider_calls": False,
        "credentials_used": False,
        "database_writes": False,
        "evidence_classification": supplier_class,
    }
    if summary["sequence_issues"] or summary["live_authority_violations"]:
        raise RuntimeError("canonical replay event validation failed")
    return result


def run_consolidated_scenario(fixture_name: str, builder_name: str) -> dict[str, Any]:
    """Run one fixture through existing authorities without persistent output."""
    with tempfile.TemporaryDirectory(prefix="marketos-commercial-replay-") as temporary_dir:
        return _replay_scenario(
            fixture_name=fixture_name,
            builder_name=builder_name,
            workspace_id="workspace_commercial_replay_fixture",
            registry_path=str(Path(temporary_dir) / "workspaces.json"),
        )


def run_operator_scenario(
    manifest_path: str | Path,
    *,
    candidate_id: str,
    scenario_template: str,
    operator_confirmations: tuple[tuple[str, str, str], ...] = (),
) -> dict[str, Any]:
    """Run one bounded operator manifest through the existing replay path.

    The manifest and exact local attestations are normalized only by the
    existing research-to-decision authority. The selected scenario template
    is explicit; candidate titles/categories are never used for routing.
    """
    try:
        from scripts.research_to_decision import (
            build_research_to_decision,
            load_manifest,
        )

        if "operator_confirmed_supplier_documents" not in inspect.signature(
            build_research_to_decision
        ).parameters:
            return {
                "result": "unavailable",
                "evidence_classification": "unavailable",
                "reason": "supplier_attestation_contract_unavailable",
            }
        manifest, base_dir = load_manifest(manifest_path)
        candidates = manifest.get("candidates")
        if (
            not isinstance(candidates, list)
            or len(candidates) != 1
            or not isinstance(candidates[0], dict)
            or candidates[0].get("candidate_id") != candidate_id
        ):
            return {
                "result": "unavailable",
                "evidence_classification": "unavailable",
                "reason": "operator_candidate_rejected",
            }
        from evaluation.commerce.dry_run_scenarios import SCENARIO_BUILDERS

        if not any(builder.__name__ == scenario_template for builder in SCENARIO_BUILDERS):
            return {
                "result": "unavailable",
                "evidence_classification": "unavailable",
                "reason": "operator_template_rejected",
            }
        replay_rows = []
        for _ in range(2):
            with tempfile.TemporaryDirectory(prefix="marketos-commercial-replay-") as temporary_dir:
                replay_rows.append(
                    _replay_scenario(
                        fixture_name="",
                        builder_name=scenario_template,
                        workspace_id="workspace_commercial_replay_operator",
                        registry_path=str(Path(temporary_dir) / "workspaces.json"),
                        research_manifest=copy.deepcopy(manifest),
                        manifest_base_dir=base_dir,
                        operator_confirmations=operator_confirmations,
                    )
                )
        first_bytes = json.dumps(
            replay_rows[0], sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        second_bytes = json.dumps(
            replay_rows[1], sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        row = {**replay_rows[0], "replay_equal": first_bytes == second_bytes}
        return {
            "result": "actual",
            "evidence_classification": row["evidence_classes"]["supplier_evidence"],
            "evidence_class_vocabulary": list(EVIDENCE_CLASS_VOCABULARY),
            "rows": [row],
        }
    except Exception:  # noqa: BLE001 - never reflect paths or imported values
        return {
            "result": "unavailable",
            "evidence_classification": "unavailable",
            "reason": "operator_manifest_rejected",
        }


def run_scenarios(
    *,
    manifest_path: str | Path | None = None,
    candidate_id: str | None = None,
    scenario_template: str | None = None,
    operator_confirmations: tuple[tuple[str, str, str], ...] = (),
) -> dict[str, Any]:
    if manifest_path is not None or candidate_id is not None or scenario_template is not None or operator_confirmations:
        if manifest_path is None or not candidate_id or not scenario_template:
            return {
                "result": "unavailable",
                "evidence_classification": "unavailable",
                "reason": "operator_manifest_rejected",
            }
        return run_operator_scenario(
            manifest_path,
            candidate_id=candidate_id,
            scenario_template=scenario_template,
            operator_confirmations=operator_confirmations,
        )
    try:
        from evaluation.commerce.dry_run_scenarios import SCENARIO_BUILDERS
    except Exception as exc:  # noqa: BLE001
        return _classify_import_error(exc)

    rows: list[dict[str, Any]] = []
    builder_names = {builder.__name__ for builder in SCENARIO_BUILDERS}
    for fixture_name, builder_name in _REPLAY_INPUTS:
        if builder_name not in builder_names:
            return _classify_import_error(ValueError(f"missing scenario builder: {builder_name}"))
        started = time.perf_counter()
        first = run_consolidated_scenario(fixture_name, builder_name)
        second = run_consolidated_scenario(fixture_name, builder_name)
        wall_ms = round((time.perf_counter() - started) * 1000, 3)
        replay_equal = first == second
        payload = json.dumps(first, sort_keys=True, default=str)
        rows.append(
            {
                **first,
                "replay_equal": replay_equal,
                "replay_fingerprint": _canonical_fingerprint(first),
                "wall_ms": wall_ms,
                "output_bytes": len(payload.encode("utf-8")),
                "failure_class": "blocked" if first["commerce"]["promotion"]["blockers"] else "ok",
            }
        )
    return {
        "result": "actual" if rows else "unavailable",
        "evidence_classification": "fixture",
        "evidence_class_vocabulary": list(EVIDENCE_CLASS_VOCABULARY),
        "rows": rows,
    }


def run_service_clients() -> dict[str, Any]:
    try:
        from decimal import Decimal

        from backend.economics.kernel import Money
        from evaluation.companyos.service_engagement import build_service_engagement
    except Exception as exc:  # noqa: BLE001
        return _classify_import_error(exc)

    thin = build_service_engagement(
        "eng-insufficient",
        "Managed Acquisition and CRO",
        "Thin Data Client",
        service_fee=Money("1500", "USD"),
        inputs={},
    ).to_dict()
    adequate = build_service_engagement(
        "eng-adequate",
        "Managed Acquisition and CRO",
        "Adequate Data Client",
        service_fee=Money("1500", "USD"),
        inputs={
            "ad_spend": Money("10000", "USD"),
            "contribution_margin": Decimal("0.40"),
            "roas_before": Decimal("1.8"),
            "roas_after": Decimal("2.3"),
            "cac_before": Money("25", "USD"),
            "cac_after": Money("18", "USD"),
            "delivery_hours": Decimal("24"),
            "capacity_hours": Decimal("160"),
        },
    ).to_dict()
    return {
        "result": "actual",
        "evidence_classification": "fixture",
        "insufficient_status": thin.get("status"),
        "adequate_status": adequate.get("status"),
        "thin_economics_is_none": thin.get("economics") is None,
    }


def isolated_perf_note() -> dict[str, Any]:
    """#255 remains an isolated benchmark. Do not treat import success as production."""
    try:
        import evaluation.perf.commerce_engine as isolated  # type: ignore
    except Exception:
        return {
            "pr_255_module": "not_present_on_this_branch",
            "classification": "isolated_benchmark_harness",
            "production_path": False,
            "recorded_before_ms": 25.172,
            "recorded_after_ms": 6.222,
            "recorded_environment": "authoring sandbox Python 3.12 fixture-only",
            "evidence_classification": "fixture",
        }
    return {
        "pr_255_module": getattr(isolated, "SCHEMA", "present"),
        "classification": "isolated_benchmark_harness",
        "production_path": False,
        "warning": "module imported only for classification; not a second commerce authority",
        "evidence_classification": "fixture",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--candidate-id")
    parser.add_argument("--scenario-template", choices=tuple(dict.fromkeys(name for _, name in _REPLAY_INPUTS)))
    parser.add_argument(
        "--confirm-supplier-document",
        action="append",
        nargs=3,
        default=[],
        metavar=("OFFER_ID", "EXACT_SKU", "REFERENCE"),
    )
    args = parser.parse_args()
    report = {
        "schema": "commercial-replay-performance-integration-v2",
        "evidence_class_vocabulary": list(EVIDENCE_CLASS_VOCABULARY),
        "repository": "ChristianV997/MarketOS",
        "commit": _git_sha(),
        "base_sha": _base_sha(),
        "command": "python scripts/run_commercial_replay_integration.py --json",
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "windows_operator_packet": "unavailable",
        },
        "scenarios": run_scenarios(
            manifest_path=args.manifest,
            candidate_id=args.candidate_id,
            scenario_template=args.scenario_template,
            operator_confirmations=tuple(tuple(item) for item in args.confirm_supplier_document),
        ),
        "service_clients": run_service_clients(),
        "isolated_perf_harness_255": isolated_perf_note(),
        "ci": "ci_unavailable",
        "missing_infrastructure": [
            "Windows operator checkout",
            "GitHub Actions runner (ci_unavailable)",
            "full-repo quality gate execution",
        ],
        "rollback": "close PR / delete exclusive files; #248 kernel untouched",
    }
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    return 0 if args.json or report["scenarios"].get("result") in {"actual", "unavailable"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

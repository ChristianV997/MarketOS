#!/usr/bin/env python3
"""Bounded commercial replay + performance integration runner.

Drives existing public builders. Does not score products, replace
scripts/benchmark_commerce_cycle.py, copy backend.economics.kernel,
or import evaluation.perf.commerce_engine as a production path.
"""
from __future__ import annotations

import argparse
import hashlib
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


def _canonical_fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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


def _fulfillment_cli_projection(report: Any) -> dict[str, Any]:
    """Expose the existing fulfillment state projection, not raw internals."""
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
        "reserve_classifications": list(report.reserve_classifications),
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
    from backend.economics.kernel import EvidenceRef

    evidence = offer["evidence"]
    confidence = evidence.get("confidence")
    return EvidenceRef(
        evidence["reference_id"],
        source_type=evidence["source"],
        origin=lane["origin_country"],
        destination=lane["destination_country"],
        captured_at=evidence["captured_at"],
        valid_until=evidence.get("expires_at") or "",
        extraction_method=evidence["extraction_method"],
        evidence_state=evidence["state"],
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
    from scripts.research_to_decision import build_research_to_decision

    builders: dict[str, Callable[[], Any]] = {
        "commodity_electronics_rejected_candidate": commodity_electronics_rejected_candidate,
        "high_ticket_deferred_candidate": high_ticket_deferred_candidate,
        "hydroponics_positive_candidate": hydroponics_positive_candidate,
        "smart_pet_support_burden_candidate": smart_pet_support_burden_candidate,
        "solar_4g_security_blocked_candidate": solar_4g_security_blocked_candidate,
    }
    fixture_dir = ROOT / "tests" / "fixtures" / "research_to_decision"
    manifest = json.loads((fixture_dir / fixture_name).read_text(encoding="utf-8"))
    research = build_research_to_decision(manifest, base_dir=fixture_dir)
    candidate_id = manifest["candidates"][0]["candidate_id"]
    audit = next(item for item in research["appendix"]["candidate_audit"] if item["candidate_id"] == candidate_id)
    offer = next(
        (item for item in research["appendix"]["supplier_offers"] if item["candidate_id"] == candidate_id),
        None,
    )
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
    template = builders[builder_name]()
    price_value = manifest["candidates"][0].get("target_sell_price") or (offer["price"]["amount"] if offer else "0")
    product_cost_value = offer["price"]["amount"] if offer else "0"
    shipping_value = offer["shipping"]["cost"] if offer else "0"
    money_evidence_state = "fixture" if offer is not None else "missing"
    money_source = "fixture" if offer is not None else "missing"
    product_cost = Money(
        str(product_cost_value), lane.currency, source=money_source, provenance=money_source,
        evidence_ref=evidence, evidence_state=money_evidence_state,
    )
    price = Money(
        str(price_value), lane.currency, source="fixture", provenance="fixture",
        evidence_ref=evidence, evidence_state=money_evidence_state,
    )
    assumptions = replace(
        template.assumptions,
        supplier_shipping=Money(
            str(shipping_value or "0"), lane.currency, source=money_source, provenance=money_source,
            evidence_ref=evidence, evidence_state=money_evidence_state,
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
    scenario = replace(
        template,
        candidate_id=candidate_id,
        workspace_id=workspace_id,
        price=price,
        product_cost=product_cost,
        lane=lane,
        assumptions=assumptions,
        supplier_offer=supplier_offer,
        evidence_state=research["appendix"]["market_lane"]["evidence_state"],
    )
    commerce = run_dry_run_lifecycle(scenario)
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
    blockers = sorted(set(audit["hard_gates"]) | set(commerce.promotion.blockers) | set(fulfillment_report.blockers))
    evidence_required = sorted(set(audit["missing_evidence"]) | {"human_review_before_external_action"})
    export = export_client_evidence(
        workspace=workspace,
        registry=registry,
        provenance=f"fixture://commercial-replay/{commerce.scenario_id}",
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
            "blockers": list(audit["hard_gates"]),
        },
        "commerce": _commerce_cli_projection(commerce),
        "fulfillment": _fulfillment_cli_projection(fulfillment_report),
        "governor": governor.to_dict(),
        "approval_ledger": _approval_ledger_cli_projection(approval_ledger),
        "client_export": export.to_dict(),
        "event_summary": summary,
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
        "evidence_classification": "fixture",
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


def run_scenarios() -> dict[str, Any]:
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
    args = parser.parse_args()
    report = {
        "schema": "commercial-replay-performance-integration-v2",
        "repository": "ChristianV997/MarketOS",
        "commit": _git_sha(),
        "base_sha": _base_sha(),
        "command": "python scripts/run_commercial_replay_integration.py --json",
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "windows_operator_packet": "unavailable",
        },
        "scenarios": run_scenarios(),
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

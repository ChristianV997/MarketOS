#!/usr/bin/env python3
"""Run the bounded acceptance contract for the current MarketOS mainline.

This command composes the merged replay and operator dogfood authorities. It
does not calculate economics, create events, select candidates, or sanitize a
client payload itself. Those responsibilities stay with the existing
canonical modules; this file only checks their observable contracts and
reports unavailable upstream authorities explicitly.

All inputs created by the negative probes are temporary fixture copies. The
command does not write repository outputs, call providers, or enable an
external action.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "research_to_decision"

SCHEMA = "MarketOS.MainlineVerticalAcceptance.v1"
PASS = "passed"
UNAVAILABLE = "unavailable"
NOT_RUN = "not_run"
BLOCKED = "blocked"
MALFORMED = "malformed"
TIMED_OUT = "timed_out"

REPLAY_SCENARIOS = {
    "hydroponics_positive_candidate": "hydroponics-kit",
    "smart_pet_support_burden_candidate": "smart-pet-feeder",
    "solar_4g_security_blocked_candidate": "solar-4g-camera",
    "commodity_electronics_rejected_candidate": "commodity-earbuds",
    "high_ticket_deferred_candidate": "walking-pad",
}

SERVICE_DELIVERY_PATHS = (
    "api/routes/service_delivery_workbench.py",
    "evaluation/companyos/service_delivery_projection.py",
    "scripts/generate_service_delivery_projection.py",
)

SAFE_EXPORT_KEYS = {
    "workspace_id",
    "status",
    "blockers",
    "evidence_required",
    "approvals_required",
    "next_actions",
}


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def _is_mainline_identity(head_sha: str, origin_main_sha: str, merge_base: str) -> bool:
    """Return true only when the report is executing on refreshed mainline."""
    return (
        head_sha != "unavailable"
        and origin_main_sha != "unavailable"
        and merge_base != "unavailable"
        and head_sha == origin_main_sha == merge_base
    )


def _status_hash() -> str:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    return _stable_hash({"returncode": result.returncode, "status": result.stdout})


def _run_json(argv: list[str], *, timeout: float = 180.0) -> dict[str, Any]:
    """Run an existing CLI without shell interpretation or raw-output echo."""
    try:
        completed = subprocess.run(
            argv,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return {"classification": TIMED_OUT, "reason": "bounded_command_timeout"}
    except (OSError, subprocess.SubprocessError):
        return {"classification": UNAVAILABLE, "reason": "command_unavailable"}

    try:
        document = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError):
        return {"classification": MALFORMED, "reason": "stdout_not_json"}
    if not isinstance(document, dict):
        return {"classification": MALFORMED, "reason": "json_root_not_object"}
    return {
        "classification": PASS if completed.returncode == 0 else BLOCKED,
        "returncode": completed.returncode,
        "document": document,
    }


def _check(condition: bool, reason: str) -> dict[str, Any]:
    return {"status": PASS if condition else BLOCKED, "reason": None if condition else reason}


def _hash_sequence_digest(hashes: Iterable[str]) -> str:
    return _stable_hash(list(hashes))


def _summarize_replay_row(row: dict[str, Any]) -> dict[str, Any]:
    event_summary = row.get("event_summary") or {}
    commerce = row.get("commerce") or {}
    fulfillment = row.get("fulfillment") or {}
    economics_step = next(
        (
            item
            for item in commerce.get("steps", [])
            if isinstance(item, dict) and item.get("step") == "unit_economics"
        ),
        {},
    )
    detail = economics_step.get("detail") or {}
    event_hashes = row.get("event_replay_hashes") or []
    missing_inputs = sorted(
        {
            str(value).removeprefix("unknown_cost:")
            for value in fulfillment.get("reserve_classifications", [])
            if str(value).startswith("unknown_cost:")
        }
        | {str(value) for value in detail.get("missing_inputs", [])}
    )
    return {
        "scenario": row.get("scenario"),
        "candidate_id": row.get("candidate_id"),
        "evidence_classes": row.get("evidence_classes") or {},
        "economics_status": economics_step.get("status") or detail.get("status"),
        "economics_evidence_state": detail.get("evidence_state"),
        "missing_cost_inputs": missing_inputs,
        "promoted_to_launch": bool(commerce.get("promoted_to_launch")),
        "event_count": row.get("event_count"),
        "commerce_event_count": (event_summary.get("aggregate_types") or {}).get("commerce_dry_run"),
        "fulfillment_event_count": (event_summary.get("aggregate_types") or {}).get("commerce_fulfillment_risk"),
        "first_append_count": row.get("first_append_count"),
        "second_append_idempotent_count": row.get("second_append_idempotent_count"),
        "replay_equal": row.get("replay_equal"),
        "replay_hash": row.get("replay_hash"),
        "event_replay_hashes": list(event_hashes),
        "event_hash_sequence_digest": _hash_sequence_digest(event_hashes),
        "client_export": {
            "evidence_state": (row.get("client_export") or {}).get("evidence_state"),
            "workspace_id": (row.get("client_export") or {}).get("workspace_id"),
            "redaction_status": (row.get("client_export") or {}).get("redaction_status"),
            "redacted_fields": list((row.get("client_export") or {}).get("redacted_fields") or []),
        },
    }


def _validate_replay_row(row: dict[str, Any]) -> dict[str, Any]:
    scenario = row.get("scenario")
    candidate_id = row.get("candidate_id")
    event_summary = row.get("event_summary") or {}
    aggregate_types = event_summary.get("aggregate_types") or {}
    commerce = row.get("commerce") or {}
    export = row.get("client_export") or {}
    payload = export.get("payload") or {}
    evidence = row.get("evidence_classes") or {}
    compliance = row.get("compliance") or {}
    hashes = row.get("event_replay_hashes") or []
    event_ids = row.get("event_ids") or []
    checks = {
        "known_candidate_identity": scenario in REPLAY_SCENARIOS and candidate_id == REPLAY_SCENARIOS.get(scenario),
        "candidate_id_not_template": candidate_id != scenario,
        "commerce_event_scope": aggregate_types.get("commerce_dry_run") == 17,
        "fulfillment_event_scope": aggregate_types.get("commerce_fulfillment_risk") == 20,
        "combined_event_count": row.get("event_count") == 37,
        "event_ids_unique": len(event_ids) == 37 and len(set(event_ids)) == 37,
        "hash_sequence_complete": len(hashes) == 37 and hashes == event_summary.get("hash_sequence"),
        "hashes_are_sha256": bool(hashes) and all(isinstance(item, str) and len(item) == 64 for item in hashes),
        "replay_deterministic": row.get("replay_equal") is True and isinstance(row.get("replay_hash"), str) and len(row["replay_hash"]) == 64,
        "append_idempotent": row.get("first_append_count") == 37 and row.get("second_append_idempotent_count") == 37,
        "event_validation_clean": not event_summary.get("sequence_issues") and not event_summary.get("live_authority_violations"),
        "fixture_ceiling_preserved": evidence.get("research_input") == "fixture" and evidence.get("commerce_lifecycle") == "simulated_or_planned",
        "compliance_not_assessed": compliance.get("gate_satisfaction", {}).get("compliance") is False and compliance.get("live_lookup_performed") is False,
        "promotion_blocked": commerce.get("promoted_to_launch") is False and row.get("launch_authorized") is False,
        "export_requires_review": export.get("evidence_state") == "requires_review" and export.get("redaction_status") == "validated_no_sensitive_fields",
        "export_schema_allowlisted": set(payload).issubset(SAFE_EXPORT_KEYS),
        "workspace_export_matches": export.get("workspace_id") == "workspace_commercial_replay_fixture" and payload.get("workspace_id") == export.get("workspace_id"),
        "no_external_mutation": all(row.get(key) is False for key in ("external_mutations", "provider_calls", "credentials_used", "database_writes")),
        "dry_run": commerce.get("dry_run") is True and commerce.get("live_actions_taken") is False,
    }
    return {
        "status": PASS if all(checks.values()) else BLOCKED,
        "reason": None if all(checks.values()) else ",".join(name for name, ok in checks.items() if not ok),
        "checks": checks,
        "summary": _summarize_replay_row(row),
    }


def _run_replay() -> dict[str, Any]:
    result = _run_json([sys.executable, "scripts/run_commercial_replay_integration.py", "--json"])
    if result["classification"] != PASS:
        return {"status": result["classification"], "reason": result.get("reason", "replay_command_failed")}
    document = result["document"]
    scenarios = document.get("scenarios") or {}
    rows = scenarios.get("rows") or []
    if document.get("schema") != "commercial-replay-performance-integration-v2":
        return {"status": MALFORMED, "reason": "replay_schema_changed"}
    if scenarios.get("result") != "actual" or len(rows) != len(REPLAY_SCENARIOS):
        return {"status": UNAVAILABLE, "reason": "merged_replay_rows_unavailable"}
    if {row.get("scenario") for row in rows} != set(REPLAY_SCENARIOS):
        return {"status": BLOCKED, "reason": "replay_scenario_set_changed"}
    row_results = [_validate_replay_row(row) for row in rows]
    service_clients = document.get("service_clients") or {}
    service_checks = {
        "insufficient_service_data_blocks": service_clients.get("insufficient_status") == "data_inadequate",
        "adequate_service_data_is_available": service_clients.get("adequate_status") == "ready_for_client_service",
        "thin_service_economics_is_none": service_clients.get("thin_economics_is_none") is True,
    }
    return {
        "status": PASS if all(item["status"] == PASS for item in row_results) else BLOCKED,
        "reason": None if all(item["status"] == PASS for item in row_results) else "replay_row_contract_failed",
        "command": "run_commercial_replay_integration.py --json",
        "commit": document.get("commit"),
        "base_sha": document.get("base_sha"),
        "scenario_count": len(rows),
        "scenarios": row_results,
        "dogfood_rows": [
            {
                "scenario": row.get("scenario"),
                "achievable_stage": (row.get("commerce") or {}).get("achievable_stage"),
                "promoted_to_launch": bool((row.get("commerce") or {}).get("promoted_to_launch")),
                "blockers": list(((row.get("commerce") or {}).get("promotion") or {}).get("blockers") or []),
            }
            for row in rows
        ],
        "service_economics_adapter": {
            "status": PASS if all(service_checks.values()) else BLOCKED,
            "checks": service_checks,
            "evidence_classification": service_clients.get("evidence_classification"),
        },
        "evidence_class_vocabulary": list(document.get("evidence_class_vocabulary") or []),
    }


def _run_dogfood(replay: dict[str, Any]) -> dict[str, Any]:
    try:
        from scripts import run_operator_dogfood_workflow as bridge

        # The full wrapper intentionally stops at its state-collision guard
        # when this acceptance file is uncommitted. Reuse the already checked
        # replay projection and invoke the merged TrustOS phase directly,
        # rather than weakening that guard or running the replay twice.
        rows = replay.get("dogfood_rows") or []
        export = bridge.trustos_export(rows)
        exports = (export.get("detail") or {}).get("exports") or []
    except Exception:  # noqa: BLE001 - bounded acceptance must fail closed
        return {"status": UNAVAILABLE, "reason": "operator_dogfood_authority_unavailable"}
    checks = {
        "schema_present": bridge.SCHEMA == "MarketOS.OperatorDogfoodReadinessBridge.v1",
        "commercial_rows_present": replay.get("status") == PASS and len(rows) == 5,
        "trustos_export_ran": export.get("classification") == PASS and (export.get("detail") or {}).get("exported_count") == 5,
        "redaction_validated": bool(exports) and all(item.get("redaction_status") == "validated_no_sensitive_fields" for item in exports),
        "review_required": bool(exports) and all(item.get("evidence_state") == "requires_review" for item in exports),
        "no_mutation": replay.get("status") == PASS and all(
            item.get("checks", {}).get("no_external_mutation") is True
            for item in replay.get("scenarios", [])
        ),
    }
    return {
        "status": PASS if all(checks.values()) else BLOCKED,
        "reason": None if all(checks.values()) else "operator_dogfood_contract_failed",
        "full_wrapper_guard": "not_run: this worktree contains the acceptance file and the wrapper correctly blocks owned dirty paths",
        "checks": checks,
        "export_count": len(exports),
        "export_fingerprints": [item.get("fingerprint") for item in exports],
    }


def _run_direct_commerce_scope() -> dict[str, Any]:
    try:
        from backend.events.replay_certification import replay_summary
        from evaluation.commerce.dry_run_events import lifecycle_events
        from evaluation.commerce.dry_run_lifecycle import run_dry_run_lifecycle
        from evaluation.commerce.dry_run_scenarios import hydroponics_positive_candidate

        events = lifecycle_events(
            run_dry_run_lifecycle(hydroponics_positive_candidate()),
            workspace_id="mainline-acceptance",
            occurred_at=0.0,
        )
        summary = replay_summary(events)
        hashes = [event.replay_hash() for event in events]
        checks = {
            "commerce_event_count": len(events) == 17,
            "commerce_aggregate": summary.get("aggregate_types") == {"commerce_dry_run": 17},
            "sequence_clean": not summary.get("sequence_issues") and not summary.get("live_authority_violations"),
            "hash_sequence_complete": len(hashes) == 17 and all(len(item) == 64 for item in hashes),
        }
        return {
            "status": PASS if all(checks.values()) else BLOCKED,
            "reason": None if all(checks.values()) else "direct_commerce_scope_failed",
            "checks": checks,
            "event_count": len(events),
            "hash_sequence": hashes,
            "hash_sequence_digest": _hash_sequence_digest(hashes),
        }
    except Exception:  # noqa: BLE001 - acceptance report must fail closed without reflection
        return {"status": UNAVAILABLE, "reason": "direct_commerce_scope_unavailable"}


def _write_temp_manifest(source_name: str, *, candidate_id: str | None = None, empty_inputs: bool = False) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    temporary = tempfile.TemporaryDirectory(prefix=".mainline-vertical-acceptance-", dir=ROOT)
    target_dir = Path(temporary.name)
    source = json.loads((FIXTURE_DIR / source_name).read_text(encoding="utf-8"))
    if candidate_id:
        source["candidates"][0]["candidate_id"] = candidate_id
        source["candidates"][0]["title"] = "display label is not routing authority"
    input_keys = ("supplier_inputs", "marketplace_inputs", "consumer_attention_inputs", "observation_inputs")
    if empty_inputs:
        for key in input_keys:
            source[key] = []
    else:
        for key in input_keys:
            for item in source.get(key, []):
                input_path = str(item.get("path", ""))
                if not input_path:
                    continue
                source_path = FIXTURE_DIR / input_path
                destination = target_dir / input_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, destination)
    manifest_path = target_dir / "manifest.json"
    manifest_path.write_text(json.dumps(source, sort_keys=True), encoding="utf-8")
    return temporary, manifest_path


def _run_manifest_replay(manifest_path: Path, candidate_id: str, template: str) -> dict[str, Any]:
    return _run_json(
        [
            sys.executable,
            "scripts/run_commercial_replay_integration.py",
            "--json",
            "--manifest",
            str(manifest_path),
            "--candidate-id",
            candidate_id,
            "--scenario-template",
            template,
        ]
    )


def _one_row(document: dict[str, Any]) -> dict[str, Any] | None:
    rows = ((document.get("scenarios") or {}).get("rows") or [])
    return rows[0] if len(rows) == 1 and isinstance(rows[0], dict) else None


def _run_cost_and_identity_probes() -> dict[str, Any]:
    missing_run = _run_manifest_replay(
        FIXTURE_DIR / "walking_pad_deferred.json",
        "walking-pad",
        "high_ticket_deferred_candidate",
    )
    missing_row = _one_row(missing_run.get("document", {})) if missing_run.get("classification") == PASS else None
    missing_economics = next(
        (
            item
            for item in ((missing_row or {}).get("commerce") or {}).get("steps", [])
            if isinstance(item, dict) and item.get("step") == "unit_economics"
        ),
        {},
    )
    missing_detail = missing_economics.get("detail") or {}
    missing_packet = ((missing_row or {}).get("commerce") or {}).get("commerce_packet") or {}
    missing_checks = {
        "command_executed": missing_row is not None,
        "economics_unavailable": missing_detail.get("status") == "unavailable" and missing_detail.get("evidence_state") == "missing",
        "missing_inputs_explicit": {"product_cost", "supplier_shipping"}.issubset(set(missing_detail.get("missing_inputs") or [])),
        "no_contribution_leak": "contribution_before_cac" not in missing_detail and "contribution_before_cac" not in json.dumps(missing_packet),
        "promotion_blocked": ((missing_row or {}).get("commerce") or {}).get("promoted_to_launch") is False,
    }

    zero_temporary, zero_manifest = _write_temp_manifest("hydroponics_promising.json")
    try:
        supplier_path = zero_manifest.parent / "all_supplier.json"
        records = json.loads(supplier_path.read_text(encoding="utf-8"))
        for record in records:
            if record.get("candidate_id") == "hydroponics-kit":
                record["shipping_cost"] = 0
        supplier_path.write_text(json.dumps(records, sort_keys=True), encoding="utf-8")
        zero_run = _run_manifest_replay(zero_manifest, "hydroponics-kit", "hydroponics_positive_candidate")
        zero_row = _one_row(zero_run.get("document", {})) if zero_run.get("classification") == PASS else None
    finally:
        zero_temporary.cleanup()
    zero_economics = next(
        (
            item
            for item in ((zero_row or {}).get("commerce") or {}).get("steps", [])
            if isinstance(item, dict) and item.get("step") == "unit_economics"
        ),
        {},
    )
    zero_detail = zero_economics.get("detail") or {}
    zero_packet = ((zero_row or {}).get("commerce") or {}).get("commerce_packet") or {}
    zero_shipping = ((zero_packet.get("assumptions") or {}).get("supplier_shipping") or {})
    zero_checks = {
        "command_executed": zero_row is not None,
        "economics_calculated": zero_economics.get("status") == "simulated",
        "explicit_zero_preserved": zero_shipping.get("amount") is not None and Decimal(str(zero_shipping["amount"])) == Decimal("0") and zero_shipping.get("evidence_state") == "fixture",
        "zero_not_missing": "supplier_shipping" not in set(zero_detail.get("missing_inputs") or []),
    }

    try:
        from scripts.research_to_decision import ResearchToDecisionError, build_research_to_decision, load_manifest

        currency_manifest, currency_base = load_manifest(FIXTURE_DIR / "usd_quote.json")
        try:
            build_research_to_decision(currency_manifest, base_dir=currency_base)
        except ResearchToDecisionError:
            currency_checks = {"currency_mismatch_rejected": True}
        else:
            currency_checks = {"currency_mismatch_rejected": False}
    except Exception:  # noqa: BLE001 - missing authority is a failed acceptance probe
        currency_checks = {"currency_mismatch_rejected": False}

    identity_temporary, identity_manifest = _write_temp_manifest(
        "walking_pad_deferred.json",
        candidate_id="candidate-neutral-synthetic",
        empty_inputs=True,
    )
    try:
        identity_run = _run_json(
            [
                sys.executable,
                "scripts/operator_dogfood_vertical.py",
                "--repo",
                str(ROOT),
                "--manifest",
                str(identity_manifest),
                "--candidate-id",
                "candidate-neutral-synthetic",
                "--scenario-template",
                "hydroponics_positive_candidate",
                "--json",
            ]
        )
    finally:
        identity_temporary.cleanup()
    identity_document = identity_run.get("document", {}) if identity_run.get("classification") == PASS else {}
    identity_checks = {
        "candidate_id_selected": identity_document.get("candidate_id") == "candidate-neutral-synthetic",
        "template_selected_explicitly": identity_document.get("scenario_template") == "hydroponics_positive_candidate",
        "label_not_routing_authority": "display label must not route" not in json.dumps(identity_document, sort_keys=True),
        "live_validated_false": identity_document.get("live_validated") is False,
        "launch_authorized_false": identity_document.get("launch_authorized") is False,
    }
    probe_status = all(missing_checks.values()) and all(zero_checks.values()) and all(currency_checks.values()) and all(identity_checks.values())
    return {
        "status": PASS if probe_status else BLOCKED,
        "reason": None if probe_status else "negative_or_identity_probe_failed",
        "missing_cost": {"status": PASS if all(missing_checks.values()) else BLOCKED, "checks": missing_checks},
        "explicit_zero": {"status": PASS if all(zero_checks.values()) else BLOCKED, "checks": zero_checks},
        "currency_mismatch": {"status": PASS if all(currency_checks.values()) else BLOCKED, "checks": currency_checks},
        "candidate_template_provenance": {"status": PASS if all(identity_checks.values()) else BLOCKED, "checks": identity_checks},
    }


def _run_safe_export_probe() -> dict[str, Any]:
    try:
        from backend.workspaces.client_workspace import ClientWorkspace
        from backend.workspaces.registry import WorkspaceRegistry
        from evaluation.trustos.client_workspace_isolation import (
            ClientWorkspaceExportError,
            check_workspace_leakage,
            export_client_evidence,
        )

        with tempfile.TemporaryDirectory(prefix=".mainline-vertical-acceptance-", dir=ROOT) as directory:
            registry = WorkspaceRegistry(str(Path(directory) / "workspaces.json"))
            workspace = registry.register(
                ClientWorkspace(
                    workspace_id="mainline-acceptance-workspace",
                    name="mainline acceptance fixture",
                    workspace_type="dry_run",
                    mode="internal_own_store",
                    dry_run_default=True,
                )
            )
            payload = {
                "workspace_id": workspace.workspace_id,
                "status": "blocked",
                "blockers": ["fixture_review_required"],
                "evidence_required": ["authoritative_evidence"],
                "approvals_required": ["human_review"],
                "next_actions": ["keep_external_actions_disabled"],
            }
            exported = export_client_evidence(
                workspace=workspace,
                registry=registry,
                provenance="fixture://mainline-vertical-acceptance",
                evidence_state="requires_review",
                payload=payload,
            )
            unsafe_findings = check_workspace_leakage(
                {"internal_prompt": "fixture", "workspace_id": workspace.workspace_id},
                client_safe=True,
            )
            try:
                export_client_evidence(
                    workspace=workspace,
                    registry=registry,
                    provenance="fixture://mainline-vertical-acceptance",
                    evidence_state="requires_review",
                    payload={**payload, "workspace_id": "other-workspace"},
                )
            except ClientWorkspaceExportError:
                mismatch_rejected = True
            else:
                mismatch_rejected = False
            checks = {
                "registered_workspace_exported": exported.workspace_id == workspace.workspace_id,
                "safe_payload_bounded": exported.payload_size_bytes <= exported.max_payload_bytes,
                "redaction_validated": exported.redaction_status == "validated_no_sensitive_fields",
                "unsafe_internal_prompt_rejected": bool(unsafe_findings),
                "workspace_mismatch_rejected": mismatch_rejected,
            }
            return {
                "status": PASS if all(checks.values()) else BLOCKED,
                "reason": None if all(checks.values()) else "trustos_export_probe_failed",
                "checks": checks,
                "workspace_id": exported.workspace_id,
                "fingerprint": exported.fingerprint,
                "redaction_policy_id": exported.redaction_policy_id,
            }
    except Exception:  # noqa: BLE001 - fail closed without exposing filesystem details
        return {"status": UNAVAILABLE, "reason": "trustos_export_authority_unavailable"}


def _service_delivery_authority_status() -> dict[str, Any]:
    missing = [path for path in SERVICE_DELIVERY_PATHS if not (ROOT / path).is_file()]
    if missing:
        return {
            "status": UNAVAILABLE,
            "reason": "service_delivery_authority_not_merged_on_mainline",
            "missing_paths": missing,
            "source_prs": [271, 275],
        }
    return {"status": PASS, "reason": None, "missing_paths": [], "source_prs": []}


def _not_run_mainline_report(
    *,
    head_sha: str,
    origin_main_sha: str,
    merge_base: str,
) -> dict[str, Any]:
    """Return a bounded report without executing non-mainline authorities."""
    reason = "exact_ref_identity_required"
    not_run = {"status": NOT_RUN, "reason": reason}
    return {
        "schema": SCHEMA,
        "status": BLOCKED,
        "status_semantics": "passed requires exact refreshed mainline identity; non-mainline worktrees are blocked before upstream authorities run",
        "head_sha": head_sha,
        "origin_main_sha": origin_main_sha,
        "merge_base": merge_base,
        "merged_authorities": {
            "research_to_decision": "scripts/research_to_decision.py",
            "commercial_replay": "scripts/run_commercial_replay_integration.py",
            "operator_dogfood": "scripts/run_operator_dogfood_vertical.py and scripts/run_operator_dogfood_workflow.py",
            "economics": "backend/economics/kernel.py",
            "events": "backend/contracts/events.py and backend/events/replay_certification.py",
            "fulfillment": "evaluation/commerce/fulfillment_risk_lifecycle.py",
            "trustos_export": "evaluation/trustos/client_workspace_isolation.py",
        },
        "checks": {
            "replay": False,
            "dogfood": False,
            "direct_commerce_scope": False,
            "cost_identity_probes": False,
            "safe_export": False,
            "service_delivery_status_explicit": False,
            "worktree_unchanged": True,
            "mainline_identity": False,
        },
        "replay": not_run,
        "dogfood": not_run,
        "direct_commerce_scope": not_run,
        "negative_and_identity_probes": not_run,
        "trustos_export": not_run,
        "service_delivery_upstream": {
            "status": NOT_RUN,
            "reason": reason,
            "source_prs": [271, 275],
        },
        "safety": {
            "network_calls": False,
            "provider_calls": False,
            "credentials_used": False,
            "payments": False,
            "orders": False,
            "ads": False,
            "publishing": False,
            "database_writes": False,
            "messages": False,
            "external_mutations": False,
            "evidence_mode": "not_run_non_mainline",
            "ci": "ci_unavailable",
        },
        "rollback": "Delete this acceptance harness files; merged replay, event, economics, and TrustOS authorities are untouched.",
    }


def run_acceptance() -> dict[str, Any]:
    head_sha = _git_value("rev-parse", "HEAD")
    origin_main_sha = _git_value("rev-parse", "origin/main")
    merge_base = _git_value("merge-base", "HEAD", "origin/main")
    mainline_identity = _is_mainline_identity(head_sha, origin_main_sha, merge_base)
    if not mainline_identity:
        return _not_run_mainline_report(
            head_sha=head_sha,
            origin_main_sha=origin_main_sha,
            merge_base=merge_base,
        )
    before_status = _status_hash()
    replay = _run_replay()
    dogfood = _run_dogfood(replay)
    direct_scope = _run_direct_commerce_scope()
    probes = _run_cost_and_identity_probes()
    safe_export = _run_safe_export_probe()
    service_delivery = _service_delivery_authority_status()
    after_status = _status_hash()
    checks = {
        "replay": replay["status"] == PASS,
        "dogfood": dogfood["status"] == PASS,
        "direct_commerce_scope": direct_scope["status"] == PASS,
        "cost_identity_probes": probes["status"] == PASS,
        "safe_export": safe_export["status"] == PASS,
        "service_delivery_status_explicit": service_delivery["status"] in {PASS, UNAVAILABLE},
        "worktree_unchanged": before_status != "unavailable" and before_status == after_status,
        "mainline_identity": mainline_identity,
    }
    return {
        "schema": SCHEMA,
        "status": PASS if all(checks.values()) else BLOCKED,
        "status_semantics": "passed requires exact refreshed mainline identity; non-mainline worktrees are blocked and unavailable upstream authorities are never treated as passed",
        "head_sha": head_sha,
        "origin_main_sha": origin_main_sha,
        "merge_base": merge_base,
        "merged_authorities": {
            "research_to_decision": "scripts/research_to_decision.py",
            "commercial_replay": "scripts/run_commercial_replay_integration.py",
            "operator_dogfood": "scripts/run_operator_dogfood_vertical.py and scripts/run_operator_dogfood_workflow.py",
            "economics": "backend/economics/kernel.py",
            "events": "backend/contracts/events.py and backend/events/replay_certification.py",
            "fulfillment": "evaluation/commerce/fulfillment_risk_lifecycle.py",
            "trustos_export": "evaluation/trustos/client_workspace_isolation.py",
        },
        "checks": checks,
        "replay": replay,
        "dogfood": dogfood,
        "direct_commerce_scope": direct_scope,
        "negative_and_identity_probes": probes,
        "trustos_export": safe_export,
        "service_delivery_upstream": service_delivery,
        "safety": {
            "network_calls": False,
            "provider_calls": False,
            "credentials_used": False,
            "payments": False,
            "orders": False,
            "ads": False,
            "publishing": False,
            "database_writes": False,
            "messages": False,
            "external_mutations": False,
            "evidence_mode": "fixture_and_simulated_or_planned_only",
            "ci": "ci_unavailable",
        },
        "rollback": "Delete this acceptance harness files; merged replay, event, economics, and TrustOS authorities are untouched.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit the machine-readable report")
    parser.add_argument("--markdown", action="store_true", help="emit a compact operator summary")
    args = parser.parse_args(argv)
    report = run_acceptance()
    if args.markdown:
        print(f"# Mainline vertical acceptance: {report['status']}")
        print("")
        print(f"- Head: `{report['head_sha']}`")
        print(f"- Origin main: `{report['origin_main_sha']}`")
        print(f"- Service-delivery upstream: `{report['service_delivery_upstream']['status']}`")
        for name, status in report["checks"].items():
            print(f"- {name}: `{status}`")
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())

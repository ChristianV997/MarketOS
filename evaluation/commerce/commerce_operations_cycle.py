"""Thin offline composition of existing MarketOS commerce consulting authorities.

This module does not rescore evidence, call providers, publish, spend, or
create tenants. It joins the existing marketplace, supplier, consumer,
synthesis, product-validation, governor, TrustOS, Approval Ledger, launch/site
draft, and workspace-isolation surfaces into one deterministic readiness cycle.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis

try:
    from evaluation.commerce.product_validation_report import generate as generate_product_validation_report
except ImportError:  # pragma: no cover - fail closed when validation is absent
    generate_product_validation_report = None

try:
    from evaluation.companyos.resource_execution_governor import (
        ExecutionDecisionRequest,
        evaluate_execution_request,
    )
except ImportError:  # pragma: no cover - fail closed when the governor is absent
    ExecutionDecisionRequest = None
    evaluate_execution_request = None

try:
    from evaluation.trustos.gate_runner import evaluate_action as evaluate_trustos_action
    from evaluation.trustos.trustos_report import build_trustos_combined_report
except ImportError:  # pragma: no cover
    evaluate_trustos_action = None
    build_trustos_combined_report = None

try:
    from evaluation.companyos.approval_ledger import build_approval_ledger, simulate_action
except ImportError:  # pragma: no cover
    build_approval_ledger = None
    simulate_action = None

try:
    from evaluation.commerce.launch_draft_pack import build_launch_draft_pack
except ImportError:  # pragma: no cover
    build_launch_draft_pack = None

try:
    from evaluation.commerce.site_draft_builder import build_site_draft_pack
except ImportError:  # pragma: no cover
    build_site_draft_pack = None

try:
    from evaluation.trustos.client_workspace_isolation import build_client_workspace_isolation_report
except ImportError:  # pragma: no cover
    build_client_workspace_isolation_report = None

REPORT_VERSION = "commerce-operations-cycle-v1"
GENERATED_AT = "offline-deterministic"
EVIDENCE_CLASSES = (
    "fixture_evidence",
    "plan_only",
    "dry_run",
    "blocked",
    "requires_approval",
    "unavailable",
    "client_safe_projection",
    "not_live_validated",
)
SECRET_KEYS = frozenset(
    {
        "actual_secret_value",
        "api_key",
        "apikey",
        "raw_api_key",
        "raw_oauth_token",
        "oauth_token",
        "access_token",
        "refresh_token",
        "password",
        "private_key",
        "private_key_material",
        "authorization",
        "cookie",
        "cookies",
        "token",
        "secret",
        "client_secret",
    }
)
RAW_KEYS = frozenset(
    {
        "raw_payload",
        "raw_html",
        "html",
        "body",
        "response_body",
        "javascript",
        "browser_trace",
        "prompt",
        "source_code",
        "internal_prompt",
    }
)
LIVE_MODES = frozenset({"live_readonly", "public_live", "authenticated_live"})
GOVERNOR_ACTIONS = (
    ("screen_product_opportunities", "intelligence", "intelligence", "report_generation_quota"),
    ("generate_launch_draft", "launch", "launch", "report_generation_quota"),
    ("generate_site_draft", "website_store_funnel", "launch", "report_generation_quota"),
)
TRUSTOS_ACTIONS = ("public_beta_launch", "publish_site", "launch_ad", "client_workspace_export")
# Map governor actions onto existing TrustOS evaluate_action names. Do not invent a cycle-local gate.
GOVERNOR_TRUSTOS_ACTION = {
    "screen_product_opportunities": "public_beta_launch",
    "generate_launch_draft": "publish_site",
    "generate_site_draft": "publish_site",
    "request_supplier_proof": "run_provider_readonly_call",
}
APPROVAL_ACTIONS = ("site_publish", "ad_launch", "supplier_order", "payment_creation")
UNIFORM_STAGE_KEYS = (
    "status",
    "evidence_references",
    "blocking_reasons",
    "next_action",
    "owner_department",
    "required_approval_or_gate",
    "client_visible_projection_state",
)
STAGE_ORDER = (
    "marketplace",
    "supplier",
    "consumer_attention",
    "synthesis",
    "product_validation",
    "trustos",
    "governor",
    "approval_ledger",
    "launch_draft_readiness",
    "site_draft_readiness",
    "client_workspace",
)


def _text(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def _mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("malformed commerce operations input: report root must be a JSON object")
    return dict(value)


def _secret_like(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in SECRET_KEYS or normalized in RAW_KEYS:
                return True
            if _secret_like(item):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_secret_like(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        if "<html" in lowered or "<!doctype html" in lowered:
            return True
        return "-----begin " in lowered or "bearer " in lowered or any(
            marker in lowered for marker in ("sk-", "ghp_", "xoxb-", "aiza")
        )
    return False


def reject_unsafe_input(value: Any, *, label: str = "input") -> None:
    """Reject secret-like keys, tokens, HTML, and raw payloads without echoing them."""
    if value is None:
        return
    if _secret_like(value):
        raise ValueError(f"secret-like or raw payload {label} is not accepted")


def _call(label: str, fn: Callable[..., Any] | None, *args: Any, **kwargs: Any) -> tuple[Any, str | None]:
    if fn is None:
        return None, f"{label}_unavailable"
    try:
        return fn(*args, **kwargs), None
    except Exception:
        return None, f"{label}_unavailable"


def _section(
    *,
    status: str,
    evidence_class: str | None = None,
    blockers: list[str] | tuple[str, ...] = (),
    evidence_references: list[str] | tuple[str, ...] = (),
    next_action: str = "",
    owner_department: str = "commerce",
    required_approval_or_gate: str = "none",
    client_visible_projection_state: str = "internal_only",
    **fields: Any,
) -> dict[str, Any]:
    reasons = list(dict.fromkeys(blockers))
    payload: dict[str, Any] = {
        "status": status,
        "evidence_class": evidence_class or status,
        "evidence_references": list(evidence_references),
        "blocking_reasons": reasons,
        "blockers": reasons,
        "next_action": next_action,
        "owner_department": owner_department,
        "required_approval_or_gate": required_approval_or_gate,
        "client_visible_projection_state": client_visible_projection_state,
    }
    payload.update(fields)
    if "blocking_reasons" in fields and "blockers" not in fields:
        payload["blockers"] = list(dict.fromkeys(payload.get("blocking_reasons") or []))
        payload["blocking_reasons"] = payload["blockers"]
    elif "blockers" in fields and "blocking_reasons" not in fields:
        payload["blocking_reasons"] = list(dict.fromkeys(payload.get("blockers") or []))
        payload["blockers"] = payload["blocking_reasons"]
    return payload


def _compact_stage(section: Mapping[str, Any]) -> dict[str, Any]:
    reasons = list(section.get("blocking_reasons") or section.get("blockers") or [])
    return {
        "status": str(section.get("status") or "unavailable"),
        "evidence_references": list(section.get("evidence_references") or []),
        "blocking_reasons": reasons,
        "next_action": str(section.get("next_action") or ""),
        "owner_department": str(section.get("owner_department") or "commerce"),
        "required_approval_or_gate": str(section.get("required_approval_or_gate") or "none"),
        "client_visible_projection_state": str(section.get("client_visible_projection_state") or "internal_only"),
    }


def _unavailable(
    label: str,
    reason: str,
    *,
    owner_department: str = "commerce",
    required_approval_or_gate: str = "none",
) -> dict[str, Any]:
    return _section(
        status="unavailable",
        evidence_class="unavailable",
        blockers=(reason,),
        evidence_references=(label,),
        next_action=f"restore_{label}",
        owner_department=owner_department,
        required_approval_or_gate=required_approval_or_gate,
        authority=label,
        live_go=False,
    )


def _pillar(name: str, report: Mapping[str, Any] | None) -> dict[str, Any]:
    if report is None:
        return _section(
            status="unavailable",
            evidence_class="unavailable",
            blockers=(f"{name}_pillar_missing",),
            evidence_references=(f"evaluation.commerce.{name}",),
            next_action=f"supply_{name}_pillar",
            owner_department="commerce",
            required_approval_or_gate="none",
            client_visible_projection_state="internal_only",
            supplied=False,
            candidate_count=0,
            evidence_mode="missing",
        )
    candidates = report.get("candidates", [])
    count = len(candidates) if isinstance(candidates, list) else 0
    mode = _text(report.get("evidence_mode") or "fixture_demo", 40)
    evidence_class = "fixture_evidence" if mode not in LIVE_MODES else "not_live_validated"
    blockers = [] if count else [f"{name}_candidates_missing"]
    return _section(
        status="unavailable" if not count else evidence_class,
        evidence_class=evidence_class if count else "unavailable",
        blockers=blockers,
        evidence_references=(f"evaluation.commerce.{name}",),
        next_action="continue_offline_cycle" if count else f"supply_{name}_candidates",
        owner_department="commerce",
        required_approval_or_gate="none",
        client_visible_projection_state="internal_only",
        supplied=True,
        candidate_count=count,
        evidence_mode=mode,
        live_validated=False,
    )


def _synthesis_section(
    marketplace: Mapping[str, Any] | None,
    supplier: Mapping[str, Any] | None,
    consumer: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    report, error = _call(
        "product_opportunity_synthesis",
        build_product_opportunity_synthesis,
        marketplace,
        supplier,
        consumer,
    )
    if error or report is None:
        return {}, _unavailable("product_opportunity_synthesis", error or "product_opportunity_synthesis_unavailable")
    data = report.to_dict() if hasattr(report, "to_dict") else dict(report)
    grade = _text(data.get("confidence_grade"), 40)
    blockers = list(data.get("risk_profile", {}).get("blockers") or []) if isinstance(data.get("risk_profile"), Mapping) else []
    authority = "evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis"
    return data, _section(
        status="fixture_evidence" if data.get("evidence_mode") in {"fixture", "fixture_demo"} else "plan_only",
        evidence_class="fixture_evidence" if data.get("evidence_mode") in {"fixture", "fixture_demo"} else "plan_only",
        blockers=blockers,
        evidence_references=(authority,),
        next_action=_text(data.get("next_best_action") or "review_synthesis_offline", 240),
        owner_department="commerce",
        required_approval_or_gate="none",
        client_visible_projection_state="internal_only",
        report_version=data.get("report_version"),
        evidence_mode=data.get("evidence_mode"),
        confidence_grade=grade,
        overall_recommendation=data.get("overall_recommendation"),
        combined_opportunity_score=data.get("combined_opportunity_score"),
        marketplace_opportunity=data.get("marketplace_opportunity"),
        supplier_feasibility=data.get("supplier_feasibility"),
        consumer_attention=data.get("consumer_attention"),
        top_candidate_id=data.get("top_candidate_id"),
        top_candidate_title=data.get("top_candidate_title"),
        next_best_action=_text(data.get("next_best_action") or "review_synthesis_offline", 240),
        source_reports=dict(data.get("source_reports") or {}),
        candidate_count=data.get("candidate_count", 0),
        live_validated=False,
        scoring_authority=authority,
    )


def _product_validation_section(
    marketplace: Mapping[str, Any] | None,
    supplier: Mapping[str, Any] | None,
    consumer: Mapping[str, Any] | None,
    synthesis_data: Mapping[str, Any],
    synthesis_section: Mapping[str, Any],
) -> dict[str, Any]:
    builder = "evaluation.commerce.product_validation_report.generate"
    # Truthy stubs: generate() treats None and {} as missing and would run path builders.
    blocked_benchmark = {"candidates": [], "evidence_mode": "fixture_demo"}
    blocked_readiness = {
        "overall_status": "blocked",
        "supplier_readiness": {"status": "unknown"},
        "blocking_gates": ["cycle_supplied_blocked_readiness"],
        "next_best_action": "expand_supplier_research",
    }
    blocked_deployment = {"overall_status": "blocked"}
    if str(synthesis_section.get("status") or "") == "unavailable":
        return _section(
            status="unavailable",
            evidence_class="unavailable",
            blockers=("product_validation_requires_synthesis",),
            evidence_references=(builder,),
            next_action="restore_synthesis_authority",
            owner_department="commerce",
            required_approval_or_gate="none",
            client_visible_projection_state="internal_only",
            presentation_builder=builder,
            live_go=False,
        )
    report, error = _call(
        "product_validation_report",
        generate_product_validation_report,
        benchmark=blocked_benchmark,
        readiness=blocked_readiness,
        deployment=blocked_deployment,
        marketplace_trends=marketplace,
        supplier_feasibility=supplier,
        consumer_attention=consumer,
        opportunity_synthesis=synthesis_data or None,
    )
    if error or report is None:
        unavailable = _unavailable(builder, error or "product_validation_report_unavailable")
        unavailable["presentation_builder"] = builder
        return unavailable
    data = report.to_dict() if hasattr(report, "to_dict") else dict(report)
    recommendation = _text(data.get("overall_recommendation"), 80)
    reasons: list[str] = []
    if recommendation.startswith("reject") or recommendation in {"do_not_launch", "hold_for_review"}:
        reasons.append(f"product_validation:{recommendation}")
    launch_readiness = data.get("launch_readiness") if isinstance(data.get("launch_readiness"), Mapping) else {}
    supplier_evidence = data.get("supplier_evidence") if isinstance(data.get("supplier_evidence"), Mapping) else {}
    source_reports = dict(data.get("source_reports") or {})
    next_actions = list(data.get("recommended_next_actions") or [])
    next_action = _text(next_actions[0] if next_actions else synthesis_section.get("next_action") or "review_product_validation_offline", 240)
    return _section(
        status="plan_only",
        evidence_class="plan_only",
        blockers=reasons,
        evidence_references=(builder,),
        next_action=next_action,
        owner_department="commerce",
        required_approval_or_gate="none",
        client_visible_projection_state="internal_only",
        presentation_builder=builder,
        overall_recommendation=recommendation,
        evidence_mode=data.get("evidence_mode"),
        risk_flags=list(data.get("risk_flags") or [])[:8],
        launch_readiness={
            "status": launch_readiness.get("status"),
            "deployment": launch_readiness.get("deployment"),
        },
        recommended_next_actions=[_text(item, 160) for item in next_actions[:6]],
        source_reports=source_reports,
        supplier_evidence_status=supplier_evidence.get("status"),
        live_go=False,
        live_validated=False,
    )


def _score(synthesis: Mapping[str, Any], key: str) -> float:
    try:
        return max(0.0, min(1.0, float(synthesis.get(key) or 0)))
    except (TypeError, ValueError):
        return 0.0


def _trustos_decision_for(action: str, by_action: Mapping[str, str], *, trustos_status: str) -> str:
    """Pass through existing TrustOS evaluate_action.decision; fail closed, never invent a cycle gate."""
    if trustos_status == "unavailable" or evaluate_trustos_action is None:
        return "blocked"
    mapped = GOVERNOR_TRUSTOS_ACTION.get(action, "public_beta_launch")
    decision = _text(by_action.get(mapped) or "", 40)
    if not decision or decision == "unavailable":
        return "blocked"
    return decision


def _governor_section(
    synthesis: Mapping[str, Any],
    *,
    live_requested: bool,
    supplier_present: bool,
    trustos_by_action: Mapping[str, str],
    trustos_status: str,
) -> dict[str, Any]:
    if ExecutionDecisionRequest is None or evaluate_execution_request is None:
        return _unavailable(
            "resource_execution_governor",
            "evaluate_execution_request_unavailable",
            owner_department="companyos",
            required_approval_or_gate="Approval Ledger + TrustOS evaluate_action",
        )
    actions = list(GOVERNOR_ACTIONS)
    if not supplier_present:
        actions.append(("request_supplier_proof", "supplier", "supplier", "report_generation_quota"))
    decisions: list[dict[str, Any]] = []
    blockers: list[str] = []
    for action, domain, owner, resource in actions:
        trustos_decision = _trustos_decision_for(action, trustos_by_action, trustos_status=trustos_status)
        request = ExecutionDecisionRequest(
            request_id=f"cycle-{action.replace('_', '-')}",
            action_type=action,
            domain=domain,
            owner_department=owner,
            workspace_id="internal-companyos",
            requested_amount=0.0,
            resource_type=resource,
            model_tier="algorithmic",
            opportunity_score=_score(synthesis, "combined_opportunity_score"),
            supplier_score=_score(synthesis, "supplier_feasibility"),
            attention_score=_score(synthesis, "consumer_attention"),
            evidence_score=_score(synthesis, "evidence_confidence"),
            unit_economics_score=0.0,
            supplier_proof=False,
            approval_state="not_requested",
            trustos_decision=trustos_decision,
            workspace_decision="allow",
        )
        result, error = _call("resource_execution_governor", evaluate_execution_request, request)
        if error or result is None:
            return _unavailable(
                "resource_execution_governor",
                error or "evaluate_execution_request_unavailable",
                owner_department="companyos",
                required_approval_or_gate="Approval Ledger + TrustOS evaluate_action",
            )
        payload = result.to_dict()
        outcome = _text(payload.get("outcome"), 40)
        compact = {
            "action_type": payload.get("action_type"),
            "outcome": outcome,
            "reason": payload.get("reason"),
            "blockers": list(payload.get("blockers") or []),
            "approvals": [
                {"approval_type": item.get("approval_type"), "reason": item.get("reason")}
                for item in payload.get("approvals") or []
                if isinstance(item, Mapping)
            ],
            "simulated_only": True,
            "trustos_decision": trustos_decision,
            "trustos_action": GOVERNOR_TRUSTOS_ACTION.get(action, "public_beta_launch"),
        }
        decisions.append(compact)
        blockers.extend(compact["blockers"])
        if outcome in {"requires_approval", "requires_finance_review", "requires_management_review", "requires_trustos_review"}:
            blockers.append(f"governor_{action}_requires_approval")
        if outcome in {"hard_block", "soft_block", "kill"}:
            blockers.append(f"governor_{action}_{outcome}")
    if live_requested:
        blockers.append("live_mode_requested")
    status = "blocked" if live_requested else "dry_run"
    return _section(
        status=status,
        evidence_class=status,
        blockers=blockers,
        evidence_references=("evaluation.companyos.resource_execution_governor.evaluate_execution_request",),
        next_action="keep_governor_simulated_and_plan_only",
        owner_department="companyos",
        required_approval_or_gate="Approval Ledger + TrustOS evaluate_action",
        client_visible_projection_state="internal_only",
        simulated_only=True,
        live_go=False,
        decisions=decisions,
    )


def _trustos_section(*, live_requested: bool) -> tuple[dict[str, Any], dict[str, str]]:
    if build_trustos_combined_report is None and evaluate_trustos_action is None:
        unavailable = _unavailable(
            "trustos_control_plane",
            "trustos_unavailable",
            owner_department="trustos",
            required_approval_or_gate="TrustOS evaluate_action",
        )
        return unavailable, {}
    report, error = _call("trustos_control_plane", build_trustos_combined_report, generated_at=GENERATED_AT, client_safe=False)
    gates: list[dict[str, Any]] = []
    blockers: list[str] = []
    for action in TRUSTOS_ACTIONS:
        result, gate_error = _call("trustos_gate", evaluate_trustos_action, action, generated_at=GENERATED_AT)
        if gate_error or result is None:
            gates.append({"action": action, "status": "unavailable", "decision": "unavailable", "blockers": [gate_error or "trustos_gate_unavailable"]})
            blockers.append(gate_error or f"{action}_unavailable")
            continue
        payload = result.to_dict()
        gates.append(
            {
                "action": action,
                "decision": payload.get("decision"),
                "blockers": list(payload.get("blockers") or []),
                "status": "blocked" if payload.get("decision") in {"hard_block", "soft_block"} else "plan_only",
            }
        )
        blockers.extend(payload.get("blockers") or [])
        if payload.get("decision") in {"hard_block", "needs_professional_review"}:
            blockers.append(f"trustos_{action}_{payload.get('decision')}")
    data = report.to_dict() if report is not None and hasattr(report, "to_dict") else {}
    if error and not gates:
        return _unavailable(
            "trustos_control_plane",
            error,
            owner_department="trustos",
            required_approval_or_gate="TrustOS evaluate_action",
        ), {}
    if live_requested:
        blockers.append("live_mode_requested")
    status = "blocked" if live_requested else "plan_only"
    by_action = {str(item.get("action") or ""): str(item.get("decision") or "blocked") for item in gates}
    section = _section(
        status=status,
        evidence_class=status,
        blockers=blockers,
        evidence_references=("evaluation.trustos.gate_runner.evaluate_action", "evaluation.trustos.trustos_report.build_trustos_combined_report"),
        next_action=_text(data.get("next_best_action") or "Keep public launch blocked until reviewed evidence exists.", 240),
        owner_department="trustos",
        required_approval_or_gate="TrustOS evaluate_action",
        client_visible_projection_state="internal_only",
        public_launch_decision=data.get("public_launch_decision") or "hard_block",
        provider_activation_decision=data.get("provider_activation_decision") or "blocked_for_live_provider_activation",
        hard_blocker_count=data.get("hard_blocker_count", 0),
        gates=gates,
        professional_conclusion=False,
        metadata_only=True,
    )
    return section, by_action


def _approval_section(*, live_requested: bool) -> dict[str, Any]:
    if simulate_action is None or build_approval_ledger is None:
        return _unavailable(
            "companyos_approval_ledger",
            "approval_ledger_unavailable",
            owner_department="companyos",
            required_approval_or_gate="Approval Ledger simulate_action",
        )
    simulations: list[dict[str, Any]] = []
    blockers: list[str] = []
    sim_objects = []
    for action in APPROVAL_ACTIONS:
        item, error = _call("approval_simulation", simulate_action, action, generated_at=GENERATED_AT)
        if error or item is None:
            simulations.append({"action": action, "status": "unavailable", "result": "unavailable", "blockers": [error or "approval_simulation_unavailable"]})
            blockers.append(error or f"{action}_unavailable")
            continue
        payload = item.to_dict()
        sim_objects.append(item)
        result = _text(payload.get("result"), 80)
        simulations.append(
            {
                "action": action,
                "result": result,
                "can_be_approved_now": bool(payload.get("can_be_approved_now")),
                "missing_conditions": list(payload.get("missing_conditions") or []),
                "blocking_reasons": list(payload.get("blocking_reasons") or []),
                "status": "blocked" if "blocked" in result or "denied" in result else "requires_approval",
            }
        )
        if payload.get("can_be_approved_now"):
            blockers.append(f"approval_{action}_must_not_auto_allow_live")
        blockers.extend(payload.get("blocking_reasons") or [])
        blockers.extend(f"approval_missing:{condition}" for condition in payload.get("missing_conditions") or [])
    ledger, error = _call(
        "companyos_approval_ledger",
        build_approval_ledger,
        generated_at=GENERATED_AT,
        registry_report={},
        approval_requests=[],
        simulations=tuple(sim_objects),
    )
    if error and not simulations:
        return _unavailable(
            "companyos_approval_ledger",
            error,
            owner_department="companyos",
            required_approval_or_gate="Approval Ledger simulate_action",
        )
    data = ledger.to_dict() if ledger is not None and hasattr(ledger, "to_dict") else {}
    if live_requested:
        blockers.append("live_mode_requested")
    status = "blocked" if live_requested else "requires_approval"
    return _section(
        status=status,
        evidence_class=status,
        blockers=blockers,
        evidence_references=("evaluation.companyos.approval_ledger.simulate_action", "evaluation.companyos.approval_ledger.build_approval_ledger"),
        next_action=_text(data.get("next_best_action") or "Keep external-world actions blocked until a human-approved policy exists.", 240),
        owner_department="companyos",
        required_approval_or_gate="Approval Ledger simulate_action",
        client_visible_projection_state="internal_only",
        live_approval_granted=False,
        simulations=simulations,
        queue_summary=data.get("queue_summary") or {},
        metadata_only=True,
        registry_loaded=False,
    )


def _launch_section(synthesis: Mapping[str, Any], supplier: Mapping[str, Any] | None, consumer: Mapping[str, Any] | None, marketplace: Mapping[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if not synthesis:
        return {}, _unavailable("launch_draft_pack", "launch_draft_readiness_requires_synthesis")
    pack, error = _call(
        "launch_draft_pack",
        build_launch_draft_pack,
        synthesis=synthesis,
        consumer_attention=consumer,
        supplier_feasibility=supplier,
        marketplace_trend=marketplace,
    )
    if error or pack is None:
        return {}, _unavailable("launch_draft_pack", error or "launch_draft_pack_unavailable")
    data = pack.to_dict()
    checklist = data.get("approval_checklist") if isinstance(data.get("approval_checklist"), Mapping) else {}
    blockers = list(checklist.get("blockers") or [])
    shopify = data.get("shopify_draft_payload") if isinstance(data.get("shopify_draft_payload"), Mapping) else {}
    medusa = data.get("medusa_draft_payload") if isinstance(data.get("medusa_draft_payload"), Mapping) else {}
    return data, _section(
        status="plan_only",
        evidence_class="plan_only",
        blockers=blockers,
        evidence_references=("evaluation.commerce.launch_draft_pack.build_launch_draft_pack",),
        next_action="keep_launch_payloads_draft_and_unpublished",
        owner_department="commerce",
        required_approval_or_gate="Approval Ledger site_publish",
        client_visible_projection_state="internal_only",
        launch_draft_status=data.get("launch_draft_status"),
        launch_authorized=bool(checklist.get("launch_authorized")),
        published=False,
        packs_written=False,
        shopify_payload_status=_text(shopify.get("status") or "draft", 20),
        medusa_payload_status=_text(medusa.get("status") or "draft", 20),
        candidate_id=data.get("candidate_id"),
    )


def _site_section(synthesis: Mapping[str, Any], launch_pack: Mapping[str, Any], supplier: Mapping[str, Any] | None, consumer: Mapping[str, Any] | None, marketplace: Mapping[str, Any] | None) -> dict[str, Any]:
    if not synthesis and not launch_pack:
        return _unavailable("site_draft_builder", "site_draft_readiness_requires_synthesis")
    pack, error = _call(
        "site_draft_builder",
        build_site_draft_pack,
        launch_draft_pack=launch_pack or None,
        opportunity_synthesis=synthesis or None,
        supplier_feasibility=supplier,
        consumer_attention=consumer,
        marketplace_trends=marketplace,
    )
    if error or pack is None:
        return _unavailable("site_draft_builder", error or "site_draft_builder_unavailable")
    data = pack.to_dict()
    readiness = data.get("deployment_readiness") if isinstance(data.get("deployment_readiness"), Mapping) else {}
    approval = data.get("approval_checklist") if isinstance(data.get("approval_checklist"), Mapping) else {}
    blockers = list(readiness.get("blockers") or []) + list(approval.get("blockers") or [])
    return _section(
        status="plan_only",
        evidence_class="plan_only",
        blockers=blockers,
        evidence_references=("evaluation.commerce.site_draft_builder.build_site_draft_pack",),
        next_action="keep_site_payloads_draft_and_unpublished",
        owner_department="commerce",
        required_approval_or_gate="Approval Ledger site_publish",
        client_visible_projection_state="internal_only",
        overall_readiness=readiness.get("overall_status") or "partially_ready",
        publishing_authorized=bool(approval.get("publishing_authorized")),
        published=False,
        packs_written=False,
        site_type=data.get("site_type"),
        candidate_id=data.get("candidate_id"),
    )


def _workspace_section(projection: Mapping[str, Any]) -> dict[str, Any]:
    report, error = _call(
        "client_workspace_isolation",
        build_client_workspace_isolation_report,
        generated_at=GENERATED_AT,
        workspace_type="client_readonly_report_workspace",
        clone_type="launch_pack_clone",
        service_package="MarketOS Growth Retainer",
        payload=projection,
        check_leakage=True,
    )
    if error or report is None:
        return _unavailable(
            "client_workspace_isolation",
            error or "client_workspace_isolation_unavailable",
            owner_department="trustos",
            required_approval_or_gate="TrustOS client_workspace_export",
        )
    data = report.to_dict()
    leakage = [item for item in data.get("leakage_checks") or [] if isinstance(item, Mapping)]
    blockers = [item.get("field_path") or item.get("status") for item in leakage if item.get("status") == "hard_block"]
    gates = [item for item in data.get("gate_results") or [] if isinstance(item, Mapping)]
    blockers.extend(f"workspace_{item.get('action')}_{item.get('decision')}" for item in gates if item.get("decision") == "hard_block")
    safety = data.get("safety_summary") if isinstance(data.get("safety_summary"), Mapping) else {}
    blocked = any(item for item in blockers if item)
    return _section(
        status="client_safe_projection",
        evidence_class="client_safe_projection",
        blockers=[item for item in blockers if item],
        evidence_references=("evaluation.trustos.client_workspace_isolation.build_client_workspace_isolation_report",),
        next_action=_text(data.get("next_best_action") or "Export only the client-safe projection; do not create tenants.", 240),
        owner_department="trustos",
        required_approval_or_gate="TrustOS client_workspace_export",
        client_visible_projection_state="blocked" if blocked else "client_safe_projection",
        tenant_created=False,
        database_writes=False,
        client_data_present=bool(safety.get("client_data_present")),
        artifacts_written=False,
        hard_blocker_count=data.get("hard_blocker_count", 0),
    )


def _client_safe_projection(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "report_version": report.get("report_version"),
        "generated_at": report.get("generated_at"),
        "overall_status": report.get("overall_status"),
        "cycle_mode": report.get("cycle_mode"),
        "evidence_class": "client_safe_projection",
        "confidence_claim": "not_live_validated",
        "live_validated": False,
        "top_candidate_id": report.get("synthesis", {}).get("top_candidate_id") if isinstance(report.get("synthesis"), Mapping) else None,
        "overall_recommendation": report.get("synthesis", {}).get("overall_recommendation") if isinstance(report.get("synthesis"), Mapping) else None,
        "confidence_grade": report.get("synthesis", {}).get("confidence_grade") if isinstance(report.get("synthesis"), Mapping) else None,
        "blockers": list(report.get("blockers") or []),
        "evidence_required": list(report.get("evidence_required") or []),
        "approvals_required": list(report.get("approvals_required") or []),
        "next_best_action": report.get("next_best_action"),
        "launch_authorized": False,
        "publishing_authorized": False,
    }


def _next_best_action(live_requested: bool, blockers: list[str], synthesis: Mapping[str, Any]) -> str:
    if live_requested:
        return "Keep the commerce operations cycle dry-run and plan-only; live mode is blocked and is not implemented."
    if any("pillar_missing" in item or "candidates_missing" in item for item in blockers):
        return _text(synthesis.get("next_best_action") or "Supply the missing sanitized evidence pillar and rerun this offline cycle.")
    if _text(synthesis.get("overall_recommendation")).startswith("reject"):
        return _text(synthesis.get("next_best_action") or "Hold the candidate; fixture evidence is not launch authorization.")
    return _text(
        synthesis.get("next_best_action")
        or "Review fixture-backed synthesis, keep launch and site drafts plan-only, and obtain Approval Ledger plus TrustOS evidence before any external action."
    )


@dataclass(frozen=True)
class CommerceOperationsCycleReport:
    report_version: str
    generated_at: str
    cycle_mode: str
    overall_status: str
    evidence_class: str
    confidence_claim: str
    live_requested: bool
    live_validated: bool
    marketplace: dict[str, Any]
    supplier: dict[str, Any]
    consumer_attention: dict[str, Any]
    synthesis: dict[str, Any]
    product_validation: dict[str, Any]
    trustos: dict[str, Any]
    governor: dict[str, Any]
    approval_ledger: dict[str, Any]
    launch_draft_readiness: dict[str, Any]
    site_draft_readiness: dict[str, Any]
    client_workspace: dict[str, Any]
    client_safe_projection: dict[str, Any]
    blockers: tuple[str, ...]
    evidence_required: tuple[str, ...]
    approvals_required: tuple[str, ...]
    next_best_action: str
    safety_summary: dict[str, Any]
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False
    artifacts_written: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "generated_at": self.generated_at,
            "cycle_mode": self.cycle_mode,
            "overall_status": self.overall_status,
            "evidence_class": self.evidence_class,
            "confidence_claim": "not_live_validated",
            "live_requested": self.live_requested,
            "live_validated": False,
            "marketplace": dict(self.marketplace),
            "supplier": dict(self.supplier),
            "consumer_attention": dict(self.consumer_attention),
            "synthesis": dict(self.synthesis),
            "product_validation": dict(self.product_validation),
            "trustos": dict(self.trustos),
            "governor": dict(self.governor),
            "approval_ledger": dict(self.approval_ledger),
            "launch_draft_readiness": dict(self.launch_draft_readiness),
            "site_draft_readiness": dict(self.site_draft_readiness),
            "client_workspace": dict(self.client_workspace),
            "client_safe_projection": dict(self.client_safe_projection),
            "stages": {
                name: _compact_stage(
                    {
                        "marketplace": self.marketplace,
                        "supplier": self.supplier,
                        "consumer_attention": self.consumer_attention,
                        "synthesis": self.synthesis,
                        "product_validation": self.product_validation,
                        "trustos": self.trustos,
                        "governor": self.governor,
                        "approval_ledger": self.approval_ledger,
                        "launch_draft_readiness": self.launch_draft_readiness,
                        "site_draft_readiness": self.site_draft_readiness,
                        "client_workspace": self.client_workspace,
                    }[name]
                )
                for name in STAGE_ORDER
            },
            "blockers": list(self.blockers),
            "evidence_required": list(self.evidence_required),
            "approvals_required": list(self.approvals_required),
            "next_best_action": self.next_best_action,
            "safety_summary": dict(self.safety_summary),
            "read_only": True,
            "network_calls": False,
            "mutated": False,
            "artifacts_written": False,
        }

    def to_markdown(self) -> str:
        data = self.to_dict()
        lines = [
            "# Commerce Operations Readiness Cycle",
            "",
            f"Cycle mode: `{data['cycle_mode']}`",
            f"Overall status: `{data['overall_status']}`",
            f"Evidence class: `{data['evidence_class']}`",
            f"Confidence claim: `{data['confidence_claim']}` (never A_live_validated from this cycle)",
            f"Live requested: `{data['live_requested']}`",
            f"Live validated: `{data['live_validated']}`",
            "",
            "This is an offline composition of existing authorities. It is fixture evidence, plan-only, dry-run, and not live-validated.",
            "",
            "## Pillars",
            "",
            "| Pillar | Status | Evidence class | Candidates | Blockers |",
            "| --- | --- | --- | ---: | --- |",
        ]
        for key, label in (("marketplace", "Marketplace"), ("supplier", "Supplier"), ("consumer_attention", "Consumer attention")):
            item = data[key]
            lines.append(
                f"| {label} | `{item.get('status')}` | `{item.get('evidence_class')}` | {item.get('candidate_count', 0)} | {', '.join(item.get('blocking_reasons') or item.get('blockers') or []) or 'none'} |"
            )
        synthesis = data["synthesis"]
        validation = data["product_validation"]
        lines += [
            "",
            "## Product Opportunity Synthesis",
            "",
            f"Scoring authority: `{synthesis.get('scoring_authority') or 'unavailable'}` (not recopied)",
            f"Recommendation: `{synthesis.get('overall_recommendation') or 'unavailable'}`",
            f"Confidence grade: `{synthesis.get('confidence_grade') or 'unavailable'}`",
            f"Combined opportunity: {synthesis.get('combined_opportunity_score')}",
            f"Top candidate: `{synthesis.get('top_candidate_id') or 'none'}`",
            "",
            "## Product Validation",
            "",
            f"Builder: `{validation.get('presentation_builder') or 'unavailable'}` (presentation only; not a scoring authority)",
            f"Recommendation: `{validation.get('overall_recommendation') or 'unavailable'}`",
            f"Evidence mode: `{validation.get('evidence_mode') or 'unavailable'}`",
            f"Launch/site packs supplied: `{((validation.get('source_reports') or {}).get('launch_draft_pack') or 'missing')}` / `{((validation.get('source_reports') or {}).get('site_draft_pack') or 'missing')}`",
            "",
            "## Governor / TrustOS / Approval",
            "",
            f"- TrustOS: `{data['trustos'].get('status')}` / public launch `{data['trustos'].get('public_launch_decision')}` / gate `{data['trustos'].get('required_approval_or_gate')}`",
            f"- Resource & Execution Governor: `{data['governor'].get('status')}` / `{data['governor'].get('evidence_class')}` (TrustOS decision passed through; not a cycle-local gate)",
            f"- Approval Ledger: `{data['approval_ledger'].get('status')}` / live approval granted `{data['approval_ledger'].get('live_approval_granted')}`",
            "",
            "## Launch and site draft readiness",
            "",
            f"- Launch draft: `{data['launch_draft_readiness'].get('status')}` / authorized `{data['launch_draft_readiness'].get('launch_authorized')}` / packs written `{data['launch_draft_readiness'].get('packs_written')}`",
            f"- Site draft: `{data['site_draft_readiness'].get('status')}` / publishing authorized `{data['site_draft_readiness'].get('publishing_authorized')}`",
            "",
            "## Client-safe projection",
            "",
            f"- Status: `{data['client_workspace'].get('status')}`",
            f"- Projection state: `{data['client_workspace'].get('client_visible_projection_state')}`",
            f"- Tenant created: `{data['client_workspace'].get('tenant_created')}`",
            "",
            "## Blockers",
            "",
        ]
        lines.extend(f"- {item}" for item in data["blockers"] or ["none recorded"])
        lines += ["", "## Next best action", "", data["next_best_action"], "", "## Safety", "", "No model, provider, or network calls. No ads, publishing, orders, payments, messages, client data, database writes, or tenant creation. Artifact writes require an explicit `--output` directory.", ""]
        return "\n".join(lines)


def build_commerce_operations_cycle(
    marketplace_report: Mapping[str, Any] | None = None,
    supplier_report: Mapping[str, Any] | None = None,
    consumer_report: Mapping[str, Any] | None = None,
    *,
    live_requested: bool = False,
) -> CommerceOperationsCycleReport:
    """Compose existing authorities into one offline readiness cycle."""
    marketplace = _mapping(marketplace_report)
    supplier = _mapping(supplier_report)
    consumer = _mapping(consumer_report)
    reject_unsafe_input(marketplace, label="marketplace report")
    reject_unsafe_input(supplier, label="supplier report")
    reject_unsafe_input(consumer, label="consumer report")
    market_section = _pillar("marketplace", marketplace)
    supplier_section = _pillar("supplier", supplier)
    consumer_section = _pillar("consumer", consumer)
    synthesis_data, synthesis_section = _synthesis_section(marketplace, supplier, consumer)
    product_validation = _product_validation_section(
        marketplace,
        supplier,
        consumer,
        synthesis_data,
        synthesis_section,
    )
    trustos, trustos_by_action = _trustos_section(live_requested=live_requested)
    governor = _governor_section(
        synthesis_data,
        live_requested=live_requested,
        supplier_present=supplier is not None and bool(supplier.get("candidates")),
        trustos_by_action=trustos_by_action,
        trustos_status=str(trustos.get("status") or "unavailable"),
    )
    approval = _approval_section(live_requested=live_requested)
    launch_pack, launch = _launch_section(synthesis_data, supplier, consumer, marketplace)
    site = _site_section(synthesis_data, launch_pack, supplier, consumer, marketplace)
    blockers: list[str] = []
    for section in (
        market_section,
        supplier_section,
        consumer_section,
        synthesis_section,
        product_validation,
        trustos,
        governor,
        approval,
        launch,
        site,
    ):
        blockers.extend(section.get("blocking_reasons") or section.get("blockers") or [])
    if live_requested:
        blockers.insert(0, "live_mode_requested")
    evidence_required = tuple(
        dict.fromkeys(
            item
            for item in blockers
            if "missing" in item or "proof" in item or "evidence" in item or item.endswith("_unavailable")
        )
    )
    approvals_required = tuple(
        dict.fromkeys(item for item in blockers if "approval" in item or "requires_approval" in item)
    )
    cycle_mode = "blocked" if live_requested else "dry_run"
    overall = "blocked" if live_requested else "plan_only"
    if synthesis_section.get("status") == "unavailable" and not live_requested:
        overall = "unavailable"
    next_action = _next_best_action(live_requested, blockers, synthesis_section)
    safety = {
        "read_only": True,
        "network_calls": False,
        "model_calls": False,
        "provider_calls": False,
        "ads_launched": False,
        "sites_published": False,
        "orders_created": False,
        "payments_created": False,
        "messages_sent": False,
        "database_writes": False,
        "tenant_created": False,
        "client_data_present": False,
        "credentials_loaded": False,
        "artifacts_written": False,
        "live_validated": False,
    }
    report = CommerceOperationsCycleReport(
        REPORT_VERSION,
        GENERATED_AT,
        cycle_mode,
        overall,
        "blocked" if live_requested else "not_live_validated",
        "not_live_validated",
        live_requested,
        False,
        market_section,
        supplier_section,
        consumer_section,
        synthesis_section,
        product_validation,
        trustos,
        governor,
        approval,
        launch,
        site,
        {},
        {},
        tuple(dict.fromkeys(blockers)),
        evidence_required,
        approvals_required,
        next_action,
        safety,
    )
    projection = _client_safe_projection(report.to_dict())
    reject_unsafe_input(projection, label="client-safe projection")
    workspace = _workspace_section(projection)
    blockers = list(dict.fromkeys([*report.blockers, *(workspace.get("blocking_reasons") or workspace.get("blockers") or [])]))
    projection = dict(projection)
    projection["blockers"] = blockers
    return CommerceOperationsCycleReport(
        report.report_version,
        report.generated_at,
        report.cycle_mode,
        report.overall_status,
        report.evidence_class,
        report.confidence_claim,
        report.live_requested,
        False,
        report.marketplace,
        report.supplier,
        report.consumer_attention,
        report.synthesis,
        report.product_validation,
        report.trustos,
        report.governor,
        report.approval_ledger,
        report.launch_draft_readiness,
        report.site_draft_readiness,
        workspace,
        projection,
        tuple(blockers),
        report.evidence_required,
        report.approvals_required,
        report.next_best_action,
        report.safety_summary,
    )


def markdown(report: Mapping[str, Any] | CommerceOperationsCycleReport) -> str:
    if isinstance(report, CommerceOperationsCycleReport):
        return report.to_markdown()
    return CommerceOperationsCycleReport(
        report_version=str(report.get("report_version") or REPORT_VERSION),
        generated_at=str(report.get("generated_at") or GENERATED_AT),
        cycle_mode=str(report.get("cycle_mode") or "dry_run"),
        overall_status=str(report.get("overall_status") or "plan_only"),
        evidence_class=str(report.get("evidence_class") or "not_live_validated"),
        confidence_claim="not_live_validated",
        live_requested=bool(report.get("live_requested")),
        live_validated=False,
        marketplace=dict(report.get("marketplace") or {}),
        supplier=dict(report.get("supplier") or {}),
        consumer_attention=dict(report.get("consumer_attention") or {}),
        synthesis=dict(report.get("synthesis") or {}),
        product_validation=dict(report.get("product_validation") or {}),
        trustos=dict(report.get("trustos") or {}),
        governor=dict(report.get("governor") or {}),
        approval_ledger=dict(report.get("approval_ledger") or {}),
        launch_draft_readiness=dict(report.get("launch_draft_readiness") or {}),
        site_draft_readiness=dict(report.get("site_draft_readiness") or {}),
        client_workspace=dict(report.get("client_workspace") or {}),
        client_safe_projection=dict(report.get("client_safe_projection") or {}),
        blockers=tuple(report.get("blockers") or ()),
        evidence_required=tuple(report.get("evidence_required") or ()),
        approvals_required=tuple(report.get("approvals_required") or ()),
        next_best_action=str(report.get("next_best_action") or ""),
        safety_summary=dict(report.get("safety_summary") or {}),
    ).to_markdown()


__all__ = [
    "REPORT_VERSION",
    "GENERATED_AT",
    "EVIDENCE_CLASSES",
    "STAGE_ORDER",
    "UNIFORM_STAGE_KEYS",
    "CommerceOperationsCycleReport",
    "build_commerce_operations_cycle",
    "markdown",
    "reject_unsafe_input",
]

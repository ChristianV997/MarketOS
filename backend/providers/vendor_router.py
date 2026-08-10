"""Deterministic, metadata-only SaaS capability routing.

This module deliberately complements the ProviderRegistry: it ranks catalog
records for an operator plan but never constructs a client, retrieves a secret,
or calls a vendor.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .capabilities import CapabilityDefinition, get_capability_definition, list_capability_definitions
from .vendor_catalog import list_vendor_capability_records
from .vendor_models import IntegrationMode, VendorCapability, VendorRouteRecommendation, VendorStage

_STAGE_RANK = {VendorStage.USE_NOW: 0, VendorStage.EVALUATE_NEXT: 1, VendorStage.DEFER: 2}
_MODE_RANK = {
    IntegrationMode.READ_ONLY_API: 0, IntegrationMode.MANUAL_EXPORT: 1, IntegrationMode.CSV_IMPORT: 2,
    IntegrationMode.CATALOG_ONLY: 3, IntegrationMode.GATEWAY: 4, IntegrationMode.MCP_TOOL: 5,
    IntegrationMode.SELF_HOSTED_SIDECAR: 6, IntegrationMode.EMBEDDED_APP: 7,
    IntegrationMode.WRITE_API_REQUIRES_APPROVAL: 8,
}


def list_capabilities() -> tuple[CapabilityDefinition, ...]:
    return list_capability_definitions()


def list_vendor_capabilities() -> tuple[VendorCapability, ...]:
    return list_vendor_capability_records()


def list_vendors_by_capability(capability_id: str) -> tuple[VendorCapability, ...]:
    get_capability_definition(capability_id)
    values = [item for item in list_vendor_capabilities() if item.capability_id == capability_id]
    return tuple(sorted(values, key=lambda item: (_STAGE_RANK[item.use_stage], not item.mvp_allowed,
                                                   item.live_mutation_risk, _MODE_RANK[item.integration_mode], item.vendor_id)))


def _env_vars_for(record: VendorCapability) -> tuple[str, ...]:
    return {
        "supabase": ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"),
        "posthog": ("POSTHOG_PROJECT_API_KEY",), "sentry": ("SENTRY_DSN",), "resend": ("RESEND_API_KEY",),
        "cloudflare_ai_gateway": ("CLOUDFLARE_AI_GATEWAY_URL",), "vercel_ai_gateway": ("VERCEL_AI_GATEWAY_URL",),
        "openrouter": ("OPENROUTER_API_KEY",), "9router": ("NINE_ROUTER_API_KEY",),
        "upstash": ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"), "qstash": ("QSTASH_TOKEN",),
    }.get(record.vendor_id, ())


def recommend_vendor_for_capability(capability_id: str, workspace_stage: str = "mvp") -> VendorRouteRecommendation:
    candidates = list_vendors_by_capability(capability_id)
    if workspace_stage == "mvp":
        eligible = [item for item in candidates if item.mvp_allowed and item.use_stage == VendorStage.USE_NOW and not item.live_mutation_risk]
        # AI routing is deliberately an explicit evaluation plan, not an MVP runtime dependency.
        if not eligible and capability_id == "ai_model_routing":
            eligible = [item for item in candidates if item.use_stage == VendorStage.EVALUATE_NEXT and not item.live_mutation_risk]
    else:
        eligible = [item for item in candidates if item.use_stage != VendorStage.DEFER and not item.live_mutation_risk]
    selected = eligible[0] if eligible else None
    definition = get_capability_definition(capability_id)
    blockers: list[str] = []
    if selected is None:
        blockers.append("no_safe_vendor_selected_for_requested_stage")
    if any(item.live_mutation_risk for item in candidates):
        blockers.append("write_or_live-capable alternatives require a separate human-approved integration")
    return VendorRouteRecommendation(
        capability_id=capability_id,
        recommended_vendor_id=selected.vendor_id if selected else None,
        alternatives=tuple(item.vendor_id for item in candidates if item is not selected),
        use_stage=selected.use_stage if selected else VendorStage.DEFER,
        rationale=tuple(filter(None, (
            f"Owned by {definition.owning_department}.",
            "MVP selection prefers use-now, no-mutation manual/read-only integration modes." if selected else "No safe MVP selection is available.",
            selected.notes if selected else "",
        ))),
        blockers=tuple(blockers), required_env_vars=_env_vars_for(selected) if selected else (),
        required_approvals=(definition.approval_policy,) if selected and selected.approval_required else (),
        next_action=("configure only after operator review" if selected and _env_vars_for(selected) else
                     "use documented manual/export workflow" if selected else "keep capability deferred"),
        manual_mode_available=any(item.integration_mode in {IntegrationMode.MANUAL_EXPORT, IntegrationMode.CSV_IMPORT, IntegrationMode.CATALOG_ONLY} for item in candidates),
    )


def compare_vendors(capability_id: str) -> dict[str, Any]:
    return {"capability": get_capability_definition(capability_id).to_dict(),
            "vendors": [item.to_dict() for item in list_vendors_by_capability(capability_id)]}


def build_workspace_vendor_plan(stage: str = "mvp") -> dict[str, Any]:
    recommendations = [recommend_vendor_for_capability(item.capability_id, stage) for item in list_capabilities()]
    selected = [item for item in recommendations if item.recommended_vendor_id]
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in selected:
        grouped[get_capability_definition(item.capability_id).owning_department].append(item.capability_id)
    return {
        "stage": stage, "routing_is_metadata_only": True, "external_calls": False, "live_mutations_enabled": False,
        "recommendations": [item.to_dict() for item in recommendations],
        "selected_capability_ids": [item.capability_id for item in selected],
        "department_capabilities": {name: sorted(values) for name, values in sorted(grouped.items())},
        "deferred_capability_ids": [item.capability_id for item in recommendations if item.recommended_vendor_id is None],
    }


def report_to_dict(stage: str = "mvp", capability_id: str | None = None) -> dict[str, Any]:
    if capability_id:
        return {"stage": stage, "comparison": compare_vendors(capability_id),
                "recommendation": recommend_vendor_for_capability(capability_id, stage).to_dict(),
                "network_calls": False, "mutated": False}
    return {**build_workspace_vendor_plan(stage), "network_calls": False, "mutated": False,
            "catalog_source_date": "2026-08-09", "pricing_caveat": "Verify current pricing before committing spend."}


def report_to_markdown(stage: str = "mvp", capability_id: str | None = None) -> str:
    report = report_to_dict(stage, capability_id)
    if capability_id:
        choice = report["recommendation"]
        lines = ["# MarketOS SaaS capability report", "", f"- Capability: `{capability_id}`", f"- Recommended vendor: `{choice['recommended_vendor_id'] or 'deferred'}`", f"- Stage: `{choice['use_stage']}`", "", "## Safety", "", "- This report did not contact a provider or enable a live integration."]
        return "\n".join(lines) + "\n"
    lines = ["# MarketOS MVP SaaS capability plan", "", "- Routing is metadata-only; no provider was contacted.", "- Pricing is intentionally qualitative; verify current pricing before committing spend.", "", "## Recommended routes", ""]
    for choice in report["recommendations"]:
        if choice["recommended_vendor_id"]:
            lines.append(f"- `{choice['capability_id']}` -> `{choice['recommended_vendor_id']}` ({choice['use_stage']})")
    lines += ["", "## Deferred gaps", ""]
    lines += [f"- `{item}`" for item in report["deferred_capability_ids"]]
    return "\n".join(lines) + "\n"


__all__ = ["build_workspace_vendor_plan", "compare_vendors", "list_capabilities", "list_vendor_capabilities", "list_vendors_by_capability", "recommend_vendor_for_capability", "report_to_dict", "report_to_markdown"]

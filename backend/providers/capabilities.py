"""Canonical SaaS capability taxonomy for the ProviderRegistry ecosystem.

This is metadata for routing and planning.  It does not instantiate vendors,
perform network calls, or grant execution authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CapabilityDefinition:
    capability_id: str
    display_name: str
    description: str
    owning_department: str
    default_agent_role: str
    canonical_event_types: tuple[str, ...]
    risk_level: str
    approval_policy: str
    allowed_mvp_modes: tuple[str, ...]
    forbidden_actions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_FORBID_MUTATION = ("spend", "publish", "send", "order", "payment", "refund", "fulfillment", "launch")
_CAPABILITY_ROWS = (
    ("database_auth_storage", "Database, Auth + Storage", "Managed durable workspace data, authentication and files.", "Data + Evidence", "data_platform_owner", ("canonical_event_persisted",), "medium", "server_only_credentials", ("mvp",), _FORBID_MUTATION),
    ("frontend_hosting", "Frontend hosting", "Static frontend deployment and preview delivery.", "Automation + Integrations", "frontend_platform_owner", ("frontend_deployment_requested",), "low", "manual_deploy_approval", ("mvp",), _FORBID_MUTATION),
    ("backend_hosting", "Backend hosting", "Managed FastAPI/container hosting.", "Automation + Integrations", "backend_platform_owner", ("backend_deployment_requested",), "medium", "manual_deploy_approval", ("mvp",), _FORBID_MUTATION),
    ("edge_security", "Edge security", "DNS, CDN, WAF and edge controls.", "Automation + Integrations", "security_platform_owner", ("edge_policy_reviewed",), "medium", "operator_approval", ("mvp",), _FORBID_MUTATION),
    ("queue_scheduler", "Queue + scheduler", "Durable message delivery and scheduled HTTP work.", "Automation + Integrations", "workflow_platform_owner", ("scheduled_job_requested",), "high", "disabled_until_operator_approval", ("evaluation",), _FORBID_MUTATION),
    ("analytics", "Analytics", "Product telemetry and feature measurement.", "Data + Evidence", "analytics_owner", ("analytics_event_exported",), "low", "telemetry_review", ("mvp",), _FORBID_MUTATION),
    ("error_tracking", "Error tracking", "Error capture and operational diagnostics.", "Automation + Integrations", "reliability_owner", ("error_report_exported",), "low", "telemetry_review", ("mvp",), _FORBID_MUTATION),
    ("email_notifications", "Email notifications", "Transactional email and manual report delivery.", "Sales + Support", "communications_owner", ("email_packet_exported",), "high", "manual_send_approval", ("evaluation",), _FORBID_MUTATION),
    ("ai_model_routing", "AI model routing", "Model gateway evaluation and cost-control metadata.", "AI Ops", "model_routing_owner", ("model_route_evaluated",), "medium", "evaluation_only", ("evaluation",), _FORBID_MUTATION),
    ("public_signal_ingestion", "Public signal ingestion", "Bounded public/no-auth, attributed market observations.", "Market Research", "signal_researcher", ("public_signal_observed",), "low", "explicit_manual_network_opt_in", ("mvp",), _FORBID_MUTATION),
    ("trend_discovery", "Trend discovery", "Trend-oriented research from public/manual sources.", "Market Research", "trend_researcher", ("trend_signal_imported",), "low", "manual_or_read_only", ("mvp", "evaluation"), _FORBID_MUTATION),
    ("market_research", "Market research", "Imported or manual market research evidence.", "Market Research", "market_researcher", ("research_evidence_imported",), "low", "manual_or_read_only", ("mvp", "evaluation"), _FORBID_MUTATION),
    ("product_research", "Product research", "Product/supplier research packets and imported evidence.", "Market Research", "product_researcher", ("product_research_imported",), "medium", "manual_import", ("mvp", "evaluation"), _FORBID_MUTATION),
    ("competitor_intelligence", "Competitor intelligence", "Read-only competitor evidence and reports.", "Market Research", "competitor_researcher", ("competitor_evidence_imported",), "medium", "manual_or_read_only", ("evaluation",), _FORBID_MUTATION),
    ("ad_spy", "Ad intelligence", "Manual/imported creative intelligence only.", "Creative Production", "creative_researcher", ("creative_evidence_imported",), "high", "manual_import", ("evaluation",), _FORBID_MUTATION),
    ("ecommerce_store_intelligence", "Store intelligence", "Read-only store technology and catalog observations.", "Market Research", "store_researcher", ("store_intelligence_imported",), "medium", "manual_or_read_only", ("evaluation",), _FORBID_MUTATION),
    ("ecommerce_platform", "Ecommerce platform", "Store platform reference and read-only import boundary.", "Ecommerce Operations", "commerce_operator", ("commerce_catalog_imported",), "high", "read_only_or_manual", ("mvp",), _FORBID_MUTATION),
    ("supplier_sourcing", "Supplier sourcing", "Supplier catalog/search evidence; never autonomous ordering.", "Ecommerce Operations", "supplier_researcher", ("supplier_catalog_imported",), "high", "manual_or_read_only", ("evaluation",), _FORBID_MUTATION),
    ("inventory_monitoring", "Inventory monitoring", "Read-only price and stock monitoring.", "Ecommerce Operations", "inventory_analyst", ("inventory_observed",), "medium", "read_only", ("evaluation",), _FORBID_MUTATION),
    ("fulfillment", "Fulfillment", "Shipment/fulfillment integration metadata.", "Ecommerce Operations", "fulfillment_operator", ("fulfillment_status_imported",), "high", "manual_approval", ("evaluation",), _FORBID_MUTATION),
    ("shipping_tracking", "Shipping tracking", "Read-only delivery tracking and exceptions.", "Ecommerce Operations", "fulfillment_operator", ("shipment_tracking_imported",), "medium", "read_only", ("evaluation",), _FORBID_MUTATION),
    ("payment_processing", "Payment processing", "Payment provider reference only; no payment action.", "Ecommerce Operations", "payments_operator", ("payment_observation_imported",), "high", "manual_approval", ("evaluation",), _FORBID_MUTATION),
    ("landing_page_builder", "Landing-page builder", "Manual landing-page packet/export target.", "Creative Production", "landing_page_specialist", ("landing_page_packet_exported",), "medium", "manual_export", ("mvp",), _FORBID_MUTATION),
    ("video_ad_generation", "Video-ad generation", "Manual creative brief/export target.", "Creative Production", "creative_producer", ("creative_brief_exported",), "medium", "manual_export", ("mvp",), _FORBID_MUTATION),
    ("social_content_generation", "Social-content generation", "Draft social content only; no publishing.", "Creative Production", "content_producer", ("social_draft_exported",), "medium", "manual_export", ("evaluation",), _FORBID_MUTATION),
    ("image_ad_generation", "Image-ad generation", "Draft image creative export target.", "Creative Production", "creative_producer", ("image_creative_exported",), "medium", "manual_export", ("evaluation",), _FORBID_MUTATION),
    ("creative_editing", "Creative editing", "Manual creative editing workspace/export target.", "Creative Production", "creative_producer", ("creative_edit_packet_exported",), "low", "manual_export", ("evaluation",), _FORBID_MUTATION),
    ("avatar_video", "Avatar video", "Draft avatar-video brief/export target.", "Creative Production", "creative_producer", ("avatar_brief_exported",), "medium", "manual_export", ("evaluation",), _FORBID_MUTATION),
    ("ugc_brief_execution", "UGC brief execution", "Creator-ready brief packet only, never fabricated testimony.", "Creative Production", "ugc_coordinator", ("ugc_brief_exported",), "high", "manual_creator_approval", ("evaluation",), _FORBID_MUTATION),
    ("chat_support", "Chat support", "Support playbook and routing metadata.", "Sales + Support", "support_lead", ("support_playbook_exported",), "high", "manual_export", ("mvp",), _FORBID_MUTATION),
    ("sales_dm", "Sales DMs", "Conversation playbook metadata; no messages are sent.", "Sales + Support", "sales_operator", ("sales_playbook_exported",), "high", "manual_export", ("evaluation",), _FORBID_MUTATION),
    ("crm", "CRM", "Customer relationship system integration planning.", "Sales + Support", "crm_owner", ("crm_import_packet_exported",), "high", "manual_import", ("evaluation",), _FORBID_MUTATION),
    ("appointment_booking", "Appointment booking", "Scheduling configuration/playbook planning.", "Sales + Support", "appointment_coordinator", ("booking_playbook_exported",), "medium", "manual_export", ("evaluation",), _FORBID_MUTATION),
    ("customer_support_automation", "Support automation", "Automation design packets only.", "Sales + Support", "support_automation_owner", ("support_automation_packet_exported",), "high", "manual_approval", ("evaluation",), _FORBID_MUTATION),
    ("workflow_automation", "Workflow automation", "Workflow connector catalog and component references.", "Automation + Integrations", "integration_engineer", ("workflow_component_reference_imported",), "high", "manual_or_read_only", ("evaluation",), _FORBID_MUTATION),
    ("durable_jobs", "Durable jobs", "Durable job platform evaluation, never automatically activated.", "Automation + Integrations", "workflow_platform_owner", ("durable_job_evaluated",), "high", "disabled_until_operator_approval", ("evaluation",), _FORBID_MUTATION),
    ("mcp_tooling", "MCP tooling", "MCP tool contract metadata and review.", "Automation + Integrations", "tooling_governor", ("mcp_contract_reviewed",), "high", "manual_tool_approval", ("evaluation",), _FORBID_MUTATION),
    ("coding_agent_orchestration", "Coding-agent orchestration", "Developer workflow pattern references only.", "AI Ops", "developer_experience_owner", ("agent_pattern_evaluated",), "medium", "reference_only", ("evaluation",), _FORBID_MUTATION),
    ("connector_component_registry", "Connector component registry", "Reusable connector/component discovery metadata.", "Automation + Integrations", "integration_engineer", ("connector_component_cataloged",), "medium", "manual_import", ("evaluation",), _FORBID_MUTATION),
)

CAPABILITIES: dict[str, CapabilityDefinition] = {
    row[0]: CapabilityDefinition(*row) for row in _CAPABILITY_ROWS
}


def list_capability_definitions() -> tuple[CapabilityDefinition, ...]:
    return tuple(CAPABILITIES[key] for key in sorted(CAPABILITIES))


def get_capability_definition(capability_id: str) -> CapabilityDefinition:
    try:
        return CAPABILITIES[capability_id]
    except KeyError as exc:
        raise KeyError(f"unknown capability_id: {capability_id}") from exc


__all__ = ["CapabilityDefinition", "CAPABILITIES", "get_capability_definition", "list_capability_definitions"]

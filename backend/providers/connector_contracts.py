"""Non-executing connector contract metadata for safe SaaS progression."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ConnectorContract:
    contract_type: str
    vendor_id: str
    required_inputs: tuple[str, ...]
    expected_outputs: tuple[str, ...]
    canonical_events_emitted: tuple[str, ...]
    risk_level: str
    approval_requirement: str
    allowed_in_mvp: bool
    forbidden_actions: tuple[str, ...]
    required_fixtures: tuple[str, ...]
    docs_requirement: str
    rollback_strategy: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ManualExportContract(ConnectorContract):
    pass
class CsvImportContract(ConnectorContract):
    pass
class ReadOnlyApiContract(ConnectorContract):
    pass
class WriteApiApprovalContract(ConnectorContract):
    pass
class McpToolContract(ConnectorContract):
    pass
class EmbeddedAppContract(ConnectorContract):
    pass
class GatewayContract(ConnectorContract):
    pass


_FORBIDDEN = ("spend", "publish", "send", "order", "payment", "refund", "fulfillment", "launch")
_SHOPIFY_READONLY_FORBIDDEN = _FORBIDDEN + ("create_product", "update_product", "publish_product", "mutate_inventory", "create_order", "capture_payment", "fulfill", "message_customer")


def _contract(cls: type[ConnectorContract], contract_type: str, vendor_id: str, *, inputs: tuple[str, ...], outputs: tuple[str, ...], events: tuple[str, ...], risk: str = "medium", approval: str = "manual_operator_approval", mvp: bool = False) -> ConnectorContract:
    return cls(contract_type, vendor_id, inputs, outputs, events, risk, approval, mvp, _FORBIDDEN,
               ("deterministic fixture", "canonical event fixture"), "Document scope, auth boundary, and source attribution.",
               "Disable the contract; preserve source artifacts and canonical events for audit.")


_CONTRACTS = (
    _contract(ReadOnlyApiContract, "read_only_api", "google_news_rss", inputs=("query", "limit", "explicit_network_opt_in"), outputs=("attributed public signals",), events=("public_signal_observed",), risk="low", approval="manual_network_opt_in", mvp=True),
    _contract(ReadOnlyApiContract, "read_only_api", "supabase", inputs=("canonical event", "server-only configuration"), outputs=("canonical event persistence result",), events=("canonical_event_persisted",), risk="medium", approval="operator_configuration", mvp=True),
    ManualExportContract("manual_file_read_only_import", "shopify", ("operator-provided Shopify-like JSON export",), ("PII-redacted catalog/order/store-context packet",), ("shopify_import_batch_started", "shopify_product_observed", "shopify_order_observed", "shopify_store_context_built", "shopify_import_batch_completed"), "high", "manual_export_review", True, _SHOPIFY_READONLY_FORBIDDEN, ("synthetic Shopify export fixture", "PII redaction fixture", "canonical event fixture"), "Document source provenance, PII redaction, manual-only input, and future least-privilege read scope.", "Stop using the importer and retain only redacted packet/event artifacts; it makes no remote state change."),
    _contract(ReadOnlyApiContract, "read_only_api_planned", "shopify", inputs=("operator-approved least-privilege read scope",), outputs=("future read-only catalog import packet",), events=("shopify_import_batch_completed",), risk="high", approval="read_only_scope_approval", mvp=False),
    _contract(McpToolContract, "mcp_tool", "zendrop_mcp", inputs=("operator-approved catalog query",), outputs=("catalog/search/tracking packet",), events=("supplier_catalog_imported",), risk="high", approval="explicit_tool_scope_approval"),
    _contract(ReadOnlyApiContract, "read_only_api", "autods", inputs=("operator-approved product list",), outputs=("stock/price observation",), events=("inventory_observed",), risk="medium", approval="read_only_scope_approval"),
    _contract(ManualExportContract, "manual_export", "creatify", inputs=("creative brief",), outputs=("manual creative export packet",), events=("creative_brief_exported",), mvp=True),
    _contract(ManualExportContract, "manual_export", "heygen", inputs=("avatar-video brief",), outputs=("manual avatar brief packet",), events=("avatar_brief_exported",), mvp=True),
    _contract(ManualExportContract, "manual_export", "pagefly", inputs=("landing-page packet",), outputs=("manual page-builder export",), events=("landing_page_packet_exported",), mvp=True),
    _contract(ManualExportContract, "manual_export", "gempages", inputs=("landing-page packet",), outputs=("manual page-builder export",), events=("landing_page_packet_exported",), mvp=True),
    _contract(ManualExportContract, "manual_export", "tidio", inputs=("support playbook",), outputs=("manual support-flow packet",), events=("support_playbook_exported",), risk="high", mvp=True),
    _contract(ManualExportContract, "manual_export", "manychat", inputs=("chat playbook",), outputs=("manual flow packet",), events=("support_playbook_exported",), risk="high", mvp=True),
    _contract(ManualExportContract, "manual_export", "pipedream", inputs=("component search result",), outputs=("component reference packet",), events=("workflow_component_reference_imported",), risk="high"),
    _contract(GatewayContract, "gateway", "qstash", inputs=("operator-approved job specification",), outputs=("scheduled-job evaluation",), events=("durable_job_evaluated",), risk="high", approval="disabled_until_operator_approval"),
    _contract(GatewayContract, "gateway", "cloudflare_ai_gateway", inputs=("model-routing evaluation",), outputs=("model-route evaluation packet",), events=("model_route_evaluated",), risk="medium", approval="evaluation_only"),
    _contract(GatewayContract, "gateway", "openrouter", inputs=("model-routing evaluation",), outputs=("model-route evaluation packet",), events=("model_route_evaluated",), risk="medium", approval="evaluation_only"),
    _contract(ManualExportContract, "manual_export", "9router", inputs=("developer routing plan",), outputs=("developer-tool routing packet",), events=("agent_pattern_evaluated",), risk="medium", approval="reference_only"),
    _contract(ManualExportContract, "manual_export", "ruflo", inputs=("developer workflow reference",), outputs=("agent pattern review",), events=("agent_pattern_evaluated",), risk="medium", approval="reference_only"),
)


def list_connector_contracts() -> tuple[ConnectorContract, ...]:
    return tuple(sorted(_CONTRACTS, key=lambda item: item.vendor_id))


def contracts_for_vendor(vendor_id: str) -> tuple[ConnectorContract, ...]:
    return tuple(item for item in list_connector_contracts() if item.vendor_id == vendor_id)


__all__ = ["ConnectorContract", "ManualExportContract", "CsvImportContract", "ReadOnlyApiContract", "WriteApiApprovalContract", "McpToolContract", "EmbeddedAppContract", "GatewayContract", "contracts_for_vendor", "list_connector_contracts"]

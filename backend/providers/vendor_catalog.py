"""Capability metadata layered on the existing ProviderRegistry catalog.

The registry remains the authority for actual provider definitions and adapters.
These records describe routing choices only; they never create credentials or
invoke a provider.  Official URLs are discovery references captured 2026-08-09;
operators must verify current pricing and terms before committing spend.
"""
from __future__ import annotations

from .capabilities import get_capability_definition
from .vendor_models import AuthMode, CostTier, IntegrationMode, VendorCapability, VendorStage

_OFFICIAL = {
    "supabase": "https://supabase.com/docs", "vercel": "https://vercel.com/docs", "railway": "https://docs.railway.com/",
    "render": "https://render.com/docs", "fly_io": "https://fly.io/docs/", "cloudflare": "https://developers.cloudflare.com/",
    "upstash": "https://upstash.com/docs", "posthog": "https://posthog.com/docs", "sentry": "https://docs.sentry.io/", "resend": "https://resend.com/docs",
    "google_news_rss": "https://news.google.com/rss", "trendspyg": "https://github.com/epogrebnyak/trendspyg", "firecrawl": "https://docs.firecrawl.dev/",
    "dropship_io": "https://dropship.io/", "minea": "https://www.minea.com/", "helium10": "https://www.helium10.com/", "jungle_scout": "https://www.junglescout.com/",
    "similarweb": "https://www.similarweb.com/", "semrush": "https://developer.semrush.com/", "builtwith": "https://api.builtwith.com/",
    "shopify": "https://shopify.dev/docs", "cj_dropshipping": "https://cjdropshipping.com/", "zendrop": "https://www.zendrop.com/", "zendrop_mcp": "https://www.zendrop.com/",
    "autods": "https://www.autods.com/", "dsers": "https://www.dsers.com/", "spocket": "https://www.spocket.co/", "printful": "https://www.printful.com/", "printify": "https://printify.com/",
    "shippo": "https://docs.goshippo.com/", "easypost": "https://docs.easypost.com/", "aftership": "https://www.aftership.com/docs/",
    "shopify_native_pages": "https://help.shopify.com/", "pagefly": "https://pagefly.io/", "gempages": "https://gempages.net/", "replo": "https://www.replo.app/", "unbounce": "https://unbounce.com/", "webflow": "https://developers.webflow.com/", "framer": "https://www.framer.com/",
    "creatify": "https://creatify.ai/", "heygen": "https://www.heygen.com/", "runway": "https://runwayml.com/", "pika": "https://pika.art/", "kling": "https://klingai.com/", "luma": "https://lumalabs.ai/", "capcut": "https://www.capcut.com/", "canva": "https://www.canva.com/developers/", "adcreative_ai": "https://www.adcreative.ai/", "pencil": "https://www.trypencil.com/",
    "tidio": "https://www.tidio.com/", "manychat": "https://manychat.com/", "gorgias": "https://docs.gorgias.com/", "hubspot": "https://developers.hubspot.com/", "gohighlevel": "https://marketplace.gohighlevel.com/", "intercom": "https://developers.intercom.com/", "zendesk": "https://developer.zendesk.com/", "cal_com": "https://cal.com/docs",
    "qstash": "https://upstash.com/docs/qstash", "n8n": "https://docs.n8n.io/", "make": "https://www.make.com/en/help", "zapier": "https://docs.zapier.com/", "pipedream": "https://pipedream.com/docs", "trigger_dev": "https://trigger.dev/docs", "inngest": "https://www.inngest.com/docs", "activepieces": "https://www.activepieces.com/docs",
    "cloudflare_ai_gateway": "https://developers.cloudflare.com/ai-gateway/", "vercel_ai_gateway": "https://vercel.com/docs/ai", "openrouter": "https://openrouter.ai/docs", "9router": "https://9router.com/", "litellm": "https://docs.litellm.ai/", "ruflo": "https://github.com/ruvnet/ruflo", "openclaw_pattern_reference": "https://docs.anthropic.com/",
}


def _record(vendor_id: str, capability_id: str, *, mode: IntegrationMode = IntegrationMode.CATALOG_ONLY,
            auth: AuthMode = AuthMode.MANUAL, cost: CostTier = CostTier.UNKNOWN,
            stage: VendorStage = VendorStage.DEFER, free: bool = False, mvp: bool = False,
            mutation: bool = False, approval: bool = False, oss: bool = False, license: str = "proprietary",
            notes: str = "") -> VendorCapability:
    definition = get_capability_definition(capability_id)
    return VendorCapability(
        vendor_id=vendor_id, capability_id=capability_id, integration_mode=mode, auth_mode=auth,
        cost_tier=cost, use_stage=stage, free_plan_available=free,
        paid_when="Verify current pricing before committing spend.", data_sent=("operator-approved packet",),
        data_received=("manual/export/read-only result",), canonical_events_emitted=definition.canonical_event_types,
        workspace_department=definition.owning_department, agent_owner_role=definition.default_agent_role,
        approval_required=approval or mutation, live_mutation_risk=mutation, mvp_allowed=mvp and not mutation,
        open_source_reference=oss, license=license, source_urls=(_OFFICIAL[vendor_id],),
        notes=notes or "Catalog/manual/export metadata only; verify current pricing and terms before committing spend.",
    )


_RECORDS = (
    # MVP infrastructure: managed systems are preferred; no client is activated here.
    _record("supabase", "database_auth_storage", mode=IntegrationMode.READ_ONLY_API, auth=AuthMode.SERVICE_ROLE, cost=CostTier.USAGE_BASED, stage=VendorStage.USE_NOW, free=True, mvp=True, notes="Existing optional EventRepository adapter; server-only credentials; no default runtime migration."),
    _record("vercel", "frontend_hosting", mode=IntegrationMode.CATALOG_ONLY, auth=AuthMode.MANUAL, cost=CostTier.USAGE_BASED, stage=VendorStage.USE_NOW, free=True, mvp=True),
    _record("railway", "backend_hosting", mode=IntegrationMode.CATALOG_ONLY, auth=AuthMode.MANUAL, cost=CostTier.USAGE_BASED, stage=VendorStage.USE_NOW, free=True, mvp=True),
    _record("render", "backend_hosting", mode=IntegrationMode.CATALOG_ONLY, auth=AuthMode.MANUAL, cost=CostTier.USAGE_BASED, stage=VendorStage.USE_NOW, free=True, mvp=True),
    _record("fly_io", "backend_hosting", cost=CostTier.USAGE_BASED, stage=VendorStage.EVALUATE_NEXT),
    _record("cloudflare", "edge_security", mode=IntegrationMode.CATALOG_ONLY, cost=CostTier.USAGE_BASED, stage=VendorStage.USE_NOW, free=True, mvp=True),
    _record("upstash", "queue_scheduler", mode=IntegrationMode.CATALOG_ONLY, auth=AuthMode.API_KEY, cost=CostTier.USAGE_BASED, stage=VendorStage.EVALUATE_NEXT),
    _record("posthog", "analytics", mode=IntegrationMode.CATALOG_ONLY, auth=AuthMode.API_KEY, cost=CostTier.USAGE_BASED, stage=VendorStage.USE_NOW, free=True, mvp=True, oss=True, license="MIT"),
    _record("sentry", "error_tracking", mode=IntegrationMode.CATALOG_ONLY, auth=AuthMode.API_KEY, cost=CostTier.USAGE_BASED, stage=VendorStage.USE_NOW, free=True, mvp=True),
    _record("resend", "email_notifications", mode=IntegrationMode.MANUAL_EXPORT, auth=AuthMode.API_KEY, cost=CostTier.USAGE_BASED, stage=VendorStage.EVALUATE_NEXT),
    # Market research stays manual/read-only. Google News RSS is the one implemented no-auth pilot.
    _record("google_news_rss", "public_signal_ingestion", mode=IntegrationMode.READ_ONLY_API, auth=AuthMode.NONE, cost=CostTier.FREE, stage=VendorStage.USE_NOW, free=True, mvp=True, notes="Existing bounded Google News RSS public-signal adapter; explicit network opt-in, cache/stale fallback, advisory events only."),
    _record("trendspyg", "trend_discovery", mode=IntegrationMode.MANUAL_EXPORT, auth=AuthMode.MANUAL, cost=CostTier.FREE, stage=VendorStage.EVALUATE_NEXT, oss=True, license="MIT"),
    _record("firecrawl", "market_research", mode=IntegrationMode.CATALOG_ONLY, auth=AuthMode.API_KEY, cost=CostTier.USAGE_BASED, stage=VendorStage.DEFER, notes="Requires API key and broad web extraction review; do not bypass access controls."),
    _record("dropship_io", "product_research", stage=VendorStage.EVALUATE_NEXT, cost=CostTier.MEDIUM),
    _record("minea", "ad_spy", stage=VendorStage.DEFER, cost=CostTier.MEDIUM),
    _record("helium10", "product_research", stage=VendorStage.EVALUATE_NEXT, cost=CostTier.MEDIUM),
    _record("jungle_scout", "product_research", stage=VendorStage.EVALUATE_NEXT, cost=CostTier.MEDIUM),
    _record("similarweb", "competitor_intelligence", stage=VendorStage.DEFER, cost=CostTier.HIGH),
    _record("semrush", "competitor_intelligence", mode=IntegrationMode.CATALOG_ONLY, auth=AuthMode.API_KEY, cost=CostTier.HIGH, stage=VendorStage.DEFER, notes="Official API is credentialed/paid; manual research only until reviewed."),
    _record("builtwith", "ecommerce_store_intelligence", mode=IntegrationMode.CATALOG_ONLY, auth=AuthMode.API_KEY, cost=CostTier.HIGH, stage=VendorStage.DEFER),
    _record("semrush", "social_content_generation", mode=IntegrationMode.MANUAL_EXPORT, cost=CostTier.HIGH, stage=VendorStage.DEFER, notes="Content research reference only; no publishing or direct API integration is selected."),
    # Commerce references: no operational write API is selected in MVP.
    _record("shopify", "ecommerce_platform", mode=IntegrationMode.MANUAL_EXPORT, auth=AuthMode.MANUAL, cost=CostTier.MEDIUM, stage=VendorStage.USE_NOW, mvp=True, notes="Operator-provided, PII-redacted manual export import only. Authenticated least-privilege read-only API access is evaluate-next; all mutations remain outside this router."),
    _record("shopify", "inventory_monitoring", mode=IntegrationMode.MANUAL_EXPORT, auth=AuthMode.MANUAL, cost=CostTier.MEDIUM, stage=VendorStage.USE_NOW, mvp=True, notes="Operator-provided, PII-redacted Shopify export import only. Authenticated read-only API access is evaluate-next; inventory mutation is forbidden."),
    _record("shopify", "payment_processing", mode=IntegrationMode.CATALOG_ONLY, auth=AuthMode.APP_INSTALLATION, cost=CostTier.MEDIUM, stage=VendorStage.DEFER, notes="Payment metadata only; no payment or refund action is available through this plan."),
    _record("cj_dropshipping", "supplier_sourcing", stage=VendorStage.EVALUATE_NEXT, cost=CostTier.USAGE_BASED),
    _record("zendrop", "supplier_sourcing", stage=VendorStage.EVALUATE_NEXT, cost=CostTier.USAGE_BASED),
    _record("zendrop_mcp", "supplier_sourcing", mode=IntegrationMode.MCP_TOOL, auth=AuthMode.MCP, cost=CostTier.UNKNOWN, stage=VendorStage.EVALUATE_NEXT, approval=True, notes="Contract reference only; catalog/search/tracking must be explicitly read-only."),
    _record("autods", "inventory_monitoring", mode=IntegrationMode.READ_ONLY_API, auth=AuthMode.API_KEY, cost=CostTier.MEDIUM, stage=VendorStage.EVALUATE_NEXT),
    _record("dsers", "supplier_sourcing", stage=VendorStage.DEFER, cost=CostTier.MEDIUM),
    _record("spocket", "supplier_sourcing", stage=VendorStage.EVALUATE_NEXT, cost=CostTier.MEDIUM),
    _record("printful", "fulfillment", stage=VendorStage.DEFER, cost=CostTier.USAGE_BASED),
    _record("printify", "fulfillment", stage=VendorStage.DEFER, cost=CostTier.USAGE_BASED),
    _record("shippo", "shipping_tracking", mode=IntegrationMode.READ_ONLY_API, auth=AuthMode.API_KEY, cost=CostTier.USAGE_BASED, stage=VendorStage.EVALUATE_NEXT),
    _record("easypost", "shipping_tracking", mode=IntegrationMode.READ_ONLY_API, auth=AuthMode.API_KEY, cost=CostTier.USAGE_BASED, stage=VendorStage.EVALUATE_NEXT),
    _record("aftership", "shipping_tracking", mode=IntegrationMode.READ_ONLY_API, auth=AuthMode.API_KEY, cost=CostTier.USAGE_BASED, stage=VendorStage.EVALUATE_NEXT),
    # Creative tools are export destinations; outputs remain drafts and never publish.
    _record("shopify_native_pages", "landing_page_builder", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.EVALUATE_NEXT, cost=CostTier.MEDIUM),
    _record("pagefly", "landing_page_builder", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.USE_NOW, cost=CostTier.MEDIUM, mvp=True),
    _record("gempages", "landing_page_builder", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.USE_NOW, cost=CostTier.MEDIUM, mvp=True),
    _record("replo", "landing_page_builder", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.EVALUATE_NEXT, cost=CostTier.HIGH),
    _record("unbounce", "landing_page_builder", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.DEFER, cost=CostTier.HIGH),
    _record("webflow", "landing_page_builder", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.EVALUATE_NEXT, cost=CostTier.MEDIUM),
    _record("framer", "landing_page_builder", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.EVALUATE_NEXT, cost=CostTier.MEDIUM),
    _record("creatify", "video_ad_generation", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.USE_NOW, cost=CostTier.USAGE_BASED, mvp=True),
    _record("heygen", "avatar_video", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.USE_NOW, cost=CostTier.USAGE_BASED, mvp=True),
    _record("creatify", "ugc_brief_execution", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.EVALUATE_NEXT, cost=CostTier.USAGE_BASED, notes="Brief export only; no fabricated creator experience or external creator outreach."),
    _record("runway", "video_ad_generation", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.EVALUATE_NEXT, cost=CostTier.USAGE_BASED),
    _record("pika", "video_ad_generation", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.EVALUATE_NEXT, cost=CostTier.USAGE_BASED),
    _record("kling", "video_ad_generation", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.EVALUATE_NEXT, cost=CostTier.USAGE_BASED),
    _record("luma", "video_ad_generation", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.EVALUATE_NEXT, cost=CostTier.USAGE_BASED),
    _record("capcut", "creative_editing", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.EVALUATE_NEXT, cost=CostTier.FREE, free=True),
    _record("canva", "image_ad_generation", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.EVALUATE_NEXT, cost=CostTier.USAGE_BASED, free=True),
    _record("adcreative_ai", "image_ad_generation", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.DEFER, cost=CostTier.MEDIUM),
    _record("pencil", "video_ad_generation", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.DEFER, cost=CostTier.HIGH),
    # Sales/support exports retain operator ownership.
    _record("tidio", "chat_support", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.USE_NOW, cost=CostTier.USAGE_BASED, free=True, mvp=True),
    _record("manychat", "chat_support", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.USE_NOW, cost=CostTier.USAGE_BASED, free=True, mvp=True),
    _record("manychat", "sales_dm", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.DEFER, cost=CostTier.USAGE_BASED, notes="Conversation playbook export only; no direct message sending."),
    _record("tidio", "customer_support_automation", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.DEFER, cost=CostTier.USAGE_BASED, notes="Automation design packet only; no customer communication is sent."),
    _record("gorgias", "chat_support", stage=VendorStage.EVALUATE_NEXT, cost=CostTier.MEDIUM),
    _record("hubspot", "crm", stage=VendorStage.EVALUATE_NEXT, cost=CostTier.USAGE_BASED, free=True),
    _record("gohighlevel", "crm", stage=VendorStage.DEFER, cost=CostTier.HIGH),
    _record("intercom", "chat_support", stage=VendorStage.DEFER, cost=CostTier.HIGH),
    _record("zendesk", "chat_support", stage=VendorStage.DEFER, cost=CostTier.HIGH),
    _record("cal_com", "appointment_booking", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.EVALUATE_NEXT, cost=CostTier.FREE, free=True, oss=True, license="AGPL-3.0"),
    # Automation/AI alternatives are cataloged, never activated by this router.
    _record("qstash", "durable_jobs", mode=IntegrationMode.CATALOG_ONLY, auth=AuthMode.API_KEY, cost=CostTier.USAGE_BASED, stage=VendorStage.EVALUATE_NEXT),
    _record("n8n", "workflow_automation", mode=IntegrationMode.SELF_HOSTED_SIDECAR, auth=AuthMode.MANUAL, cost=CostTier.LOW, stage=VendorStage.DEFER, oss=True, license="Sustainable-Use"),
    _record("make", "workflow_automation", stage=VendorStage.DEFER, cost=CostTier.MEDIUM),
    _record("zapier", "workflow_automation", stage=VendorStage.DEFER, cost=CostTier.MEDIUM),
    _record("pipedream", "connector_component_registry", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.EVALUATE_NEXT, cost=CostTier.USAGE_BASED),
    _record("pipedream", "mcp_tooling", mode=IntegrationMode.MANUAL_EXPORT, stage=VendorStage.DEFER, cost=CostTier.USAGE_BASED, approval=True, notes="Component-reference review only; no remote MCP tool is installed or executed."),
    _record("trigger_dev", "durable_jobs", stage=VendorStage.EVALUATE_NEXT, cost=CostTier.USAGE_BASED),
    _record("inngest", "durable_jobs", stage=VendorStage.EVALUATE_NEXT, cost=CostTier.USAGE_BASED),
    _record("activepieces", "workflow_automation", mode=IntegrationMode.SELF_HOSTED_SIDECAR, stage=VendorStage.DEFER, cost=CostTier.LOW, oss=True, license="MIT"),
    _record("cloudflare_ai_gateway", "ai_model_routing", mode=IntegrationMode.GATEWAY, auth=AuthMode.API_KEY, cost=CostTier.USAGE_BASED, stage=VendorStage.EVALUATE_NEXT),
    _record("vercel_ai_gateway", "ai_model_routing", mode=IntegrationMode.GATEWAY, auth=AuthMode.API_KEY, cost=CostTier.USAGE_BASED, stage=VendorStage.EVALUATE_NEXT),
    _record("openrouter", "ai_model_routing", mode=IntegrationMode.GATEWAY, auth=AuthMode.API_KEY, cost=CostTier.USAGE_BASED, stage=VendorStage.EVALUATE_NEXT),
    _record("9router", "coding_agent_orchestration", mode=IntegrationMode.GATEWAY, auth=AuthMode.API_KEY, cost=CostTier.UNKNOWN, stage=VendorStage.EVALUATE_NEXT),
    _record("litellm", "ai_model_routing", mode=IntegrationMode.SELF_HOSTED_SIDECAR, auth=AuthMode.API_KEY, cost=CostTier.LOW, stage=VendorStage.DEFER, oss=True, license="MIT"),
    _record("ruflo", "coding_agent_orchestration", mode=IntegrationMode.CATALOG_ONLY, cost=CostTier.UNKNOWN, stage=VendorStage.DEFER, oss=True, license="MIT"),
    _record("openclaw_pattern_reference", "coding_agent_orchestration", mode=IntegrationMode.CATALOG_ONLY, cost=CostTier.FREE, stage=VendorStage.DEFER, oss=True, license="reference_only"),
)


def list_vendor_capability_records() -> tuple[VendorCapability, ...]:
    return tuple(sorted(_RECORDS, key=lambda record: (record.capability_id, record.vendor_id)))


def vendor_capability_records_for(vendor_id: str) -> tuple[VendorCapability, ...]:
    return tuple(record for record in list_vendor_capability_records() if record.vendor_id == vendor_id)


__all__ = ["list_vendor_capability_records", "vendor_capability_records_for"]

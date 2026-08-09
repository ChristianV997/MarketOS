"""backend.providers.provider_catalog — initial Provider Registry seed data.

Every dollar figure below is a documented, conservative estimate of public
list pricing at authoring time — not a live price lookup, and not a
credential. Payment-processing percentages are env-overridable (mirroring
backend.validation.margin_calculator's own env-tunable-constant convention)
since those numbers matter most for cost comparisons and change over time;
fixed monthly costs are plain literals with a `notes` field documenting the
source tier, since those change rarely enough that a comment is sufficient
and a per-provider env var for every line item would be unwarranted sprawl
for this catalog's purpose (a stack *comparison*, not a billing system).

Importing this module registers every provider into `provider_registry` as
a side effect — `from backend.providers import provider_registry` always
sees a populated registry.
"""
from __future__ import annotations

import os

from .registry import provider_registry
from .schemas import Provider, ProviderCostComponent, ProviderPlan, ProviderRisk

_STRIPE_MX_PCT = float(os.getenv("PROVIDER_STRIPE_MX_FEE_PCT", "0.036"))
_STRIPE_MX_FIXED_MXN = float(os.getenv("PROVIDER_STRIPE_MX_FEE_FIXED_MXN", "3.0"))
_MERCADOPAGO_MX_PCT = float(os.getenv("PROVIDER_MERCADOPAGO_MX_FEE_PCT", "0.0349"))
_MERCADOPAGO_MX_FIXED_MXN = float(os.getenv("PROVIDER_MERCADOPAGO_MX_FEE_FIXED_MXN", "0.0"))
_SHOPIFY_PAYMENTS_PCT = float(os.getenv("PROVIDER_SHOPIFY_PAYMENTS_PCT", "0.029"))
_SHOPIFY_PAYMENTS_FIXED_USD = float(os.getenv("PROVIDER_SHOPIFY_PAYMENTS_FIXED_USD", "0.30"))

_fixed = lambda amount, notes="": ProviderCostComponent(kind="fixed_monthly", amount=amount, unit="USD/mo", notes=notes)  # noqa: E731


def _register_all() -> None:
    provider_registry.register(Provider(
        provider_id="hostinger",
        name="Hostinger",
        category="hosting",
        capabilities=("shared_hosting", "vps", "wordpress_hosting"),
        integration_status="adapter_available",
        plans=(
            ProviderPlan("business", "Business Web Hosting", (_fixed(3.99, "renews ~13.99 after promo period"),)),
            ProviderPlan("vps_kvm2", "VPS KVM 2", (_fixed(8.99, "renews ~13.99 after promo period"),)),
        ),
        license="proprietary",
        notes="Lowest-cost path for a self-managed WooCommerce store; no free tier beyond trial windows. HostingProvider adapter built (backend/integrations/hostinger.py) — read-only status/plan-usage only, no provisioning.",
    ))
    provider_registry.register(Provider(
        provider_id="woocommerce",
        name="WooCommerce",
        category="commerce_platform",
        capabilities=("catalog", "inventory", "orders", "refunds"),
        integration_status="adapter_available",
        plans=(ProviderPlan("core", "WooCommerce (self-hosted plugin)", (_fixed(0.0, "free plugin; hosting cost is separate (see hostinger)"),)),),
        risk=ProviderRisk(level="high", reasons=("GPL-3.0 is a restricted license under scripts/check_oss_policy.py",), requires_legal_approval=True),
        license="GPL-3.0",
        oss_inventory_ref="woocommerce",
        notes="Requires a WordPress host (e.g. hostinger) — its own fixed cost is $0. Adapter built and tested; legal review required before commercial deployment (same precedent as Postiz — see docs/oss/LICENSE_MANIFEST.yml).",
    ))
    provider_registry.register(Provider(
        provider_id="medusa",
        name="Medusa",
        category="headless_commerce",
        capabilities=("catalog", "inventory", "orders", "refunds", "carts", "fulfillment"),
        integration_status="adapter_available",
        plans=(ProviderPlan("self_hosted", "Medusa (self-hosted)", (_fixed(20.0, "illustrative small VPS/container infra line item"),)),),
        risk=ProviderRisk(level="low", reasons=("MIT-licensed, self-hosted, full data ownership",)),
        license="MIT",
        oss_inventory_ref="medusa",
        notes="MarketOS's owned-commerce path; already has a CommerceProvider adapter.",
    ))
    provider_registry.register(Provider(
        provider_id="shopify",
        name="Shopify",
        category="commerce_platform",
        capabilities=("catalog", "inventory", "orders", "refunds", "carts", "checkout", "app_ecosystem"),
        integration_status="catalog_only",
        plans=(
            ProviderPlan("basic", "Basic", (_fixed(39.0), ProviderCostComponent("payment_pct", _SHOPIFY_PAYMENTS_PCT, notes="Shopify Payments, online"), ProviderCostComponent("payment_fixed", _SHOPIFY_PAYMENTS_FIXED_USD))),
            ProviderPlan("grow", "Shopify", (_fixed(105.0), ProviderCostComponent("payment_pct", _SHOPIFY_PAYMENTS_PCT - 0.001), ProviderCostComponent("payment_fixed", _SHOPIFY_PAYMENTS_FIXED_USD))),
            ProviderPlan("advanced", "Advanced", (_fixed(399.0), ProviderCostComponent("payment_pct", _SHOPIFY_PAYMENTS_PCT - 0.002), ProviderCostComponent("payment_fixed", _SHOPIFY_PAYMENTS_FIXED_USD)), min_monthly_revenue_usd=10000.0),
        ),
        license="proprietary",
        notes="Preferred when checkout/app-ecosystem needs or an existing Shopify store justify the higher fixed cost.",
    ))
    provider_registry.register(Provider(
        provider_id="stripe_mx",
        name="Stripe (Mexico)",
        category="payment_processor",
        capabilities=("card_processing", "webhooks", "refunds"),
        integration_status="adapter_available",
        plans=(ProviderPlan("standard", "Standard", (ProviderCostComponent("payment_pct", _STRIPE_MX_PCT, notes="domestic card, MXN"), ProviderCostComponent("payment_fixed", _STRIPE_MX_FIXED_MXN, unit="MXN"))),),
        license="proprietary",
        notes="Fee-estimation-only adapter; distinct from connectors.stripe_connector's revenue-reconciliation job.",
    ))
    provider_registry.register(Provider(
        provider_id="mercado_pago_mx",
        name="Mercado Pago (Mexico)",
        category="payment_processor",
        capabilities=("card_processing", "webhooks", "refunds"),
        integration_status="adapter_available",
        plans=(ProviderPlan("standard", "Standard checkout", (ProviderCostComponent("payment_pct", _MERCADOPAGO_MX_PCT, notes="domestic card, MXN"), ProviderCostComponent("payment_fixed", _MERCADOPAGO_MX_FIXED_MXN, unit="MXN"))),),
        license="proprietary",
        notes="Regionally preferred in MX for buyer trust/checkout familiarity.",
    ))
    provider_registry.register(Provider(
        provider_id="chatwoot",
        name="Chatwoot",
        category="conversation_inbox",
        capabilities=("conversation_inbox", "support_ticketing"),
        integration_status="adapter_available",
        plans=(ProviderPlan("self_hosted", "Chatwoot (self-hosted)", (_fixed(0.0, "self-hosted; infra cost only"),)),),
        risk=ProviderRisk(level="low", reasons=("MIT-licensed",)),
        license="MIT",
        oss_inventory_ref="chatwoot",
        notes="ConversationProvider adapter built (backend/integrations/chatwoot.py).",
    ))
    provider_registry.register(Provider(
        provider_id="n8n",
        name="n8n",
        category="workflow_automation",
        capabilities=("internal_workflows", "notifications", "crm_sync"),
        integration_status="adapter_available",
        plans=(ProviderPlan("internal", "n8n (internal sidecar)", (_fixed(0.0, "internal-only; not a billable client-facing line item"),)),),
        risk=ProviderRisk(level="medium", reasons=("Sustainable-Use license; internal operations only",), internal_only=True),
        license="Sustainable-Use",
        oss_inventory_ref="n8n",
        notes="Never recommended for a white-labeled, client-facing stack — internal-only per existing governance.",
    ))
    provider_registry.register(Provider(
        provider_id="mautic",
        name="Mautic",
        category="marketing_automation",
        capabilities=("email_marketing", "marketing_automation", "segmentation"),
        integration_status="adapter_available",
        plans=(ProviderPlan("self_hosted", "Mautic (self-hosted)", (_fixed(0.0, "self-hosted; infra cost only"),)),),
        risk=ProviderRisk(level="medium", reasons=("GPL-3.0-or-later",)),
        license="GPL-3.0-or-later",
        oss_inventory_ref="mautic",
        notes="MarketingAutomationProvider adapter built (backend/integrations/mautic.py).",
    ))
    provider_registry.register(Provider(
        provider_id="activepieces",
        name="Activepieces",
        category="workflow_automation",
        capabilities=("workflow_automation", "connectors"),
        integration_status="adapter_available",
        plans=(
            ProviderPlan("self_hosted", "Activepieces (self-hosted)", (_fixed(0.0, "self-hosted; infra cost only"),)),
            ProviderPlan("cloud_standard", "Cloud Standard", (_fixed(20.0),)),
        ),
        license="MIT",
        oss_inventory_ref="activepieces",
        notes="CustomerAutomationProvider adapter built (backend/integrations/activepieces.py) — distinct from the internal-only n8n WorkflowAutomationProvider.",
    ))
    provider_registry.register(Provider(
        provider_id="gohighlevel",
        name="GoHighLevel",
        category="crm",
        capabilities=("crm", "conversation_inbox", "marketing_automation", "white_label_saas"),
        integration_status="catalog_only",
        plans=(
            ProviderPlan("starter", "Starter", (_fixed(97.0),), min_monthly_revenue_usd=3000.0),
            ProviderPlan("unlimited", "Unlimited", (_fixed(297.0),), min_monthly_revenue_usd=8000.0),
            ProviderPlan("agency_pro", "Agency Pro / White Label", (_fixed(497.0),), min_monthly_revenue_usd=15000.0),
        ),
        risk=ProviderRisk(level="medium", reasons=("high fixed cost relative to a low-budget or validation-stage business",)),
        license="proprietary",
        notes="Only justified once client revenue clears the plan's min_monthly_revenue_usd threshold.",
    ))
    provider_registry.register(Provider(
        provider_id="postiz",
        name="Postiz",
        category="social_publishing",
        capabilities=("social_publishing",),
        integration_status="adapter_available",
        plans=(ProviderPlan("sidecar", "Postiz (sidecar)", (_fixed(0.0, "self-hosted sidecar; infra cost only"),)),),
        risk=ProviderRisk(level="high", reasons=("AGPL-3.0",), requires_legal_approval=True),
        license="AGPL-3.0",
        oss_inventory_ref="postiz",
        notes="Never recommended without an explicit legal-approval flag (postiz_legal_approval).",
    ))
    provider_registry.register(Provider(
        provider_id="posthog",
        name="PostHog",
        category="analytics",
        capabilities=("product_analytics", "pageviews", "custom_events"),
        integration_status="adapter_available",
        plans=(ProviderPlan("cloud", "PostHog Cloud (usage-based)", (_fixed(0.0, "generous free tier, then usage-based — see posthog.com/pricing"),)),),
        risk=ProviderRisk(level="low", reasons=("MIT-licensed",)),
        license="MIT",
        oss_inventory_ref="posthog",
        notes="Frontend client (posthog-js) already selected for pageviews/events. AnalyticsProvider adapter (backend/integrations/posthog_backend.py) adds server-side capture + HogQL query, both against PostHog Cloud.",
    ))
    provider_registry.register(Provider(
        provider_id="twenty",
        name="Twenty CRM",
        category="crm",
        capabilities=("crm", "pipeline", "contact_management"),
        integration_status="catalog_only",
        plans=(ProviderPlan("self_hosted", "Twenty (self-hosted)", (_fixed(0.0, "self-hosted; infra cost only"),)),),
        risk=ProviderRisk(level="high", reasons=("AGPL-3.0",), requires_legal_approval=True),
        license="AGPL-3.0",
        oss_inventory_ref="twenty-crm",
        notes="Deferred by explicit prior user decision; left untouched this pass. No CRMProvider adapter — catalog data only, so the Stack Planner's CRM-dependent strategies fall back to GoHighLevel (proprietary) or report the gap honestly.",
    ))


_register_all()

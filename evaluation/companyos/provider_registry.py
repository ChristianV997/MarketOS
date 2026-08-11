"""Curated provider candidates; metadata only, with no provider clients."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping, Sequence
from .credential_registry import ProviderCapabilityMatrix

PROVIDER_CATEGORIES = ("secrets_manager", "llm_gateway", "llm_provider", "observability", "intelligence_data", "search_serp_data", "scraping_proxy", "marketplace_api", "supplier_api", "crm", "email", "whatsapp_sms", "voice_ai", "accounting", "payments", "ecommerce_platform", "cms_website", "analytics", "workflow_automation", "integration_platform", "vector_database", "cloud_infrastructure")
INTEGRATION_STAGES = ("use_now_manual", "configure_reference_now", "integrate_soon", "integrate_later", "study_later", "avoid_for_now")
ACTION_MODES = ("reference_only", "manual_export_only", "read_only_requires_approval", "write_requires_approval", "blocked")


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value)
    return (str(value),)


def _clean(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _clean(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_clean(item) for item in value]
    return value


@dataclass(frozen=True)
class ProviderDefinition:
    provider_id: str
    name: str
    category: str
    recommended_use: str
    integration_stage: str
    commercial_use_note: str
    license_or_terms_risk: str
    security_risk: str
    operational_complexity: str
    credential_types_supported: tuple[str, ...]
    auth_modes: tuple[str, ...]
    tool_registry_mapping: tuple[str, ...]
    approval_ledger_mapping: tuple[str, ...]
    model_router_mapping: tuple[str, ...]
    knowledge_registry_mapping: tuple[str, ...]
    estimated_monthly_cost_min: float
    estimated_monthly_cost_max: float
    cost_driver: str
    free_tier_note: str
    start_now_recommendation: str
    avoid_now_reason: str
    default_action_mode: str = "reference_only"

    def __post_init__(self) -> None:
        if self.category not in PROVIDER_CATEGORIES:
            raise ValueError(f"invalid provider category: {self.category}")
        if self.integration_stage not in INTEGRATION_STAGES:
            raise ValueError(f"invalid integration stage: {self.integration_stage}")
        if self.default_action_mode not in ACTION_MODES:
            raise ValueError(f"invalid action mode: {self.default_action_mode}")
        if self.estimated_monthly_cost_min < 0 or self.estimated_monthly_cost_max < self.estimated_monthly_cost_min:
            raise ValueError("invalid provider cost band")


@dataclass(frozen=True)
class ProviderRegistryReport:
    report_version: str
    generated_at: str
    providers: tuple[ProviderDefinition, ...]
    capability_matrix: tuple[ProviderCapabilityMatrix, ...]
    categories: tuple[str, ...]
    integration_stages: tuple[str, ...]
    safety_summary: dict[str, Any]
    highest_priority_providers: tuple[str, ...]
    providers_to_avoid_now: tuple[str, ...]
    next_best_action: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)

    def to_markdown(self) -> str:
        lines = ["# CompanyOS Provider Registry", "", "## Summary", "", f"- Providers: **{len(self.providers)}**", f"- Categories: **{len(self.categories)}**", "- Mode: **reference-only, offline**", "", "## Highest-Priority Providers", ""]
        lines.extend(f"- **{provider}**" for provider in self.highest_priority_providers)
        lines += ["", "## Provider Candidates", "", "| Provider | Category | Stage | Action mode | Cost band |", "|---|---|---|---|---|"]
        for item in self.providers:
            lines.append(f"| {item.name} | {item.category} | {item.integration_stage} | {item.default_action_mode} | ${item.estimated_monthly_cost_min:.0f}-${item.estimated_monthly_cost_max:.0f}/mo |")
        lines += ["", "## Providers To Avoid Now", ""]
        lines.extend(f"- {provider}" for provider in self.providers_to_avoid_now)
        lines += ["", "## Safety", "", "- Provider entries are planning metadata; no SDK, API call, actor run, credential validation, or provider mutation is performed.", "- Most providers remain reference-only; live read-only use requires an Approval Ledger gate.", "", "## Next Best Action", "", self.next_best_action, ""]
        return "\n".join(lines)


def _provider(provider_id: str, name: str, category: str, use: str, stage: str, cost_min: float, cost_max: float, *, action: str = "reference_only", creds: tuple[str, ...] = ("api_key",), auth: tuple[str, ...] = ("manual_reference",), tools: tuple[str, ...] = (), approvals: tuple[str, ...] = (), routes: tuple[str, ...] = (), knowledge: tuple[str, ...] = (), driver: str = "usage", free: str = "Free tier and current pricing require operator verification.", avoid: str = "No live integration in this release.") -> ProviderDefinition:
    return ProviderDefinition(provider_id, name, category, use, stage, "Commercial use requires provider terms and owner review.", "Terms/licensing must be reviewed before use.", "Credential scope and data handling require a security review.", "Reference metadata only; no client is installed.", creds, auth, tools, approvals, routes, knowledge, cost_min, cost_max, driver, free, "Keep as a sanitized reference and manual-import candidate.", avoid, action)


def _seed_providers() -> list[ProviderDefinition]:
    providers: list[ProviderDefinition] = []
    for pid, name in (("infisical", "Infisical"), ("doppler", "Doppler"), ("aws-secrets-manager", "AWS Secrets Manager"), ("gcp-secret-manager", "GCP Secret Manager"), ("azure-key-vault", "Azure Key Vault"), ("github-actions-secrets", "GitHub Actions Secrets"), ("supabase-secrets", "Supabase Secrets")):
        providers.append(_provider(pid, name, "secrets_manager", "server-side secret reference storage", "configure_reference_now", 0, 50, creds=("api_key", "service_account"), auth=("manual_reference",), approvals=("provider_call", "workflow_resume"), driver="secret count", free="Plan/tier and limits require operator verification."))
    providers += [
        _provider("litellm", "LiteLLM", "llm_gateway", "central model gateway, virtual keys, spend tracking, and budgets", "integrate_soon", 0, 150, action="read_only_requires_approval", creds=("model_gateway_key",), tools=("run_script",), approvals=("model_spend", "provider_call"), routes=("local_low_cost", "cheap_api", "frontier_reasoning"), driver="model tokens"),
        _provider("openai", "OpenAI", "llm_provider", "frontier and cheap model candidate", "study_later", 0, 300, approvals=("model_spend", "provider_call"), routes=("cheap_api", "frontier_reasoning")),
        _provider("anthropic", "Anthropic", "llm_provider", "frontier reasoning candidate", "study_later", 0, 300, approvals=("model_spend", "provider_call"), routes=("frontier_reasoning",)),
        _provider("google-gemini", "Google Gemini", "llm_provider", "model provider candidate", "study_later", 0, 250, approvals=("model_spend", "provider_call"), routes=("cheap_api", "frontier_reasoning")),
        _provider("mistral", "Mistral", "llm_provider", "model provider candidate", "study_later", 0, 200, approvals=("model_spend", "provider_call"), routes=("cheap_api", "frontier_reasoning")),
        _provider("groq", "Groq", "llm_provider", "low-latency model candidate", "study_later", 0, 200, approvals=("model_spend", "provider_call"), routes=("cheap_api",)),
        _provider("together", "Together", "llm_provider", "model provider candidate", "study_later", 0, 200, approvals=("model_spend", "provider_call"), routes=("cheap_api",)),
        _provider("aws-bedrock", "AWS Bedrock", "llm_provider", "managed enterprise model boundary", "study_later", 0, 500, creds=("service_account",), approvals=("model_spend", "provider_call"), routes=("frontier_reasoning",)),
        _provider("ollama", "Ollama", "llm_provider", "local model runtime candidate", "use_now_manual", 0, 50, creds=("none",), auth=("none",), routes=("local_low_cost",)),
        _provider("llama-cpp", "llama.cpp", "llm_provider", "embedded local model runtime candidate", "study_later", 0, 50, creds=("none",), auth=("none",), routes=("local_low_cost",)),
        _provider("vllm", "vLLM", "llm_provider", "self-hosted inference candidate", "study_later", 50, 500, creds=("none",), auth=("none",), routes=("local_low_cost", "cheap_api")),
        _provider("langfuse", "Langfuse", "observability", "traces, prompts, evals, and cost monitoring", "integrate_soon", 0, 200, approvals=("provider_call", "model_spend"), knowledge=("trace_collection", "eval_dataset"), driver="trace volume"),
        _provider("phoenix", "Phoenix", "observability", "local observability and evaluation candidate", "study_later", 0, 150, creds=("none",), auth=("none",), knowledge=("trace_collection", "regression_testing")),
        _provider("open-telemetry", "OpenTelemetry/OpenInference", "observability", "portable traces and spans", "study_later", 0, 100, creds=("none",), auth=("none",), knowledge=("trace_collection",)),
    ]
    for pid, name, category, use, stage, cost in (("apify", "Apify", "intelligence_data", "broad public extraction and scheduled actors", "integrate_soon", (0, 200)), ("dataforseo", "DataForSEO", "search_serp_data", "SERP, keyword, and search demand intelligence", "integrate_soon", (50, 500)), ("serpapi", "SerpApi", "search_serp_data", "bounded search/SERP intelligence", "integrate_soon", (0, 300)), ("bright-data", "Bright Data", "scraping_proxy", "enterprise public-data infrastructure", "integrate_later", (500, 3000)), ("scrapingbee", "ScrapingBee", "scraping_proxy", "public page acquisition candidate", "study_later", (49, 500)), ("scraperapi", "ScraperAPI", "scraping_proxy", "public page acquisition candidate", "study_later", (49, 500)), ("oxylabs", "Oxylabs", "scraping_proxy", "enterprise hard-target acquisition", "avoid_for_now", (0, 5000)), ("browse-ai", "Browse AI", "intelligence_data", "manual monitored extraction candidate", "study_later", (0, 300))):
        approvals = ("provider_call", "web_data_acquisition")
        providers.append(_provider(pid, name, category, use, stage, cost[0], cost[1], action="read_only_requires_approval", approvals=approvals, tools=("search_web", "run_script"), driver="pages, rows, or requests", avoid="Terms, robots, privacy, and anti-bot review must pass before any live use."))
    providers += [
        _provider("official-marketplace-apis", "Official marketplace APIs", "marketplace_api", "compliant marketplace demand and listing validation", "configure_reference_now", 0, 300, action="read_only_requires_approval", creds=("api_key", "oauth_token"), auth=("manual_reference", "oauth"), approvals=("provider_call", "web_data_acquisition"), driver="API calls"),
        _provider("official-social-search-apis", "Official social/search APIs", "marketplace_api", "compliant public trend and content validation", "configure_reference_now", 0, 500, action="read_only_requires_approval", creds=("api_key", "oauth_token"), auth=("manual_reference", "oauth"), approvals=("provider_call", "web_data_acquisition"), driver="API calls"),
    ]
    for pid, name in (("composio", "Composio"), ("pipedream", "Pipedream"), ("apideck", "Apideck"), ("unified-to", "Unified.to"), ("activepieces", "Activepieces"), ("n8n", "n8n"), ("windmill", "Windmill")):
        providers.append(_provider(pid, name, "integration_platform" if pid in {"composio", "pipedream", "apideck", "unified-to"} else "workflow_automation", "future connector or workflow simplifier", "integrate_later" if pid in {"composio", "pipedream", "apideck", "unified-to"} else "study_later", 0, 300, action="write_requires_approval", approvals=("workflow_resume", "provider_call"), tools=("run_script",), driver="workflow runs", avoid="No external integration until Approval Ledger, scopes, and failure policy are implemented."))
    for pid, name, category, use, stage, cost, approvals in (("hubspot", "HubSpot", "crm", "CRM reference candidate", "integrate_later", (0, 500), ("crm_mutation", "email_send")), ("pipedrive", "Pipedrive", "crm", "CRM reference candidate", "study_later", (0, 300), ("crm_mutation",)), ("close", "Close", "crm", "sales CRM candidate", "study_later", (0, 300), ("crm_mutation", "email_send")), ("apollo", "Apollo", "crm", "lead research candidate", "study_later", (0, 500), ("crm_mutation", "email_send")), ("clay", "Clay", "crm", "lead enrichment candidate", "study_later", (0, 500), ("crm_mutation", "provider_call")), ("instantly", "Instantly", "email", "outreach candidate", "avoid_for_now", (0, 300), ("email_send",)), ("smartlead", "Smartlead", "email", "outreach candidate", "avoid_for_now", (0, 300), ("email_send",)), ("twilio", "Twilio", "whatsapp_sms", "messaging infrastructure candidate", "integrate_later", (0, 300), ("sms_send", "whatsapp_send")), ("meta-whatsapp-cloud", "Meta WhatsApp Cloud API", "whatsapp_sms", "official WhatsApp messaging candidate", "integrate_later", (0, 500), ("whatsapp_send",)), ("retell", "Retell", "voice_ai", "voice agent candidate", "avoid_for_now", (0, 500), ("voice_call",)), ("vapi", "Vapi", "voice_ai", "voice agent candidate", "avoid_for_now", (0, 500), ("voice_call",)), ("bland", "Bland", "voice_ai", "voice agent candidate", "avoid_for_now", (0, 500), ("voice_call",)), ("elevenlabs", "ElevenLabs", "voice_ai", "voice synthesis candidate", "study_later", (0, 300), ("voice_call",))):
        providers.append(_provider(pid, name, category, use, stage, cost[0], cost[1], action="blocked", approvals=approvals, driver="messages or minutes", avoid="Human consent, policy, and message/call approval are not implemented for live use."))
    for pid, name, category, use, stage, cost, approvals in (("quickbooks", "QuickBooks", "accounting", "accounting sync candidate", "integrate_later", (35, 300), ("accounting_sync", "invoice_creation")), ("xero", "Xero", "accounting", "accounting sync candidate", "integrate_later", (20, 300), ("accounting_sync", "invoice_creation")), ("stripe", "Stripe", "payments", "payment reference candidate", "avoid_for_now", (0, 100), ("payment_creation",)), ("paypal", "PayPal", "payments", "payment reference candidate", "avoid_for_now", (0, 100), ("payment_creation",)), ("shopify", "Shopify", "ecommerce_platform", "storefront reference candidate", "integrate_later", (39, 399), ("site_publish", "supplier_order", "payment_creation")), ("medusa", "Medusa", "ecommerce_platform", "headless storefront candidate", "study_later", (0, 300), ("site_publish",)), ("woocommerce", "WooCommerce", "ecommerce_platform", "open storefront reference candidate", "study_later", (0, 200), ("site_publish",)), ("webflow", "Webflow", "cms_website", "CMS website reference candidate", "study_later", (0, 300), ("site_publish",)), ("wix", "Wix", "cms_website", "business website reference candidate", "study_later", (0, 300), ("site_publish",)), ("squarespace", "Squarespace", "cms_website", "business website reference candidate", "study_later", (0, 300), ("site_publish",)), ("supabase", "Supabase", "vector_database", "future memory and event infrastructure", "integrate_later", (0, 500), ("vector_indexing", "accounting_sync"))):
        providers.append(_provider(pid, name, category, use, stage, cost[0], cost[1], action="blocked" if "payment" in approvals else "write_requires_approval", approvals=approvals, driver="seats, storage, or usage", avoid="No live account, publish, payment, or database action is available in this release."))
    return providers


def build_provider_registry(*, generated_at: str = "offline-deterministic", seed: Mapping[str, Any] | None = None) -> ProviderRegistryReport:
    providers = _seed_providers()
    overrides = {str(item.get("provider_id")): item for item in (seed or {}).get("providers", []) if isinstance(item, Mapping)}
    normalized: list[ProviderDefinition] = []
    for item in providers:
        override = overrides.get(item.provider_id, {})
        stage = str(override.get("integration_stage", item.integration_stage))
        action = str(override.get("default_action_mode", item.default_action_mode))
        if stage not in INTEGRATION_STAGES:
            stage = "study_later"
        if action not in ACTION_MODES:
            action = "blocked"
        normalized.append(replace(item, integration_stage=stage, default_action_mode=action))
    matrix = tuple(ProviderCapabilityMatrix(item.provider_id, tuple(f"cap-{item.provider_id}-{index}" for index, _ in enumerate(item.approval_ledger_mapping, 1)), (), ("sanitized_report",), ("live adapter not installed",), "reference_only") for item in normalized)
    high = tuple(item.provider_id for item in normalized if item.integration_stage == "integrate_soon")
    avoid = tuple(item.provider_id for item in normalized if item.integration_stage == "avoid_for_now")
    return ProviderRegistryReport("companyos-provider-registry-v1", generated_at, tuple(sorted(normalized, key=lambda item: item.provider_id)), matrix, PROVIDER_CATEGORIES, INTEGRATION_STAGES, {"read_only": True, "network_calls": False, "mutated": False, "credentials_present": False, "provider_clients_installed": False, "default_action_mode": "reference_only", "fail_closed": True}, high, avoid, "Review Apify and DataForSEO as bounded future intelligence candidates, but configure only metadata and Approval Ledger gates first.")


__all__ = ["PROVIDER_CATEGORIES", "INTEGRATION_STAGES", "ACTION_MODES", "ProviderDefinition", "ProviderCapabilityMatrix", "ProviderRegistryReport", "build_provider_registry"]

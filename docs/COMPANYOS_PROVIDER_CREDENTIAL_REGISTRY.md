# CompanyOS Credential / Provider / Subscription Registry v1

This registry is the metadata layer after the Approval Ledger. It answers: which provider candidates exist, what capabilities they could cover, where a future secret reference would live, who owns it, what scopes and budgets would apply, how it should be rotated, and what must be approved before activation.

It never stores a secret value, raw API key, OAuth token, password, private key, real account ID, customer recipient, or `.env` content. It never calls a provider, validates a credential, installs an SDK, activates a subscription, or writes a platform.

The DataForSEO adapter consumes this registry as metadata only. Its
`credential-dataforseo` reference proves only that a safe reference can be
declared; it never loads or validates a secret. Provider activation still
requires Approval Ledger approval, budget/rate caps, and terms/privacy review.

TrustOS consumes the same metadata to decide whether provider activation is
blocked, warned, or ready for a future professional/human review. It does not
read or validate the referenced secret.

## Why it follows the Approval Ledger

The Approval Ledger defines action-level gates. This registry attaches those gates to provider metadata and credential references. A provider can be strategically useful while still being blocked from activation. A credential can have a safe server-side reference while remaining `needed`, `pending_approval`, or `active_reference_only` rather than live.

## Credential references

A `CredentialReference` contains provider/account placeholders, environment, secret-manager reference, credential type, permission scopes, department owner, allowed tool/workflow/agent IDs, approval policy, risk, rate limits, budgets, rotation policy, health metadata, expiry, status, and notes.

Supported secret-manager references include Infisical, Doppler, AWS Secrets Manager, GCP Secret Manager, Azure Key Vault, Supabase Secrets, GitHub Actions Secrets, environment variables, and manual references. The value behind the reference is never accepted by the model or CLI.

Health status is metadata-only: `not_checked` means the registry has not made a network call. It is not proof that a provider account works.

## Provider registry

The registry covers:

- secret managers;
- model gateways and model providers;
- observability and eval systems;
- public intelligence, SERP, scraping-proxy, marketplace, supplier, and social/search candidates;
- workflow and integration platforms;
- CRM, messaging, voice, accounting, payments, commerce, CMS, analytics, vector, and cloud candidates.

Every provider has an integration stage, cost band, terms/security/operational risk, credential/auth metadata, tool categories, Approval Ledger request types, model routes, knowledge mappings, and a default action mode. Most entries are `reference_only`. `read_only_requires_approval` is a roadmap state, not an enabled network path.

## Intelligence provider plan

Current fixture/manual intelligence remains the working mode. The roadmap prioritizes:

1. Apify for broad public extraction and bounded scheduled actors;
2. DataForSEO or SerpApi for search/SERP and keyword evidence;
3. official marketplace/social/search APIs where compliant reliability matters;
4. Bright Data and Oxylabs only for later enterprise review, not the current phase.

Each data need declares its current mode, provider sequence, credentials, budget cap, terms/privacy reviews, output evidence model, and blocking gate. No actor, scrape, or API request is made by this plan.

## Subscriptions and cost control

Subscription entries are planning bands, not invoices or spend authority. Plans cover:

`phase_0_offline_only`, `phase_1_manual_imports`, `phase_2_live_read_only_intelligence`, `phase_3_model_gateway_observability`, `phase_4_sales_integrations`, and `phase_5_accounting_crm_ecommerce_integrations`.

Each plan tracks owner, billing frequency, included usage, overage risk, monthly range, capability coverage, replacement candidates, consolidation notes, activation approval, renewal review, and cancellation candidates. DataForSEO/SerpApi and LiteLLM/Ollama are intentionally presented as consolidation choices, not simultaneous purchases.

## Approval, tool, and model links

Provider mappings reuse existing vocabularies:

- `provider_call`, `web_data_acquisition`, and `model_spend` link to the Approval Ledger;
- `search_web`, `run_script`, `read_crm`, `send_email`, `query_vector_memory`, `sync_accounting`, `publish_site`, and `launch_ad` remain tool-level metadata only;
- LiteLLM maps to `local_low_cost`, `cheap_api`, and `frontier_reasoning`, while live external action remains blocked;
- Langfuse maps to future trace, prompt/version, eval-dataset, and cost-monitoring work;
- Composio, Pipedream, and Apideck are later integration simplifiers, not installed clients.

Activation gates require an owner, secret-manager reference, least-privilege scope, budget cap, terms/privacy review, read-only output test, and Approval Ledger decision. Customer credentials require an additional consent and privacy review.

## Commands

```powershell
python scripts/run_companyos_provider_registry.py --json
python scripts/run_companyos_provider_registry.py --markdown
python scripts/run_companyos_provider_registry.py --phase phase_2_live_read_only_intelligence --markdown
python scripts/run_companyos_provider_registry.py --provider apify --markdown
python scripts/run_companyos_provider_registry.py --provider dataforseo --markdown
python scripts/run_companyos_provider_registry.py --output artifacts/companyos_provider_registry/latest --markdown
```

The output is sanitized JSON/Markdown only. Do not commit generated artifacts.

The [Intelligence Live Read-Only Adapter Plan](INTELLIGENCE_ADAPTER_PLAN.md)
consumes these references to create offline request envelopes, cost/rate caps,
approval checks, and normalized evidence mappings. It does not activate or
validate any credential.

## Safety boundary

No credentials, API keys, OAuth tokens, private keys, provider calls, model calls, vector indexing, CRM/accounting mutations, email, WhatsApp/SMS, voice, payments, ads, publishing, orders, customer messages, subscription activation, or live network calls occur by default.

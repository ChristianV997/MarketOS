# Third-party notices

MarketOS is intended for commercial distribution. Upstream source is not
copied into the MarketOS commercial core: reviewed systems are connected only
through adapters, optional Python profiles, or independently deployed
sidecars. This notice file is aligned with
[`docs/oss/LICENSE_MANIFEST.yml`](docs/oss/LICENSE_MANIFEST.yml) and is not
legal advice.

| Component | Reviewed reference | License | Distribution and notice |
|---|---:|---|---|
| medusa | v2.14.2 | MIT | Commerce sidecar; retain its upstream MIT notice. |
| crawl4ai | v0.8.6 | Apache-2.0-with-attribution | Optional research worker; retain Apache notice and required attribution. |
| browser-use | v0.13.6 | MIT | Optional browser worker; retain upstream MIT notice. |
| pydantic-ai | v2.20.0 | MIT | Optional typed-agent profile; retain upstream MIT notice. |
| postiz | pending-legal-review | AGPL-3.0 | Independently deployed sidecar only; commercial use requires explicit legal approval. |
| n8n | n8n@2.30.5 | Sustainable-Use | Internal operational sidecar only; do not embed or white-label without review. |
| erpnext | pending-deferred-review | GPL-3.0 | Deferred; do not vendor into the commercial core. |
| airbyte | pending-deferred-review | review_required | Deferred pending license and integration review. |
| saleor | pending-benchmark-review | review_required | Benchmark only; do not deploy alongside Medusa. |
| twenty-crm | pending-deferred-review | AGPL-3.0 | Deferred by explicit user decision; AGPL requires legal review before adoption. |
| chatwoot | pending-deferred-review | MIT | ConversationProvider adapter built and tested (backend/integrations/chatwoot.py); MIT, no legal-review gate needed. |
| cal.com | pending-deferred-review | AGPL-3.0 | Deferred by explicit user decision; AGPL requires legal review before adoption. |
| posthog | posthog-js@1.x | MIT | Client SDK (posthog-js) against PostHog Cloud; retain upstream MIT notice. Default-off via VITE_POSTHOG_KEY; no session-replay enabled. Also consumed server-side via the optional `posthog` Python SDK for backend event capture + query. |
| temporal | pending-deferred-review | MIT | Deferred by explicit user decision; would replace hand-rolled workflow tracking if adopted later. |
| crawlee | pending-deferred-review | Apache-2.0 | Deferred; redundant with crawl4ai + firecrawl already selected. |
| woocommerce | pending-version-pin | GPL-3.0 | Merchant-operated WordPress plugin; adapter implements the existing CommerceProvider Protocol. Restricted license (same precedent as Postiz) — legal review required before commercial deployment. |
| mautic | pending-deferred-review | GPL-3.0-or-later | MarketingAutomationProvider adapter built and tested; copyleft license treated with the same legal-review precedent as GPL-3.0/AGPL-3.0 candidates. |
| activepieces | pending-deferred-review | MIT | CustomerAutomationProvider adapter built and tested; MIT, no legal-review gate needed. |
| openlineage | 1.28.0 | Apache-2.0 | Studied/emulated pattern in `backend.observability.lineage_facets`; no upstream source vendored; retain Apache-2.0 notice. |
| great-expectations | 1.3.0 | Apache-2.0 | Studied/emulated assertion DSL in `evaluation.quality`; no upstream source vendored; retain Apache-2.0 notice. |
| dagster | 1.9.10 | Apache-2.0 | Studied/emulated software-defined asset lineage metadata in `backend.observability.lineage_facets`; retain Apache-2.0 notice. |
| higgsfield-ai/skills | 0.12.0 | MIT | Studied creative workflow concepts in `docs.ai.skills`; retain upstream MIT notice. |
| higgsfield-ai/cli | v0.3.1 | MIT | Studied status/cost reporting lifecycle in `docs.ai.standards`; retain upstream MIT notice. |
| higgsfield-ai/higgsfield-client | 0.1.0 | Apache-2.0 | Studied polling/error schema contracts in `docs.ai.standards`; retain Apache-2.0 notice. |
| gstack | main-pinned | MIT | Benchmark and QA review methodology referenced in `docs.ai.standards`; retain MIT notice. |
| hermes-agent-spec | v1.2.0 | MIT | Contract-first specifications and ADR conventions referenced in `docs.ai.standards`; retain MIT notice. |
| duckdb | v1.1.3 | MIT | In-process analytical query pattern emulated in `backend.analytics.embedded_query_engine`; retain MIT notice. |
| polars | py-1.17.1 | MIT | Tabular query expression patterns referenced in `backend.analytics.dataframe_engine`; retain MIT notice. |
| scrapy | 2.12.0 | BSD-3-Clause | Staged item validation pipeline pattern emulated in `backend.scouting.item_pipeline`; retain BSD-3-Clause notice. |
| shopify/product-taxonomy | v2026-08 | MIT | Pinned, partial category-name data snapshot bundled in `data/shopify_product_taxonomy/`, consumed offline by `services.category_mapping`; retain upstream MIT notice. |

The generated release SBOM captures resolved Python packages actually present
in the build environment. Before enabling or updating any listed component,
review its exact release, transitive licenses, security posture, attribution,
and rollback plan according to `docs/oss/DEPENDENCY_POLICY.md`.

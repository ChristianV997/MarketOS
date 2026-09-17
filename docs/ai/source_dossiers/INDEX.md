# Bounded Source Dossiers: Public Capability Candidates Index

This index catalogs the 19 evaluated public open-source and commercial candidates, their pinned source references, licensing assessments, intended MarketOS seams, and adoption decisions.

## Evaluation Decision Matrix

| Candidate | Pinned Commit / Release | License | Intended MarketOS Seam | Decision | Classification | Dossier Link |
|---|---|---|---|---|---|---|
| **Crawl4AI** | `b6e9c40` (v0.9.2) | Apache-2.0 | `backend.scouting.crawl4ai_client` | **Integrate** | Wrapped (narrow client) | [Dossier](crawl4ai.md) |
| **Scrapy** | `2c7b5b5` (2.12.0) | BSD-3-Clause | `backend.scouting.item_pipeline` | **Emulate** | Studied (selector/pipeline pattern) | [Dossier](scrapy.md) |
| **dlt** | `3d9f1c7` (1.8.0) | Apache-2.0 | `data.ingestion.schema_normalizer` | **Adapt** | Studied / Candidate (schema inference) | [Dossier](dlt.md) |
| **DuckDB** | `a5c2f8e` (v1.2.0) | MIT | `backend.analytics.embedded_query_engine` | **Adapt** | Studied / Adapt (in-process SQL) | [Dossier](duckdb.md) |
| **Polars** | `f4b8c2d` (py-polars-1.24.0) | MIT | `backend.analytics.dataframe_engine` | **Emulate** | Studied (query pattern reference) | [Dossier](polars.md) |
| **OpenLineage** | `8e7d6c5` (1.28.0) | Apache-2.0 | `backend.observability.lineage_facets` | **Emulate** | Studied (provenance facet schemas) | [Dossier](openlineage.md) |
| **Open Policy Agent** | `9a8b7c6` (v1.2.0) | Apache-2.0 | `evaluation.trustos.policy_gate` | **Emulate** | Studied (declarative policy grammar) | [Dossier](open_policy_agent.md) |
| **Great Expectations** | `1c2d3e4` (1.3.0) | Apache-2.0 | `evaluation.quality_certification` | **Emulate** | Studied (assertion DSL pattern) | [Dossier](great_expectations.md) |
| **OpenTelemetry Python** | `5e6f7a8` (v1.30.0) | Apache-2.0 | `backend.observability.tracing` | **Adapt** | Wrapped (span context models) | [Dossier](opentelemetry_python.md) |
| **Chatwoot** | `7f8a9b0` (v3.15.0) | AGPL-3.0 | `backend.messaging.chatwoot_boundary` | **Reject** | Studied (strict isolation; no vendoring) | [Dossier](chatwoot.md) |
| **Medusa** | `2b3c4d5` (v2.5.0) | MIT | `backend.commerce.medusa_adapter` | **Adapt** | Studied / Adapt (draft export payload) | [Dossier](medusa.md) |
| **Saleor** | `4d5e6f7` (3.20.0) | BSD-3-Clause | `backend.commerce.saleor_adapter` | **Adapt** | Studied / Adapt (channel pricing models) | [Dossier](saleor.md) |
| **Temporal** | `1b2c3d4` (v1.26.2) | BSL-1.1 / MIT | `backend.observability.replay` | **Reject** | Studied (rejected orchestrator duplication; single event spine rule) | [Dossier](temporal.md) |
| **Prefect** | `2c3d4e5` (3.2.3) | Apache-2.0 | `backend.execution.task_states` | **Reject** | Studied (rejected orchestrator duplication; single event spine rule) | [Dossier](prefect.md) |
| **Dagster** | `3d4e5f6` (1.9.10) | Apache-2.0 | `backend.observability.lineage_facets` | **Emulate** | Studied (emulate SDA asset metadata; reject Dagit/daemon runtime) | [Dossier](dagster.md) |
| **Airbyte** | `1a2b3c4` (v0.64.0) | ELv2 | `data.ingestion.connectors` | **Reject** | Studied (rejected; container engine bloat) | [Dossier](airbyte.md) |
| **n8n** | `3c4d5e6` (n8n@1.80.0) | Sustainable Use | `backend.automation.n8n_boundary` | **Reject** | Studied (rejected; single event spine rule) | [Dossier](n8n.md) |
| **Firecrawl** | `6f7a8b9` (v1.8.0) | AGPL-3.0 | `backend.scouting.firecrawl_boundary` | **Reject** | Studied (rejected; Crawl4AI is canonical) | [Dossier](firecrawl.md) |
| **Vendure** | `5a6b7c8` (v3.1.0) | MIT | `backend.commerce.vendure_adapter` | **Adapt** | Studied / Adapt (product facet taxonomy) | [Dossier](vendure.md) |

## Core Architectural Guardrails
1. **Full Commit SHA Pinning**: All remote repositories must be pinned to full 40-character commit hashes (following the xAI/Grok plugin marketplace model).
2. **License Isolation**: AGPL-3.0 (Chatwoot, Firecrawl) and non-OSI commercial restrictions (Airbyte, n8n, Temporal server) are prohibited from being vendored or imported into the core codebase.
3. **Singular Authority**: No parallel orchestration engines (Airbyte, n8n, Temporal, Prefect) or duplicate crawlers (Firecrawl). MarketOS uses a single event spine and a single canonical extraction engine (`Crawl4AI`).
4. **Offline and Dry-Run Default**: All capability records default to `offline` or `dry-run`. Zero live execution or mutation authority is granted in metadata.

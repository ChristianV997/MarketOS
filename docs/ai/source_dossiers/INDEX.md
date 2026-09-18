# Bounded Source Dossiers: Public Capability Candidates Index

This index catalogs the 19 evaluated public open-source and commercial candidates, their pinned source references, licensing assessments, intended MarketOS seams, and adoption decisions.

## Evaluation Decision Matrix

| Candidate | Pinned Commit / Release | License | Intended MarketOS Seam | Decision | Classification | Dossier Link |
|---|---|---|---|---|---|---|
| **Crawl4AI** | `b04ed9f3a941a96509272f3bc14be85f5767736a` (v0.4.2) | Apache-2.0 | `backend.scouting.crawl4ai_client` | **Integrate** | Wrapped (narrow client) | [Dossier](crawl4ai.md) |
| **Scrapy** | `8c85937adef8279f12e35e0ee9a20c52ff6d1648` (2.12.0) | BSD-3-Clause | `backend.scouting.item_pipeline` | **Emulate** | Studied (selector/pipeline pattern) | [Dossier](scrapy.md) |
| **dlt** | `5a608086b7f7c6735968911138cb449472f7a259` (1.7.0) | Apache-2.0 | `data.ingestion.schema_normalizer` | **Adapt** | Studied / Candidate (schema inference) | [Dossier](dlt.md) |
| **DuckDB** | `19864453f7d0ed095256d848b46e7b8630989bac` (v1.1.3) | MIT | `backend.analytics.embedded_query_engine` | **Adapt** | Studied / Adapt (in-process SQL) | [Dossier](duckdb.md) |
| **Polars** | `87feed72585eff5acf3defb7f81029123d5cba68` (py-1.17.1) | MIT | `backend.analytics.dataframe_engine` | **Emulate** | Studied (query pattern reference) | [Dossier](polars.md) |
| **OpenLineage** | `e7a768ffef28b2dd011e2376d4c63267316b6584` (1.28.0) | Apache-2.0 | `backend.observability.lineage_facets` | **Emulate** | Studied (provenance facet schemas) | [Dossier](openlineage.md) |
| **Open Policy Agent** | `b2c26708e9d55645d7f837db495031f7e4152594` (v1.20.2) | Apache-2.0 | `evaluation.trustos.policy_gate` | **Emulate** | Studied (declarative policy grammar) | [Dossier](open_policy_agent.md) |
| **Great Expectations** | `883fd69e62d44fde0db8c61e300305a4f678b87f` (1.3.0) | Apache-2.0 | `evaluation.quality` | **Emulate** | Studied (assertion DSL pattern; consolidated into evaluation.quality) | [Dossier](great_expectations.md) |
| **OpenTelemetry Python** | `74509a111acd486d195ec5ea8478c8ccbf1f93c1` (v1.31.1) | Apache-2.0 | `backend.observability.tracing` | **Adapt** | Wrapped (span context models) | [Dossier](opentelemetry_python.md) |
| **Chatwoot** | `9f920b549c14491a4e587687a3eed5d21c6ccc7d` (v4.18.0) | AGPL-3.0 | `backend.messaging.chatwoot_boundary` | **Reject** | Studied (strict isolation; no vendoring) | [Dossier](chatwoot.md) |
| **Medusa** | `956a50e934fb0db6f55d5b9fa459a43abcee358b` (v2.4.0) | MIT | `backend.commerce.medusa_adapter` | **Adapt** | Studied / Adapt (draft export payload) | [Dossier](medusa.md) |
| **Saleor** | `a2a04538ed9e64bfee844179e672645d4fd3f6a5` (3.20.91) | BSD-3-Clause | `backend.commerce.saleor_adapter` | **Adapt** | Studied / Adapt (channel pricing models) | [Dossier](saleor.md) |
| **Temporal** | `b16215104069f798b79592679d8a16dd3d702883` (1.8.0) | BSL-1.1 / MIT | `backend.observability.replay` | **Reject** | Studied (rejected orchestrator duplication; single event spine rule) | [Dossier](temporal.md) |
| **Prefect** | `c8986edebb2dde3e2a931adbe24d2eaefcb799cb` (3.2.0) | Apache-2.0 | `backend.execution.task_states` | **Reject** | Studied (rejected orchestrator duplication; single event spine rule) | [Dossier](prefect.md) |
| **Dagster** | `21db4e55d3d1b723be3fdd90690fb9ca638744ac` (1.9.10) | Apache-2.0 | `backend.observability.lineage_facets` | **Emulate** | Studied (emulate SDA asset metadata; reject Dagit/daemon runtime) | [Dossier](dagster.md) |
| **Airbyte** | `2fa9e2ec2098ef2e400d7e39fd1db4200209c628` (v0.64.4) | ELv2 | `data.ingestion.connectors` | **Reject** | Studied (rejected; container engine bloat) | [Dossier](airbyte.md) |
| **n8n** | `0e26f58ae66c2aaad05af24fd56c28c960bcdd9b` (n8n@1.71.0) | Sustainable Use | `backend.automation.n8n_boundary` | **Reject** | Studied (rejected; single event spine rule) | [Dossier](n8n.md) |
| **Firecrawl** | `2a71f0190a02544f1ae06f0e1ce0c050cc4fe36a` (v2.11.359) | AGPL-3.0 | `backend.scouting.firecrawl_boundary` | **Reject** | Studied (rejected; Crawl4AI is canonical) | [Dossier](firecrawl.md) |
| **Vendure** | `b3d79ebfe5fa490b025e9004badad2fe0fe08df2` (v3.3.7) | MIT | `backend.commerce.vendure_adapter` | **Adapt** | Studied / Adapt (product facet taxonomy) | [Dossier](vendure.md) |


## Core Architectural Guardrails
1. **Full Commit SHA Pinning**: All remote repositories must be pinned to full 40-character commit hashes (following the xAI/Grok plugin marketplace model).
2. **License Isolation**: AGPL-3.0 (Chatwoot, Firecrawl) and non-OSI commercial restrictions (Airbyte, n8n, Temporal server) are prohibited from being vendored or imported into the core codebase.
3. **Singular Authority**: No parallel orchestration engines (Airbyte, n8n, Temporal, Prefect) or duplicate crawlers (Firecrawl). MarketOS uses a single event spine and a single canonical extraction engine (`Crawl4AI`).
4. **Offline and Dry-Run Default**: All capability records default to `offline` or `dry-run`. Zero live execution or mutation authority is granted in metadata.

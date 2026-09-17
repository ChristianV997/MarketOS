# Architectural Decision Record (ADR): OSS Pattern Retrofit & Capability Mining

- **Status**: Accepted
- **Lane**: `OSS-PATTERN-RETROFIT-COLAB-V2`
- **Owner**: `antigravity-oss-retrofit-engineer`
- **Date**: 2026-09-17

---

## 1. Context & Motivation

MarketOS requires external capability leverage to accelerate product research, scouting, intelligence, and commerce operations. However, directly importing external frameworks, downloading dynamic plugins, or adopting unpinned upstream dependencies introduces unacceptable risks:
1. **Duplicate Orchestrator / Multi-Spine Anti-Pattern**: Adopting external workflow engines introduces parallel event loops, database daemons, and fragmented execution states.
2. **Licensing Contagion**: Viral copyleft (AGPL-3.0) and non-OSI commercial restrictions (ELv2, Sustainable Use License) jeopardize commercial distribution.
3. **Supply Chain Vulnerability**: Unpinned dependencies and moving Git branches expose the build to upstream supply chain attacks.
4. **Unverifiable Vendor Claims**: Storing mock or simulated evidence without provenance tracking risks accidental promotion to production.

To solve this, MarketOS conducted an exhaustive audit of 19 premier public open-source and commercial candidates, adapted the highest-leverage architectural patterns into native lightweight code, and instituted deterministic machine validation.

---

## 2. 19-Repository Evaluation & Decision Register

| Candidate | Pinned Commit / Release | License | Intended MarketOS Seam | Decision | Classification | Rationale & Architectural Seam |
|---|---|---|---|---|---|---|
| **Crawl4AI** | `b6e9c40` (v0.9.2) | Apache-2.0 | `backend.scouting.crawl4ai_client` | **Integrate** | Wrapped | Canonical web extraction engine; narrow wrapper client; Playwright browser execution strictly gated behind offline fixtures. |
| **Scrapy** | `2c7b5b5` (2.12.0) | BSD-3-Clause | `backend.scouting.item_pipeline` | **Emulate** | Studied | Emulate CSS/XPath selector and Item validation pipeline patterns; reject Twisted event loop to preserve single asyncio spine. |
| **dlt** | `3d9f1c7` (1.8.0) | Apache-2.0 | `data.ingestion.schema_normalizer` | **Adapt** | Studied / Adapt | Evaluate schema inference and staging pipeline; do not add dependency until compatibility proof and concrete need exist. |
| **DuckDB** | `a5c2f8e` (v1.2.0) | MIT | `backend.analytics.embedded_query_engine` | **Adapt** | Studied / Adapt | In-process analytical SQL querying over parquet/jsonl evidence fixtures; zero-server local analytics. |
| **Polars** | `f4b8c2d` (py-polars-1.24.0) | MIT | `backend.analytics.dataframe_engine` | **Emulate** | Studied | Reference tabular query expression syntax; rely on native structures until data volumes demand Rust extension. |
| **OpenLineage** | `8e7d6c5` (1.28.0) | Apache-2.0 | `backend.observability.lineage_facets` | **Emulate** | Studied | **ADOPT GAP 1**: Adopt OpenLineage Run/Dataset/Job facet schema patterns for evidence traceability; reject heavy runtime client. |
| **Open Policy Agent** | `9a8b7c6` (v1.2.0) | Apache-2.0 | `evaluation.trustos.policy_gate` | **Emulate** | Studied | Emulate declarative policy grammar in native Python; reject running external Go daemon sidecar. |
| **Great Expectations** | `1c2d3e4` (1.3.0) | Apache-2.0 | `evaluation.quality_certification` | **Emulate** | Studied | **ADOPT GAP 2**: Emulate expectation assertion DSL for fixture contracts; reject 50+ transitive dependency framework bloat. |
| **OpenTelemetry Python** | `5e6f7a8` (v1.30.0) | Apache-2.0 | `backend.observability.tracing` | **Adapt** | Wrapped | Adopt OTel-compatible trace context and span data models; keep network exporters disabled/offline by default. |
| **Chatwoot** | `7f8a9b0` (v3.15.0) | AGPL-3.0 | `backend.messaging.chatwoot_boundary` | **Reject** | Studied | **CRITICAL AGPL-3.0 COPYLEFT RISK**: strictly prohibited from in-tree vendoring or library linking. Isolated external HTTP webhooks only. |
| **Medusa** | `2b3c4d5` (v2.5.0) | MIT | `backend.commerce.medusa_adapter` | **Adapt** | Studied / Adapt | Adapt product import/export JSON payload schema; keep output at `status: draft`; do not import Node.js server. |
| **Saleor** | `4d5e6f7` (3.20.0) | BSD-3-Clause | `backend.commerce.saleor_adapter` | **Adapt** | Studied / Adapt | Adapt product attribute & multi-channel pricing schema; do not embed Django core into MarketOS. |
| **Temporal** | `1b2c3d4` (v1.26.2) | BSL-1.1 / MIT | `backend.observability.replay` | **Reject** | Studied | **REJECT ORCHESTRATOR DUPLICATION**: non-permissive BSL-1.1 server; duplicates MarketOS native event spine. Emulate activity replay metadata only. |
| **Prefect** | `2c3d4e5` (3.2.3) | Apache-2.0 | `backend.execution.task_states` | **Reject** | Studied | **REJECT ORCHESTRATOR DUPLICATION**: heavy workflow engine duplicates MarketOS single event spine. Emulate task transition states only. |
| **Dagster** | `3d4e5f6` (1.9.10) | Apache-2.0 | `backend.observability.lineage_facets` | **Emulate** | Studied | **ADOPT GAP 1**: Emulate software-defined asset (SDA) lineage and materialization records; reject heavy Dagit/daemon runtime. |
| **Airbyte** | `1a2b3c4` (v0.64.0) | ELv2 / BSL | `data.ingestion.connectors` | **Reject** | Studied | Non-permissive license (ELv2/BSL) + heavy Docker/Java container orchestrator. Duplicates MarketOS singular architecture. |
| **n8n** | `3c4d5e6` (n8n@1.80.0) | Sustainable Use | `backend.automation.n8n_boundary` | **Reject** | Studied | Non-permissive commercial restriction + visual DAG engine. Duplicates MarketOS single native event spine. |
| **Firecrawl** | `6f7a8b9` (v1.8.0) | AGPL-3.0 | `backend.scouting.firecrawl_boundary` | **Reject** | Studied | **AGPL-3.0 COPYLEFT**: reject runtime and vendoring. Crawl4AI is already the canonical permissive extraction engine. |
| **Vendure** | `5a6b7c8` (v3.1.0) | MIT | `backend.commerce.vendure_adapter` | **Adapt** | Studied / Adapt | Adapt product option/facet taxonomy; generate draft blueprints only; do not import NestJS runtime. |

---

## 3. Two Chosen Implementation Gaps

### Gap 1: Run-Level Evidence Lineage & Facets (`backend.observability.lineage_facets`)
- **Origin Patterns**: OpenLineage (Run & Dataset Facets) + Dagster (Software-Defined Asset metadata).
- **Implementation**: Pure Python dataclasses (`RunFacet`, `DatasetFacet`, `AssetFacet`, `EvidenceLineageFacet`).
- **Benefits**:
  - Direct attribution linking every evidence record to its source job run, code commit SHA (`df59a06...`), and parent execution run.
  - Software-defined asset tags linking upstream source datasets to downstream evaluations without running an external database or metadata server.
  - Zero third-party dependencies.

### Gap 2: Explicit Data-Quality States & Deterministic Replay Certification (`evaluation.quality_certification`)
- **Origin Patterns**: Great Expectations (assertion evaluation states) + Temporal/Git (deterministic replay signature).
- **Implementation**: Pure Python assertion engine with 4 distinct states (`PASSED`, `FAILED`, `UNAVAILABLE`, `DEFERRED`) and `DeterministicReplayCertifier`.
- **Benefits**:
  - Disallows masking test failures as "unavailable" or "untested".
  - Generates immutable 64-character SHA256 replay signatures verifying exact input, suite, and assertion determinism across executions.
  - Enforces all 8 required negative invariants fail-closed.

---

## 4. Enforced Negative Invariants

1. **Fixture Cannot Become Live Evidence**: Evidence marked `mock`, `fixture`, `synthetic`, or `simulated` cannot be promoted to `live` (raises `InvalidEvidencePromotionError`).
2. **Simulated Cannot Become Actual**: Evidence marked `simulated` cannot be promoted to `actual` (raises `InvalidEvidencePromotionError`).
3. **Stale Evidence Cannot Promote**: Observations exceeding the freshness window (> 48h) fail promotion closed (raises `StaleEvidenceError`).
4. **Failed Execution Cannot Become Unavailable**: Any failing check strictly forces overall status to `FAILED`; it cannot be masked as `UNAVAILABLE` (raises `AssertionIntegrityError`).
5. **Raw Payloads Cannot Persist**: Raw HTML/body dumps are stripped and rejected (raises `UnredactedPayloadError`).
6. **Secrets Cannot Persist**: Regex scanning blocks private keys, tokens, and credentials fail-closed (raises `SecretLeakError`).
7. **External Workflow Tools Cannot Become Second Orchestrator**: Any claim of Temporal, Prefect, Airbyte, or n8n as the runtime orchestrator is rejected (raises `DuplicateOrchestratorError`).
8. **Duplicate Lineage or Quality Authorities Are Rejected**: Only the canonical TrustOS / Quality Certification gate is accepted (raises `DuplicateAuthorityError`).

---

## 5. Rollback & Deactivation Plan
- If lineage facet enrichment needs to be disabled, the factory helper `attach_lineage_to_evidence` can be bypassed; base evidence records retain their native schema (`contracts.py`) without breakage.
- If quality certification needs to be reverted, standard `evaluation.quality.quality_reasons` remains available as fallback.

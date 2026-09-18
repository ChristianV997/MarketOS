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
| **Crawl4AI** | `b04ed9f3a941a96509272f3bc14be85f5767736a` (v0.4.2) | Apache-2.0 | `backend.scouting.crawl4ai_client` | **Integrate** | Wrapped | Canonical web extraction engine; narrow wrapper client; Playwright browser execution strictly gated behind offline fixtures. |
| **Scrapy** | `8c85937adef8279f12e35e0ee9a20c52ff6d1648` (2.12.0) | BSD-3-Clause | `backend.scouting.item_pipeline` | **Emulate** | Studied | Emulate CSS/XPath selector and Item validation pipeline patterns; reject Twisted event loop to preserve single asyncio spine. |
| **dlt** | `5a608086b7f7c6735968911138cb449472f7a259` (1.7.0) | Apache-2.0 | `data.ingestion.schema_normalizer` | **Adapt** | Studied / Adapt | Evaluate schema inference and staging pipeline; do not add dependency until compatibility proof and concrete need exist. |
| **DuckDB** | `19864453f7d0ed095256d848b46e7b8630989bac` (v1.1.3) | MIT | `backend.analytics.embedded_query_engine` | **Adapt** | Studied / Adapt | In-process analytical SQL querying over parquet/jsonl evidence fixtures; zero-server local analytics. |
| **Polars** | `87feed72585eff5acf3defb7f81029123d5cba68` (py-1.17.1) | MIT | `backend.analytics.dataframe_engine` | **Emulate** | Studied | Reference tabular query expression syntax; rely on native structures until data volumes demand Rust extension. |
| **OpenLineage** | `e7a768ffef28b2dd011e2376d4c63267316b6584` (1.28.0) | Apache-2.0 | `backend.observability.lineage_facets` | **Emulate** | Studied | **ADOPT GAP 1**: Adopt OpenLineage Run/Dataset/Job facet schema patterns for evidence traceability; reject heavy runtime client. |
| **Open Policy Agent** | `b2c26708e9d55645d7f837db495031f7e4152594` (v1.20.2) | Apache-2.0 | `evaluation.trustos.policy_gate` | **Emulate** | Studied | Emulate declarative policy grammar in native Python; reject running external Go daemon sidecar. |
| **Great Expectations** | `883fd69e62d44fde0db8c61e300305a4f678b87f` (1.3.0) | Apache-2.0 | `evaluation.quality` | **Emulate** | Studied | **ADOPT GAP 2**: Emulate expectation assertion DSL for fixture contracts; consolidated into canonical `evaluation.quality` authority. |
| **OpenTelemetry Python** | `74509a111acd486d195ec5ea8478c8ccbf1f93c1` (v1.31.1) | Apache-2.0 | `backend.observability.tracing` | **Adapt** | Wrapped | Adopt OTel-compatible trace context and span data models; keep network exporters disabled/offline by default. |
| **Chatwoot** | `9f920b549c14491a4e587687a3eed5d21c6ccc7d` (v4.18.0) | AGPL-3.0 | `backend.messaging.chatwoot_boundary` | **Reject** | Studied | **CRITICAL AGPL-3.0 COPYLEFT RISK**: strictly prohibited from in-tree vendoring or library linking. Isolated external HTTP webhooks only. |
| **Medusa** | `956a50e934fb0db6f55d5b9fa459a43abcee358b` (v2.4.0) | MIT | `backend.commerce.medusa_adapter` | **Adapt** | Studied / Adapt | Adapt product import/export JSON payload schema; keep output at `status: draft`; do not import Node.js server. |
| **Saleor** | `a2a04538ed9e64bfee844179e672645d4fd3f6a5` (3.20.91) | BSD-3-Clause | `backend.commerce.saleor_adapter` | **Adapt** | Studied / Adapt | Adapt product attribute & multi-channel pricing schema; do not embed Django core into MarketOS. |
| **Temporal** | `b16215104069f798b79592679d8a16dd3d702883` (1.8.0) | BSL-1.1 / MIT | `backend.observability.replay` | **Reject** | Studied | **REJECT ORCHESTRATOR DUPLICATION**: non-permissive BSL-1.1 server; duplicates MarketOS native event spine. Emulate activity replay metadata only. |
| **Prefect** | `c8986edebb2dde3e2a931adbe24d2eaefcb799cb` (3.2.0) | Apache-2.0 | `backend.execution.task_states` | **Reject** | Studied | **REJECT ORCHESTRATOR DUPLICATION**: heavy workflow engine duplicates MarketOS single event spine. Emulate task transition states only. |
| **Dagster** | `21db4e55d3d1b723be3fdd90690fb9ca638744ac` (1.9.10) | Apache-2.0 | `backend.observability.lineage_facets` | **Emulate** | Studied | **ADOPT GAP 1**: Emulate software-defined asset (SDA) lineage and materialization records; reject heavy Dagit/daemon runtime. |
| **Airbyte** | `2fa9e2ec2098ef2e400d7e39fd1db4200209c628` (v0.64.4) | ELv2 / BSL | `data.ingestion.connectors` | **Reject** | Studied | Non-permissive license (ELv2/BSL) + heavy Docker/Java container orchestrator. Duplicates MarketOS singular architecture. |
| **n8n** | `0e26f58ae66c2aaad05af24fd56c28c960bcdd9b` (n8n@1.71.0) | Sustainable Use | `backend.automation.n8n_boundary` | **Reject** | Studied | Non-permissive commercial restriction + visual DAG engine. Duplicates MarketOS single native event spine. |
| **Firecrawl** | `2a71f0190a02544f1ae06f0e1ce0c050cc4fe36a` (v2.11.359) | AGPL-3.0 | `backend.scouting.firecrawl_boundary` | **Reject** | Studied | **AGPL-3.0 COPYLEFT**: reject runtime and vendoring. Crawl4AI is already the canonical permissive extraction engine. |
| **Vendure** | `b3d79ebfe5fa490b025e9004badad2fe0fe08df2` (v3.3.7) | MIT | `backend.commerce.vendure_adapter` | **Adapt** | Studied / Adapt | Adapt product option/facet taxonomy; generate draft blueprints only; do not import NestJS runtime. |

---

## 3. Two Chosen Implementation Gaps

### Gap 1: Run-Level Evidence Lineage & Facets (`backend.observability.lineage_facets`)
- **Origin Patterns**: OpenLineage (Run & Dataset Facets) + Dagster (Software-Defined Asset metadata).
- **Implementation**: Pure Python dataclasses (`RunFacet`, `DatasetFacet`, `AssetFacet`, `EvidenceLineageFacet`).
- **Benefits**:
  - Direct attribution linking every evidence record to its source job run, code commit SHA (`df59a06...`), and parent execution run.
  - Software-defined asset tags linking upstream source datasets to downstream evaluations without running an external database or metadata server.
  - Zero third-party dependencies.

### Gap 2: Explicit Data-Quality States & Deterministic Replay Certification (`evaluation.quality`)
- **Origin Patterns**: Great Expectations (assertion evaluation states) + Temporal/Git (deterministic replay signature).
- **Implementation**: Pure Python assertion engine consolidated directly into canonical `evaluation.quality` (`QualityAssertionState`, `ExpectationSuite`, `DeterministicReplayCertifier`), with `evaluation.quality_certification` retained as a thin backward-compatibility adapter.
- **Benefits**:
  - Eliminates secondary quality authority risk while providing full assertion rigor.
  - Disallows masking test failures as "unavailable" or "untested".
  - Generates immutable 64-character SHA256 replay signatures verifying exact input, suite, and assertion determinism across executions.
  - Enforces all 8 required negative invariants fail-closed.
  - Directly bridges `DataQuality` contracts to deterministic certification.

---

## 4. Enforced Negative Invariants

1. **Fixture Cannot Become Live Evidence**: Evidence marked `mock`, `fixture`, `synthetic`, or `simulated` cannot be promoted to `live` (raises `InvalidEvidencePromotionError`).
2. **Simulated Cannot Become Actual**: Evidence marked `simulated` cannot be promoted to `actual` (raises `InvalidEvidencePromotionError`).
3. **Stale Evidence Cannot Promote**: Observations exceeding the freshness window (> 48h) fail promotion closed (raises `StaleEvidenceError`).
4. **Failed Execution Cannot Become Unavailable**: Any failing check strictly forces overall status to `FAILED`; it cannot be masked as `UNAVAILABLE` (raises `AssertionIntegrityError`).
5. **Raw Payloads Cannot Persist**: Raw HTML/body dumps are stripped and rejected (raises `UnredactedPayloadError`).
6. **Secrets Cannot Persist**: Regex scanning blocks private keys, tokens, and credentials fail-closed (raises `SecretLeakError`).
7. **External Workflow Tools Cannot Become Second Orchestrator**: Any claim of Temporal, Prefect, Airbyte, or n8n as the runtime orchestrator is rejected (raises `DuplicateOrchestratorError`).
8. **Duplicate Lineage or Quality Authorities Are Rejected**: Only the canonical `evaluation.quality` authority is accepted (raises `DuplicateAuthorityError`).

---

## 5. Rollback & Deactivation Plan
- If lineage facet enrichment needs to be disabled, the factory helper `attach_lineage_to_evidence` can be bypassed; base evidence records retain their native schema (`contracts.py`) without breakage.
- If advanced expectation rules need to be bypassed, standard `evaluation.quality.quality_reasons` continues to operate identically as the baseline data-quality evaluator.

---

## 6. Source-Adaptation Governance Registry & Acceptance Pipeline
- **Lane**: `OSS-SOURCE-ADAPTATION-REGISTRY-AND-QUALITY-V2`
- **Canonical Schema**: `evaluation/source_governance/registry.py` (`SourceAdaptationRecord`, `SourceAdaptationRegistry`)
- **Fail-Closed Validator**: `evaluation/source_governance/validator.py` (`validate_registry`, `validate_source_record`)
- **Canonical Registry**: `data/source_adaptation_registry.json` (28 evaluated sources with 100% 40-character commit SHAs)
- **Governance CLI**: `python scripts/ai/validate_source_adaptation_registry.py --summary`
- **Deterministic Matrix Benchmark**: `python scripts/benchmarks/benchmark_source_adaptation_registry.py` (10/10 scenarios intercepted fail-closed, 100% bit-identical hash stability)
- **Benchmark Report**: `docs/ai/SOURCE_ADAPTATION_GOVERNANCE_REPORT.md`
- **Key Invariants**:
  - Pinned immutable 40-character commit SHAs mandatory for all Git repositories.
  - Incompatible/restrictive licenses (AGPL-3.0, ELv2, BSL-1.1, Sustainable Use) strictly prohibited from core integration.
  - Secret-shaped metadata intercepted with automated output redaction.
  - Desktop control / local IPC bridges (Higgsfield MCP bridge) rejected fail-closed.
  - GPU orchestration sources deferred until dedicated cluster infrastructure exists.
  - Protected MarketOS authorities (TrustOS, Governor, Approval Ledger, Quality, Event Spine) cannot be duplicated or replaced.

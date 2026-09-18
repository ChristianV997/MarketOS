# Source Adaptation Governance & Validation Matrix Benchmark Report

## Operational Context & Execution Classification
- **Lane**: `OSS-SOURCE-ADAPTATION-REGISTRY-AND-QUALITY-V2`
- **Benchmark Driver**: `scripts/benchmarks/benchmark_source_adaptation_registry.py`
- **Execution Mode**: `actual_executed` (Offline dev workstation; 0 live network calls, 0 credentials, 0 mutations).
- **Google Colab Environment**: `simulated_offline` (Headless Colab environment not attached; executed via offline deterministic runner).
- **Execution Timestamp**: `2026-09-18T04:41:24.469893+00:00`
- **Stable Catalog Hash**: `3571bc3f9ddcf73c99362b1a26c4eab99e43b92af540ef22860d16739bfb29b2`

---

## Throughput & Hash Determinism
- **Catalog Size**: 28 source candidates
- **Validation Latency**: 9.21 ms per full pass
- **Validation Throughput**: 3039.1 records/sec
- **Deterministic Hash Stability**: CONFIRMED (100% bit-identical)

---

## 10-Scenario Deterministic Matrix Results

| Case | Scenario Description | Expected | Result | Interception Status |
|---|---|---|---|---|
| Case 1 | Valid MIT source record | PASS | PASS | **PASSED** |
| Case 2 | Valid Apache-2.0 source record | PASS | PASS | **PASSED** |
| Case 3 | Missing license identifier | INTERCEPTED | INTERCEPTED | **PASSED** |
| Case 4 | Incompatible restrictive license (AGPL-3.0 in integrate mode) | INTERCEPTED | INTERCEPTED | **PASSED** |
| Case 5 | Missing immutable 40-character commit SHA | INTERCEPTED | INTERCEPTED | **PASSED** |
| Case 6 | Duplicate authority target (parallel event spine claim) | INTERCEPTED | INTERCEPTED | **PASSED** |
| Case 7 | Secret-shaped token in metadata (GitHub PAT pattern) | INTERCEPTED | INTERCEPTED | **PASSED** |
| Case 8 | Unbounded live network / mutation mode | INTERCEPTED | INTERCEPTED | **PASSED** |
| Case 9 | Rejected desktop-control bridge (local IPC / OS scripting) | INTERCEPTED | INTERCEPTED | **PASSED** |
| Case 10 | Unauthorized GPU orchestration in integrate mode | INTERCEPTED | INTERCEPTED | **PASSED** |

**Fault Interception Rate**: **10 / 10 (100.0%)** fail-closed.

---

## Architectural Invariants Enforced
1. **Zero Runtime Imports of External Orchestrators**: Temporal, Prefect, Airbyte, and n8n rejected fail-closed.
2. **Strict Licensing Isolation**: AGPL-3.0 (Chatwoot, Firecrawl), ELv2 (Airbyte), and Sustainable Use (n8n) prohibited from core.
3. **Zero Secret Persistence**: Credential patterns intercepted fail-closed with automated output redaction.
4. **Desktop Security Boundary**: Local IPC and desktop scripting bridges (Higgsfield MCP bridge) rejected fail-closed.
5. **Authority Protection**: Existing canonical authorities (TrustOS, Governor, Approval Ledger, Quality, Event Spine) cannot be duplicated.


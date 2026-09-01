# MarketOS Integration Acceptance Standard

This standard dictates how MarketOS adopts public repositories, APIs, CLIs, SaaS, platforms, and sidecars without duplicating capabilities or creating unsafe hidden mutation paths.

> **CRITICAL RULE:** Registry metadata, budgets, drafts, and scorecards do NOT grant execution authority. All integrations must strictly separate intent (offline metadata) from execution (live network mutation).

## External Capability Lifecycle
Every new external capability must define and document the following 20 lifecycle phases before merge:

1. **Capability gap and business outcome:** What exact capability is missing, and what business objective does it serve?
2. **Source/provenance and license:** Where does the dependency originate, who maintains it, and what is its license?
3. **Reuse disposition:** Can an existing integration (e.g., DataForSEO, unified model router) solve this without a new dependency?
4. **Adapter/sidecar/CLI/API/plugin boundary:** Is this an in-process SDK, an out-of-process CLI, a sidecar container, or a REST adapter?
5. **Credential reference boundary:** How are secrets resolved? (Must route through the singular credential registry).
6. **Dry-run and fixture behavior:** How does the integration behave entirely offline with mocked data? (Must be default).
7. **Availability states:** How does the system degrade when the capability is unreachable or rate-limited?
8. **Timeout/retry/output caps:** What are the strict numerical bounds for network wait times, retries, and output byte limits?
9. **Cost and approval policy:** What is the per-call or per-month cost, and what Approval Ledger policy governs it?
10. **TrustOS gates:** What security, privacy, and compliance checks must pass before the integration can execute?
11. **Approval Ledger requirements:** Does this integration require human operator sign-off per action, per session, or per budget?
12. **Resource Governor budgets and quotas:** What are the hard spending and usage caps enforced by the governor?
13. **Client Workspace isolation:** How does this integration guarantee cross-client data isolation (no leakage of payloads)?
14. **Evidence schema:** What normalized telemetry, audit logs, or output structures does this integration produce?
15. **Failure classification:** How are HTTP errors, network timeouts, and authentication failures mapped to standard error types?
16. **Rollback and disable behavior:** How is the integration instantly disabled via a feature flag or configuration toggle?
17. **Human handoff:** When does the integration intentionally halt and request operator intervention?
18. **Live activation checklist:** What specific operator steps are required to move from fixture-mode to live-network mode?
19. **Post-run learning capture:** How does the outcome feed back into the Learning Ledger for future agent context?
20. **Deprecation and replacement process:** How will this capability be gracefully retired if the vendor fails or a better alternative arises?

## Capability Acceptance Matrix

| Category | Default State | Required Evidence / Isolation | Mutation Authority |
|---|---|---|---|
| **Provider Adapters** (e.g. SerpApi, DataForSEO) | Offline / Fixtures | Proven no double-counting; strictly bound by central credential registry. | None (Read-only observation). |
| **Model Adapters** | Offline / Fixtures | Must route exclusively through the singular central inference router. | None. |
| **Browser/Automation Tools** | Disabled | Strict container isolation, output byte caps, no local file-system escapes. | None. |
| **Publishing Platforms** | Draft Only | Drafts generated offline. Publishing requires Approval Ledger operator sign-off. | Explicit Human Approval Only. |
| **Sales/Customer Messaging** | Offline / Blocked | Consent checks, DNC (Do-Not-Contact) verification, draft review. | Explicit Human Approval Only. |
| **Payments/Orders** | Sandboxed | Simulated test-mode gateways; strict Resource Governor cost bounds. | Operator Verification Required. |
| **Data Sources** | Fixtures | TrustOS privacy scanning, sanitized imports, rate-limit proofs. | None (Read-only ingestion). |
| **Observability Systems** | Offline | Normalized OTEL compliance; no raw PII or secret transmission. | Write telemetry only. |

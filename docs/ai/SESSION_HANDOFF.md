# Session Handoff

Updated: 2026-09-01

## High-Throughput Completion Contract
All agent workflows must execute the following strict sequence:
1. **inspect**
2. **implement**
3. **test**
4. **repair**
5. **diff review**
6. **commit**
7. **push**
8. **PR evidence**
## Release and Integration State
For explicit definitions of CI states (passed, failed, unavailable, timed_out, etc.) and the 16-point release criteria, refer to `docs/ai/INTEGRATION_RELEASE_CONTRACT.md`.

## Agentic Quality Gate
The Agentic Quality Gate **must not** self-report final CI readiness before sanitized `CIEvidence` is available and deterministically processed.

## Integration Rules
Preserve strict offline, dry-run, no-credentials, and no-mutation rules for all new capability adapters. All capability integrations must adhere to the `docs/ai/INTEGRATION_ACCEPTANCE_STANDARD.md` and use the `docs/ai/EXTERNAL_CAPABILITY_INTEGRATION_TEMPLATE.md`.
## Historical Directions
*(Note: Older Phase-1 supplier-validation states, CJ Dropshipping probes, and crawl4ai fallbacks detailed in previous handoffs are preserved in Git history as historical context, but do not dictate the current CI baseline or active merge train.)*

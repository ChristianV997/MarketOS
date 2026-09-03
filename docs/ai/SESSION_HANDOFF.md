# Session Handoff

Updated: 2026-09-02

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
For explicit definitions of CI states (passed, failed, unavailable, timed_out, etc.) and the strict release criteria, refer to docs/ai/INTEGRATION_RELEASE_CONTRACT.md. The release matrix now explicitly blocks duplicate/superseded PRs, enforces strict dependency ordering (e.g., #229 -> #230), prevents stale-agent loops, and traps is_stale_base states (#225 behind main) ensuring integration bounds.

## Agentic Quality Gate
The Agentic Quality Gate **must not** self-report final CI readiness before sanitized CIEvidence is available and deterministically processed.

## Integration Rules
Preserve strict offline, dry-run, no-credentials, and no-mutation rules for all new capability adapters (including security #231 and supplier surfaces #237). All capability integrations must adhere to the docs/ai/INTEGRATION_ACCEPTANCE_STANDARD.md and use the docs/ai/EXTERNAL_CAPABILITY_INTEGRATION_TEMPLATE.md.

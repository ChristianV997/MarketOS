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

## State Classifications
- **passed**: Deterministic success.
- **failed**: Executed failure (cannot be bypassed).
- **unavailable**: Resource not present.
- **timed_out**: Execution exceeded bounds.
- **not_run**: Skipped or omitted.
- **collection_failed**: Evidence gathering error.
- **blocked**: Upstream dependency unmet.
- **malformed**: Invalid syntax/structure.
- **ci_unavailable**: Zero-step runner outage (requires explicit manual override with local evidence to bypass).

## Agentic Quality Gate
The Agentic Quality Gate **must not** self-report final CI readiness before sanitized `CIEvidence` is available and deterministically processed.

## Integration Rules
Preserve strict offline, dry-run, no-credentials, and no-mutation rules for all new capability adapters.

## Historical Directions
*(Note: Older Phase-1 supplier-validation states, CJ Dropshipping probes, and crawl4ai fallbacks detailed in previous handoffs are preserved in Git history as historical context, but do not dictate the current CI baseline or active merge train.)*

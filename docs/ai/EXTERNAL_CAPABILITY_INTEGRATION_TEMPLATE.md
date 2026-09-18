# External Capability Integration Template

**Capability Name:** [Name of the API/Tool/Platform]
**Date:** [Date]
**Owner:** [Agent or Operator Name]

*All 20 lifecycle phases must be explicitly defined before submitting a PR to adopt a new external capability.*

### 1. Capability Gap and Business Outcome
[Describe the exact capability missing and the business objective it serves.]

### 2. Source/Provenance and License
[Where does the dependency originate, who maintains it, and what is its license?]

### 3. Reuse Disposition
[Explain why an existing integration cannot solve this without introducing a new dependency.]

### 4. Adapter/Sidecar/CLI/API/Plugin Boundary
[Define the architectural boundary: in-process SDK, CLI, sidecar container, or REST adapter.]

### 5. Credential Reference Boundary
[How are secrets resolved? Confirm routing through the singular credential registry.]

### 6. Dry-Run and Fixture Behavior
[Detail the offline, mocked-data behavior. Must be the default execution mode.]

### 7. Availability States
[How does the system gracefully degrade when unreachable or rate-limited?]

### 8. Timeout/Retry/Output Caps
[Specify strict numerical bounds for network timeouts, max retries, and output byte limits.]

### 9. Cost and Approval Policy
[State the per-call/per-month cost and the governing Approval Ledger policy.]

### 10. TrustOS Gates
[List the security, privacy, and compliance checks required before execution.]

### 11. Approval Ledger Requirements
[Does this require human operator sign-off per action, per session, or per budget?]

### 12. Resource Governor Budgets and Quotas
[List the hard spending and usage caps enforced by the Resource Governor.]

### 13. Client Workspace Isolation
[How does this guarantee cross-client data isolation and prevent payload leakage?]

### 14. Evidence Schema
[Provide the expected normalized telemetry, audit logs, or output structures.]

### 15. Failure Classification
[Map HTTP errors, timeouts, and auth failures to standard internal error types.]

### 16. Rollback and Disable Behavior
[How is the integration instantly disabled via a feature flag or configuration toggle?]

### 17. Human Handoff
[Define the conditions under which the integration halts and requests operator intervention.]

### 18. Live Activation Checklist
[Detail the specific operator steps required to move from fixture-mode to live-network mode.]

### 19. Post-Run Learning Capture
[How does the outcome feed back into the Learning Ledger for future agent context?]

### 20. Deprecation and Replacement Process
[How will this capability be gracefully retired if the vendor fails or a better alternative arises?]

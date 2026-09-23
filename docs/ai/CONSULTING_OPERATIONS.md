# Consulting Operations Readiness

This module (`services/consulting_operations`) evaluates whether a consulting package is operationally deliverable.

## Design Constraints
- **Not a CI Gate**: This is an operational readiness check for service delivery, distinct from code CI or deployment readiness.
- **No Live Mutation**: It evaluates state and planning estimates as assumptions. It does not create billing records, CRM updates, messages, or external actions.
- **Fail-Closed Design**: Incomplete scopes, missing data, and unapproved client exports explicitly block readiness.

## Readiness States
1. `incomplete`: Intake or scope is missing, or required client data is absent.
2. `blocked`: Human review rejected, milestone dependencies unmet, or client export unsafe.
3. `ready_for_review`: Intake complete, evidence provided, waiting on human review.
4. `ready_for_client_service`: Approved review, safe export, and handoff checklist complete.

## Verification
Tests are maintained in `tests/services/test_consulting_operations/` and enforce the exact state transitions and negative controls (unsafe client data rejection).

## Chain Verification
The `evaluate_consulting_chain` executes the full six-stage pipeline (offers -> engagement -> economics -> portfolio -> evidence register -> delivery), incorporating real constraints:
- Pricing uses ranges instead of scalar commitments.
- Missing, stale, or conflicting evidence is preserved safely.
- Workspace boundary and leakage are strictly tested.
- Output uses deterministic fingerprinting.

# Canonical Architecture

Updated: 2026-09-16
Scope: MarketOS agent-assisted development context.

Source of truth: executable code, tests, and current deployment configuration. This file is a compact index, not a second architecture document.

Inspect first: `orchestrator/`, `backend/`, `core/`, `signals/`, `evaluation/`, and `tests/`.

Current shape: signals and research feed normalized commerce/evaluation contracts; decision and validation logic applies economics and safety gates; commerce and launch adapters perform approved external actions; metrics and signal-cache telemetry feed feedback and learning.

Avoid duplicating orchestration, provider clients, risk gates, commerce contracts, or telemetry. Search callers before adding a subsystem.

Financial contract: new commercial calculations use `backend.economics.kernel`
for Decimal `Money`, `EvidenceRef`, `MarketLane`, unit economics, scenarios,
and service economics. Existing float-shaped evaluation and service reports
are compatibility adapters. FX conversion requires explicit rate provenance;
unknown evidence remains unknown. The CompanyOS service catalog remains the
single catalog authority and exposes typed price/economics adapters.

Export & isolation contract: `evaluation.trustos.client_workspace_isolation` is
the canonical export boundary for client-facing artifacts. Internal prompts,
scoring formulas, raw heuristics, source code, and cross-client data must never
cross into client workspace projections or exports.

Pre-integration & mutation gates: `evaluation.companyos.approval_ledger` governs
simulation and fail-closed approval policy for all external mutations. Real world
actions (publishing, live ads, customer outreach, payment execution) remain default-off
and require an explicit human-approved policy.

Readiness contract: readiness gates compose without competing authorities:
`evaluation/commerce/readiness.py` governs Phase 1 commercial viability;
`backend/deployment/readiness.py` governs infrastructure and environment deployment;
`evaluation/trustos/public_launch_readiness.py` governs pre-launch governance and compliance.

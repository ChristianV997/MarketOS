# Canonical Architecture

Updated: 2026-09-16
Scope: MarketOS agent-assisted development context.

Source of truth: executable code, tests, and current deployment configuration. This file is a compact index, not a second architecture document.

Inspect first: `orchestrator/`, `backend/`, `core/`, `signals/`, `evaluation/`, and `tests/`.

Current shape: signals and research feed normalized commerce/evaluation contracts; decision and validation logic applies economics and safety gates; commerce and launch adapters perform approved external actions; metrics and signal-cache telemetry feed feedback and learning.

Avoid duplicating orchestration, provider clients, risk gates, commerce contracts, or telemetry. Search callers before adding a subsystem.

Financial contract: `backend.economics.kernel` is the sole authority for
money arithmetic, Decimal `Money`, `EvidenceRef`, `MarketLane`, unit economics,
scenarios, and service economics. Re-implementing formulas or adding a second
calculator is strictly prohibited. Existing float-shaped evaluation and service
reports are compatibility adapters. FX conversion requires explicit rate
provenance; unknown/fixture evidence demotes to assumed and never upgrades to
live without verified proof.

Event spine & replay identity: `backend/contracts/events.py` defines the canonical
`Event` envelope with deterministic `replay_hash()`. Replay sequence validation,
hash verification, and live-authority exclusion are owned by
`backend/events/replay_certification.py`. Replay stores and journals are
temporary adapters pending `EventRepository`.

Export & isolation contract: `evaluation.trustos.client_workspace_isolation` is
the canonical export boundary for client-facing artifacts (`check_workspace_leakage`).
Internal prompts, scoring formulas, raw heuristics, source code, and cross-client data
must never cross into client workspace projections or exports (enforced fail-closed).

Resource execution governance: `evaluation.companyos.resource_execution_governor`
is the canonical offline authority for deterministic budget, quota, portfolio,
model spend, runaway guard, and cross-department decisions.

Pre-integration & mutation gates: `evaluation.companyos.approval_ledger` governs
simulation and fail-closed approval policy for all external mutations. Real world
actions (publishing, live ads, customer outreach, payment execution) in
`LIVE_ACTION_TYPES` remain default-off and require explicit human-approved
metadata (`approval_id`, `approved_by`, `policy_id`).

Research-to-decision & service projections:
`evaluation.commerce.opportunity_synthesis` is the canonical three-pillar fusion
layer. Service projections in `evaluation.companyos.service_engagement` and
`evaluation.companyos.service_delivery_artifact` are pure read-only projections.
Duplicate projection packets for an existing domain are strictly rejected.

Frontend boundary: `frontend/src/lib/apiBase.ts` (`resolveApiBaseUrl`) is the
sole API base resolution authority. Frontend code must never compute backend
economics or margin formulas (`price - cost`, `break_even_roas`, `break_even_cac`,
`contribution_before_cac`, `contribution_after_cac`, `refund_lag_exposure`).

Benchmark isolation: benchmarks (`scripts.*`, `evaluation.perf.*`) must never
be imported by `PRODUCTION_ROOTS` or create alternative production execution paths.

Readiness contract: readiness gates compose without competing authorities:
`evaluation/commerce/readiness.py` governs Phase 1 commercial viability;
`backend/deployment/readiness.py` governs infrastructure and environment deployment;
`evaluation/trustos/public_launch_readiness.py` governs pre-launch governance and compliance.

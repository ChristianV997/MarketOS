# MarketOS Architecture Contract

Status: enforceable direction of travel. This contract does not migrate legacy systems or enable live behavior.

## Canonical owners

| Concern | Canonical owner | Current transitional paths |
| --- | --- | --- |
| Runtime scheduling and lifecycle | `orchestrator/` | `backend/workflows/orchestrator.py` remains a workflow-stage coordinator, not a second runtime. |
| Business decision-cycle semantics | `backend/execution/` | `backend/decision/`, `core/execution/`, and simulation paths remain existing collaborators. |
| Financial calculations and money | `backend/economics/kernel.py` | Sole calculator authority; legacy float-shaped evaluation/service reports are compatibility adapters delegating to kernel. Introducing a second calculator is prohibited. |
| Event envelope schemas and identity | `backend/contracts/events.py` (`Event`) | Canonical envelope with deterministic `replay_hash()`. Existing pub/sub envelopes are compatibility adapters. |
| Replay certification and identity authority | `backend/events/replay_certification.py` | Read-only sequence validator, hash verification, and live-authority exclusion. |
| Client export boundary and isolation | `evaluation/trustos/client_workspace_isolation.py` | `check_workspace_leakage` enforces fail-closed isolation; internal prompts, formulas, heuristics, and secrets are hard-blocked. |
| Resource execution governance | `evaluation/companyos/resource_execution_governor.py` | Deterministic offline budget, quota, portfolio, model spend, runaway guard, and cross-department governance. |
| Pre-integration policy gate | `evaluation/companyos/approval_ledger.py` | Fail-closed simulation and offline approval ledger; external mutation requires explicit human approval metadata (`approval_id`, `approved_by`, `policy_id`). |
| Research-to-decision authority | `evaluation/commerce/opportunity_synthesis.py` | Canonical three-pillar fusion; read-only evidence synthesis without live mutation authority. |
| Service projection contract | `evaluation/companyos/service_engagement.py`, `evaluation/companyos/service_delivery_artifact.py` | Pure deterministic projection layers; no duplicate service packets or independent financial engines. |
| Frontend API client & base URL | `frontend/src/lib/apiBase.ts` | Single `resolveApiBaseUrl` authority; frontend must not compute financial formulas or bypass API base resolution. |
| Readiness projections | Distinct non-competing gates | `evaluation/commerce/readiness.py` (Phase 1), `backend/deployment/readiness.py` (deployment), `evaluation/trustos/public_launch_readiness.py` (TrustOS launch governance). |
| Event append abstraction | `backend/events/` | `backend/events/log.py` and `backend/orchestration/event_store.py` are current legacy paths pending `EventRepository`. |
| Durable operational store | Future `EventRepository` on Postgres | JSONL, DuckDB, and replay-store paths remain temporary adapters. |
| Application/use-case services | `services/` | Services must use backend abstractions rather than construct persistence or provider clients. |
| Real external mutation | `backend/integrations/` | Callers may use integration abstractions; they must not directly mutate providers. |
| Public interfaces | `api/`, `backend/api.py`, `marketos/cli.py` | Interfaces remain thin adapters and do not own domain decisions. |
| Advisory intelligence | `backend/commercial_intelligence/`, `backend/creative_intelligence/`, `backend/intelligence/` | Reports may feed planning and workflow context only. |
| Speculative architecture | `docs/rfcs/` | `backend/dao_future/` is production-excluded placeholder vocabulary. |

## Dependency direction

Allowed direction is interface -> application/use case -> domain/decision -> ports/contracts -> adapters/integrations. `orchestrator/` schedules and observes lifecycle; it does not duplicate the decision cycle in `backend/execution/`. `services/` coordinates use cases but does not own infrastructure. Integrations implement provider boundaries and never choose budgets, capital allocations, or promotion policy.

Forbidden directions include core/domain importing `api` or `backend.api`; backend execution importing API or frontend code; services importing frontend or low-level persistence implementations directly; backend runtime importing frontend; and production modules importing `backend.dao_future`.

## Event-spine migration target

The canonical event schema is now `backend/contracts/events.py`; the append/persistence foundation is `backend/events/repository.py`. See [`docs/EVENT_REPOSITORY.md`](docs/EVENT_REPOSITORY.md) for adapter and migration semantics. This PR explicitly retains `backend/events/log.py` (replay-store facade) and `backend/orchestration/event_store.py` (workflow JSONL journal) as legacy paths. `backend/events/adapters/legacy.py` is the sole new, read-only compatibility importer. No new event-store module may be introduced outside approved event locations. Existing importers are a temporary, documented file-level allowlist enforced by `tests/contracts/test_architecture_boundaries.py` until adapters replace them; directory-wide exceptions are intentionally forbidden.

## Boundary rules

- **Single Financial Authority**: `backend.economics.kernel` is the sole authority for financial arithmetic, unit economics, service economics, and `Money`. Introducing a second economics calculator or alternative money implementation is rejected.
- **Unique Projection Packets**: Every projection packet domain must map 1:1 to a canonical authority in `CANONICAL_PROJECTIONS`. Introducing a duplicate packet or alternative projection for an existing domain fails closed.
- **Frontend Financial Prohibition & Single API Client**: Frontend code must not calculate backend economics or margin formulas (`price - cost`, `break_even_roas`, `break_even_cac`, `contribution_before_cac`, `contribution_after_cac`, `refund_lag_exposure`). All frontend API calls must resolve via `frontend/src/lib/apiBase.ts` (`resolveApiBaseUrl`).
- **Fixture Demotion**: Fixture, simulated, or assumed evidence can never be promoted to `verified` or `live_readonly` without live validated proof. Composite evidence state demotes to `assumed`, and opportunity synthesis confidence grading restricts fixture candidates to grade `C` or `D`, never `A_live_validated`.
- **TrustOS Export Isolation**: Client deliverables and export endpoints must enforce `check_workspace_leakage`. Internal prompts, scoring formulas, heuristics, source code, cross-client data, and credentials trigger `hard_block`.
- **Benchmark Production Isolation**: Benchmarks (`scripts.*`, `evaluation.perf.*`) must never be imported by `PRODUCTION_ROOTS` (`api`, `backend`, `core`, `marketos`, `orchestrator`, `services`) or act as alternative production paths.
- **Pre-Integration Mutation Approval**: All live mutation actions in `LIVE_ACTION_TYPES` (`site_publish`, `ad_launch`, `payment_creation`, `supplier_order`, `crm_mutation`, etc.) require explicit human approval metadata (`approval_id`, `approved_by`, `policy_id`) and fail closed by default.
- Services call backend abstractions, not replay stores, JSONL journals, concrete repositories, or provider clients directly.
- Only `backend/integrations/` may contain real external mutation implementations. Every real mutation remains human-approved, capped, audit-trailed, and dry-run by default.
- Commercial, Creative, and Executive Intelligence are advisory. They emit evidence-constrained artifacts and recommendations; they cannot override opportunity gates or authorize publishing, launch, spend, fulfillment, payment, orders, or capital allocation.
- API and CLI layers validate/dispatch/serialize only. Move business rules to backend domain or application owners.
- Placeholder or future packages must be production-excluded. Put new speculative proposals in `docs/rfcs/`, not importable runtime packages.

## Current exceptions

`backend.api` currently mounts route modules, and `orchestrator/main.py` currently coordinates API state. These are legacy interface/runtime couplings and not a precedent for new dependencies. The two current event stores remain in place because a safe migration requires a canonical envelope and adapters first.

## Open-source reuse policy

Prefer standard-library AST and `pathlib` checks for this repository's static boundaries. Evaluate external tools such as import-linter only when they materially reduce maintenance; identify source and license before adoption, avoid GPL/AGPL/copyleft impact unless explicitly accepted, and attribute any adapted code. Do not vendor code or add dependencies for simple import checks.

## Runtime and toolchain policy

Production, CI, and local development must converge on the supported Python version. Today `.python-version`, Docker, and CI use 3.12, while Ruff targets Python 3.11; normalize that mismatch in a dedicated toolchain PR. Ruff remains advisory until its baseline is deliberately ratcheted to zero.

## Definition of done for future feature PRs

1. Reuse a canonical owner or document an approved exception.
2. Keep dry-run, claim-safety, live-mode, and human-approval boundaries intact.
3. Add or update a focused architecture/safety test when a new dependency or mutation path is introduced.
4. Document any external dependency's source, license, and reason for use.
5. Run focused tests, the repository policy checks available locally, and `git diff --check`.

# MarketOS Architecture Contract

Status: enforceable direction of travel. This contract does not migrate legacy systems or enable live behavior.

## Canonical owners

| Concern | Canonical owner | Current transitional paths |
| --- | --- | --- |
| Runtime scheduling and lifecycle | `orchestrator/` | `backend/workflows/orchestrator.py` remains a workflow-stage coordinator, not a second runtime. |
| Business decision-cycle semantics | `backend/execution/` | `backend/decision/`, `core/execution/`, and simulation paths remain existing collaborators. |
| Financial calculations and money | `backend/economics/kernel.py` | Legacy float-shaped evaluation/service reports are compatibility adapters delegating to kernel. |
| Client export boundary and isolation | `evaluation/trustos/client_workspace_isolation.py` | Workspace leakage detection and curated evidence export; internal IP remains unexported. |
| Pre-integration policy gate | `evaluation/companyos/approval_ledger.py` | Fail-closed simulation and offline approval ledger; external mutation requires explicit human approval. |
| Readiness projections | Distinct non-competing gates | `evaluation/commerce/readiness.py` (Phase 1), `backend/deployment/readiness.py` (deployment), `evaluation/trustos/public_launch_readiness.py` (TrustOS launch governance). |
| Event envelope schemas | `backend/contracts/events.py` | Existing pub/sub envelopes and workflow records are not migrated by this change. |
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

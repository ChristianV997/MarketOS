# Architecture consolidation audit

Date: 2026-08-09. Scope: local repository inspection after the unstaged Creative Intelligence v1 contribution. No external source or package search was available or used.

## Audit table

| Area | Canonical owner | Current implementation paths | Duplication / sprawl risk | Safety risk | Recommended action | This PR |
| --- | --- | --- | --- | --- | --- | --- |
| Runtime lifecycle | `orchestrator/` | `orchestrator/main.py`, `backend/workflows/orchestrator.py` | Two orchestration-shaped modules | Competing lifecycle ownership | Preserve workflow coordinator; prohibit new runtimes | document/test |
| Decision cycle | `backend/execution/` | `backend/execution/loop.py`, `backend/decision/`, `core/execution/` | Semantic overlap with simulation/core paths | Budget behavior can drift | Treat execution as canonical; defer consolidation | document/test |
| Events | `backend/contracts/events.py`, then `backend/events/` | `backend/events/log.py`, `backend/orchestration/event_store.py`, replay store, JSONL, DuckDB | Multiple envelopes and append surfaces | Audit/replay inconsistency | Introduce contract and EventRepository in a later PR | document/test/defer |
| Services | `services/` application layer | service packages and reporting helpers | Service modules can acquire infrastructure | Bypassing approval/audit paths | Block direct persistence/client imports | test |
| Integrations | `backend/integrations/` | Shopify, ads, payments, Postiz, Medusa, etc. | Provider responsibilities can leak upward | Real mutation | Keep provider mutation isolated | test |
| Interfaces | `api/`, `backend/api.py`, `marketos/cli.py` | FastAPI routes, API monolith, CLI | `backend.api`/runtime coupling | Domain rules in interfaces | Freeze new coupling; defer legacy split | document/test |
| Creative Intelligence | `backend/creative_intelligence/` | route, registry, workflow stage, deliverables, graph, priorities, optimization, Obsidian | Integration fan-out | Unsupported claims or implicit launch | Keep reports advisory; block direct mutation imports | document/test |
| Commercial / Executive intelligence | advisory intelligence owners | commercial package; `backend/intelligence/` executive runner | Similar report/registry/workflow patterns | Gate bypass through recommendations | Keep artifacts non-authoritative | document/test |
| Frontend | `frontend/` | Vite application and Python API mounting | Legacy/unmounted UI uncertainty | Backend import leakage | Do not add dashboard or mount points | test/defer |
| Future DAO | `docs/rfcs/` | `backend/dao_future/` schemas; DAO architecture doc | Importable placeholder package | Speculative capital/governance semantics | Keep excluded; future proposals belong in RFCs | document/test |

## Modules inspected

Top-level layout; `backend/creative_intelligence/`; `api/routes/creative_intelligence.py`; commercial and executive intelligence paths; workflow runbook/stage executor; both event stores; `backend/execution/`; `services/`; `backend/integrations/`; API/CLI; frontend; `backend/dao_future/`; existing dependency and claim-safety tests; Python/dependency manifests; Dockerfile; CI; AGENTS/Claude instructions; and AI session scripts.

## Consolidation findings

**Keep:** deterministic Creative Intelligence claim safety, local registries, workflow stages, dry-run defaults, human gates, the current orchestrator, and existing OSS/safety CI checks.

**Merge later:** event schema and append ownership; legacy workflow JSONL, replay-store facade, DuckDB, and replay persistence behind `EventRepository`.

**Migrate later:** event writers through canonical envelopes/adapters; API-state coordination out of runtime; service direct-infrastructure edge cases through backend ports.

**Delete/archive candidates:** no significant code is deleted in this PR. `backend/dao_future/` is a production-excluded placeholder and its design discussion should ultimately be an RFC-only concern. Frontend mounting/unmounted legacy status requires a separate runtime inspection before deletion.

**Make canonical:** `orchestrator/` for lifecycle; `backend/execution/` for decision-cycle semantics; `backend/contracts/events.py` then `backend/events/` for events; `backend/integrations/` for provider mutation; advisory intelligence packages for recommendations only.

**Make blocking test:** prohibited layer imports, placeholder imports, advisory-to-live mutation imports, event-store locations and approved transitional importers, and the architecture/creative authorization statements. The legacy event exception is file-level, not a directory-wide carve-out.

## Creative Intelligence integration review

Creative Intelligence is integrated into Product Validation Sprint deliverables, knowledge graph snapshots, strategic priorities, optimization actions, Obsidian notes, and the `creative_intelligence` workflow stage. Its own documentation and inspected integration call sites label outputs as hypothesis/draft/advisory and route follow-up to local/manual evidence collection or dry-run validation. No direct imports of launch, Shopify mutation, payment, order, or advertising provider mutation modules were found in `backend/creative_intelligence/`.

Commercial, Creative, and Executive Intelligence all produce persisted reports that inform later planning. Their overlap is at the artifact/recommendation level: Commercial assesses evidence and viability; Creative drafts evidence-constrained messaging; Executive composes cross-system priorities. None should become a promotion or allocation authority.

## Event recommendation

Do not migrate now. First define canonical envelopes in `backend/contracts/events.py`, then introduce `backend/events/EventRepository`, then add adapters for workflow JSONL, replay store, and DuckDB/replay paths under replay fixtures. Preserve read compatibility and audit trails during that work.

## Runtime / quality notes

`.python-version`, Dockerfile, and CI use Python 3.12. `pyproject.toml` declares Ruff target Python 3.11, a drift that should be normalized separately. CI treats Ruff as advisory and documents a baseline; this PR does not make it blocking. The repository's configured CI already runs `pytest tests/`, so no CI workflow change is needed for the new contract test.

## Recommended next PR sequence

1. Canonical event contract and `EventRepository`.
2. Event adapters for JSONL/DuckDB/replay-store.
3. Shadow feature evaluation harness.
4. Golden replay scenarios.
5. Ruff-zero/blocking quality ratchet.
6. Runtime/toolchain normalization.
7. Duplicate FastAPI operation-ID cleanup.

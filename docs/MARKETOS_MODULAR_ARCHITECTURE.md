# MarketOS modular architecture

How the pieces built across this modularization effort fit together, and
how they relate to MarketOS's pre-existing core engine.

## Layers

```
┌─────────────────────────────────────────────────────────────────────┐
│  Core engine (pre-existing, unchanged)                              │
│  backend/discovery, backend/validation, backend/decision,           │
│  backend/risk, backend/metrics, backend/economics, backend/regime,   │
│  backend/learning, core/creative, core/content, core/ugc,           │
│  backend/commerce, backend/integrations, orchestrator/main.py       │
│  — the real, tested, dry-run-gated quant/execution machinery.       │
└───────────────────────────┬───────────────────────────────────────┘
                             │ wrapped by, never duplicated
┌───────────────────────────▼───────────────────────────────────────┐
│  Service modules (services/*)                                      │
│  product_research · unit_economics · ecommerce_operator ·           │
│  creative_growth · customer_intelligence · digital_products ·       │
│  sales_automation · reporting                                       │
│  — each is a thin, sellable-shaped orchestration layer over the     │
│  core engine above. See docs/SERVICE_MODULES.md for the full        │
│  per-module reference (inputs/outputs/CLI/API/pricing/status).      │
└───────────────────────────┬───────────────────────────────────────┘
                             │ every module call produces
┌───────────────────────────▼───────────────────────────────────────┐
│  Foundations (backend/workspaces, backend/experiments)               │
│  ClientWorkspace · CredentialScope · LiveModeChecklist ·             │
│  ArtifactStore · CommercialRunEnvelope · ExperimentRegistry          │
│  — multi-tenant isolation, the durable audit trail, and the safety   │
│  gate every module runs through. See docs/COMMERCIAL_RUN_ENVELOPE.md │
│  and docs/LIVE_MODE_SAFETY.md.                                       │
└───────────────────────────┬───────────────────────────────────────┘
                             │ reports/evidence persisted under
┌───────────────────────────▼───────────────────────────────────────┐
│  Client workspaces & artifact storage                                │
│  state/workspaces/{workspace_id}/experiments/{experiment_id}/       │
│    result.json, report.md                                           │
│  — the durable, per-tenant record of every run.                     │
└───────────────────────────┬───────────────────────────────────────┘
                             │ optionally executed against
┌───────────────────────────▼───────────────────────────────────────┐
│  Live integration adapters (pre-existing, unchanged)                 │
│  backend/integrations/{tiktok_ads,meta_ads_client}.py,               │
│  backend/creation/store_builder.py, backend/commerce/checkout.py     │
│  — dry-run by default; only actually spend/mutate when explicit      │
│  flags + real credentials + backend.risk.gate all agree.             │
└─────────────────────────────────────────────────────────────────────┘
```

Two things sit alongside every layer above, not inside one of them:

- **Dry-run simulation** is the default state of the entire stack —
  `ClientWorkspace.dry_run_default=True` by default, every service module's
  `status`/`dry_run` fields reflect it, and nothing above the "Live
  integration adapters" layer can spend real money or send a real message.
- **Governance/safety gates**: `backend.risk.gate` (real spend gate),
  `backend.workspaces.live_mode_checklist` (credentials + budget + live-mode
  checks), and each service module's own guardrails (e.g.
  `services.ecommerce_operator.launch_guard`, `services.sales_automation`'s
  hand-off-to-human rules) all compose rather than duplicate each other.
- **Future DAO/business-automation layer** (`backend/dao_future/`,
  `docs/DAO_FUTURE_ARCHITECTURE.md`) sits conceptually above the whole
  stack — documentation and placeholder schemas only, no behavior.

## Directory map

| Path | What it is |
|---|---|
| `services/` | Sellable service modules (Phase 2/3/5/6 of this effort) |
| `backend/workspaces/` | ClientWorkspace, CredentialScope, LiveModeChecklist, ArtifactStore (Phase 1) |
| `backend/experiments/` | CommercialRunEnvelope, ExperimentRegistry, audit_log (Phase 1) |
| `backend/ledger/` | Event-sourced commerce ledger (OrderCreated/PaymentCaptured/.../AdSpendObserved) + derived CAC/contribution-profit/cash-conversion-cycle projections — see `docs/COMMERCE_LEDGER.md` |
| `backend/dao_future/` | Placeholder-only future governance schemas (Phase 8) |
| `marketos/cli.py` | Terminal entrypoint for the service modules |
| `api/routes/services.py` | REST wrappers for all 8 service modules (`/api/services/*`) |
| `frontend/src/pages/Services.tsx` | Dashboard UI — a form + live result panel per module, hitting the same `/api/services/*` routes as the CLI |
| `docs/` | This doc + `SERVICE_MODULES.md`, `COMMERCIAL_RUN_ENVELOPE.md`, `LIVE_MODE_SAFETY.md`, `OWN_ECOMMERCE_VALIDATION_WORKFLOW.md`, `DIGITAL_PRODUCT_WORKFLOW.md`, `SALES_AUTOMATION_MODULE.md`, `DAO_FUTURE_ARCHITECTURE.md`, `COMMERCE_LEDGER.md` |
| everything else (`backend/discovery`, `backend/decision`, `core/*`, `orchestrator/`, ...) | Pre-existing core engine — reused, never duplicated |

## Operating modes

`ClientWorkspace.mode` (from `backend/workspaces/client_workspace.py`)
supports the full ladder this effort was scoped to serve, in order of
increasing commercial maturity:

```
internal_own_store → client_service → saas_lite → full_saas → dao_future
```

Nothing in the codebase currently branches behavior on this field beyond
recording it — it's a label for where a given workspace sits on the
roadmap, not yet a gate. See `docs/SERVICE_MODULES.md`'s "SaaS-lite
readiness" section for exactly what's built vs. deferred at each rung.

## Design principle carried through every phase

Every module in this effort was built by locating the real, already-tested
MarketOS function that does the actual work, and wrapping it — never by
re-implementing logic that already exists. Where genuinely new logic was
needed (e.g. `services.unit_economics.break_even_cac`,
`services.digital_products.validation`), it was derived from or built
directly on top of an existing verified function, and the derivation is
documented in that module's own docstring. This is the same discipline
`docs/ARCHITECTURE_PRINCIPLES.md`'s "One Orchestration Layer" and
"Deterministic First" principles already establish for the core engine —
extended to the service layer rather than invented fresh for it.

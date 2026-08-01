# MarketOS

### Autonomous commerce decision engine for dropshipping, packaged as a modular revenue operating system — discover, validate, launch, and optimize products with risk-aware capital allocation, and sell any piece of that pipeline as a standalone service.

MarketOS runs a continuous **Discover → Validate → Create → Launch → Optimize** loop over real ad platforms (TikTok, Meta) and a Shopify storefront, driven by a quantitative decision core: convex-optimization budget allocation, contextual bandits, statistically calibrated ROAS prediction, regime/changepoint detection, and adaptive risk limits. Every risky change ships behind a **shadow-mode flag** — the new logic runs and journals its decisions alongside the old one, and only takes over real budget after validation.

On top of that quant core sits a **modular commercial layer**: 9 independently sellable `services/*` modules (product research, unit economics, e-commerce operations, creative growth, customer intelligence, sales automation, digital products, profit stack advisor, reporting), each reachable via a CLI, a REST API, and a real dashboard UI, backed by a multi-tenant workspace model, an event-sourced commerce ledger, and a cost-aware commerce/payment/automation Provider Registry + Stack Planner. See [Modular commercial layer](#modular-commercial-layer) below for the full picture — this is what turns the quant core from "one internal pipeline" into "a set of things you can run for your own store, sell as a done-for-you service, or eventually offer as self-serve SaaS."

---

## What it actually does

**The dropshipping pipeline** (`backend/dropship/run_dropship_cycle`):

1. **Discover** — trend signals from Reddit (live, no auth needed), Google Trends/pytrends, TikTok Creative Center, Amazon Bestsellers; Meta Ad Library saturation scoring. Opportunity = signal score × (1 − 0.5 × market saturation). File-cached with stale-fallback.
2. **Validate** — supplier quotes fetched in parallel from CJ Dropshipping, Zendrop, Spocket, and Printful; full unit-economics margin model (payment fees, platform fees, returns, CAC); confidence score = 0.40·margin + 0.35·(1−saturation) + 0.25·supplier reliability; green/yellow/red verdict with risk flags. Auto-prices for a 20% net margin when no retail price is given.
3. **Create** — LLM-generated product listings and ad copy (deterministic template fallback), Shopify product-page creation.
4. **Launch** — TikTok (0.55) / Meta (0.45) budget split with per-platform failure isolation; optional transactional launch (`LaunchTransaction`) with circuit-breaker health gating, budget reallocation away from unhealthy platforms, and compensation (pause siblings) on partial failure.
5. **Optimize** — orchestrator workers ingest real ROAS per campaign, close the prediction→outcome calibration loop, kill losers (spend > 1.2× budget & ROAS < 0.8), and scale winners (×1.5 after 3 wins ≥ 1.5).

**The decision core** (`backend/execution/loop.py::run_cycle`, driven by the orchestrator and API):

Each cycle: a LinUCB contextual bandit picks a macro action (scale/hold/pause/launch_new/kill) → `decide()` scores 5 variants (calibrated world-model ROAS prediction + causal score + velocity + bandit weight + regime bonus − competition penalty, scaled by a three-factor confidence) → budget allocated across variants by convex optimization → outcomes update calibration, the causal graph, bandit rewards, regime detection, delayed rewards, and the replay buffer.

> **Honest caveat:** the decision loop's economics are a *stochastic market simulation* out of the box. Real Shopify/Meta/TikTok data calibrates the simulator (via the reality-gap engine and metrics-ingestion workers) and takes over per-integration when credentials are configured — every external integration ships **dry-run by default** and never spends real money until explicitly enabled.

---

## The ROI overhaul (Phases 1–8, complete)

An eight-phase quantitative rebuild of the financial decision layer, each phase shipped behind a shadow-mode flag with full old-vs-new journaling to the event store. Phases 1-6 fixed specific broken math; Phases 7-8 added new capability on top rather than fixing a defect — see the table below for 1-6, and the flags table's Phase 7/8 rows for what each of those adds (creative fatigue detection, statistically valid A/B testing, unified urgency scoring, Monte Carlo pre-launch risk intervals, and the organic/earned-media channel with its own creator-seeding tracker and content calendar in `core/ugc/`).

| Phase | What was broken | The fix |
|---|---|---|
| **1 — Attribution** | Cross-platform revenue double-counted (TikTok and Meta both claim the same sale) | `backend/metrics/attribution.py` reconciles platform-claimed revenue against Shopify ground truth — scales down proportionally, never up |
| **2 — Capital allocation** | Four disconnected allocators with no shared theory, no covariance modeling | `backend/decision/capital_policy.py`: one mean-variance QP (CVXPY) with block-correlation by platform/group, drawdown-scaled risk aversion, portfolio-size-adaptive concentration bounds; solver ladder QP → LP → uniform, never raises |
| **3 — Decision scoring** | Unnormalized flat sum — any unbounded term could dominate regardless of real ROAS | `backend/learning/score_normalization.py`: rolling z-score normalization per term + inverse-variance (Bayesian precision) weighting |
| **4 — Calibration & regime** | Bias and uncertainty estimated from the same window (leaky, overconfident); regime detection by hardcoded thresholds | Chronological train/holdout split with isotonic regression (honest out-of-sample uncertainty); additive two-sided CUSUM (Page-Hinkley) changepoint detector (ARL₀ ≈ 5,940 cycles between false alarms, ~16-cycle detection delay at a 1σ shift); regime bonus down-weighted by the detector's own chance-corrected hit-rate |
| **5 — Risk management** | `max_drawdown`/`max_daily_spend` hardcoded twice, static dollar amounts | `backend/risk/config.py`: single source; spend cap scales with capital × inverse volatility, drawdown tolerance tightens (never widens) with concentration and volatility |
| **6 — Unit economics** | Flat 12% return rate for every product; no geo economics; static supplier reliability; zero repeat-purchase awareness | Category-aware return rates; geo margins (shipping bands, customs/duty over $800, COD refusal 10% vs card 2.5%); supplier-reliability EMA feedback loop from observed stockouts/delays; Beta-Binomial CAC-vs-LTV tracker so consumables outrank one-off items with identical first-order margin |

### Shadow-mode flags

All default **off** — legacy behavior is byte-identical until a flag is flipped. Both paths are always computed and journaled to the event store (`state/workflow_executions.jsonl`) as `shadow_*` events for validation.

| Flag | Gates |
|---|---|
| `ATTRIBUTION_RECONCILE_LIVE` | Reconciled (deduplicated) revenue drives profitability figures |
| `CAPITAL_POLICY_LIVE` | Mean-variance QP replaces the legacy LP for budget allocation |
| `SCORING_NORMALIZE_LIVE` | Normalized precision-weighted decision score replaces the flat sum |
| `CALIBRATION_HOLDOUT_LIVE` | Train/holdout isotonic calibration replaces same-window bias/std |
| `REGIME_CONFIDENCE_WEIGHTING_LIVE` | Regime bonus down-weighted by detector accuracy |
| `RISK_ADAPTIVE_LIVE` | Adaptive drawdown/spend caps replace static 0.30 / $10k |
| `GEO_ECONOMICS_LIVE` | GeoAgent expands/pauses on margin-adjusted ROAS, not raw platform ROAS |
| `SUPPLIER_RISK_RANKING_LIVE` | Return-risk-adjusted supplier ranking replaces cheapest-landed-cost |
| `SUPPLIER_FEEDBACK_LIVE` | Observed EMA reliability replaces static per-supplier constants |
| `PHASE7_AB_TEST_VALIDITY_LIVE` | Hook/angle candidate pool restricted to statistically valid (sample-size-gated) winners, not just highest-raw-score |
| `PHASE7_FATIGUE_DETECTION_LIVE` | Rolling-window-vs-lifetime-average fatigue detection (`core/creative/fatigue_detector.py`, `hook_performance.py`, `sequence_optimizer.py`) drives hook/angle rotation |
| `PHASE7_URGENCY_SCORING_LIVE` | Unified trend-urgency score (validated in `backend/validation/shadow_validator.py`'s `urgency_scoring` phase) informs early-mover ranking |
| `PHASE7_MONTE_CARLO_LIVE` | Monte Carlo pre-launch prediction intervals (`simulation/model.py`/`engine.py`, 1,000 bootstrap samples, capped to the top 20 candidates per cycle) replace point-estimate ROAS risk |
| `PHASE8_ORGANIC_CHANNEL_LIVE` | Organic/earned-media channel (`core/ugc/content_calendar.py`, `creator_tracker.py`) — zero-marginal-CAC creator seeding + content calendar — runs alongside paid |
| `PHASE8_AFFILIATE_SCALING_LIVE` | Affiliate/organic-winner scaling gate |

The CUSUM changepoint signal is journaled every cycle (`shadow_regime_changepoint`) but deliberately gates nothing yet — its false-positive rate and detection latency are being validated against journal data first.

---

## Architecture

```text
        ┌────────────────────────────────────────────────┐
        │                ORCHESTRATOR                    │
        │  phase controller: RESEARCH→EXPLORE→VALIDATE→  │
        │  SCALE · per-phase worker dispatch every 10s   │
        └───────┬──────────────┬─────────────┬───────────┘
                │              │             │
     ┌──────────▼───┐  ┌───────▼──────┐  ┌───▼──────────────┐
     │  DISCOVERY   │  │  EXECUTION   │  │ METRICS/FEEDBACK  │
     │ Reddit·Trends│  │ decide() →   │  │ real ROAS ingest  │
     │ AdLib·TikTok │  │ QP budget →  │  │ attribution recon │
     │ SignalEngine │  │ outcomes →   │  │ calibration loop  │
     └──────────┬───┘  │ learn        │  └───┬──────────────┘
                │      └───────┬──────┘      │
     ┌──────────▼───┐          │      ┌──────▼───────────┐
     │  VALIDATION  │          │      │  RISK & AGENTS   │
     │ suppliers ×4 │          │      │ GlobalRiskEngine │
     │ margins·geo  │          │      │ Scaling/Geo/     │
     │ CAC-LTV      │          │      │ Audience/Risk +  │
     └──────────┬───┘          │      │ veto arbitration │
                │              │      └──────┬───────────┘
     ┌──────────▼──────────────▼─────────────▼───────────┐
     │             ORCHESTRATION BACKBONE                │
     │  event sourcing (append-only JSONL) · circuit     │
     │  breakers per platform · rate mesh · transactions │
     └──────────┬────────────────────────────────────────┘
                │
     ┌──────────▼────────────────────────────────────────┐
     │  INTEGRATIONS (all dry-run by default)            │
     │  TikTok Ads · Meta Graph · Shopify · CJ/Zendrop/  │
     │  Spocket/Printful · FRED macro · Adobe AJO        │
     └───────────────────────────────────────────────────┘
```

**Key subsystems:**

- `backend/orchestration/` — append-only event store (crash-safe, powers replay and prediction→outcome pairing), per-platform circuit breakers (HEALTHY→DEGRADED→FAILED→RECOVERING + RATE_LIMITED), cross-platform rate mesh, transactional multi-platform launches with compensation.
- `backend/decision/` + `backend/learning/` + `backend/regime/` + `backend/risk/` — the quantitative core described above.
- `agents/` — four threshold agents (Scaling, Geo, Audience, Risk) + an arbitration engine: RiskAgent veto wins unconditionally; same-axis conflicts resolve halt-beats-scale, then by confidence; never raises.
- `backend/metrics/` + `backend/economics/` — profitability with attribution reconciliation, confidence-bucketed calibration tuning, Beta-Binomial LTV, supplier feedback.
- `core/creative/` + `core/content/` — hook/sequence performance tracking, pattern store (atomic JSON persistence), playbook memory, creative generation pipeline (composer, renderer, voiceover, video generator).
- `backend/memory/` (episodic/procedural/semantic) + `backend/vector/` (Qdrant embeddings, semantic search) + `backend/lineage/` — cognitive write-through: winning decisions are indexed and traceable decision→outcome.
- `simulation/` — DuckDB replay store for historical analysis, Ridge scoring model, calibration store.
- `api/` + `backend/api.py` — FastAPI app (100+ endpoints across the quant core and the `services/*` commercial layer: decisions, budget, portfolio, agents, risk kill-switch, orchestration traces, observability, dropship dashboard, `/api/services/*`) + a `/ws` WebSocket event stream that the frontend now actually connects to.
- `backend/workspaces/` + `backend/experiments/` + `backend/ledger/` + `backend/providers/` + `backend/costs/` + `backend/stack_planner/` + `services/*` + `marketos/cli.py` — the modular commercial layer described in full below.
- `frontend/` — React 18 + Vite + Tailwind + react-router-dom dashboard. Two things live here now: the router app (`Shell` layout + `Sidebar` nav — Dashboard, Campaigns, Products, Creatives, Signals, Runtime, Risk, Replay, **Services**), which is what actually mounts from `main.tsx`; and the original tab-based `App.tsx` component tree, kept in the repo (unmounted) rather than deleted. Dev-mode only (not served by the backend; run via `vite dev` — see Getting started).

---

## Modular commercial layer

Everything above is the quant core that runs MarketOS's *own* dropshipping operation. Sitting on top of it — reusing its functions, never duplicating them — is a separate layer that turns individual pieces of that pipeline into sellable units: run them for your own store, deliver them as a paid service to a client, or (once the gaps below are closed) offer them as self-serve SaaS.

### Foundations

- **`backend/workspaces/`** — `ClientWorkspace` (a tenant: name, mode, dry-run default, live-mode flag, allowed integrations, budget ceilings), `WorkspaceRegistry` (JSON-file-backed, `workspace_id` derived deterministically from name), `CredentialScope` (per-integration configured/allowed/dry-run status, wrapping `backend.config.list_configured_services()`), `LiveModeChecklist` (the gate every live external mutation must clear — credentials + live-mode + budget ceilings, always journaled, never raises), `ArtifactStore` (per-workspace result/report persistence under `state/workspaces/{workspace_id}/experiments/{experiment_id}/`).
- **`backend/experiments/`** — `CommercialRunEnvelope` (subclasses the existing `BaseArtifact`, not a parallel system: every service-module call gets an `experiment_id`, `status` lifecycle `created→running→completed/blocked/failed`, and an audit trail), `ExperimentRegistry` (a thin filtered view over the existing `ArtifactRegistry`), `audit_log` (journals every status transition to the same `event_store` every shadow-mode gate already uses).
- **`backend/ledger/`** — an event-sourced commerce ledger: `OrderCreated`/`PaymentCaptured`/`OrderCanceled`/`RefundIssued`/`ChargebackOpened`/`SupplierCostObserved`/`FulfillmentCompleted`/`AdSpendObserved`/`AttributionClaimObserved` events (thin wrappers over the existing `event_store`, no second log), replayed per-workspace into recognized revenue, cash collected, CAC (blended + per-channel), contribution profit, profit-per-{order,product,channel}, and a cash-conversion-cycle proxy. `services.unit_economics`/`services.ecommerce_operator` get `from_ledger()` entry points that derive their inputs from this instead of requiring the caller to supply pre-aggregated numbers. Full details: `docs/COMMERCE_LEDGER.md`.
- **`backend/dao_future/`** — placeholder-only dataclasses (`BusinessCell`, `Proposal`, `GovernanceDecision`, `CapitalAllocationRequest`, `OperatorRole`, `RevenueShareRule`) mapping today's real infrastructure to a possible future DAO-governed operating model. Zero behavior, imported by nothing live. See `docs/DAO_FUTURE_ARCHITECTURE.md`.
- **`backend/providers/`** + **`backend/costs/`** + **`backend/stack_planner/`** — a cost-aware Provider Registry (static commerce/payment/hosting/automation provider catalog), Cost Engine (composes `backend.validation.margin_calculator` — no duplicated fee/margin math), and Stack Planner (recommends Hostinger+WooCommerce vs. Shopify vs. Medusa vs. GoHighLevel, Stripe MX vs. Mercado Pago MX, applying hard cost-governance rules — no unjustified SaaS cost recommended). Wrapped as the sellable `services.profit_stack_advisor` module. Full details: `docs/COST_AWARE_INTEGRATION_AUDIT.md`, `docs/PROVIDER_REGISTRY.md`, `docs/STACK_PLANNER.md`.

### The 9 service modules (`services/*`)

| Module | What it does | Status |
|---|---|---|
| `product_research` | Discovery + validation pipeline → structured opportunity audit (demand, competitor saturation, supplier quote, pricing, real-vs-mock data provenance) | `ready_for_client_service` |
| `unit_economics` | Margin/break-even/ROAS diagnostic, ledger-aware (`from_ledger()`) | `ready_for_client_service` |
| `ecommerce_operator` | Launch-readiness gate, ledger-derived contribution profit, kill/scale decisions | readiness: `ready_for_client_service`; profit/decision: `needs_live_data` (honest — needs your real numbers) |
| `creative_growth` | Ad angles/hooks (wraps `core/creative`), fatigue analysis, next-batch recommendation | `ready_for_client_service` |
| `customer_intelligence` | ICP, segments, lead strategy, publicity plan, 7 vertical playbooks (real estate, car sales, e-commerce brand, clinic/wellness, home services, coaching/consulting, luxury) | `ready_for_client_service` |
| `digital_products` | Offer/funnel/content-plan/validation/margin/launch-checklist for turning an artifact or expertise into a sellable digital product | `ready_for_client_service` |
| `sales_automation` | Deterministic (no-LLM) chat lead-qualification + appointment handoff simulation | `ready_for_internal_use` (honest — simulation only, no real messaging adapter exists yet) |
| `profit_stack_advisor` | Cost-aware commerce/payment/automation stack recommendation (Hostinger+WooCommerce vs. Shopify vs. Medusa vs. GoHighLevel; Stripe MX vs. Mercado Pago MX) + margin/break-even numbers, composing `backend/providers`+`backend/costs`+`backend/stack_planner` | `ready_for_client_service` |
| `reporting` | Shared markdown rendering + artifact persistence + `json_safe()` (non-finite-float sanitization at API/CLI boundaries) used by all of the above | n/a (shared infrastructure) |

Full per-module reference (inputs/outputs/pricing guidance in MXN/exact CLI+API signatures): `docs/SERVICE_MODULES.md`. Full layered-architecture picture: `docs/MARKETOS_MODULAR_ARCHITECTURE.md`.

### How to run a service module

```bash
# CLI — every module has a subcommand
python -m marketos.cli services unit-economics --product "Widget" --cost 10 --price 40
python -m marketos.cli services product-audit --product "Widget" --category general
python -m marketos.cli services ecommerce-operator --product "Widget" --roas 2.0
python -m marketos.cli services creative-growth --product "Widget"
python -m marketos.cli services customer-intelligence --business-type "dental clinic" --vertical clinic_wellness
python -m marketos.cli services digital-product --offer-name "Product Validation Playbook" --price 497
python -m marketos.cli services sales-bot-sim --vertical car_sales
python -m marketos.cli services profit-stack-advisor --business-name "Own Store" --business-model own_ecommerce --expected-monthly-revenue 5000
python -m marketos.cli stack recommend --business-model own_ecommerce --target-geo MX --expected-monthly-revenue 5000   # lighter, non-billable

# REST API — same 8 non-reporting modules, mounted at /api/services/* in backend/api.py
# (plus the lighter POST /api/stack/recommend, not tied to a service module)
curl -X POST "http://localhost:3000/api/services/unit-economics?product=Widget&cost=10&price=40"

# Dashboard — the Services nav item in the router app (frontend/src/pages/Services.tsx)
# renders a form + live result panel for all 8, hitting the same API routes above.
```

### Safety: nothing here spends money or contacts anyone on its own

Every module either produces read-only analysis, or a decision/readiness verdict that a separate, pre-existing, already-dry-run-gated integration (`backend/integrations/*`) must still execute. `LiveModeChecklist` and `services.ecommerce_operator.launch_guard` compose with (never duplicate) the existing `backend.risk.gate.check_spend()` real-money choke point. Full reasoning + a module-by-module "does this ever mutate something real?" table: `docs/LIVE_MODE_SAFETY.md`.

### What's still a gap here

No real multi-tenant auth or Postgres-backed persistence (workspaces are JSON files, isolated by convention, not by a database), no billing/metering. See Known gaps below for the full, current list.

---

## Getting started

```bash
# Requirements: Python 3.11+, pip install -r requirements.txt

# Run the test suite (no credentials or network needed)
python -m pytest -q                 # 2,495 passed, 4 skipped (2,499 collected)
python -m pytest -q -n auto         # same, parallelized via pytest-xdist (~4-5 min vs ~10-13 min serial)

# Run the API + background decision loop
uvicorn backend.api:app --port 3000

# Run the full orchestrator (phase-scheduled workers)
python run.py                # == python -m orchestrator.main

# Guided MVP run: credential wizard + one dropship cycle (3 products, $50/day)
./run_mvp.sh

# Run a sellable service module directly (see Modular commercial layer above)
python -m marketos.cli services unit-economics --product "Widget" --cost 10 --price 40

# Frontend dashboard (dev-mode; proxies /api and /ws to the backend above)
cd frontend && npm install && npm run dev

# Docker
docker compose up            # api, orchestrator, redis, qdrant, prometheus, grafana
```

**Everything is dry-run by default.** Real spend requires explicitly setting the per-integration gates (`TIKTOK_DRY_RUN=false`, `META_DRY_RUN=false`, `STORE_DRY_RUN=false`, `SUPPLIERS_DRY_RUN=false`, `ADLIB_DRY_RUN=false`) *and* providing credentials — via environment (`TIKTOK_ACCESS_TOKEN`/`TIKTOK_ADVERTISER_ID`, `META_ACCESS_TOKEN`/`META_AD_ACCOUNT_ID`, `SHOPIFY_STORE_URL`/`SHOPIFY_ACCESS_TOKEN`, `CJ_API_KEY`, `ZENDROP_API_KEY`, `SPOCKET_API_KEY`, `PRINTFUL_API_KEY`, `FRED_API_KEY`) or the setup wizard (`~/.marketos/credentials.json`, written 0600).

State persists under `state/` (`STATE_DIR`/`MARKETOS_STATE_DIR`): DuckDB system state, append-only JSONL event/metric/cost/error logs, atomic-JSON stores for patterns, playbooks, and calibration.

---

## Engineering principles

1. **Shadow mode before live.** New financial logic never touches real budget on day one: it runs alongside the old logic, journals both results, and takes over only after validation against realized outcomes.
2. **Event sourcing as ground truth.** Every workflow step, shadow comparison, and launch is an append-only journal entry — crash recovery, replay, and prediction→outcome pairing all derive from it.
3. **Never raise in the money path.** Solver ladders (QP → LP → uniform), dry-run fallbacks, fail-silent journaling, and compensation-based rollback: a subsystem failure degrades the decision, it doesn't halt the loop.
4. **Statistics over vibes.** Isotonic calibration on held-out data, CUSUM with derived ARL bounds, Beta-Binomial shrinkage toward category priors, chance-corrected confidence weighting — parameters are derived, not guessed.
5. **Conservative by construction.** Attribution reconciliation only scales revenue *down*; adaptive drawdown tolerance only *tightens*; arbitration resolves conflicts toward halting, not scaling.

---

## Status & roadmap

**Complete** — orchestration framework (event sourcing, circuit breakers, transactions), multi-agent arbitration, the full dropshipping pipeline (dry-run verified end to end), the eight-phase ROI overhaul (Phases 1-6 quant core + Phase 7 creative fatigue/A-B-testing/urgency/Monte Carlo + Phase 8 organic/UGC channel — all shadow-gated, see the flags table above), the full modular commercial layer (see [Modular commercial layer](#modular-commercial-layer)), and the frontend router + Services UI. 232 test files / 2,499 collected tests, 2,495 passing / 4 skipped.

**Shadow validation in progress** — every `*_LIVE` flag defaults off pending journal-data validation that each new path outperforms its legacy counterpart on reconciled metrics. This includes both the six original quant-core flags and the six Phase 7/8 flags added since.

**Known gaps** (tracked, honest):
- **No real multi-tenant auth or database.** `ClientWorkspace`/`WorkspaceRegistry` (`backend/workspaces/`) isolate data by a `workspace_id` convention over JSON files — real, but there's no login, no API key, no billing meter, no Postgres. This is the single largest gap between "ready to sell as a service" and "self-serve SaaS anyone could sign up for." A full Supabase-Auth-plus-Postgres-with-RLS migration is designed (schema, shadow-mode dual-write, auth middleware, cutover) but intentionally not yet built — ask if you want to see the design.
- **Two audit logs, unified only structurally.** `backend/events/log.py` (DuckDB-backed, artifact/lineage replay) and `backend/orchestration/event_store.py` (JSONL, every dry-run/shadow gate + the commerce ledger) are genuinely different logs for different purposes; they now share a `backend.contracts.event_log.EventLogProtocol` structural interface, but nothing merges their storage or schema.
- **The LTV tracker** has no production caller wiring real orders in yet (rates sit at category priors from the Amazon Reviews 2023 / Olist datasets).
- **`Workflow`/`PlatformAdapter` abstractions** are test-covered but not yet on the production path.
- **Live (non-dry-run) API paths** are implemented but unverified against real ad-platform/Shopify accounts.
- **A handful of OSS integrations remain deliberately deferred** pending explicit sign-off before adoption: Twenty CRM, Chatwoot, Cal.com, Temporal/Prefect (see `docs/oss/LICENSE_MANIFEST.yml` for the full reasoning per tool — PostHog was the one candidate adopted, client-side only, default-off).

---

## Repository layout

```text
backend/
  decision/       QP capital policy, decision engine, budget allocator, portfolio
  learning/       calibration (holdout+isotonic), score normalization, LinUCB, replay
  regime/         threshold detector + CUSUM changepoint, confidence, strategy memory
  risk/           single-source risk config with adaptive caps
  orchestration/  event store, circuit breakers, rate mesh, transactions, workflow
  execution/      the production decision cycle (run_cycle)
  metrics/        profitability, attribution reconciliation, campaign metrics
  economics/      Beta-Binomial LTV, supplier reliability feedback
  discovery/      trend adapters, Meta Ad Library intelligence, signal cache
  validation/     validator, margin calculator (category/geo/LTV), 4 supplier clients
  creation/       LLM listings + ad copy, Shopify store builder
  launch/         launch orchestrator (plain + transactional)
  integrations/   TikTok, Meta, Shopify clients (dry-run default)
  memory/ vector/ lineage/   cognitive layer (episodic memory, Qdrant, lineage)
  workspaces/     ClientWorkspace, CredentialScope, LiveModeChecklist, ArtifactStore
  experiments/    CommercialRunEnvelope, ExperimentRegistry, audit_log
  ledger/         event-sourced commerce ledger (events + replay projections)
  providers/      Provider Registry — commerce/payment/hosting/automation catalog
  costs/          Cost Engine — composes margin_calculator, no duplicated fee math
  stack_planner/  recommends a commerce/payment/automation stack per business
  dao_future/     placeholder-only future-governance dataclasses, zero behavior
  contracts/      BaseArtifact/ArtifactRegistry + adapter Protocols (incl. event_log)
agents/           Scaling/Geo/Audience/Risk agents + veto/consensus arbitration
core/             portfolio, LinUCB, risk engines, creative pipeline, content patterns,
                  core/ugc/ (organic/UGC content calendar + creator tracker, Phase 8)
orchestrator/     phase-scheduled worker runtime (the production spine)
services/         9 sellable modules — product_research, unit_economics,
                  ecommerce_operator, creative_growth, customer_intelligence,
                  digital_products, sales_automation, profit_stack_advisor, reporting
marketos/         CLI entrypoint (marketos/cli.py) for the services/* modules + stack recommend
api/              FastAPI route modules incl. api/routes/{services,stack}.py, dashboards, WS stream
frontend/         React + Vite + react-router-dom dashboard: Shell/Sidebar router app
                  (Dashboard, Campaigns, Products, Creatives, Signals, Runtime, Risk,
                  Replay, Services) + the original tab-based App.tsx (kept, unmounted)
simulation/       DuckDB replay, scoring model, calibration store, Monte Carlo (Phase 7)
docs/             SERVICE_MODULES.md, MARKETOS_MODULAR_ARCHITECTURE.md,
                  COMMERCE_LEDGER.md, LIVE_MODE_SAFETY.md, DAO_FUTURE_ARCHITECTURE.md,
                  OWN_ECOMMERCE_VALIDATION_WORKFLOW.md, DIGITAL_PRODUCT_WORKFLOW.md,
                  SALES_AUTOMATION_MODULE.md, oss/ (dependency + license governance)
tests/            232 test files — 2,495 passing / 4 skipped (2,499 collected)
```

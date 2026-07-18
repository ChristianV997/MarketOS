# MarketOS

### Autonomous commerce decision engine for dropshipping — discover, validate, launch, and optimize products with risk-aware capital allocation.

MarketOS runs a continuous **Discover → Validate → Create → Launch → Optimize** loop over real ad platforms (TikTok, Meta) and a Shopify storefront, driven by a quantitative decision core: convex-optimization budget allocation, contextual bandits, statistically calibrated ROAS prediction, regime/changepoint detection, and adaptive risk limits. Every risky change ships behind a **shadow-mode flag** — the new logic runs and journals its decisions alongside the old one, and only takes over real budget after validation.

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

## The ROI overhaul (Phases 1–6, complete)

A six-phase quantitative rebuild of the financial decision layer, each phase shipped behind a shadow-mode flag with full old-vs-new journaling to the event store:

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
- `api/` + `backend/api.py` — FastAPI app (~40 endpoints: decisions, budget, portfolio, agents, risk kill-switch, orchestration traces, observability, dropship dashboard) + WebSocket event stream; background cycle runner.
- `frontend/` — React 18 + Vite + Tailwind dashboard (command center, metrics, simulation, tasks). Dev-mode only (not served by the backend; run via `vite dev`).

---

## Getting started

```bash
# Requirements: Python 3.11+, pip install -r requirements.txt

# Run the test suite (no credentials or network needed)
python -m pytest -q          # 1,276 passed, 4 skipped

# Run the API + background decision loop
uvicorn backend.api:app --port 3000

# Run the full orchestrator (phase-scheduled workers)
python run.py                # == python -m orchestrator.main

# Guided MVP run: credential wizard + one dropship cycle (3 products, $50/day)
./run_mvp.sh

# Docker
docker compose up            # api, orchestrator, redis, qdrant, prometheus, grafana
```

**Everything is dry-run by default.** Real spend requires explicitly setting the per-integration gates (`TIKTOK_DRY_RUN=false`, `META_DRY_RUN=false`, `STORE_DRY_RUN=false`, `SUPPLIERS_DRY_RUN=false`, `ADLIB_DRY_RUN=false`) *and* providing credentials — via environment (`TIKTOK_ACCESS_TOKEN`/`TIKTOK_ADVERTISER_ID`, `META_ACCESS_TOKEN`/`META_AD_ACCOUNT_ID`, `SHOPIFY_SHOP_URL`/`SHOPIFY_ACCESS_TOKEN`, `CJ_API_KEY`, `ZENDROP_API_KEY`, `SPOCKET_API_KEY`, `PRINTFUL_API_KEY`, `FRED_API_KEY`) or the setup wizard (`~/.marketos/credentials.json`, written 0600).

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

**Complete** — orchestration framework (event sourcing, circuit breakers, transactions), multi-agent arbitration, the full dropshipping pipeline (dry-run verified end to end), the six-phase ROI overhaul, 103 test files / 1,276 passing tests.

**Shadow validation in progress** — all nine `*_LIVE` flags are off pending journal-data validation that each new path outperforms its legacy counterpart on reconciled metrics.

**Next (designed, not yet implemented):**
- **Phase 7** — creative fatigue detection (rolling-window trend vs lifetime average), statistically valid A/B testing (sample-size gates + significance tests), a unified trend-urgency score, Monte Carlo pre-launch simulation.
- **Phase 8** — organic/earned-media channel (`core/ugc/` is currently an empty stub): creator-seeding tracker and content calendar, so a zero-marginal-CAC channel exists alongside paid.

**Known gaps** (tracked, honest): the frontend is dev-mode only with a broken WS path (`/ws/events` vs `/ws`); the LTV tracker has no production caller wiring orders in yet (rates sit at category priors); the `Workflow`/`PlatformAdapter` abstractions are test-covered but not yet on the production path; live (non-dry-run) API paths are implemented but unverified against real accounts.

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
agents/           Scaling/Geo/Audience/Risk agents + veto/consensus arbitration
core/             portfolio, LinUCB, risk engines, creative pipeline, content patterns
orchestrator/     phase-scheduled worker runtime (the production spine)
api/              FastAPI route modules, dashboards, WebSocket stream
frontend/         React dashboard (dev-mode)
simulation/       DuckDB replay, scoring model, calibration store
tests/            103 test files — 1,276 passing
```

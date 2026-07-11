# MarketOS — Audit, Prune/Specialize Decision, and Consolidation Plan

**Scope:** full repo, branch `claude/analyze-repository-fsGUx`, 542 Python files across 26 top-level dirs.
**Method:** 6 parallel subsystem audits (runtime spine, signals/connectors, decision/execution/content, learning/simulation/RL, integrations/agents/api, inference/memory/vector/observability).

---

## 1. Executive summary

MarketOS is not one system — it is **two systems sharing a repo**:

1. **The live spine** — actually runs, actually gets invoked by `orchestrator/main.py` / `backend/api.py`, actually calls real (if often mocked-with-fallback) external APIs. This is a genuinely working, moderately mature autonomous commerce loop: signals → decision → execution → content → integrations → learning → risk/capital, wrapped in a real event bus, replay store, and API surface.
2. **The cognitive shadow system** — `backend/memory/`, `backend/vector/`, `backend/lineage/`, `backend/runtime/sleep/`, `backend/runtime/topology/`, most of `backend/inference/`. This is well-built and the *best-tested* code in the repo (~250 tests) but is wired **only to itself** — the live spine never calls it. It represents the README's "replay-safe, deterministic, cognitive" positioning, but that positioning is currently aspirational.

On top of that split, there are **~12 duplicate implementations** of the same concern (two decision engines, two content systems, two memory systems, two capital allocators, three calibration stores, two risk guards, two API entrypoints with a live prod/dev mismatch bug, etc.) — almost all duplicates split one LIVE-and-wired copy from one well-built-but-orphaned copy.

**The decision this audit makes:** prune the orphaned duplicate *engines* (they add no capability, only confusion), and instead of discarding the cognitive shadow system, **finish wiring it into the live spine** — it's the most-invested, most-differentiated, best-tested code in the repo; the gap is integration, not construction. That is the "most complete artifact" worth specializing in.

---

## 2. The live spine (what actually runs)

```
core/signals.py (SignalEngine)
  ← backend/adapters/research/trend_source_v1.py   (Google Trends, real, LIVE)
  ← backend/adapters/amazon_bestsellers.py         (real scrape attempt + mock fallback)
  ← backend/adapters/reddit_trends.py               (real public JSON API)
  ← backend/adapters/tiktok_organic.py              (gated real + pytrends + mock, 3-tier)
        ↓
orchestrator/main.py  (real tick loop, phase dispatch, docker service)
        ↓
backend/decision/engine.py + scoring/confidence/budget_allocator/portfolio_engine
  ← connectors/meta_ads_intel.py, connectors/shopify_scraper.py (real, unauthenticated public endpoints)
        ↓
backend/execution/loop.py (run_cycle — THE production cycle)
  ← core/content/{playbook,patterns,feedback}.py   (live content intelligence)
  ← core/creative/generator.py + hooks.py            (real Anthropic call + deterministic fallback)
  ← connectors/macro_signals.py, connectors/supabase_connector.py, connectors/adobe_ajo_connector.py
        ↓
backend/integrations/{tiktok_ads,adobe_ajo,shopify_client,meta_ads_client,supabase_client}.py
  (real HTTP clients, dry-run/mock fallback when unconfigured)
        ↓
backend/learning/{world_model_calibration,replay_buffer,signals,update}.py
  + simulation/ (top-level: Ridge scorer, DuckDB replay, calibration audit — all LIVE, real ML)
  + backend/causal/ (real statsmodels Granger causality)
  + backend/regime/ (variance/slope regime detection)
        ↓
core/risk/global_risk_engine.py (kill-switch, drawdown, spend caps)
core/capital/__init__.py (CapitalEngine — allocation)
        ↓
backend/pubsub/broker.py + backend/events/ + backend/ws/stream.py   (event spine)
backend/runtime/{state,task_inventory,replay_store,topology}.py     (state + replay)
backend/contracts/ (artifact registry)
backend/core/{state,serializer,db_serializer}.py → warehouse/duckdb_store.py (persistence)
core/system/{phase_controller,resource_allocator}.py (tick driver)
core/memory/ (the simple, actually-used memory)
backend/jobs/ (job runner, scheduler)
backend/api.py (primary FastAPI app, mounts api/control.py, dashboard.py, pods.py, ws.py)
```

This is real, testable, and mostly works end to end today (with graceful degradation to mocks when API keys are absent). **This is the artifact to keep and specialize in.**

---

## 3. Critical bug found (fix first, before anything else)

`docker-compose.yml` (dev) launches `uvicorn backend.api:app` — the full, real application.
`docker-compose.prod.yml` launches `uvicorn api.main:app` — a **different, smaller, standalone FastAPI app**.

**Production is running the wrong app.** This isn't a style nit — the two apps expose different route sets and different behavior. This must be fixed before any "single run" claim is credible. Confirmed directly:

```
docker-compose.yml:34:      command: uvicorn backend.api:app --host 0.0.0.0 --port 3000 --reload
docker-compose.prod.yml:5:  command: uvicorn api.main:app --host 0.0.0.0 --port 8000
```

**Fix:** point `docker-compose.prod.yml` at `backend.api:app`, then decide whether `api/main.py` should be deleted or kept as an intentionally thin alternative (recommendation: delete — see §5).

---

## 4. Duplication clusters (pick one side, delete the other)

| # | Concern | LIVE / wired copy (keep) | Orphaned duplicate (prune) |
|---|---|---|---|
| 1 | Decision + execution engine | `backend/decision/` + `backend/execution/loop.py` | `core/copilot/` + `core/engine/{execution_loop,master_loop}.py` |
| 2 | Content intelligence | `core/content/{playbook,patterns,feedback,schemas}.py` | `content/` (top-level, near-identical API, test-only) |
| 3 | Memory | `core/memory/` (simple, actually used) | `backend/memory/` (tiered episodic/semantic/procedural, unwired) — **see §6, don't prune blindly** |
| 4 | Capital allocation | `core/capital/__init__.py::CapitalEngine` (simple even-split, wired) | `core/capital/allocator.py` (richer softmax, 32 tests, unwired) |
| 5 | Calibration | `backend/learning/world_model_calibration.py` + `simulation/calibration.py` | `backend/learning/calibration.py`, `calibration_log.py` |
| 6 | Bandit | `backend/learning/bandit_update.py` (stub, wired) | `backend/learning/contextual_bandit.py` (real LinUCB, orphaned) — **recommend swapping which side wins, see §7** |
| 7 | Risk guard | `core/risk/global_risk_engine.py` (wired into `backend/api.py`) | `core/risk/guard.py` (duplicate wrapper, unwired) |
| 8 | Replay store | `backend/runtime/replay_store.py` (wired) | `backend/runtime/runtime_replay_store.py` (dead 24-line dup) |
| 9 | Macro signals connector | `connectors/macro_signals.py` (wired into api.py, execution/loop.py) | `backend/integrations/macro_signals.py` (dead dup) |
| 10 | Meta Ads client | `backend/integrations/meta_ads_client.py` (wired) | `agents/meta_ads_agent.py` (independent duplicate impl) |
| 11 | API entrypoint | `backend/api.py` (full app) | `api/main.py` (thinner app — **this is the prod bug in §3**) |
| 12 | Evolution wrapper | `backend/agents/structural_evolution` (called directly from `execution/loop.py`) | `core/evolution/integration.py` (dead pass-through wrapper) |

---

## 5. Full prune list (dead, orphaned, or superseded — no capability lost)

```
backend/core/system_v5.py                     # duplicate engine, test-only caller
backend/core/regime_transition.py              # stub, test-only
backend/runtime/runtime_replay_store.py        # dead duplicate (cluster #8)
runtime/                                       # top-level: broken imports (backend.api.replay_api unreachable), zero callers
execution/                                     # top-level: telemetry*, connectors/playwright_tiktok — orphaned
core/execution/pacing.py                       # orphaned, test-only
core/execution/ads_launch.py                   # orphaned, zero callers anywhere
content/                                       # top-level duplicate (cluster #2)
core/ugc/                                      # mock/stub, orphaned
core/copilot/                                  # duplicate decision engine (cluster #1)
core/engine/                                   # duplicate execution engine (cluster #1)
core/evolution/integration.py                  # dead wrapper (cluster #12)
core/rl/                                       # only consumed by dead core/engine/master_loop.py
core/risk/guard.py                             # duplicate (cluster #7)
research/{competition,swot,economics,market_score}.py   # pure mock, literally orphaned, docstring admits "placeholder"
connectors/supplier_api.py                     # hardcoded single dict, no network code, zero callers
connectors/stripe_connector.py                 # orphaned in production (tests only) — prune or promote (see §7)
backend/learning/calibration.py                # superseded (cluster #5)
backend/learning/calibration_log.py            # dead, zero callers
backend/learning/campaign_learning.py          # dead, zero callers
backend/simulation/replay_debugger.py          # dead, zero callers
backend/integrations/macro_signals.py          # dead dup (cluster #9)
agents/meta_ads_agent.py                       # dead dup (cluster #10)
workers/consumer.py                            # real code, but zero callers anywhere (compose "worker" service runs Celery instead)
monitoring/                                    # top-level: orphaned wrapper around backend/monitoring/alerting.py
production/                                    # scaffolding, zero importers anywhere
metrics/                                       # top-level: metrics/providers/tiktok_analytics.py, orphaned
backend/ci/regression_guard.py                 # orphaned (hyperparam_meta.py in the same dir stays — it's wired)
api/main.py                                    # once docker-compose.prod.yml is repointed (§3), this has no reason to exist
```

Expected impact: removes a large fraction of dead weight without touching any test that covers live behavior — most of these files' only test coverage is from tests that exclusively import the dead file itself (verified per-audit, not assumed).

---

## 6. The strategic call: don't prune the cognitive subsystem — finish wiring it

`backend/memory/`, `backend/vector/`, `backend/lineage/`, `backend/runtime/sleep/`, `backend/runtime/topology/`, and most of `backend/inference/` are collectively the largest, best-tested (~250 tests), most architecturally deliberate code in the repo. They are disconnected from the live loop only because nobody added the call sites — the plumbing (DuckDB, Qdrant-with-fallback, OpenTelemetry hooks) is already real.

Deleting this would be throwing away the most expensive, most differentiated part of MarketOS to save a moderate amount of dead-code cleanup. Wiring it in, by contrast, is a bounded, mechanical job:

- `backend/execution/loop.py::run_cycle` → after each cycle, write the outcome to `backend/memory` (episodic) instead of only `core/memory`.
- `core/creative/generator.py` → route its Anthropic call through `backend/inference`'s provider router instead of calling the SDK directly, so caching/fallback/cost-tracking actually apply.
- Signals and creatives → embed via `backend/vector/embeddings.py` and index in the existing Qdrant-or-in-memory store, so `backend/observability`'s snapshot/entropy endpoints stop reflecting empty state.
- `orchestrator/main.py` → add a periodic `Phase` (or reuse an existing tick) that calls `backend/runtime/sleep`'s consolidation pass — it's fully built and tested, just never invoked.
- `backend/lineage` → have `backend/decision/engine.py` and `backend/execution/loop.py` register causal edges (signal → decision → outcome) as they already do conceptually with events; lineage just needs to be a subscriber.

This is the single highest-leverage piece of "finishing development of the most complete artifact."

---

## 7. Partial-fix list (real logic worth completing, lower priority than §6)

| Item | Current state | Fix |
|---|---|---|
| `backend/learning/contextual_bandit.py` (LinUCB) | Real, orphaned | Swap in as the bandit `backend/decision/engine.py` calls, retire `bandit_update.py` |
| `core/capital/allocator.py` | Real softmax allocator, orphaned, 32 tests | Swap in as `CapitalEngine`'s implementation, retire the even-split version |
| `core/creative/video_generator.py`, `voiceover.py` | Real API clients (Runway, ElevenLabs) + stub fallback, unwired | Wire into `core/creative/generator.py`'s pipeline once product needs video/voice ads |
| `core/creative/avatar.py` | Pure stub (`{"status": "stub"}`) | Either implement against D-ID/HeyGen or delete — don't leave a silent no-op in a creative pipeline |
| `backend/adapters/youtube_trends.py` | Uses pytrends (unofficial scraper) only, no real YouTube Data API | Replace with `google-api-python-client` (`youtube.videos().list`) — official, quota-based, stable |
| `backend/adapters/amazon_bestsellers.py` | Real scrape attempt, will likely get CAPTCHA'd | Replace scraping with Amazon Product Advertising API (PA-API 5.0) or a paid data provider (Keepa, Rainforest API) |
| `backend/adapters/reddit_trends.py` | Raw `urllib` against Reddit's public JSON, no auth, no rate-limit handling | Swap to `praw` (official Reddit API wrapper) for auth, rate limits, and resilience |
| `backend/causal/` | Real Granger causality via `statsmodels` | `dowhy` is already in `requirements.txt` and unused — upgrade to real causal-effect estimation instead of correlation-only Granger tests |
| `connectors/stripe_connector.py` | Real API code, zero production callers | Either wire into `backend/integrations/` as the revenue-attribution source, or prune — currently it's dead weight either way |
| `api/main.py` vs `backend/api.py` | prod/dev mismatch | See §3 — fix first |

---

## 8. Ordered execution plan (for the next agent run — "single pass, single run" goal)

Do these in order; each phase should leave the test suite green before starting the next.

**Phase 0 — Fix the prod bug (5 min, zero risk)**
1. Point `docker-compose.prod.yml` at `uvicorn backend.api:app` (matching dev).
2. Run `pytest tests/ -q` to confirm no import relies on `api.main`.

**Phase 1 — Prune (mechanical, no logic changes)**
1. Delete every path in §5's list.
2. Delete the test files whose *only* subject is a pruned file (audit already identified these as test-only-of-dead-code; do not delete tests that cover files being kept, e.g. `test_steps_31_38.py`/`test_steps_53_54_55.py` cover multiple things — trim only the pruned-module tests within them, don't delete the file wholesale without checking).
3. Run full test suite; expect only pruned-module test failures/removals, zero regressions in kept modules.

**Phase 2 — Resolve duplication clusters (§4)**
For each of the 12 clusters: confirm the "keep" side is what's actually imported by `orchestrator/main.py` / `backend/api.py` (already verified in this audit), delete the orphaned side, fix any stray imports.

**Phase 3 — Wire the cognitive spine (§6)**
This is the substantive engineering work. Suggested order: memory write-through → vector indexing → inference router adoption in `core/creative/generator.py` → lineage subscription → sleep-cycle scheduling in `orchestrator/main.py`. Each step should come with a test that proves the live loop now touches the previously-orphaned module (not just that the module works in isolation — that's already proven).

**Phase 4 — Partial-fixes (§7)**, roughly in priority order:
1. Bandit swap (LinUCB in), capital allocator swap (softmax in) — both are drop-in replacements with existing tests.
2. Real YouTube Data API + PRAW for Reddit — bounded, well-scoped external API integrations.
3. Amazon: decide between PA-API registration (needs seller/affiliate credentials) or a paid provider — flag as a product decision, not purely engineering.
4. `dowhy` causal upgrade — optional, only if causal rigor becomes a product requirement.
5. Creative avatar/video/voice — only if video/voice ad formats are on the roadmap; otherwise prune `avatar.py`'s stub rather than ship a silent no-op.

**Phase 5 — Single-run verification**
Define and script one command that proves the "single run" goal:
```bash
uvicorn backend.api:app &          # the one true entrypoint (post Phase 0)
python -m orchestrator.main         # one full tick: signals → decision → execution → learning → risk
pytest tests/ -q                    # full suite green, deterministic (no flaky randomness in kept modules)
```
No dependency on `run.py`/`core.loop` (a third, older entrypoint using `core.loop.run_cycle` with a trivial hardcoded signal provider) — either retire `run.py` or repoint it at the real `orchestrator/main.py` tick so there is exactly one way to start the system.

---

## 9. What NOT to do

- Don't blindly vendor code from external GitHub repos into this one — the recommendations in §7 are *library* recommendations (official SDKs: `google-api-python-client`, `praw`, packages already in `requirements.txt` like `dowhy`/`pytrends`), not "copy files from repo X." Pulling in unreviewed third-party source is a supply-chain risk this plan explicitly avoids.
- Don't prune `backend/memory`/`vector`/`lineage`/`sleep`/`topology` — see §6. Their problem is integration, not quality.
- Don't touch `frontend/` — out of scope for this pass (standard Vite/React/TS app, not part of the Python consolidation).

---

## 10. Summary counts

- Files/modules recommended for **prune**: ~29 paths (§5), all confirmed zero-caller or fully superseded.
- Duplication clusters to resolve: 12 (§4).
- Critical bugs found: 1 (prod/dev entrypoint mismatch, §3).
- Highest-leverage single investment: wiring the cognitive subsystem (§6) — ~250 existing tests already validate its correctness in isolation; the only missing piece is call sites in the live loop.

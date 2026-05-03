"""
MarketOS v4 — FastAPI backend
Serves the Replit market UI frontend.

Environment variables (set in Replit Secrets):
  PORT               Web server port (default 8000; Replit sets this automatically)
  STATE_PATH         DuckDB file (default state/state.db)
  ALLOWED_ORIGINS    Comma-separated CORS origins (default "*")
  CYCLES_PER_MINUTE  Background runner speed (default 10 → one cycle / 6 s)
"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import numpy as np
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

# ── structured logging ────────────────────────────────────────────────────────
try:
    import structlog
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
except ImportError:
    pass  # fall back to standard logging

# ── Prometheus metrics ────────────────────────────────────────────────────────
try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
    _prom_cycles     = Counter("marketos_cycles_total",       "Total run_cycle() calls")
    _prom_capital    = Gauge("marketos_capital_usd",          "Current capital in USD")
    _prom_avg_roas   = Gauge("marketos_avg_roas",             "Average ROAS last 100 cycles")
    _prom_regime     = Gauge("marketos_regime",               "Detected regime label", ["regime"])
    _prom_cycle_time = Histogram("marketos_cycle_duration_s", "run_cycle() latency")
    _PROMETHEUS_OK   = True
except ImportError:
    _PROMETHEUS_OK = False

from backend.core.state import SystemState
from backend.execution.loop import run_cycle
from backend.decision.engine import decide
from backend.decision.budget_allocator import allocate as budget_allocate
import backend.learning.calibration as cal
import backend.learning.bandit_update as bu
import backend.regime.confidence as rc
from backend.agents.structural_evolution import structural_engine

# ── config ────────────────────────────────────────────────────────────────────

STATE_PATH = os.getenv("STATE_PATH", "state/state.db")
_CYCLES_PER_MINUTE = max(1, int(os.getenv("CYCLES_PER_MINUTE", "10")))

# When ORCHESTRATOR_HANDLES_CYCLES=true the background runner skips run_cycle()
# and only publishes the current snapshot. Set this when orchestrator/main.py
# is deployed alongside the API to prevent double-execution of the same state.
_ORCHESTRATOR_HANDLES_CYCLES = (
    os.getenv("ORCHESTRATOR_HANDLES_CYCLES", "false").lower() == "true"
)

# ── app ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="MarketOS v4", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── shared state ──────────────────────────────────────────────────────────────

_state = SystemState()
_lock = threading.Lock()
_bg_running = False
_started_at = time.time()
_last_cycle_at: float | None = None

_RESEARCH_INTERVAL_S = 300  # run intelligence loop every 5 minutes
_last_research_at: float = 0.0


# ── background runner ─────────────────────────────────────────────────────────

_api_log = logging.getLogger(__name__)


def _background_runner():
    global _state, _last_cycle_at
    sleep_s = 60.0 / _CYCLES_PER_MINUTE
    while _bg_running:
        t0 = time.time()
        try:
            if not _ORCHESTRATOR_HANDLES_CYCLES:
                # sole runner: execute the full cycle and update shared state
                new_state = run_cycle(_state)   # compute outside lock
                with _lock:
                    _state = new_state
                    _last_cycle_at = time.time()
            else:
                # orchestrator is the cycle driver; just read current state
                with _lock:
                    new_state = _state

            # Prometheus instrumentation
            if _PROMETHEUS_OK and not _ORCHESTRATOR_HANDLES_CYCLES:
                elapsed = time.time() - t0
                _prom_cycles.inc()
                _prom_capital.set(new_state.capital)
                rows = new_state.event_log.rows[-100:]
                avg_roas = sum(r.get("roas", 0) for r in rows) / max(len(rows), 1)
                _prom_avg_roas.set(avg_roas)
                regime = new_state.detected_regime or "unknown"
                _prom_regime.labels(regime=regime).set(1)
                _prom_cycle_time.observe(elapsed)
            # Publish full snapshot to live event stream (WebSocket clients)
            try:
                from backend.runtime.state import build_snapshot
                from backend.events.emitter import emit_snapshot
                snap = build_snapshot(new_state)
                emit_snapshot(snap, source="api")
            except Exception:
                pass
            try:
                from backend.runtime.task_inventory import task_registry as _tr
                _tr.heartbeat("background_runner", status="ok")
                _tr.heartbeat("sw_runtime_snapshot", status="ok")
            except Exception:
                pass
        except Exception:
            _api_log.exception("background runner cycle error")
        time.sleep(sleep_s)


# ── lifecycle ─────────────────────────────────────────────────────────────────

def _research_runner():
    from backend.jobs.runner import JobRegistry
    from backend.jobs.scheduler import IngestionScheduler
    from backend.jobs.research_trend_v1 import register_research_trend_v1_job, register_research_prune_job
    registry = JobRegistry()
    register_research_trend_v1_job(registry)
    register_research_prune_job(registry)
    scheduler = IngestionScheduler(registry)
    while _bg_running:
        try:
            scheduler.tick()
            # Feed trend keywords into the core intelligence discovery loop
            with _lock:
                recent = list(_state.event_log.rows[-50:])
            keywords = list({str(r.get("variant", "")) for r in recent if r.get("variant")})[:20]
            if keywords:
                try:
                    from core.intelligence_loop import run_intelligence
                    run_intelligence(keywords)
                except Exception:
                    pass
        except Exception:
            _api_log.exception("research runner error")
        try:
            from backend.runtime.task_inventory import task_registry as _tr
            _tr.heartbeat("research_runner", status="ok")
        except Exception:
            pass
        time.sleep(300)  # check every 5 minutes


@app.on_event("startup")
async def _startup():
    global _state, _bg_running
    from backend.core.serializer import load
    loaded = load(STATE_PATH)
    if loaded:
        _state = loaded

    _bg_running = True
    threading.Thread(target=_background_runner, daemon=True).start()
    threading.Thread(target=_research_runner, daemon=True).start()
    try:
        from backend.runtime.task_inventory import start_heartbeat_broadcaster
        start_heartbeat_broadcaster(interval_s=30.0)
    except Exception:
        pass


@app.on_event("shutdown")
async def _shutdown():
    global _bg_running
    _bg_running = False
    try:
        from backend.runtime.task_inventory import stop_heartbeat_broadcaster
        stop_heartbeat_broadcaster()
    except Exception:
        pass
    from backend.core.serializer import save
    try:
        save(_state, STATE_PATH)
    except Exception:
        pass


# ── helpers ───────────────────────────────────────────────────────────────────

def _roas_trend_slope(rows: list[dict], tail: int = 20) -> float:
    vals = [r.get("roas", 0) for r in rows[-tail:]]
    if len(vals) < 2:
        return 0.0
    n = len(vals)
    xs = list(range(n))
    xm = sum(xs) / n
    ym = sum(vals) / n
    num = sum((xs[i] - xm) * (vals[i] - ym) for i in range(n))
    den = sum((xs[i] - xm) ** 2 for i in range(n))
    return round(num / den, 6) if den > 1e-9 else 0.0


def _variant_avg(rows: list[dict]) -> dict[str, float]:
    buckets: dict[str, list[float]] = {}
    for r in rows:
        v = str(r.get("variant", "?"))
        buckets.setdefault(v, []).append(float(r.get("roas", 0)))
    return {v: round(sum(vs) / len(vs), 4) for v, vs in buckets.items()}


def _cac_estimate() -> float | None:
    """Compute CAC estimate from core memory events.

    Returns None when insufficient data is available.
    """
    try:
        from core.cac import estimate_cac
        from core.memory import get_memory
        events = get_memory()
        if not events:
            # Fall back to recent event_log rows
            events = _state.event_log.rows[-100:]
        cac = estimate_cac(events)
        return round(cac, 4) if cac else None
    except Exception:
        return None


# ── endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Replit uptime monitor / health check."""
    return {"ok": True}


@app.get("/status")
def status():
    """Lightweight status snapshot for polling."""
    uptime = round(time.time() - _started_at, 1)
    last = (
        datetime.fromtimestamp(_last_cycle_at, tz=timezone.utc).isoformat()
        if _last_cycle_at else None
    )
    return {
        "capital": round(_state.capital, 2),
        "regime": _state.regime,
        "detected_regime": _state.detected_regime,
        "energy": _state.energy,
        "event_count": len(_state.event_log.rows),
        "memory_size": len(_state.memory),
        "causal_edges": len(_state.graph.edges),
        "total_cycles": _state.total_cycles,
        "uptime_s": uptime,
        "last_cycle_at": last,
        "bg_running": _bg_running,
    }


@app.post("/cycle")
def cycle():
    """Trigger one manual cycle (useful for testing / Replit buttons)."""
    global _state, _last_cycle_at
    new_state = run_cycle(_state)
    with _lock:
        _state = new_state
        _last_cycle_at = time.time()
    return {
        "capital": round(_state.capital, 2),
        "total_cycles": _state.total_cycles,
        "event_count": len(_state.event_log.rows),
        "detected_regime": _state.detected_regime,
    }


@app.post("/runner/pause")
def pause_runner():
    """Pause the background cycle runner."""
    global _bg_running
    _bg_running = False
    return {"bg_running": False}


@app.post("/runner/resume")
def resume_runner():
    """Resume the background cycle runner if paused."""
    global _bg_running
    if not _bg_running:
        _bg_running = True
        threading.Thread(target=_background_runner, daemon=True).start()
    return {"bg_running": True}


@app.get("/decisions")
def decisions():
    """Top 5 ranked decisions with full prediction detail and human-readable reason."""
    top = decide(_state)[:5]
    budgets = budget_allocate(top)
    result = []
    for i, d in enumerate(top):
        pred = round(d.get("pred", 0), 4)
        pred_width = round(d.get("pred_width") or 0, 4)
        system_conf = round(d.get("system_conf") or 0, 4)
        interval_conf = round(d.get("interval_conf") or 0, 4)
        score = round(d["score"], 4)

        # Build human-readable decision explanation
        if pred >= 2.0 and system_conf >= 0.6 and interval_conf >= 0.6:
            reason = (
                f"Scaled: ROAS {pred} predicted with high confidence "
                f"(system={system_conf}, interval={interval_conf})"
            )
        elif pred < 1.0:
            reason = (
                f"Kill candidate: predicted ROAS {pred} below break-even "
                f"(score={score})"
            )
        elif pred_width > 1.0:
            reason = (
                f"Hold: high prediction uncertainty (width={pred_width}), "
                f"awaiting more data"
            )
        elif pred >= 1.5:
            reason = (
                f"Monitor/Scale: ROAS {pred} above threshold, "
                f"confidence={system_conf}"
            )
        else:
            reason = (
                f"Hold: moderate ROAS {pred}, insufficient confidence "
                f"(score={score})"
            )

        result.append({
            "action":        d["action"],
            "score":         score,
            "pred":          pred,
            "pred_lo":       round(d.get("pred_lo") or 0, 4),
            "pred_hi":       round(d.get("pred_hi") or 0, 4),
            "pred_width":    pred_width,
            "interval_conf": interval_conf,
            "system_conf":   system_conf,
            "budget":        round(budgets[i], 2),
            "reason":        reason,
        })
    return result


@app.get("/metrics")
def metrics():
    """Rich dashboard payload — all key metrics in one call."""
    rows = _state.event_log.rows
    recent = rows[-100:] if rows else []

    avg_roas = round(sum(r.get("roas", 0) for r in recent) / max(len(recent), 1), 4)
    slope = _roas_trend_slope(rows)
    capital_history = [
        round(_state.capital, 2)
    ]  # live capital; historical snapshots need DB

    # calibration
    cal_stats = cal.calibration_model.stats()

    # bandit rankings
    bandit_rankings = []
    for action_key, rewards in bu.bandit_memory.history.items():
        if rewards:
            bandit_rankings.append({
                "action": action_key,
                "avg_reward": round(float(np.mean(rewards)), 4),
                "count": len(rewards),
            })
    bandit_rankings.sort(key=lambda x: x["avg_reward"], reverse=True)

    # regime confidence
    reg_conf = round(rc.regime_confidence.confidence(), 4)

    # population diversity
    diversity = (
        round(structural_engine.population_diversity(), 4)
        if structural_engine.population else None
    )

    return {
        "avg_roas": avg_roas,
        "roas_trend_slope": slope,
        "capital": round(_state.capital, 2),
        "capital_gain": round(_state.capital - 1000.0, 2),
        "detected_regime": _state.detected_regime,
        "regime_confidence": reg_conf,
        "calibration": {
            "bias": round(cal_stats.get("bias", 0), 4),
            "uncertainty": round(cal_stats.get("uncertainty", 1), 4),
            "confidence_weight": round(cal.calibration_model.confidence_weight(), 4),
        },
        "variant_performance": _variant_avg(recent),
        "bandit_rankings": bandit_rankings[:5],
        "total_cycles": _state.total_cycles,
        "causal_edges": len(_state.graph.edges),
        "population_diversity": diversity,
        "event_count": len(rows),
        "cac_estimate": _cac_estimate(),
    }


@app.get("/events")
def events(limit: int = Query(default=200, ge=1, le=1000)):
    """
    Last `limit` event-log rows for chart rendering.
    Reads from in-memory event log; columns: id, roas, prediction, error,
    cost, revenue, env_regime, env_trend, pred_width, interval_conf.
    """
    rows = _state.event_log.rows[-limit:]
    keep = {
        "roas", "prediction", "error", "cost", "revenue",
        "env_regime", "env_trend", "pred_width", "interval_conf",
        "roas_6h", "roas_12h", "roas_24h", "variant",
    }
    result = []
    for i, r in enumerate(rows):
        row = {k: v for k, v in r.items() if k in keep}
        row["idx"] = i
        result.append(row)
    return result


@app.get("/budget")
def budget():
    """Latest CVXPY budget allocation across the top 5 decisions."""
    top = decide(_state)[:5]
    budgets = budget_allocate(top)
    return [
        {
            "variant": d["action"].get("variant"),
            "budget": round(budgets[i], 2),
            "pred": round(d.get("pred", 0), 4),
            "pred_width": round(d.get("pred_width") or 0, 4),
        }
        for i, d in enumerate(top)
    ]


@app.get("/causal")
def causal():
    """Causal graph edges sorted by Granger weight."""
    return [
        {"from": p, "to": c, "weight": round(w, 4)}
        for (p, c), w in sorted(
            _state.graph.edges.items(), key=lambda x: abs(x[1]), reverse=True
        )
    ]


@app.get("/drift")
def drift():
    """Latest Evidently drift report JSON, if available."""
    for candidate in ["drift_report.json", "state/drift_report.json"]:
        if os.path.exists(candidate):
            try:
                with open(candidate) as f:
                    return json.load(f)
            except Exception:
                break
    return {"available": False}


@app.get("/memory")
def memory():
    """Last 20 learning memory rows."""
    recent = _state.memory[-20:]
    return [
        {k: round(v, 4) if isinstance(v, float) else v for k, v in r.items()}
        for r in recent
    ]


@app.get("/agent-metrics")
def agent_metrics():
    """Per-agent PnL, decision counts, and drift status."""
    try:
        from backend.agents.agent_metrics import agent_metrics_registry
        return {"agents": agent_metrics_registry.snapshot()}
    except Exception:
        return {"agents": []}


@app.get("/portfolio")
def portfolio():
    """ROAS-weighted budget allocation across active products/variants."""
    try:
        from backend.decision.portfolio_engine import get_allocations, top_products
        return {
            "allocations": get_allocations(),
            "top_products": top_products(n=5),
        }
    except Exception:
        return {"allocations": {}, "top_products": []}


@app.get("/opportunities")
def opportunities(limit: int = Query(default=20, ge=1, le=100)):
    """Ranked product opportunities from the live simulation layer.

    Returns the current top-N candidates scored by the simulation engine,
    enriched with:
      - simulation rank score and corrected ROAS prediction
      - playbook confidence and evidence count
      - calibration status (are predictions reliable for this product?)
      - suggested top hooks and angles from PatternStore

    Designed for operational decision-making: highest rank_score products
    are the best candidates for content generation and campaign launch.
    """
    try:
        from simulation.engine import simulation_engine
        from core.content.patterns import pattern_store
        from core.content.playbook import playbook_memory
        from simulation.calibration import calibration_store
        from core.signals import signal_engine

        signals = signal_engine.get()
        patterns = pattern_store.get_patterns()
        all_pbs  = {p.product: vars(p) for p in playbook_memory.all()}

        ranked = simulation_engine.score_signals(
            signals[:30],
            patterns=patterns,
            playbooks=all_pbs,
        )

        cal_summary = calibration_store.summary()
        by_product  = cal_summary.get("by_product", {})

        results = []
        for r in ranked[:limit]:
            pb = all_pbs.get(r.product, {})
            product_cal = by_product.get(r.product, {})
            results.append({
                "rank":              r.rank,
                "product":           r.product,
                "rank_score":        round(r.rank_score, 4),
                "predicted_roas":    round(r.predicted_roas, 4),
                "corrected_roas":    round(r.corrected_roas, 4),
                "predicted_ctr":     round(r.predicted_ctr, 4),
                "confidence":        round(r.confidence, 4),
                "risk_score":        round(r.risk_score, 4),
                # Playbook context
                "playbook_confidence": round(float(pb.get("confidence", 0.0)), 4),
                "evidence_count":      int(pb.get("evidence_count", 0)),
                "top_hooks":           pb.get("top_hooks", [])[:3],
                "top_angles":          pb.get("top_angles", [])[:3],
                # Calibration readiness
                "calibrated":          product_cal.get("n", 0) >= 5,
                "calibration_records": product_cal.get("n", 0),
                # Action priority: corrected_roas * confidence / (1 + risk)
                "action_priority": round(
                    r.corrected_roas * r.confidence / max(1.0 + r.risk_score, 0.01), 4
                ),
            })

        results.sort(key=lambda x: x["action_priority"], reverse=True)
        return {
            "count":        len(results),
            "calibrated":   cal_summary.get("ready", False),
            "top_hooks":    patterns.get("top_hooks", [])[:5],
            "top_angles":   patterns.get("top_angles", [])[:5],
            "opportunities": results,
        }
    except Exception as exc:
        return {"count": 0, "opportunities": [], "error": str(exc)}


# ── UPOS compatibility routes (optional — imported only when present) ──────────

try:
    from api.control import router as _control_router
    from api.dashboard import router as _dashboard_router
    app.include_router(_control_router, prefix="/control")
    app.include_router(_dashboard_router, prefix="/dashboard")
except ImportError:
    pass

try:
    from api.pods import router as _pods_router
    app.include_router(_pods_router, prefix="/pods-v2")
except ImportError:
    pass


# ── observability endpoints ───────────────────────────────────────────────────

@app.get("/metrics/prometheus", response_class=PlainTextResponse)
def prometheus_metrics():
    """Prometheus scrape endpoint — exposes all registered metrics."""
    if not _PROMETHEUS_OK:
        return PlainTextResponse("# prometheus_client not installed\n", media_type="text/plain")
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/phase")
def phase_status():
    """Current lifecycle phase and promotion KPIs."""
    try:
        from core.system.phase_controller import phase_controller
        from core.system.resource_allocator import resource_allocator
        status = phase_controller.status()
        alloc  = resource_allocator.describe(
            phase_controller.current,
            total_budget=500.0,
        )
        return {"phase": status, "allocation": alloc}
    except Exception:
        return {"phase": {"phase": "RESEARCH"}, "allocation": {}}


# ── Phase 2 connector endpoints ───────────────────────────────────────────────

@app.get("/macro")
def macro():
    """Latest FRED macro signals (falls back to static stubs when key absent)."""
    from connectors.macro_signals import get_macro_signals
    try:
        return get_macro_signals()
    except Exception:
        return {"error": "macro signals unavailable"}


@app.get("/replay_buffer")
def replay_buffer_stats():
    """Replay buffer size and readiness."""
    from backend.learning.replay_buffer import replay_buffer as _rb
    return {
        "size": len(_rb),
        "capacity": _rb.capacity,
        "ready": _rb.is_ready(),
    }


@app.get("/bandit")
def bandit_status():
    """LinUCB contextual bandit arm registry (arm names only)."""
    from backend.learning.contextual_bandit import bandit_instance
    b = bandit_instance()
    return {"arms": b.arms, "alpha": b.alpha}


@app.get("/snapshot")
def snapshot():
    """Full runtime snapshot — used by dashboard on initial load before WS connects."""
    try:
        from backend.runtime.state import build_snapshot
        with _lock:
            snap = build_snapshot(_state)
        return snap.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/runtime/tasks")
def runtime_tasks():
    """Live task inventory: all loops, schedulers, Celery tasks, queues, WS emitters,
    and state writers with their current status and heartbeat timestamps."""
    try:
        from backend.runtime.task_inventory import task_registry
        return {
            "summary": task_registry.summary(),
            "live_threads": task_registry.live_threads(),
            "tasks": task_registry.all(),
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/playbook")
def get_playbook(product: str = None):
    """Return stored playbooks and content patterns. Filter by ?product= if desired."""
    try:
        from core.content.playbook import playbook_memory
        from core.content.patterns import pattern_store
        playbooks = playbook_memory.all()
        if product:
            pb = playbook_memory.get(product)
            playbooks = [pb] if pb else []
        return {
            "playbooks": [vars(p) for p in playbooks],
            "patterns":  pattern_store.get_patterns(),
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/ajo/apply")
def ajo_apply(campaign_id: str, action: str, budget_multiplier: float = 1.5):
    """Apply a MarketOS action (pause/scale/hold) to an Adobe AJO campaign."""
    from connectors.adobe_ajo_connector import apply_decision
    try:
        return apply_decision(campaign_id, action, budget_multiplier)
    except Exception:
        return {"error": "AJO action failed", "campaign_id": campaign_id}


# ── Step 41: Real-Time Dashboard Endpoints ────────────────────────────────────

# Window constants for event-log slicing
_RECENT_ROWS_WINDOW = 200       # general short-term window (~20 min at 6 s/cycle)
_ROWS_PER_48H = 48 * 60 * 10   # 48 h at 10 cycles/min (6 s/cycle) = 28 800 rows

# Mock data store for manual campaign overrides (in-memory)
_campaign_overrides: dict[str, str] = {}

_MOCK_CAMPAIGNS = [
    {
        "campaign_id": "camp_us_001",
        "geo": "US",
        "roas": 2.7,
        "spend": 450.0,
        "revenue": 1215.0,
        "ctr": 0.023,
        "cpc": 0.45,
        "conversion_rate": 0.031,
        "status": "scale",
        "current_budget": 500.0,
    },
    {
        "campaign_id": "camp_uk_002",
        "geo": "UK",
        "roas": 1.8,
        "spend": 220.0,
        "revenue": 396.0,
        "ctr": 0.018,
        "cpc": 0.62,
        "conversion_rate": 0.021,
        "status": "hold",
        "current_budget": 250.0,
    },
    {
        "campaign_id": "camp_ca_003",
        "geo": "CA",
        "roas": 0.8,
        "spend": 180.0,
        "revenue": 144.0,
        "ctr": 0.011,
        "cpc": 0.91,
        "conversion_rate": 0.012,
        "status": "kill",
        "current_budget": 200.0,
    },
    {
        "campaign_id": "camp_au_004",
        "geo": "AU",
        "roas": 3.1,
        "spend": 310.0,
        "revenue": 961.0,
        "ctr": 0.031,
        "cpc": 0.38,
        "conversion_rate": 0.041,
        "status": "scale",
        "current_budget": 400.0,
    },
    {
        "campaign_id": "camp_de_005",
        "geo": "DE",
        "roas": 1.4,
        "spend": 95.0,
        "revenue": 133.0,
        "ctr": 0.014,
        "cpc": 0.75,
        "conversion_rate": 0.018,
        "status": "hold",
        "current_budget": 100.0,
    },
]

_MOCK_GEO = [
    {"country": "US", "roas": 2.7, "spend": 450.0, "revenue": 1215.0, "status": "scaling"},
    {"country": "UK", "roas": 1.8, "spend": 220.0, "revenue": 396.0,  "status": "testing"},
    {"country": "CA", "roas": 0.8, "spend": 180.0, "revenue": 144.0,  "status": "paused"},
    {"country": "AU", "roas": 3.1, "spend": 310.0, "revenue": 961.0,  "status": "scaling"},
    {"country": "DE", "roas": 1.4, "spend": 95.0,  "revenue": 133.0,  "status": "testing"},
    {"country": "FR", "roas": 2.0, "spend": 140.0, "revenue": 280.0,  "status": "testing"},
]

_MOCK_ACCOUNTS = [
    {
        "account_id": "acct_001",
        "name": "Primary TikTok",
        "status": "scaling",
        "spend": 1055.0,
        "risk_flags": [],
    },
    {
        "account_id": "acct_002",
        "name": "Backup TikTok",
        "status": "warm",
        "spend": 250.0,
        "risk_flags": ["new_account"],
    },
    {
        "account_id": "acct_003",
        "name": "EU TikTok",
        "status": "restricted",
        "spend": 95.0,
        "risk_flags": ["policy_review", "spend_limited"],
    },
]

_MOCK_CREATIVES = {
    "hooks_ranking": [
        {"hook": "Stop scrolling — this changed my life", "roas": 3.2, "ctr": 0.041, "views": 48200},
        {"hook": "I was skeptical until I tried this",   "roas": 2.9, "ctr": 0.036, "views": 39100},
        {"hook": "The secret nobody tells you about",    "roas": 2.4, "ctr": 0.029, "views": 31500},
        {"hook": "POV: you finally found the solution",  "roas": 2.1, "ctr": 0.025, "views": 27800},
        {"hook": "Why are people obsessed with this?",   "roas": 1.7, "ctr": 0.019, "views": 21200},
    ],
    "clip_performance": [
        {"clip_id": "clip_001", "roas": 3.1, "spend": 210.0, "revenue": 651.0,  "views": 45000},
        {"clip_id": "clip_002", "roas": 2.7, "spend": 180.0, "revenue": 486.0,  "views": 38000},
        {"clip_id": "clip_003", "roas": 1.9, "spend": 120.0, "revenue": 228.0,  "views": 24000},
        {"clip_id": "clip_004", "roas": 0.9, "spend": 90.0,  "revenue": 81.0,   "views": 15000},
    ],
    "sequence_performance": [
        {"sequence": "hook→demo→cta",    "avg_roas": 3.0, "completion_rate": 0.72},
        {"sequence": "hook→social→cta",  "avg_roas": 2.6, "completion_rate": 0.65},
        {"sequence": "problem→solution", "avg_roas": 2.2, "completion_rate": 0.58},
    ],
    "variant_leaderboard": [],
}


@app.get("/campaigns")
def campaigns():
    """Campaign performance table with ROAS, spend, status, and geo filters."""
    rows = _state.event_log.rows
    recent = rows[-_RECENT_ROWS_WINDOW:] if rows else []

    # Enrich mock campaigns with live avg ROAS from event log if available
    live_avg_roas: float | None = (
        round(sum(r.get("roas", 0) for r in recent) / len(recent), 4)
        if recent else None
    )

    result = []
    for c in _MOCK_CAMPAIGNS:
        entry = dict(c)
        # Apply any manual overrides
        override = _campaign_overrides.get(c["campaign_id"])
        if override:
            entry["status"] = override
            entry["override"] = True
        else:
            entry["override"] = False
        # Attach live system avg_roas as a reference
        if live_avg_roas is not None:
            entry["system_avg_roas"] = live_avg_roas
        result.append(entry)

    return result


@app.post("/campaigns/{campaign_id}/override")
def campaign_override(campaign_id: str, action: str):
    """Manual override for a campaign: scale | pause | kill."""
    allowed = {"scale", "pause", "kill", "hold"}
    if action not in allowed:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"action must be one of {allowed}")
    _campaign_overrides[campaign_id] = action
    return {"campaign_id": campaign_id, "status": action, "overridden": True}


@app.get("/creatives")
def creatives():
    """Creative performance: hooks ranking, clip ROAS, sequence performance, variant leaderboard."""
    rows = _state.event_log.rows
    recent = rows[-_RECENT_ROWS_WINDOW:] if rows else []

    # Build live variant leaderboard from event log
    variant_buckets: dict[str, list[float]] = {}
    for r in recent:
        v = str(r.get("variant", ""))
        if v:
            variant_buckets.setdefault(v, []).append(float(r.get("roas", 0)))
    leaderboard = sorted(
        [
            {"variant": v, "avg_roas": round(sum(vs) / len(vs), 4), "count": len(vs)}
            for v, vs in variant_buckets.items()
        ],
        key=lambda x: x["avg_roas"],
        reverse=True,
    )

    payload = dict(_MOCK_CREATIVES)
    payload["variant_leaderboard"] = leaderboard or payload["variant_leaderboard"]
    return payload


@app.get("/risk")
def risk():
    """Risk monitoring panel: alerts, drawdown, anomaly flags, system health."""
    rows = _state.event_log.rows
    recent_48h = rows[-_ROWS_PER_48H:] if rows else []

    # Drawdown from event-log capital proxy
    capital = _state.capital
    from core.risk.drawdown import DrawdownProtector
    dp = DrawdownProtector()
    for r in rows:
        rev = float(r.get("revenue", 0))
        dp.update(rev)
    drawdown_pct = round(dp.drawdown(capital), 4)

    # ROAS over last 48 h
    roas_48h_values = [float(r.get("roas", 0)) for r in recent_48h]
    avg_roas_48h = (
        round(sum(roas_48h_values) / len(roas_48h_values), 4) if roas_48h_values else 0.0
    )

    # Anomaly detection on ROAS
    from core.risk.anomaly import AnomalyDetector
    ad = AnomalyDetector()
    all_roas = [float(r.get("roas", 0)) for r in rows]
    for v in all_roas[:-1]:
        ad.update(v)
    latest_roas = all_roas[-1] if all_roas else 0.0
    is_anomaly = ad.is_anomaly(latest_roas) if all_roas else False

    alerts = []
    if drawdown_pct > 0.30:
        alerts.append({
            "level": "critical",
            "color": "red",
            "message": f"Drawdown {round(drawdown_pct * 100, 1)}% exceeds 30% threshold",
            "metric": "drawdown",
        })
    if avg_roas_48h < 1.0 and roas_48h_values:
        alerts.append({
            "level": "critical",
            "color": "red",
            "message": f"ROAS {avg_roas_48h} below 1.0 over last 48 h — review campaigns",
            "metric": "roas_48h",
        })
    if is_anomaly:
        alerts.append({
            "level": "warning",
            "color": "yellow",
            "message": f"ROAS anomaly detected: latest value {round(latest_roas, 4)}",
            "metric": "anomaly",
        })

    # System health colour
    if any(a["color"] == "red" for a in alerts):
        health = "critical"
    elif alerts:
        health = "warning"
    else:
        health = "healthy"

    return {
        "system_health": health,
        "drawdown_pct": drawdown_pct,
        "avg_roas_48h": avg_roas_48h,
        "anomaly_detected": is_anomaly,
        "alerts": alerts,
    }


@app.get("/geo")
def geo():
    """Geo performance: ROAS per country, spend distribution, expansion status."""
    rows = _state.event_log.rows
    recent = rows[-_RECENT_ROWS_WINDOW:] if rows else []

    # Compute live system-wide avg ROAS as a reference
    live_avg: float | None = (
        round(sum(r.get("roas", 0) for r in recent) / len(recent), 4)
        if recent else None
    )

    result = [dict(g) for g in _MOCK_GEO]
    if live_avg is not None:
        for entry in result:
            entry["system_avg_roas"] = live_avg
    return result


@app.get("/accounts")
def accounts():
    """Account health: status, spend per account, risk flags."""
    return list(_MOCK_ACCOUNTS)


@app.get("/alerts")
def alerts():
    """Real-time alerts across all sub-systems with severity levels."""
    # Delegate to the /risk endpoint logic and aggregate
    risk_data = risk()
    base_alerts = list(risk_data.get("alerts", []))

    # Additional alert: pacing (check capital vs expected)
    rows = _state.event_log.rows
    recent = rows[-20:] if rows else []
    if recent:
        avg_cost = sum(float(r.get("cost", r.get("spend", 0))) for r in recent) / len(recent)
        if avg_cost > 50:
            base_alerts.append({
                "level": "warning",
                "color": "yellow",
                "message": f"Pacing alert: avg cycle cost {round(avg_cost, 2)} may exceed budget",
                "metric": "pacing",
            })

    return {
        "count": len(base_alerts),
        "system_health": risk_data.get("system_health", "healthy"),
        "alerts": base_alerts,
    }


# ── Step 52: Production Hardening + Agent Hierarchy ───────────────────────────

# Module-level singletons for Step 52 features
from core.risk.global_risk_engine import global_risk_engine as _global_risk_engine
from backend.agents.agent_metrics import agent_metrics_registry as _agent_metrics
from backend.learning.world_model_calibration import world_model_calibrator as _wm_calibrator
from agents.hierarchy import ScalingAgent, GeoAgent, AudienceAgent, RiskAgent
from backend.execution.loop import TOTAL_CYCLE_BUDGET

_scaling_agent = ScalingAgent()
_geo_agent = GeoAgent()
_audience_agent = AudienceAgent()
_risk_agent = RiskAgent()


def _current_peak_capital() -> float:
    """Read the peak capital tracked by the execution loop (falls back to current capital)."""
    return getattr(_state, "_peak_capital", _state.capital)


@app.get("/agents")
def agent_performance():
    """Agent performance panel: decisions, PnL, and drift detection per agent."""
    rows = _state.event_log.rows
    recent = rows[-_RECENT_ROWS_WINDOW:] if rows else []

    # Run agents against the latest window to record live decisions
    if recent:
        avg_roas = sum(r.get("roas", 0) for r in recent) / len(recent)
        avg_ctr = sum(r.get("ctr", 0) for r in recent) / len(recent)
        avg_cvr = sum(r.get("cvr", 0) for r in recent) / len(recent)

        scaling_dec = _scaling_agent.decide({"roas": avg_roas, "current_budget": TOTAL_CYCLE_BUDGET})
        geo_dec = _geo_agent.decide({"country": "system", "roas": avg_roas})
        audience_dec = _audience_agent.decide({"ctr": avg_ctr, "cvr": avg_cvr})
        risk_input = {
            "current_capital": _state.capital,
            "peak_capital": _current_peak_capital(),
            "today_spend": _global_risk_engine.today_spend(),
            "roas": avg_roas,
            "kill_switch": _global_risk_engine.kill_switch_active,
        }
        risk_dec = _risk_agent.decide(risk_input)

        for dec in [scaling_dec, geo_dec, audience_dec, risk_dec]:
            _agent_metrics.record_decision(dec.agent, dec.action)

    return {
        "agents": _agent_metrics.snapshot(),
        "risk_status": _global_risk_engine.status(),
    }


@app.get("/risk/status")
def risk_engine_status():
    """Global risk engine status: kill-switch, daily spend, drawdown caps."""
    return _global_risk_engine.status()


@app.post("/risk/killswitch/activate")
def activate_kill_switch(reason: str = "manual"):
    """Activate the global kill-switch — halts all new spend immediately."""
    _global_risk_engine.activate_kill_switch(reason=reason)
    return {"kill_switch_active": True, "reason": reason}


@app.post("/risk/killswitch/deactivate")
def deactivate_kill_switch():
    """Deactivate the global kill-switch — resumes normal operation."""
    _global_risk_engine.deactivate_kill_switch()
    return {"kill_switch_active": False}


@app.get("/capital_allocation")
def capital_allocation():
    """Capital allocation view: portfolio split and risk-adjusted budgets."""
    top = decide(_state)[:5]
    budgets = budget_allocate(top)

    total = sum(budgets) or 1.0
    result = []
    for i, d in enumerate(top):
        raw_budget = budgets[i]
        # enforce through global risk engine
        override = _global_risk_engine.enforce(
            proposed_budget=raw_budget,
            current_capital=_state.capital,
            peak_capital=_current_peak_capital(),
        )
        safe_budget = override.adjusted_budget if override.allowed else 0.0
        result.append({
            "variant": d["action"].get("variant"),
            "raw_budget": round(raw_budget, 2),
            "safe_budget": round(safe_budget, 2),
            "allocation_pct": round(raw_budget / total * 100, 2),
            "risk_override": override.triggered_cap != "" or not override.allowed,
            "risk_reason": override.reason,
            "pred": round(d.get("pred", 0), 4),
        })

    return {
        "total_budget": round(total, 2),
        "risk_status": _global_risk_engine.status(),
        "allocations": result,
    }


@app.get("/prediction_errors")
def prediction_errors(limit: int = Query(default=100, ge=1, le=500)):
    """Prediction error chart: recent (predicted, actual, error) pairs with calibration stats."""
    errors = _wm_calibrator.prediction_errors()[-limit:]
    stats = _wm_calibrator.stats()
    return {
        "errors": errors,
        "calibration": stats,
        "total_updates": _wm_calibrator.total_updates,
    }


# ── TikTok Ads endpoints ─────────────────────────────────────────────────────

@app.post("/tiktok/launch")
def tiktok_launch(product: str, phase: str = "EXPLORE"):
    """Launch a TikTok campaign from the best playbook for this product.
    Safe: defaults to dry-run mode. Set TIKTOK_DRY_RUN=false to go live.
    """
    try:
        from backend.integrations.tiktok_ads import launch_from_playbook
        from core.content.playbook import playbook_memory
        pb = playbook_memory.get(product)
        if not pb:
            return {"status": "error", "reason": "no_playbook", "product": product}
        return launch_from_playbook(vars(pb), phase=phase)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@app.get("/tiktok/roas")
def tiktok_roas_report():
    """Fetch latest ROAS from TikTok reporting API (or simulated in dry-run)."""
    try:
        from backend.integrations.tiktok_ads import fetch_roas
        # Real: pull active campaign IDs from portfolio engine
        try:
            from backend.decision.portfolio_engine import top_products
            products = top_products(n=10)
            cids = [str(p.get("product_id", "")) for p in products if p.get("product_id")]
        except Exception:
            cids = []
        if not cids:
            cids = ["demo_campaign"]
        roas_map = fetch_roas(cids)
        return {"roas": roas_map, "campaign_count": len(cids)}
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/tiktok/check")
def tiktok_check_and_act(campaign_id: str, spend: float, budget: float, roas: float):
    """Run anomaly check on a campaign: kill if overspend+bad ROAS, scale if win streak."""
    try:
        from backend.integrations.tiktok_ads import check_and_act
        action = check_and_act(campaign_id, spend, budget, roas)
        return {"campaign_id": campaign_id, "action": action}
    except Exception as exc:
        return {"error": str(exc)}


# ── Simulation layer ───────────────────────────────────────────────────────────

@app.get("/simulation/scores")
def simulation_scores(limit: int = 20):
    """Return top-ranked simulation scores from the most recent scoring run."""
    try:
        from simulation.engine import simulation_engine
        from core.signals import signal_engine as _sig
        from core.content.patterns import pattern_store
        from core.content.playbook import playbook_memory

        patterns = pattern_store.get_patterns()
        all_playbooks = {p.product: p for p in playbook_memory.all()}
        signals = _sig.get()[:limit]
        ranked = simulation_engine.score_signals(
            signals,
            patterns=patterns,
            playbooks=all_playbooks,
        )
        return {
            "scores": [r.to_dict() for r in ranked],
            "total": len(ranked),
            "model_info": simulation_engine.report().get("model", {}),
        }
    except Exception as exc:
        return {"error": str(exc), "scores": []}


@app.get("/simulation/report")
def simulation_report():
    """Return simulation layer health: calibration stats, model info, replay row count."""
    try:
        from simulation.engine import simulation_engine
        return simulation_engine.report()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/simulation/calibration")
def simulation_calibration():
    """Return prediction-vs-reality calibration audit (MAE, RMSE, bias, per-product)."""
    try:
        from simulation.calibration import calibration_store
        return calibration_store.summary()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/runtime/state")
def runtime_state():
    """Return full canonical RuntimeState as JSON."""
    try:
        from backend.runtime.state import build_runtime_state
        rs = build_runtime_state(_state)
        return rs.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


# ── Phase 5: observability + topology endpoints ───────────────────────────────

@app.get("/observability/snapshot")
def observability_snapshot(workspace: str = "default"):
    """Full CognitionSnapshot for the given workspace."""
    try:
        from backend.observability.exporters import cognition_json
        return cognition_json(workspace=workspace)
    except Exception as exc:
        return {"error": str(exc), "workspace": workspace}


@app.get("/observability/entropy")
def observability_entropy(workspace: str = "default"):
    """Current entropy report for the workspace."""
    try:
        from backend.observability.exporters import entropy_json
        return entropy_json(workspace=workspace)
    except Exception as exc:
        return {"error": str(exc), "workspace": workspace}


@app.get("/observability/traces")
def observability_traces(n: int = 20):
    """Last n completed traces."""
    try:
        from backend.observability.exporters import recent_traces_json
        return recent_traces_json(n=n)
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/topology")
def topology(workspace: str = "default"):
    """Full topology snapshot for the workspace."""
    try:
        from backend.runtime.topology.topology_snapshot import capture_topology_snapshot
        return capture_topology_snapshot(workspace=workspace).to_dict()
    except Exception as exc:
        return {"error": str(exc), "workspace": workspace}


@app.get("/topology/cognition")
def topology_cognition(workspace: str = "default"):
    """High-level cognitive state map: topology + entropy + heatmap."""
    try:
        from backend.runtime.topology.cognition_map import cognition_map
        return cognition_map(workspace=workspace)
    except Exception as exc:
        return {"error": str(exc), "workspace": workspace}


@app.get("/topology/entropy")
def topology_entropy(workspace: str = "default"):
    """Per-node-type entropy overlay for the workspace."""
    try:
        from backend.runtime.topology.entropy_map import entropy_overlay
        return entropy_overlay(workspace=workspace)
    except Exception as exc:
        return {"error": str(exc), "workspace": workspace}


@app.get("/governance/schemas")
def governance_schemas():
    """Return all registered schema versions."""
    try:
        from backend.contracts.governance.registry import get_governance_registry
        return get_governance_registry().to_dict()
    except Exception as exc:
        return {"error": str(exc)}


# ── WebSocket live event stream ────────────────────────────────────────────────

try:
    from fastapi import WebSocket as _WebSocket
    from api.ws import event_stream as _ws_event_stream

    @app.websocket("/ws")
    async def websocket_endpoint(ws: _WebSocket):
        """Live event stream. Pushes cycle/signal/worker/feedback events as JSON frames."""
        await _ws_event_stream(ws)

except ImportError:
    pass

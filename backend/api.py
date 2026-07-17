"""
MarketOS v4 — FastAPI backend
Serves the Replit market UI frontend.

Environment variables (set in Replit Secrets):
  PORT               Web server port (default 8000; Replit sets this automatically)
  STATE_PATH         DuckDB file (default state/state.db)
  ALLOWED_ORIGINS    Comma-separated CORS origins (default "*")
  CYCLES_PER_MINUTE  Background runner speed (default 10 → one cycle / 6 s)

Route handlers live in api/routes/*.py (health, cycle_control, decisions,
metrics, portfolio, observability, dashboard_panels, agents_risk, tiktok,
simulation) — this file owns app setup, the background runner, and the
shared mutable state (_state, _lock, _bg_running, ...) those route modules
read/write via ``import backend.api as _core`` + qualified attribute
access. Several handlers reassign _state/_bg_running with ``global``;
route modules must always go through ``_core._state`` (never a
destructured ``from backend.api import _state``) so they see the current
value instead of the one that existed at import time.
"""
import logging
import os
import threading
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    from prometheus_client import Counter, Gauge, Histogram
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


# ── helpers (used by api.routes.metrics via _core.<name>) ────────────────────

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


# ── Step 52: Production Hardening + Agent Hierarchy singletons ───────────────
# (used by api.routes.agents_risk and api.routes.decisions via _core.<name>)

from core.risk.global_risk_engine import global_risk_engine as _global_risk_engine
from backend.agents.agent_metrics import agent_metrics_registry as _agent_metrics
from backend.learning.world_model_calibration import world_model_calibrator as _wm_calibrator
from agents.hierarchy import ScalingAgent, GeoAgent, AudienceAgent, RiskAgent

_scaling_agent = ScalingAgent()
_geo_agent = GeoAgent()
_audience_agent = AudienceAgent()
_risk_agent = RiskAgent()


def _current_peak_capital() -> float:
    """Read the peak capital tracked by the execution loop (falls back to current capital)."""
    return getattr(_state, "_peak_capital", _state.capital)


# ── Step 41 mock data (used by api.routes.dashboard_panels via _core.<name>) ─
# Fixture data for dashboard panels not yet backed by a live data source.

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


# ── route modules ─────────────────────────────────────────────────────────────
# Each import happens after every _core.<name> a route module might reference
# is already defined above. Handlers only touch _core.<name> at call time
# (never at import time), so the actual order here is not load-bearing —
# it's kept late for readability, matching where these endpoints used to live.

from api.routes import (
    health as _r_health,
    cycle_control as _r_cycle_control,
    decisions as _r_decisions,
    metrics as _r_metrics,
    portfolio as _r_portfolio,
    observability as _r_observability,
    dashboard_panels as _r_dashboard_panels,
    agents_risk as _r_agents_risk,
    tiktok as _r_tiktok,
    simulation as _r_simulation,
    orchestration as _r_orchestration,
)

app.include_router(_r_health.router)
app.include_router(_r_cycle_control.router)
app.include_router(_r_decisions.router)
app.include_router(_r_metrics.router)
app.include_router(_r_portfolio.router)
app.include_router(_r_observability.router)
app.include_router(_r_dashboard_panels.router)
app.include_router(_r_agents_risk.router)
app.include_router(_r_tiktok.router)
app.include_router(_r_simulation.router)
app.include_router(_r_orchestration.router)


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

try:
    from api.dropship_dashboard import router as _dropship_router
    app.include_router(_dropship_router, prefix="/api/dropship")
except ImportError:
    pass

try:
    from api.credentials_setup import router as _credentials_router
    app.include_router(_credentials_router, prefix="/api/setup")
except ImportError:
    pass


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

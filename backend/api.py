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
import json
import hashlib
import hmac
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import numpy as np
from fastapi import Body, FastAPI, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

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
    _prom_webhook_events = Counter("marketos_integration_webhook_events_total", "Sidecar webhook events by outcome", ["source", "outcome"])
    _prom_integration_configured = Gauge("marketos_integration_configured", "Configured optional integrations", ["integration"])
    _prom_integration_reachable = Gauge("marketos_integration_reachable", "Reachable optional integrations", ["integration"])
    _prom_integration_probe_duration = Histogram("marketos_integration_health_probe_duration_seconds", "Optional integration health probe duration", ["integration"])
    _prom_integration_probes = Counter("marketos_integration_health_probes_total", "Optional integration health probes by outcome", ["integration", "outcome"])
    _PROMETHEUS_OK   = True
except ImportError:
    _PROMETHEUS_OK = False
    _prom_webhook_events = None
    _prom_integration_configured = _prom_integration_reachable = _prom_integration_probe_duration = _prom_integration_probes = None

from backend.core.state import SystemState
from backend.execution.loop import run_cycle

# ── config ────────────────────────────────────────────────────────────────────

STATE_PATH = os.getenv("STATE_PATH", "state/state.db")
_CYCLES_PER_MINUTE = max(1, int(os.getenv("CYCLES_PER_MINUTE", "10")))
_INTEGRATION_HEALTH_TTL_S = max(1.0, float(os.getenv("MARKETOS_INTEGRATION_HEALTH_TTL_S", "30")))
_integration_health_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_integration_health_lock = threading.Lock()

# When ORCHESTRATOR_HANDLES_CYCLES=true the background runner skips run_cycle()
# and only publishes the current snapshot. Set this when orchestrator/main.py
# is deployed alongside the API to prevent double-execution of the same state.
_ORCHESTRATOR_HANDLES_CYCLES = (
    os.getenv("ORCHESTRATOR_HANDLES_CYCLES", "false").lower() == "true"
)

# ── app ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(_: FastAPI):
    """Start and stop MarketOS runtime services with the FastAPI app."""
    global _state, _bg_running, _runtime_services_ready
    try:
        from backend.observability.sentry_init import init_sentry
        init_sentry(component="api")
    except Exception:
        pass
    from backend.core.serializer import load, save

    loaded = load(STATE_PATH)
    if loaded:
        _state = loaded

    _bg_running = True
    _runtime_services_ready = False
    threading.Thread(target=_background_runner, daemon=True).start()
    threading.Thread(target=_research_runner, daemon=True).start()
    _start_runtime_services()
    _runtime_services_ready = True
    try:
        yield
    finally:
        _bg_running = False
        _runtime_services_ready = False
        _stop_runtime_services()
        try:
            save(_state, STATE_PATH)
        except Exception:
            pass


app = FastAPI(title="MarketOS v4", version="4.0.0", lifespan=_lifespan)

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
_runtime_services_ready = False
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


def _start_runtime_services() -> None:
    try:
        from backend.contracts.registry import get_registry
        get_registry().hydrate_from_replay()
    except Exception:
        pass

    try:
        from backend.runtime.task_inventory import start_heartbeat_broadcaster
        start_heartbeat_broadcaster(interval_s=30.0)
    except Exception:
        pass

    try:
        from backend.runtime.sleep.replay_scheduler import get_scheduler
        get_scheduler().start()
    except Exception:
        pass


def _stop_runtime_services() -> None:
    try:
        from backend.runtime.task_inventory import stop_heartbeat_broadcaster
        stop_heartbeat_broadcaster()
    except Exception:
        pass

    try:
        from backend.runtime.sleep.replay_scheduler import get_scheduler
        get_scheduler().stop()
    except Exception:
        pass


def _public_sleep_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "cycle_id"):
        errors = list(getattr(result, "errors", []) or [])
        return {
            "cycle_id": getattr(result, "cycle_id", ""),
            "workspace": getattr(result, "workspace", "default"),
            "started_at": getattr(result, "started_at", 0.0),
            "finished_at": getattr(result, "finished_at", 0.0),
            "duration_s": getattr(result, "duration_s", 0.0),
            "episodes_read": getattr(result, "episodes_read", 0),
            "episodes_compacted": getattr(result, "episodes_compacted", 0),
            "semantic_units_created": getattr(result, "semantic_units_created", 0),
            "semantic_units_pruned": getattr(result, "semantic_units_pruned", 0),
            "procedures_reinforced": getattr(result, "procedures_reinforced", 0),
            "procedures_deprecated": getattr(result, "procedures_deprecated", 0),
            "lineage_nodes_summarized": getattr(result, "lineage_nodes_summarized", 0),
            "vectors_indexed": getattr(result, "vectors_indexed", 0),
            "compression_ratio": getattr(result, "compression_ratio", 0.0),
            "decay_applied": getattr(result, "decay_applied", False),
            "error_count": len(errors),
            "ok": not errors,
        }
    return {"result": result}


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

@app.get("/integrations/health")
def integrations_health():
    """Expose optional OSS adapter health without making any adapter mandatory."""
    return {"integrations": _integration_health_snapshot(force=True)}


def _integration_health_snapshot(*, force: bool = False) -> dict[str, dict[str, Any]]:
    """Probe optional adapters with bounded cache and export safe metric labels."""
    from backend.adapters.research.crawl4ai import Crawl4AIResearchAdapter
    from backend.agents.pydantic_boundary import PydanticAIAgentProvider
    from backend.integrations.browser_use_worker import browser_use_worker
    from backend.integrations.medusa import commerce_provider
    from backend.integrations.n8n import automation_provider
    from backend.integrations.postiz import publisher

    providers = [commerce_provider, Crawl4AIResearchAdapter(), browser_use_worker, publisher, automation_provider, PydanticAIAgentProvider()]
    now = time.monotonic()
    snapshot: dict[str, dict[str, Any]] = {}
    with _integration_health_lock:
        for provider in providers:
            cached = _integration_health_cache.get(provider.name)
            if not force and cached and now - cached[0] < _INTEGRATION_HEALTH_TTL_S:
                snapshot[provider.name] = dict(cached[1])
                continue
            started = time.monotonic()
            try:
                health = provider.health()
                record = {
                    "configured": health.configured,
                    "reachable": health.reachable,
                    "capabilities": list(health.capabilities),
                    "detail": health.detail,
                    "observed_at": health.observed_at.isoformat(),
                }
                outcome = "reachable" if health.reachable else "unreachable"
            except Exception as exc:
                record = {"configured": False, "reachable": False, "capabilities": [], "detail": str(exc), "observed_at": datetime.now(timezone.utc).isoformat()}
                outcome = "error"
            duration = time.monotonic() - started
            if _prom_integration_configured is not None:
                _prom_integration_configured.labels(integration=provider.name).set(1 if record["configured"] else 0)
                _prom_integration_reachable.labels(integration=provider.name).set(1 if record["reachable"] else 0)
                _prom_integration_probe_duration.labels(integration=provider.name).observe(duration)
                _prom_integration_probes.labels(integration=provider.name, outcome=outcome).inc()
            _integration_health_cache[provider.name] = (now, dict(record))
            snapshot[provider.name] = record
    return snapshot

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
    services as _r_services,
    stack as _r_stack,
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
app.include_router(_r_services.router)
app.include_router(_r_stack.router)


# ── Prometheus scrape endpoint ────────────────────────────────────────────────
# Mounted at /metrics/prometheus, not /metrics — that path is already the JSON
# dashboard-metrics route above (api/routes/metrics.py). The Counter/Gauge/
# Histogram objects declared near the top of this file were being updated on
# every cycle (see _prom_cycles.inc() etc. below) but nothing ever actually
# exposed them over HTTP for a real Prometheus server to scrape — this ASGI
# mount is that missing piece. monitoring/prometheus.yml's scrape config
# points at this exact path.
if _PROMETHEUS_OK:
    try:
        from prometheus_client import make_asgi_app
        app.mount("/metrics/prometheus", make_asgi_app())
    except ImportError:
        pass


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

try:
    from api.routes.storefront import router as _storefront_router
    app.include_router(_storefront_router)
except ImportError:
    pass

try:
    from api.routes.webhooks import router as _webhooks_router
    app.include_router(_webhooks_router)
except ImportError:
    pass


# ── commerce evaluation (vendor-neutral, read-only) ──────────────────────────

@app.post("/evaluation/product")
def evaluation_product(payload: dict[str, Any] = Body(...)):
    """Evaluate product economics and launch readiness from normalized records."""
    try:
        from evaluation.contracts import DataQuality, ProductCandidate, SupplierOffer
        from evaluation.readiness import evaluate_product
        product_data = dict(payload.get("product", {}))
        offer_data = payload.get("offer")
        product_quality = DataQuality(**product_data.pop("quality", {}))
        product = ProductCandidate(**product_data, quality=product_quality)
        offer = None
        if offer_data:
            offer_data = dict(offer_data)
            offer_quality = DataQuality(**offer_data.pop("quality", {}))
            offer = SupplierOffer(**offer_data, quality=offer_quality)
        return evaluate_product(product, offer).to_dict()
    except Exception as exc:
        return {"launchable": False, "reasons": ["invalid_evaluation_request", str(exc)]}


@app.post("/commerce/cycle")
def commerce_cycle(payload: dict[str, Any] | None = Body(default=None)):
    """Run the complementary commerce loop from signal to feedback.

    Live platform execution requires an explicit JSON ``confirm_live: true``
    acknowledgement; omitted or malformed boolean values remain dry-run.
    """
    try:
        from backend.commerce import run_commerce_cycle

        data = payload or {}
        raw_dry_run = data.get("dry_run", True)
        dry_run = (
            raw_dry_run
            if isinstance(raw_dry_run, bool)
            else str(raw_dry_run).strip().lower() not in {"false", "0", "no", "off"}
        )
        if not dry_run and data.get("confirm_live") is not True:
            return {
                "launchable": False,
                "reasons": ["live_execution_requires_confirm_live"],
            }
        top_k = int(data.get("top_k", 5) or 5)
        budget = float(data.get("budget", 20.0) or 20.0)
        if top_k < 1 or budget < 0:
            return {
                "launchable": False,
                "reasons": ["invalid_commerce_cycle_limits"],
            }
        signals = data.get("signals")
        products_payload = data.get("products") or {}
        offers_payload = data.get("offers") or {}
        products = (
            dict(products_payload)
            if isinstance(products_payload, dict)
            else {
                str(item.get("product_id") or item.get("name") or item.get("product")): dict(item)
                for item in products_payload
            }
        )
        offers = (
            dict(offers_payload)
            if isinstance(offers_payload, dict)
            else {
                str(item.get("product_id") or item.get("supplier_id") or item.get("product")): dict(item)
                for item in offers_payload
            }
        )
        report = run_commerce_cycle(
            signals=signals,
            products=products,
            offers=offers,
            top_k=top_k,
            budget=budget,
            dry_run=dry_run,
        )
        return report.to_dict()
    except Exception as exc:
        return {"launchable": False, "reasons": ["invalid_commerce_cycle_request", str(exc)]}


@app.post("/commerce/provider-cycle")
def commerce_provider_cycle(payload: dict[str, Any] | None = Body(default=None)):
    """Run the canonical loop from allowlisted research URLs.

    This endpoint is dry-run by default and delegates all ranking, QA, launch,
    and feedback behavior to ``run_provider_cycle``.
    """
    try:
        data = payload or {}
        urls = data.get("urls") or data.get("research_urls") or []
        if not isinstance(urls, list) or not urls or len(urls) > 20 or not all(isinstance(url, str) and url.strip() for url in urls):
            return {"launchable": False, "reasons": ["provider_cycle_requires_1_to_20_urls"]}
        raw_dry_run = data.get("dry_run", True)
        dry_run = raw_dry_run if isinstance(raw_dry_run, bool) else str(raw_dry_run).lower() not in {"false", "0", "no", "off"}
        if not dry_run and data.get("confirm_live") is not True:
            return {"launchable": False, "reasons": ["live_execution_requires_confirm_live"]}
        from backend.commerce import run_provider_cycle
        from backend.contracts.adapters import SidecarContext
        report = run_provider_cycle(
            urls,
            context=SidecarContext(dry_run=dry_run, approval_state="approved" if not dry_run else "not_required"),
            top_k=max(1, min(int(data.get("top_k", 5) or 5), 50)),
            budget=max(0.0, float(data.get("budget", 20.0) or 20.0)),
            dry_run=dry_run,
        )
        return report.to_dict()
    except Exception as exc:
        return {"launchable": False, "reasons": ["invalid_provider_cycle_request", str(exc)]}


def _verify_integration_webhook(source: str, payload: dict[str, Any], signature: str | None) -> bool:
    secret = os.getenv(f"{source.upper()}_WEBHOOK_SECRET", "")
    if not secret:
        return True
    if not signature:
        return False
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    provided = signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)


@app.post("/integrations/webhooks/{source}")
def integration_webhook(source: str, payload: dict[str, Any] = Body(...), x_webhook_signature: str | None = Header(default=None)):
    """Receive deduplicated Medusa/Postiz events into the canonical broker."""
    if source not in {"medusa", "postiz"}:
        if _prom_webhook_events is not None:
            _prom_webhook_events.labels(source="unknown", outcome="unsupported").inc()
        return JSONResponse({"accepted": False, "reason": "unsupported_webhook_source"}, status_code=404)
    if not _verify_integration_webhook(source, payload, x_webhook_signature):
        if _prom_webhook_events is not None:
            _prom_webhook_events.labels(source=source, outcome="invalid_signature").inc()
        return JSONResponse({"accepted": False, "reason": "invalid_webhook_signature"}, status_code=401)
    event_id = str(payload.get("id") or payload.get("event_id") or payload.get("webhook_id") or "")
    if not event_id:
        if _prom_webhook_events is not None:
            _prom_webhook_events.labels(source=source, outcome="missing_id").inc()
        return JSONResponse({"accepted": False, "reason": "webhook_event_id_required"}, status_code=400)
    try:
        if source == "medusa":
            from backend.integrations.medusa import commerce_provider
            accepted = commerce_provider.accept_webhook(event_id)
        else:
            from backend.integrations.postiz import publisher
            accepted = publisher.accept_webhook(event_id)
        if not accepted:
            if _prom_webhook_events is not None:
                _prom_webhook_events.labels(source=source, outcome="duplicate").inc()
            return {"accepted": False, "duplicate": True, "event_id": event_id}
        from backend.pubsub.broker import broker
        broker_event_id = broker.publish(f"{source}.webhook", payload, source=source, correlation_id=event_id)
        from backend.commerce.feedback import observation_from_webhook
        observation = observation_from_webhook(payload, source=source)
        feedback = None
        if observation is not None and os.getenv("MARKETOS_WEBHOOK_LEARNING", "true").lower() == "true":
            from backend.commerce.feedback import webhook_feedback_recorder
            feedback = webhook_feedback_recorder.record_observation(observation)
        if _prom_webhook_events is not None:
            _prom_webhook_events.labels(source=source, outcome="accepted").inc()
        return {
            "accepted": True, "duplicate": False, "event_id": event_id,
            "broker_event_id": broker_event_id,
            "observation": observation.__dict__ if observation else None,
            "feedback": feedback,
        }
    except Exception as exc:
        # Do not mark an event as permanently handled when downstream
        # publication failed; the source should be able to retry it.
        try:
            if source == "medusa":
                commerce_provider.release_webhook(event_id)
            else:
                publisher.release_webhook(event_id)
        except Exception:
            pass
        if _prom_webhook_events is not None:
            _prom_webhook_events.labels(source=source, outcome="failed").inc()
        return JSONResponse({"accepted": False, "reason": "webhook_processing_failed", "detail": str(exc)}, status_code=503)


@app.post("/commerce/publish")
def commerce_publish(payload: dict[str, Any] | None = Body(default=None)):
    """Publish one canonical CreativeBundle through the publishing adapter."""
    try:
        data = payload or {}
        raw_dry_run = data.get("dry_run", True)
        dry_run = raw_dry_run if isinstance(raw_dry_run, bool) else str(raw_dry_run).lower() not in {"false", "0", "no", "off"}
        if not dry_run and data.get("confirm_live") is not True:
            return {"published": False, "reasons": ["live_publishing_requires_confirm_live"]}
        bundle_data = data.get("bundle") if isinstance(data.get("bundle"), dict) else data
        from backend.commerce.contracts import CreativeBundle
        from backend.commerce.loop import CommerceLoop
        from backend.contracts.adapters import SidecarContext
        bundle = CreativeBundle(**{key: value for key, value in bundle_data.items() if key in CreativeBundle.__dataclass_fields__})
        records = CommerceLoop().publish_creatives(
            [bundle], dry_run=dry_run,
            approval_state="approved" if not dry_run else "not_required",
        )
        return {"published": bool(records), "dry_run": dry_run, "records": records, "artifact_id": bundle.artifact_id}
    except Exception as exc:
        return {"published": False, "reasons": ["invalid_publish_request", str(exc)]}


@app.post("/integrations/postiz/analytics/reconcile")
def reconcile_postiz_analytics(payload: dict[str, Any] = Body(...)):
    """Fetch one Postiz post's analytics and store canonical feedback evidence."""
    post_id = str(payload.get("post_id") or "").strip()
    campaign_id = str(payload.get("campaign_id") or "").strip()
    if not post_id or not campaign_id:
        return {"reconciled": False, "reasons": ["post_id_and_campaign_id_required"]}
    try:
        days = payload.get("days")
        if days is not None:
            days = int(days)
        from backend.integrations.postiz import publisher
        from backend.commerce.feedback import _observation_dict, webhook_feedback_recorder
        observation = publisher.fetch_campaign_observation(
            post_id,
            campaign_id,
            product_id=str(payload.get("product_id") or ""),
            creative_id=str(payload.get("creative_id") or ""),
            days=days,
        )
        feedback = webhook_feedback_recorder.record_observation(observation)
        return {"reconciled": bool(feedback.get("recorded") or feedback.get("deduplicated")), "observation": _observation_dict(observation), "feedback": feedback}
    except Exception as exc:
        return {"reconciled": False, "reasons": ["postiz_analytics_reconcile_failed", str(exc)]}


@app.post("/evaluation/campaign")
def evaluation_campaign(payload: dict[str, Any] = Body(...)):
    """Evaluate campaign observations without changing campaign state."""
    try:
        from evaluation.contracts import CampaignCandidate, CampaignObservation, DataQuality
        from evaluation.readiness import evaluate_campaign
        campaign_data = dict(payload.get("campaign", {}))
        campaign_quality = DataQuality(**campaign_data.pop("quality", {}))
        campaign = CampaignCandidate(**campaign_data, quality=campaign_quality)
        observations = []
        for row in payload.get("observations", []):
            row = dict(row)
            quality = DataQuality(**row.pop("quality", {}))
            observations.append(CampaignObservation(**row, quality=quality))
        return evaluate_campaign(campaign, observations).to_dict()
    except Exception as exc:
        return {"launchable": False, "reasons": ["invalid_evaluation_request", str(exc)]}


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

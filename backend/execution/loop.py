import logging
import random

from backend.decision.engine import decide
from backend.decision.budget_allocator import allocate as budget_allocate, allocation_summary
from backend.decision.portfolio_engine import ingest_results as portfolio_ingest
from backend.learning.delayed_rewards import DelayedRewardStore
from backend.learning.bandit_update import update_from_delayed
from backend.learning.update import learn
from backend.learning.calibration import calibration_model
from backend.learning.calibration_log import calibration_log
from backend.learning.contextual_bandit import select_arm, record_reward
from backend.learning.replay_buffer import replay_buffer
from backend.learning.world_model_calibration import world_model_calibrator
from backend.causal.update import update_causal
from backend.regime.detector import detector
from backend.regime.confidence import regime_confidence
from backend.core.regime_transition import detect_transition
from backend.core.state import ensure_state_shape
from backend.regime.meta_strategy import strategy_memory
from backend.agents.structural_evolution import structural_engine
from backend.agents.self_healing import self_healing_engine
from backend.agents.agent_metrics import agent_metrics_registry
from backend.simulation.reality_gap import reality_gap_engine
from agents.auto_kill import should_kill
from agents.amplifier import Amplifier
from backend.integrations.shopify_client import get_orders, compute_metrics
from backend.integrations.meta_ads_client import get_ad_spend
import backend.ci.hyperparam_meta as hp_meta
from connectors.macro_signals import get_macro_signals

_log = logging.getLogger(__name__)
_amplifier = Amplifier()
store = DelayedRewardStore()

# Stochastic market environment — regime-driven trend with noise
ENV = {"trend": 0.0, "regime": "stable"}

# Cached macro context refreshed every N cycles to avoid excessive API calls
_macro_cache: dict = {}
_MACRO_REFRESH_CYCLES = 10

# Hyperparameter meta-learning state (persisted to JSON file)
_hp_meta_state = hp_meta.load_hp_meta()
_prev_avg_roas: float | None = None

TOTAL_CYCLE_BUDGET = 500.0  # total spend per cycle, split across all decisions
TRANSITION_COOLDOWN_CYCLES = 5
# Scales the macro-risk adjustment to trend; 0.02 keeps macro nudge small
# relative to the ±0.1 volatile step, preventing macro from dominating.
_MACRO_TREND_COEFFICIENT = 0.02

# Campaigns flagged for kill (module-level; cleared on restart)
_kill_set: set[str] = set()

# Real-data state for reality gap calibration
_real_roas_cache: float | None = None
_real_data_counter: int = 0

# Hook/angle pool — refreshed from PatternStore every 60 s, fallback to HOOKS
_hook_pool:     list[str] = []
_angle_pool:    list[str] = []
_pool_ts:       float = 0.0
_POOL_TTL:      float = 60.0
_DEFAULT_ANGLES = ["problem-solution", "social-proof", "urgency", "curiosity", "authority"]


# Lineage: previous cycle's node id, so cycles chain into a worldline
_last_cycle_node: str = ""


def _cognitive_writethrough(state, results: list[dict], avg_roas: float) -> None:
    """Feed the cycle's outcomes into the cognitive subsystem.

    Three fail-silent writes per cycle:
      episodic memory  — one episode per execution outcome (raw history)
      vector store     — winning creatives indexed for semantic recall
      lineage tracker  — decision→outcome edges chained across cycles
    Failures never disturb the execution loop.
    """
    global _last_cycle_node

    # 1. Episodic memory write-through
    try:
        from backend.memory.episodic import get_episodic_store
        epi = get_episodic_store()
        for r in results:
            epi.record_event(
                "execution.outcome",
                payload={
                    "product": r.get("product", ""),
                    "hook":    r.get("hook", ""),
                    "angle":   r.get("angle", ""),
                    "roas":    r.get("roas", 0.0),
                    "cost":    r.get("cost", 0.0),
                    "revenue": r.get("revenue", 0.0),
                    "ctr":     r.get("ctr", 0.0),
                    "cvr":     r.get("cvr", 0.0),
                    "regime":  state.detected_regime,
                },
                source="execution_loop",
            )
    except Exception:
        _log.debug("episodic_writethrough_failed", exc_info=True)

    # 2. Vector indexing of winning creatives (ROAS > 1.5)
    try:
        from backend.vector.embeddings import embed_text
        from backend.vector.indexing import creative_record, index_batch
        records = []
        for r in results:
            if r.get("roas", 0.0) <= 1.5 or not r.get("hook"):
                continue
            text = f"{r.get('hook', '')} | {r.get('angle', '')} | {r.get('product', '')}"
            records.append(creative_record(
                creative_id=f"cyc{state.total_cycles}_{r.get('product', '')[:24]}",
                vector=embed_text(text),
                hook=r.get("hook", ""),
                product=r.get("product", ""),
                roas=float(r.get("roas", 0.0)),
                angle=r.get("angle", ""),
            ))
        if records:
            index_batch(records)
    except Exception:
        _log.debug("vector_writethrough_failed", exc_info=True)

    # 3. Lineage: decision node → outcome node, chained to the previous cycle
    try:
        from backend.lineage import get_tracker
        tracker = get_tracker()
        decision_node = tracker.track(
            "execution.decision",
            label=f"cycle_{state.total_cycles}_decision",
            parent_ids=[_last_cycle_node] if _last_cycle_node else [],
            source="execution_loop",
            payload={"regime": state.detected_regime, "n_decisions": len(results)},
        )
        outcome_node = tracker.track(
            "execution.outcome",
            label=f"cycle_{state.total_cycles}_outcome",
            parent_ids=[decision_node],
            source="execution_loop",
            payload={
                "avg_roas": round(avg_roas, 4),
                "capital":  round(getattr(state, "capital", 0.0), 2),
                "winners":  sum(1 for r in results if r.get("roas", 0) > 1.5),
            },
        )
        _last_cycle_node = outcome_node
    except Exception:
        _log.debug("lineage_writethrough_failed", exc_info=True)


def _refresh_pools() -> tuple[list[str], list[str]]:
    global _hook_pool, _angle_pool, _pool_ts
    import time as _time
    if _hook_pool and (_time.time() - _pool_ts) < _POOL_TTL:
        return _hook_pool, _angle_pool
    try:
        from core.content.patterns import pattern_store
        hooks  = pattern_store.get_top_hooks(n=5)
        angles = pattern_store.get_top_angles(n=5)
    except Exception:
        hooks, angles = [], []
    if not hooks:
        from core.creative.hooks import HOOKS
        hooks = list(HOOKS)
    if not angles:
        angles = list(_DEFAULT_ANGLES)
    _hook_pool, _angle_pool, _pool_ts = hooks, angles, _time.time()
    return _hook_pool, _angle_pool


def _simulate_environment():
    if random.random() < 0.05:
        ENV["regime"] = random.choice(["growth", "decay", "volatile", "stable"])
    if ENV["regime"] == "growth":
        ENV["trend"] += random.uniform(0.01, 0.05)
    elif ENV["regime"] == "decay":
        ENV["trend"] -= random.uniform(0.01, 0.05)
    elif ENV["regime"] == "volatile":
        ENV["trend"] += random.uniform(-0.1, 0.1)
    elif ENV["regime"] == "stable":
        ENV["trend"] *= 0.95
    # Macro risk nudges the trend: high risk → downward pressure
    macro_risk = _macro_cache.get("macro_risk_score", 0.5)
    ENV["trend"] -= (macro_risk - 0.5) * _MACRO_TREND_COEFFICIENT
    ENV["trend"] = max(-1.0, min(1.0, ENV["trend"]))


def _generate_roas():
    _simulate_environment()
    base = 1.0 + ENV["trend"]
    noise = random.uniform(-0.3, 0.3)
    delayed = random.uniform(-0.1, 0.1)
    return max(0.1, base + noise + delayed)


def _population_diversity():
    from backend.agents.structural_evolution import structure_distance
    pop = structural_engine.population
    if len(pop) < 2:
        return 1.0
    dists = [structure_distance(pop[i], pop[j]) for i in range(len(pop)) for j in range(i + 1, len(pop))]
    return sum(dists) / len(dists)


def _refresh_real_roas():
    """Fetch real ROAS from Shopify/Meta every 10 calls; returns cached value."""
    global _real_roas_cache, _real_data_counter
    _real_data_counter += 1
    if _real_data_counter % 10 != 0:
        return _real_roas_cache
    try:
        orders = get_orders(last_n_minutes=60)
        meta = get_ad_spend(last_n_minutes=60)
        metrics = compute_metrics(orders)
        spend = meta.get("total_spend", 0.0)
        if spend > 0:
            _real_roas_cache = round(metrics["revenue"] / spend, 4)
    except Exception:
        pass  # keep cached value; clients already have their own fallback
    return _real_roas_cache


def execute(decisions, state):
    budgets = budget_allocate(decisions, total_budget=TOTAL_CYCLE_BUDGET)
    _log.debug(allocation_summary(decisions, budgets))

    # Track peak capital for drawdown monitoring (stored on state object)
    peak_capital = getattr(state, "_peak_capital", state.capital)
    if state.capital > peak_capital:
        peak_capital = state.capital
    state._peak_capital = peak_capital

    hook_pool, angle_pool = _refresh_pools()
    results = []
    for i, d in enumerate(decisions):
        action = d.get("action", {})
        structure = d.get("structure")
        campaign_id = str(action.get("campaign_id", "") or action.get("variant", ""))
        cost = round(budgets[i], 4)
        hook  = hook_pool[i % len(hook_pool)]
        angle = angle_pool[i % len(angle_pool)]
        product = d.get("product_name", str(action.get("variant", "")))

        roas = _generate_roas()
        revenue = roas * cost
        if cost > 0:
            clicks = max(1, int(cost * 2))
            impressions = max(clicks, int(clicks / 0.02))
            conversions = max(1, int(clicks * random.uniform(0.02, 0.15)))
            ctr = clicks / impressions
            cvr = conversions / clicks
            cac = cost / conversions
        else:
            clicks = 0
            impressions = 0
            conversions = 0
            ctr = 0.0
            cvr = 0.0
            cac = 0.0
        profit = round(revenue - cost, 2)

        pred = d.get("pred", 1.0)
        calibration_model.update(pred, roas)
        # Bayesian world model calibration
        world_model_calibrator.update(pred, roas)

        # Record agent-level metrics
        agent_metrics_registry.record_pnl("execution", revenue, cost)

        outcome = {
            "product":       product,
            "hook":          hook,
            "angle":         angle,
            "roas":          round(roas, 4),
            "roas_6h":       round(max(0.01, roas * random.uniform(0.70, 0.95)), 4),
            "roas_12h":      round(max(0.01, roas * random.uniform(0.85, 1.05)), 4),
            "roas_24h":      round(max(0.01, roas * random.uniform(0.90, 1.10)), 4),
            "revenue":       round(revenue, 2),
            "cost":          cost,
            "profit":        profit,
            "ctr":           round(ctr, 4),
            "cvr":           round(cvr, 4),
            "cac":           round(cac, 4),
            "prediction":    round(pred, 4),
            "error":         round(pred - roas, 4),
            "pred_lo":       d.get("pred_lo"),
            "pred_hi":       d.get("pred_hi"),
            "pred_width":    d.get("pred_width"),
            "interval_conf": d.get("interval_conf"),
            "env_regime":    ENV["regime"],
            "env_trend":     round(ENV["trend"], 4),
        }
        # Preserve the nested action so downstream consumers (portfolio
        # bucketing, kill/amplify sets, replay buffer) can recover the
        # variant. Also flatten action keys onto the outcome for readers
        # that expect the legacy flat shape.
        outcome["action"] = action
        outcome.update(action)

        # structural evolution scoring
        if structure:
            structural_engine.score(structure, roas)

        # regime performance feedback
        strategy_memory.update(ENV["regime"], roas)

        # reality gap — feed real ROAS when Shopify/Meta credentials present
        reality_gap_engine.update(roas, _refresh_real_roas())

        # campaign lifecycle: flag kills for next cycle
        kill_signal = should_kill(outcome)
        outcome["kill_signal"] = kill_signal
        if kill_signal and campaign_id:
            _kill_set.add(campaign_id)

        store.log(action, outcome)
        state.capital += revenue - cost
        results.append(outcome)
    return results


def process_delayed():
    for delay in [5, 10, 20]:
        ready = store.get_ready(delay)
        if ready:
            update_from_delayed(ready)


def run_cycle(state):
    global _macro_cache

    state = ensure_state_shape(state)

    if not structural_engine.population:
        structural_engine.initialize(n=5)

    # refresh macro signals periodically (no-op when FRED key absent)
    if state.total_cycles % _MACRO_REFRESH_CYCLES == 0:
        try:
            _macro_cache = get_macro_signals()
        except Exception:
            pass

    # expose the current market trend on state so the bandit's trend
    # feature is live (ENV is module-level; the bandit reads state.trend)
    state.trend = ENV["trend"]

    # select high-level arm from LinUCB contextual bandit
    bandit_arm = select_arm(state)

    try:
        decisions = decide(state)
        results = execute(decisions, state)
    except Exception:
        _log.exception("cycle execute failed")
        state.total_cycles += 1
        return state

    state.event_log.log_batch(results)

    # feed results into portfolio engine for ROAS-weighted allocation
    portfolio_ingest(results)

    # auto_kill: pause underperforming campaigns via AJO (ROAS < 0.5)
    _cycle_kill = {
        str(r.get("action", {}).get("variant", ""))
        for r in results
        if r.get("roas", 1.0) < 0.5 and r.get("action", {}).get("variant")
    }
    if _cycle_kill:
        try:
            from backend.integrations.adobe_ajo import pause_campaign, is_configured as _ajo_ok
            if _ajo_ok():
                for cid in _cycle_kill:
                    pause_campaign(cid)
        except Exception:
            pass

    # amplifier: scale high-ROAS campaigns via AJO (ROAS > 2.0)
    _amplified_ids = [
        str(r.get("action", {}).get("variant", ""))
        for r in results
        if r.get("roas", 0.0) > 2.0 and r.get("action", {}).get("variant")
    ]
    if _amplified_ids:
        try:
            from backend.integrations.adobe_ajo import scale_campaign, is_configured as _ajo_ok
            if _ajo_ok():
                for cid in _amplified_ids[-5:]:
                    scale_campaign(cid)
        except Exception:
            pass

    try:
        state = learn(state, results)
    except Exception:
        _log.exception("cycle learn failed")

    try:
        state.graph = update_causal(state.graph, state.event_log)
    except Exception:
        _log.exception("cycle causal failed")

    # update LinUCB bandit reward using mean ROAS this cycle
    avg_roas_cycle = sum(r.get("roas", 0) for r in results) / max(len(results), 1)
    record_reward(bandit_arm, state, avg_roas_cycle)

    # feed outcomes into the cognitive subsystem (episodic/vector/lineage)
    _cognitive_writethrough(state, results, avg_roas_cycle)

    # push experiences into the replay buffer
    for r in results:
        action = r.get("action", {})
        features = [
            float(r.get("roas", 0)),
            float(r.get("cost", 0)),
            float(r.get("ctr", 0)),
            float(r.get("cvr", 0)),
            float(_macro_cache.get("macro_risk_score", 0.5)),
        ]
        replay_buffer.add(features, action, r.get("roas", 0.0))

    previous_regime = state.detected_regime
    state.detected_regime = detector.detect(state.event_log, _macro_cache or None)
    transition_detected = detect_transition(previous_regime, state.detected_regime)
    state.previous_regime = previous_regime
    state.transition = {
        "occurred": transition_detected,
        "from": previous_regime,
        "to": state.detected_regime,
    }

    cooldown = max(0, state.transition_cooldown)
    if transition_detected:
        cooldown = TRANSITION_COOLDOWN_CYCLES
    elif cooldown > 0:
        cooldown -= 1
    state.transition_cooldown = cooldown

    if results:
        for row in results:
            row["transition"] = state.transition
            row["transition_cooldown"] = cooldown

    regime_confidence.update(state.detected_regime, ENV["regime"])
    calibration_log.log(calibration_model.stats())

    process_delayed()

    # amplify winners from this cycle (stored in memory for next decide())
    try:
        winners = [r for r in results if r.get("roas", 0) > 1.5 and not r.get("kill_signal")]
        amplified = _amplifier.amplify(winners)
        if amplified:
            state.memory.extend(amplified[-5:])
    except Exception:
        _log.exception("cycle amplify failed")

    # structural evolution + hyperparam meta-learning every 10 cycles
    if state.total_cycles % 10 == 0 and state.total_cycles > 0:
        global _hp_meta_state, _prev_avg_roas
        try:
            structural_engine.evolve()
            avg_roas = (sum(r.get("roas", 0) for r in results) / max(len(results), 1))
            diversity = _population_diversity()
            self_healing_engine.heal(avg_roas, diversity, structural_engine)

            improvement = (avg_roas - _prev_avg_roas) if _prev_avg_roas is not None else 0.0
            _prev_avg_roas = avg_roas

            _hp_meta_state = hp_meta.step(
                _hp_meta_state,
                regime=state.detected_regime,
                improvement=improvement,
                evolution_engine=structural_engine,
            )
            hp_meta.save_hp_meta(_hp_meta_state)
        except Exception:
            _log.exception("cycle evolution failed")

    # persist cycle summary to Supabase (no-op when credentials absent)
    try:
        from connectors.supabase_connector import save_cycle_summary
        save_cycle_summary({
            "total_cycles": state.total_cycles,
            "capital": round(state.capital, 2),
            "detected_regime": state.detected_regime,
            "avg_roas": round(avg_roas_cycle, 4),
            "macro_risk": _macro_cache.get("macro_risk_score"),
            "bandit_arm": bandit_arm,
        })
    except Exception:
        pass

    state.total_cycles += 1
    return state

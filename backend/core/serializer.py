"""
State persistence router.
  .db  extension  → DuckDB (default, recommended)
  .json extension → legacy JSON (still supported for migration)
"""
import json
import os

import backend.learning.bandit_update as bu
import backend.learning.calibration as cal
import backend.learning.calibration_log as cal_log
import backend.regime.confidence as rc
from backend.execution.loop import ENV
from backend.core.state import SystemState

STATE_PATH = "state/state.db"


def save(state, path=STATE_PATH):
    if path.endswith(".db"):
        from backend.core.db_serializer import save as db_save
        db_save(state, path)
        # Dual-write to Supabase when credentials are configured
        try:
            from backend.integrations.supabase_client import save_state, is_configured
            if is_configured():
                payload = {
                    "capital": state.capital,
                    "regime": state.regime,
                    "detected_regime": state.detected_regime,
                    "energy": state.energy,
                    "total_cycles": state.total_cycles,
                }
                save_state(payload)
        except Exception:
            pass
        return

    # --- legacy JSON ---
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "capital": state.capital,
        "regime": state.regime,
        "detected_regime": state.detected_regime,
        "energy": state.energy,
        "total_cycles": state.total_cycles,
        "event_log": state.event_log.rows[-2000:],
        "memory": state.memory[-500:],
        "graph_edges": {f"{p}|{c}": w for (p, c), w in state.graph.edges.items()},
        "bandit_history": {k: list(v) for k, v in bu.bandit_memory.history.items()},
        "calibration_errors": cal.calibration_model.errors,
        "calibration_log": cal_log.calibration_log.history[-200:],
        "regime_confidence": rc.regime_confidence.history,
        "env": {"trend": ENV["trend"], "regime": ENV["regime"]},
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"State saved → {path} ({os.path.getsize(path):,} bytes)")


def load(path=STATE_PATH):
    if path.endswith(".db"):
        from backend.core.db_serializer import load as db_load
        return db_load(path)

    # --- legacy JSON ---
    if not os.path.exists(path):
        return None
    with open(path) as f:
        d = json.load(f)

    state = SystemState()
    state.capital = d.get("capital", 1000.0)
    state.regime = d.get("regime", "neutral")
    state.detected_regime = d.get("detected_regime", "unknown")
    state.energy = d.get("energy", {"fatigue": 0.1, "load": 0.2})
    state.total_cycles = d.get("total_cycles", 0)
    state.event_log.rows = d.get("event_log", [])
    state.memory = d.get("memory", [])

    for key, weight in d.get("graph_edges", {}).items():
        parts = key.split("|", 1)
        if len(parts) == 2:
            state.graph.add_edge(parts[0], parts[1], weight)

    # Rebuild as the same bounded OrderedDict-of-deques shape
    # bandit_memory.update() maintains (see backend/core/db_serializer.py's
    # equivalent load path) — a plain dict of lists would silently drop
    # the memory cap on every restore.
    from collections import OrderedDict, deque
    bu.bandit_memory.history = OrderedDict(
        (k, deque(v, maxlen=bu._MAX_REWARDS_PER_KEY))
        for k, v in d.get("bandit_history", {}).items()
    )
    cal.calibration_model.errors = d.get("calibration_errors", [])
    cal_log.calibration_log.history = d.get("calibration_log", [])
    rc.regime_confidence.history = d.get("regime_confidence", [])

    env = d.get("env", {})
    if env:
        ENV["trend"] = env.get("trend", 0.0)
        ENV["regime"] = env.get("regime", "stable")

    return state

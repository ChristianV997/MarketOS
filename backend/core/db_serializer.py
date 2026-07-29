"""
DuckDB-backed state persistence.

Schema:
  system_meta      — scalar state (one row, replaced each save)
  event_log        — append-only event history (never deleted, grows across runs)
  memory_rows      — latest learning memory, 500-row snapshot
  graph_edges      — causal graph snapshot
  bandit_history   — per-action reward lists snapshot
  calibration_errs — prediction error list snapshot
  calibration_log  — bias/uncertainty history snapshot (200 rows)
  regime_conf      — regime confidence history snapshot
"""
import json
import os

import duckdb

import backend.learning.bandit_update as bu
import backend.learning.calibration as cal
import backend.learning.calibration_log as cal_log
import backend.regime.confidence as rc
from backend.execution.loop import ENV
from backend.core.state import SystemState

# DDL — executed one statement at a time (DuckDB has no executescript)
_DDL = [
    "CREATE SEQUENCE IF NOT EXISTS event_log_seq START 1",
    """CREATE TABLE IF NOT EXISTS system_meta (
        capital         REAL,
        regime          TEXT,
        detected_regime TEXT,
        energy_fatigue  REAL,
        energy_load     REAL,
        total_cycles    INTEGER,
        env_trend       REAL,
        env_regime      TEXT,
        saved_at        TIMESTAMP DEFAULT current_timestamp
    )""",
    """CREATE TABLE IF NOT EXISTS event_log (
        id             BIGINT DEFAULT nextval('event_log_seq'),
        roas           REAL,
        roas_6h        REAL,
        roas_12h       REAL,
        roas_24h       REAL,
        revenue        REAL,
        cost           REAL,
        prediction     REAL,
        error          REAL,
        pred_lo        REAL,
        pred_hi        REAL,
        pred_width     REAL,
        interval_conf  REAL,
        env_regime     TEXT,
        env_trend      REAL,
        velocity       REAL,
        acceleration   REAL,
        advantage      REAL,
        variant        TEXT,
        extra_json     TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS memory_rows (
        pos      INTEGER,
        row_json TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS graph_edges (
        parent TEXT,
        child  TEXT,
        weight REAL
    )""",
    """CREATE TABLE IF NOT EXISTS bandit_history (
        action       TEXT,
        rewards_json TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS calibration_errs (
        pos   INTEGER,
        error REAL
    )""",
    """CREATE TABLE IF NOT EXISTS calibration_log (
        pos         INTEGER,
        bias        REAL,
        uncertainty REAL
    )""",
    """CREATE TABLE IF NOT EXISTS regime_conf (
        pos        INTEGER,
        entry_json TEXT
    )""",
]

_KNOWN_COLS = {
    "roas", "roas_6h", "roas_12h", "roas_24h",
    "revenue", "cost", "prediction", "error",
    "pred_lo", "pred_hi", "pred_width", "interval_conf",
    "env_regime", "env_trend",
    "velocity", "acceleration", "advantage", "variant",
}


def _connect(path: str) -> duckdb.DuckDBPyConnection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = duckdb.connect(path)
    for stmt in _DDL:
        con.execute(stmt)
    return con


def _row_to_record(row: dict) -> tuple:
    extra = {k: v for k, v in row.items() if k not in _KNOWN_COLS}
    return (
        row.get("roas"),
        row.get("roas_6h"),
        row.get("roas_12h"),
        row.get("roas_24h"),
        row.get("revenue"),
        row.get("cost"),
        row.get("prediction"),
        row.get("error"),
        row.get("pred_lo"),
        row.get("pred_hi"),
        row.get("pred_width"),
        row.get("interval_conf"),
        row.get("env_regime"),
        row.get("env_trend"),
        row.get("velocity"),
        row.get("acceleration"),
        row.get("advantage"),
        str(row.get("variant", "")) or None,
        json.dumps(extra) if extra else None,
    )


def _record_to_row(rec) -> dict:
    cols = [
        "id", "roas", "roas_6h", "roas_12h", "roas_24h",
        "revenue", "cost", "prediction", "error",
        "pred_lo", "pred_hi", "pred_width", "interval_conf",
        "env_regime", "env_trend",
        "velocity", "acceleration", "advantage", "variant", "extra_json",
    ]
    row = dict(zip(cols, rec))
    extra_raw = row.pop("extra_json", None)
    row.pop("id", None)
    if extra_raw:
        try:
            row.update(json.loads(extra_raw))
        except (json.JSONDecodeError, TypeError):
            pass
    return {k: v for k, v in row.items() if v is not None}


def save(state: SystemState, path: str) -> None:
    con = _connect(path)
    con.begin()
    try:
        # system_meta — snapshot
        con.execute("DELETE FROM system_meta")
        con.execute(
            """INSERT INTO system_meta
               VALUES (?,?,?,?,?,?,?,?, current_timestamp)""",
            (
                state.capital,
                state.regime,
                state.detected_regime,
                state.energy.get("fatigue", 0.1),
                state.energy.get("load", 0.2),
                state.total_cycles,
                ENV["trend"],
                ENV["regime"],
            ),
        )

        # event_log — append-only: only insert rows not yet persisted
        (db_count,) = con.execute("SELECT COUNT(*) FROM event_log").fetchone()
        new_rows = state.event_log.rows[db_count:]
        if new_rows:
            records = [_row_to_record(r) for r in new_rows]
            con.executemany(
                """INSERT INTO event_log
                   (roas, roas_6h, roas_12h, roas_24h,
                    revenue, cost, prediction, error,
                    pred_lo, pred_hi, pred_width, interval_conf,
                    env_regime, env_trend,
                    velocity, acceleration, advantage, variant, extra_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                records,
            )

        # memory_rows — snapshot
        con.execute("DELETE FROM memory_rows")
        if state.memory:
            con.executemany(
                "INSERT INTO memory_rows VALUES (?, ?)",
                [(i, json.dumps(r)) for i, r in enumerate(state.memory[-500:])],
            )

        # graph_edges — snapshot
        con.execute("DELETE FROM graph_edges")
        if state.graph.edges:
            con.executemany(
                "INSERT INTO graph_edges VALUES (?, ?, ?)",
                [(p, c, w) for (p, c), w in state.graph.edges.items()],
            )

        # bandit_history — snapshot (history values are bounded deques, not
        # lists — json.dumps needs a plain list)
        con.execute("DELETE FROM bandit_history")
        if bu.bandit_memory.history:
            con.executemany(
                "INSERT INTO bandit_history VALUES (?, ?)",
                [(k, json.dumps(list(v))) for k, v in bu.bandit_memory.history.items()],
            )

        # calibration_errs — snapshot
        con.execute("DELETE FROM calibration_errs")
        if cal.calibration_model.errors:
            con.executemany(
                "INSERT INTO calibration_errs VALUES (?, ?)",
                [(i, e) for i, e in enumerate(cal.calibration_model.errors)],
            )

        # calibration_log — snapshot, 200-row cap
        con.execute("DELETE FROM calibration_log")
        hist = cal_log.calibration_log.history[-200:]
        if hist:
            con.executemany(
                "INSERT INTO calibration_log VALUES (?, ?, ?)",
                [(i, h.get("bias", 0.0), h.get("uncertainty", 0.0))
                 for i, h in enumerate(hist)],
            )

        # regime_conf — snapshot
        con.execute("DELETE FROM regime_conf")
        if rc.regime_confidence.history:
            con.executemany(
                "INSERT INTO regime_conf VALUES (?, ?)",
                [(i, json.dumps(h))
                 for i, h in enumerate(rc.regime_confidence.history)],
            )

        con.commit()
    except Exception:
        con.rollback()
        con.close()
        raise

    con.close()
    size = os.path.getsize(path)
    total = db_count + len(new_rows) if new_rows else db_count
    print(
        f"State saved → {path} "
        f"({size:,} bytes | {total:,} events total | +{len(new_rows) if new_rows else 0} new)"
    )


def load(path: str) -> SystemState | None:
    if not os.path.exists(path):
        return None

    con = _connect(path)

    row = con.execute(
        "SELECT * FROM system_meta ORDER BY saved_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        con.close()
        return None

    state = SystemState()
    (
        state.capital,
        state.regime,
        state.detected_regime,
        energy_fatigue,
        energy_load,
        state.total_cycles,
        env_trend,
        env_regime,
        _saved_at,
    ) = row
    state.energy = {"fatigue": energy_fatigue, "load": energy_load}
    ENV["trend"] = env_trend
    ENV["regime"] = env_regime

    # event_log
    rows = con.execute("SELECT * FROM event_log ORDER BY id").fetchall()
    state.event_log.rows = [_record_to_row(r) for r in rows]

    # memory
    mem_rows = con.execute(
        "SELECT row_json FROM memory_rows ORDER BY pos"
    ).fetchall()
    state.memory = [json.loads(r[0]) for r in mem_rows]

    # graph_edges
    for parent, child, weight in con.execute("SELECT * FROM graph_edges").fetchall():
        state.graph.add_edge(parent, child, weight)

    # bandit_history — rebuild as the same bounded OrderedDict-of-deques
    # shape bandit_memory.update() maintains, not a plain unbounded dict of
    # lists (which would silently drop the memory cap on every restore).
    from collections import OrderedDict, deque
    bu.bandit_memory.history = OrderedDict(
        (action, deque(json.loads(rewards_json), maxlen=bu._MAX_REWARDS_PER_KEY))
        for action, rewards_json
        in con.execute("SELECT * FROM bandit_history").fetchall()
    )

    # calibration_errs
    cal.calibration_model.errors = [
        e for (_pos, e)
        in con.execute("SELECT * FROM calibration_errs ORDER BY pos").fetchall()
    ]

    # calibration_log
    cal_log.calibration_log.history = [
        {"bias": bias, "uncertainty": uncertainty}
        for (_pos, bias, uncertainty)
        in con.execute("SELECT * FROM calibration_log ORDER BY pos").fetchall()
    ]

    # regime_conf
    rc.regime_confidence.history = [
        json.loads(entry_json)
        for (_pos, entry_json)
        in con.execute("SELECT * FROM regime_conf ORDER BY pos").fetchall()
    ]

    con.close()
    return state


def query(path: str, sql: str):
    """Run an arbitrary SQL query against the state DB. Returns list of rows."""
    if not os.path.exists(path):
        return []
    con = duckdb.connect(path, read_only=True)
    result = con.execute(sql).fetchall()
    con.close()
    return result

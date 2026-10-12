"""MarketOS Live Dashboard — run with:
    streamlit run backend/monitoring/streamlit_dashboard.py

Reads live data directly from the DuckDB state file (state/state.db).
Auto-refreshes every 30 seconds.
"""
from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# Allow imports from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

STATE_PATH = os.environ.get("STATE_PATH", "state/state.db")
REFRESH_INTERVAL = 30  # seconds


def _get_dashboard_root(custom_root: Path | str | None = None) -> Path:
    """Return the canonical root directory to which state paths must be confined."""
    if custom_root is not None:
        return Path(custom_root).resolve()
    override = os.environ.get("MARKETOS_STATE_ROOT") or os.environ.get("MARKETOS_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent.parent


def confine_state_path(raw_path: str | os.PathLike[str], *, root: Path | str | None = None) -> Path:
    """Validate and confine a raw state database path within the intended root.

    Prevents path injection (CWE-22 / py/path-injection) by resolving symlinks,
    normalizing traversal tokens, rejecting null bytes, and verifying strict boundary
    containment via `commonpath` and `is_relative_to` (not string-prefix matching).
    Raises ValueError on invalid, escaping, or traversal-bearing paths without echoing
    untrusted input.
    """
    if raw_path is None or not isinstance(raw_path, (str, os.PathLike)):
        raise ValueError("state_path_invalid")

    path_str = str(raw_path).strip()
    if not path_str or "\x00" in path_str:
        raise ValueError("state_path_invalid")

    # Normalize directory separators for consistent cross-platform behavior
    normalized_str = path_str.replace("\\", "/")

    # Windows drive paths (e.g. C:/...) on non-Windows hosts cannot be safely placed under root
    if re.match(r"^[a-zA-Z]:", normalized_str) and os.name != "nt":
        raise ValueError("state_path_outside_root")

    # Explicit traversal check on path components
    p = Path(normalized_str)
    if ".." in p.parts:
        raise ValueError("state_path_traversal_blocked")

    root_path = _get_dashboard_root(root)
    root_s = os.path.realpath(str(root_path))

    # Construct candidate path relative to root if not already absolute
    candidate = p if p.is_absolute() else Path(root_s) / p

    try:
        resolved = candidate.resolve()
        resolved_s = os.path.realpath(str(resolved))
    except (OSError, ValueError):
        raise ValueError("state_path_invalid") from None

    # Path boundary checks: commonpath + is_relative_to (immune to sibling-prefix bypasses)
    try:
        if os.path.commonpath([root_s, resolved_s]) != root_s:
            raise ValueError("state_path_outside_root")
        if not resolved.is_relative_to(root_path):
            raise ValueError("state_path_outside_root")
        rel = resolved.relative_to(root_path)
    except (ValueError, OSError):
        raise ValueError("state_path_outside_root") from None

    # Disallow root itself as a state DB file
    if not rel.parts or rel == Path(".") or ".." in rel.parts:
        raise ValueError("state_path_outside_root")

    return root_path / rel


def _is_safe_regular_file(path: Path | str, *, root: Path | str | None = None) -> bool:
    """Validate that the target path exists, is a regular file, and can be opened safely.

    Validates the opened file descriptor directly rather than only pre-open strings,
    checking stat.S_ISREG to prevent FIFOs, sockets, device nodes, or directories.
    """
    try:
        root_path = _get_dashboard_root(root)
        p = Path(path).resolve()
        if not p.is_relative_to(root_path):
            return False
        if not p.is_file():
            return False
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(str(p), flags)
        try:
            st_stat = os.fstat(fd)
            return stat.S_ISREG(st_stat.st_mode)
        finally:
            os.close(fd)
    except (OSError, ValueError):
        return False


# ── data loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=REFRESH_INTERVAL)
def load_event_log(state_path: str | Path, limit: int = 500, *, root: Path | str | None = None) -> pd.DataFrame:
    try:
        safe_path = confine_state_path(state_path, root=root)
    except (ValueError, OSError):
        return pd.DataFrame()

    if not _is_safe_regular_file(safe_path, root=root):
        return pd.DataFrame()

    try:
        import duckdb
        con = duckdb.connect(str(safe_path), read_only=True)
        df = con.execute(
            f"""
            SELECT id, roas, prediction, error, pred_width, interval_conf,
                   cost, revenue, env_regime, env_trend
            FROM event_log
            ORDER BY id DESC
            LIMIT {limit}
            """
        ).df()
        con.close()
        return df.sort_values("id").reset_index(drop=True)
    except Exception:
        st.warning("Could not read event_log from state database.")
        return pd.DataFrame()


@st.cache_data(ttl=REFRESH_INTERVAL)
def load_system_meta(state_path: str | Path, *, root: Path | str | None = None) -> dict[str, Any]:
    try:
        safe_path = confine_state_path(state_path, root=root)
    except (ValueError, OSError):
        return {}

    if not _is_safe_regular_file(safe_path, root=root):
        return {}

    try:
        import duckdb
        con = duckdb.connect(str(safe_path), read_only=True)
        row = con.execute(
            "SELECT * FROM system_meta ORDER BY saved_at DESC LIMIT 1"
        ).fetchone()
        con.close()
        if row is None:
            return {}
        cols = [
            "capital", "regime", "detected_regime",
            "energy_fatigue", "energy_load", "total_cycles",
            "env_trend", "env_regime", "saved_at",
        ]
        return dict(zip(cols, row))
    except Exception:
        return {}


@st.cache_data(ttl=REFRESH_INTERVAL)
def load_causal_edges(state_path: str | Path, *, root: Path | str | None = None) -> pd.DataFrame:
    try:
        safe_path = confine_state_path(state_path, root=root)
    except (ValueError, OSError):
        return pd.DataFrame()

    if not _is_safe_regular_file(safe_path, root=root):
        return pd.DataFrame()

    try:
        import duckdb
        con = duckdb.connect(str(safe_path), read_only=True)
        df = con.execute(
            "SELECT parent, child, weight FROM graph_edges ORDER BY ABS(weight) DESC LIMIT 20"
        ).df()
        con.close()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=REFRESH_INTERVAL)
def load_drift_report(*, root: Path | str | None = None) -> dict[str, Any]:
    """Load latest drift report JSON if it exists."""
    base_root = _get_dashboard_root(root)
    for candidate in ["drift_report.json", "state/drift_report.json"]:
        try:
            candidate_path = confine_state_path(candidate, root=base_root)
        except (ValueError, OSError):
            continue
        if _is_safe_regular_file(candidate_path, root=base_root):
            try:
                with open(candidate_path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


# ── dashboard rendering ───────────────────────────────────────────────────────

def render_dashboard() -> None:
    st.set_page_config(
        page_title="MarketOS Dashboard",
        page_icon="📈",
        layout="wide",
    )

    st.title("MarketOS — Live Decision System Dashboard")

    # ── sidebar controls ──────────────────────────────────────────────────────────

    with st.sidebar:
        st.header("Settings")
        raw_state_path = st.text_input("State DB path", value=STATE_PATH)
        window = st.slider("Event window (rows)", min_value=50, max_value=500, value=200, step=50)
        if st.button("Force refresh"):
            st.cache_data.clear()
            st.rerun()
        st.caption(f"Auto-refreshes every {REFRESH_INTERVAL}s")

    # ── validate and confine state path ───────────────────────────────────────────

    try:
        safe_state_path = confine_state_path(raw_state_path)
    except (ValueError, OSError):
        st.error("Invalid or unconfined state database path.")
        st.stop()
        return

    if not _is_safe_regular_file(safe_state_path):
        st.error("No state DB found at configured location. Run `scripts/run_cycles.py` first.")
        st.stop()
        return

    # ── load data ─────────────────────────────────────────────────────────────────

    meta = load_system_meta(safe_state_path)
    df = load_event_log(safe_state_path, limit=window)
    edges_df = load_causal_edges(safe_state_path)
    drift = load_drift_report()

    if df.empty:
        st.warning("Event log is empty — system has not run yet.")
        st.stop()
        return

    # ── top metrics row ───────────────────────────────────────────────────────────

    col1, col2, col3, col4, col5 = st.columns(5)

    avg_roas = df["roas"].mean() if "roas" in df else 0.0
    total_cycles = meta.get("total_cycles", "—")
    capital = meta.get("capital", "—")
    detected_regime = meta.get("detected_regime", "—")
    avg_error = df["error"].abs().mean() if "error" in df else 0.0

    col1.metric("Avg ROAS", f"{avg_roas:.4f}")
    col2.metric("Total Cycles", f"{total_cycles:,}" if isinstance(total_cycles, int) else total_cycles)
    col3.metric("Capital", f"${capital:,.2f}" if isinstance(capital, float) else capital)
    col4.metric("Detected Regime", str(detected_regime).capitalize())
    col5.metric("Avg |Pred Error|", f"{avg_error:.4f}")

    st.divider()

    # ── ROAS & prediction error charts ───────────────────────────────────────────

    row1_left, row1_right = st.columns(2)

    with row1_left:
        st.subheader("ROAS Over Time")
        roas_df = df[["id", "roas"]].set_index("id")
        roas_df["roas_ma20"] = roas_df["roas"].rolling(20, min_periods=1).mean()
        st.line_chart(roas_df)

    with row1_right:
        st.subheader("Prediction Error Over Time")
        if "error" in df.columns:
            err_df = df[["id", "error"]].set_index("id")
            err_df["abs_error"] = err_df["error"].abs()
            st.line_chart(err_df[["abs_error"]])
        else:
            st.info("No prediction error data yet.")

    # ── uncertainty & budget ──────────────────────────────────────────────────────

    row2_left, row2_right = st.columns(2)

    with row2_left:
        st.subheader("Prediction Interval Width (Uncertainty)")
        if "pred_width" in df.columns and df["pred_width"].notna().any():
            pw_df = df[["id", "pred_width"]].dropna().set_index("id")
            st.line_chart(pw_df)
        else:
            st.info("Conformal intervals not yet available (need ≥30 events for MAPIE).")

    with row2_right:
        st.subheader("Cost per Decision (Budget Allocation)")
        if "cost" in df.columns:
            cost_df = df[["id", "cost"]].set_index("id")
            st.line_chart(cost_df)
        else:
            st.info("No cost data.")

    # ── environment regime & trend ────────────────────────────────────────────────

    st.subheader("Environment — Regime & Trend")

    if "env_regime" in df.columns and "env_trend" in df.columns:
        regime_col, trend_col = st.columns(2)

        with regime_col:
            regime_counts = df["env_regime"].value_counts().rename_axis("Regime").reset_index(name="Count")
            st.dataframe(regime_counts, use_container_width=True, hide_index=True)

        with trend_col:
            trend_df = df[["id", "env_trend"]].set_index("id")
            st.line_chart(trend_df)

    # ── causal graph ──────────────────────────────────────────────────────────────

    st.subheader("Causal Graph — Top Edges (Granger causality)")

    if not edges_df.empty:
        edges_df["weight"] = edges_df["weight"].round(4)
        st.dataframe(
            edges_df.rename(columns={"parent": "Feature", "child": "Target", "weight": "Granger strength"}),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No causal edges learned yet.")

    # ── drift detection status ────────────────────────────────────────────────────

    st.subheader("Drift Detection (Evidently)")

    if drift:
        any_drift = drift.get("any_drift", False)
        drift_status = "🔴 DRIFT DETECTED" if any_drift else "🟢 No drift"
        col_d1, col_d2, col_d3 = st.columns(3)
        col_d1.metric("Status", drift_status)
        col_d2.metric("Total Events Analysed", drift.get("total_events", "—"))
        col_d3.metric("Drifted Features", f"{drift.get('share_drifted', 0):.0%}")

        if "columns" in drift:
            drift_rows = [
                {"Feature": col, "p-value": info.get("p_value", "—"), "Drifted": "Yes" if info.get("drifted") else "No"}
                for col, info in drift["columns"].items()
            ]
            st.dataframe(pd.DataFrame(drift_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No drift report found. Run `scripts/drift_report.py --out drift_report.json` to generate one.")

    # ── system meta details ───────────────────────────────────────────────────────

    with st.expander("System metadata"):
        if meta:
            st.json(meta)
        else:
            st.write("No metadata available.")

    # ── raw event log tail ────────────────────────────────────────────────────────

    with st.expander("Latest 20 events"):
        st.dataframe(df.tail(20), use_container_width=True, hide_index=True)

    # auto-refresh
    try:
        rel_display = safe_state_path.relative_to(_get_dashboard_root())
    except (ValueError, OSError):
        rel_display = safe_state_path.name
    st.caption(f"Showing last {len(df)} events from `{rel_display}`")


if st.runtime.exists():
    render_dashboard()

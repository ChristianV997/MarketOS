#!/usr/bin/env python3
"""
Evidently AI drift detection report.

Compares the most recent `--window` events (current) against the previous
window of equal size (reference) and reports statistical distribution drift
for key system metrics.

Usage:
    python scripts/drift_report.py >> $GITHUB_STEP_SUMMARY
    python scripts/drift_report.py --state-path state/state.db --window 200 --out drift_report.json
"""
import argparse
from dataclasses import dataclass
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from scipy.stats import ks_2samp

try:
    from evidently import Report
    from evidently.presets import DataDriftPreset

    EVIDENTLY_AVAILABLE = True
except ImportError:  # Evidently is optional in lean/local deployments.
    Report = None
    DataDriftPreset = None
    EVIDENTLY_AVAILABLE = False

from backend.core.db_serializer import query as db_query

STATE_PATH = "state/state.db"

# Columns checked for drift — all numeric, all in event_log schema
DRIFT_FEATURES = ["roas", "prediction", "error", "pred_width", "env_trend"]

# p-value threshold (K-S test default in Evidently)
DRIFT_THRESHOLD = 0.05

# Minimum rows required in both reference and current windows
MIN_WINDOW = 20


@dataclass
class _FallbackSnapshot:
    """Minimal Evidently-compatible snapshot backed by SciPy's K-S test.

    Evidently remains the preferred renderer when installed.  This fallback
    preserves the report's decision semantics and JSON parsing contract for
    local development and minimal runtime images where the optional package is
    intentionally absent.
    """

    results: dict

    def json(self) -> str:
        metrics = [
            {
                "metric_name": "DriftedColumnsCount()",
                "value": {"share": self.results["share_drifted"]},
            }
        ]
        for column, info in self.results["columns"].items():
            metrics.append(
                {
                    "metric_name": f"ValueDrift(column={column}, threshold={info['threshold']})",
                    "value": info["p_value"],
                }
            )
        return json.dumps({"metrics": metrics})

    def save_html(self, path: str) -> None:
        rows = "".join(
            "<tr><td>{}</td><td>{:.6f}</td><td>{}</td></tr>".format(
                col, info["p_value"], "drift" if info["drifted"] else "ok"
            )
            for col, info in sorted(self.results["columns"].items())
        )
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(
                "<html><body><h1>Drift Report (SciPy fallback)</h1>"
                "<table><tr><th>Feature</th><th>p-value</th><th>Status</th></tr>"
                f"{rows}</table></body></html>"
            )


def build_drift_snapshot(reference_data: pd.DataFrame, current_data: pd.DataFrame):
    """Run Evidently when available, otherwise use a deterministic K-S fallback."""
    if EVIDENTLY_AVAILABLE:
        return Report([DataDriftPreset()]).run(
            reference_data=reference_data,
            current_data=current_data,
        )

    columns = {}
    for column in reference_data.columns.intersection(current_data.columns):
        reference = reference_data[column].dropna()
        current = current_data[column].dropna()
        if not len(reference) or not len(current):
            continue
        p_value = float(ks_2samp(reference, current).pvalue)
        columns[column] = {
            "p_value": round(p_value, 6),
            "threshold": DRIFT_THRESHOLD,
            "drifted": p_value < DRIFT_THRESHOLD,
        }
    share = sum(info["drifted"] for info in columns.values()) / len(columns) if columns else 0.0
    return _FallbackSnapshot({"share_drifted": share, "columns": columns})


def _load_window(state_path: str, window: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns (reference_df, current_df).
    current  = last `window` rows
    reference = the `window` rows immediately before current
    """
    all_rows = db_query(
        state_path,
        f"""
        SELECT roas, prediction, error, pred_width, env_trend, env_regime, id
        FROM event_log
        ORDER BY id
        """,
    )
    cols = ["roas", "prediction", "error", "pred_width", "env_trend", "env_regime", "id"]
    df = pd.DataFrame(all_rows, columns=cols)

    numeric = [c for c in DRIFT_FEATURES if c in df.columns]
    df[numeric] = df[numeric].apply(pd.to_numeric, errors="coerce")

    n = len(df)
    if n < window * 2:
        # Not enough data: split 50/50
        split = n // 2
    else:
        split = n - window

    ref = df.iloc[:split][numeric].dropna()
    cur = df.iloc[split:][numeric].dropna()
    return ref, cur


def _parse_snapshot(snap) -> dict:
    """Extract per-column drift results from an Evidently Snapshot."""
    j = json.loads(snap.json())
    per_col = {}
    share_drifted = 0.0

    for m in j.get("metrics", []):
        name = m.get("metric_name", "")
        val = m.get("value")

        if "DriftedColumnsCount" in name and isinstance(val, dict):
            share_drifted = val.get("share", 0.0)

        elif name.startswith("ValueDrift"):
            try:
                col = name.split("column=")[1].split(",")[0]
                threshold_str = name.split("threshold=")[1].rstrip(")")
                threshold = float(threshold_str)
                p_val = float(val)
                per_col[col] = {
                    "p_value": round(p_val, 6),
                    "threshold": threshold,
                    "drifted": p_val < threshold,
                }
            except (IndexError, ValueError, TypeError):
                pass

    return {"share_drifted": share_drifted, "columns": per_col}


def _markdown_report(
    results: dict,
    ref_size: int,
    cur_size: int,
    total_events: int,
    window: int,
) -> str:
    cols = results["columns"]
    share = results["share_drifted"]
    any_drift = any(v["drifted"] for v in cols.values())
    status_icon = "🔴" if any_drift else "🟢"
    status_text = "DRIFT DETECTED" if any_drift else "No drift detected"

    lines = [
        "### Evidently Drift Report",
        "",
        f"| | |",
        f"|---|---|",
        f"| Status | {status_icon} **{status_text}** |",
        f"| Reference window | {ref_size:,} events |",
        f"| Current window | {cur_size:,} events |",
        f"| Total events in DB | {total_events:,} |",
        f"| Drifted features | {share:.0%} ({sum(v['drifted'] for v in cols.values())}/{len(cols)}) |",
        "",
        "#### Per-Feature Results (K-S test, α=0.05)",
        "",
        "| Feature | p-value | Status |",
        "|---------|---------|--------|",
    ]

    for col, info in sorted(cols.items()):
        icon = "🔴 Drift" if info["drifted"] else "🟢 OK"
        lines.append(f"| `{col}` | {info['p_value']:.4f} | {icon} |")

    if any_drift:
        drifted_cols = [c for c, v in cols.items() if v["drifted"]]
        lines += [
            "",
            "> **Drifted features:** " + ", ".join(f"`{c}`" for c in drifted_cols),
            "> Model retraining or regime investigation may be warranted.",
        ]
    else:
        lines += ["", "> All features within expected distribution bounds."]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-path", default=STATE_PATH)
    parser.add_argument("--window", type=int, default=200,
                        help="Number of events in each comparison window")
    parser.add_argument("--out", default=None,
                        help="Optional path to write JSON summary")
    parser.add_argument("--html", default=None,
                        help="Optional path to write Evidently HTML report")
    args = parser.parse_args()

    # -- guard: no DB yet --
    if not os.path.exists(args.state_path):
        print("### Evidently Drift Report")
        print()
        print("> No state DB found — run `scripts/run_cycles.py` first.")
        return

    # -- count total events --
    count_rows = db_query(args.state_path, "SELECT COUNT(*) FROM event_log")
    total_events = int(count_rows[0][0]) if count_rows else 0

    if total_events < MIN_WINDOW * 2:
        print("### Evidently Drift Report")
        print()
        print(f"> Not enough data for drift analysis "
              f"({total_events} events, need ≥ {MIN_WINDOW * 2}).")
        return

    ref_df, cur_df = _load_window(args.state_path, args.window)

    if len(ref_df) < MIN_WINDOW or len(cur_df) < MIN_WINDOW:
        print("### Evidently Drift Report")
        print()
        print(f"> Windows too small after NaN drop "
              f"(ref={len(ref_df)}, cur={len(cur_df)}, min={MIN_WINDOW}).")
        return

    # -- run Evidently, with an equivalent SciPy fallback for lean installs --
    snap = build_drift_snapshot(ref_df, cur_df)

    results = _parse_snapshot(snap)
    md = _markdown_report(results, len(ref_df), len(cur_df), total_events, args.window)
    print(md)

    # -- optional JSON output --
    summary = {
        "total_events": total_events,
        "ref_size": len(ref_df),
        "cur_size": len(cur_df),
        "window": args.window,
        "share_drifted": results["share_drifted"],
        "any_drift": any(v["drifted"] for v in results["columns"].values()),
        "columns": results["columns"],
    }

    if args.out:
        os.makedirs(os.path.dirname(args.out) if os.path.dirname(args.out) else ".", exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"\n> Drift JSON saved → `{args.out}`", file=sys.stderr)

    if args.html:
        snap.save_html(args.html)
        print(f"> Drift HTML saved → `{args.html}`", file=sys.stderr)

    return summary


if __name__ == "__main__":
    main()

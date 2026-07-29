"""
Causal graph updater using Granger causality.

For each numeric feature X in the last `_WINDOW` event-log rows we test:
  H0: X_lagged does NOT help predict ROAS beyond ROAS_lagged alone  (AR(1) null)
  H1: X_lagged + ROAS_lagged jointly predict ROAS better  (VAR(1) alternative)

We use the statsmodels F-test at lag=1.  Features with p < ALPHA get a directed
causal edge X → roas with weight = -log10(p), giving stronger edges to more
significant relationships.

Pearson correlation (|r| > PEARSON_FLOOR) is used as a cheap pre-filter to
skip obviously uncorrelated features before the heavier Granger test.

Requires ≥ MIN_ROWS rows so the VAR(1) regression is numerically stable.
"""
import io
import logging
import os
import sys

import numpy as np
try:  # Statsmodels is an optional statistical refinement.
    from statsmodels.tsa.stattools import grangercausalitytests
except ImportError:  # pragma: no cover - minimal-runtime fallback
    grangercausalitytests = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_WINDOW = 100       # rows used per update
_MIN_ROWS = 20      # minimum rows needed for a reliable Granger test
_LAG = 1            # test lag-1 Granger causality
_ALPHA = 0.10       # significance threshold for the F-test
_PEARSON_FLOOR = 0.03  # fast pre-filter: skip features below this Pearson |r|


def update_causal(graph, event_log):
    data = event_log.rows[-_WINDOW:]

    if len(data) < _MIN_ROWS:
        return graph

    all_keys = list(data[0].keys())

    # keep only numeric-valued keys
    numeric_keys = []
    for k in all_keys:
        try:
            vals = [float(row.get(k, 0)) for row in data]
            if not any(np.isnan(v) or np.isinf(v) for v in vals):
                numeric_keys.append(k)
        except (TypeError, ValueError):
            pass

    if "roas" not in numeric_keys:
        return graph

    # build feature matrix
    matrix = np.array(
        [[float(row.get(k, 0)) for k in numeric_keys] for row in data]
    )

    roas_idx = numeric_keys.index("roas")
    roas_col = matrix[:, roas_idx]

    for i, k in enumerate(numeric_keys):
        if k == "roas":
            continue

        x = matrix[:, i]

        # skip constant features
        if np.std(x) < 1e-9 or np.std(roas_col) < 1e-9:
            continue

        # fast Pearson pre-filter
        corr = float(np.corrcoef(x, roas_col)[0, 1])
        if np.isnan(corr) or abs(corr) < _PEARSON_FLOOR:
            continue

        # Granger causality F-test: does x_{t-1} help predict roas_t?
        # In lean deployments, retain a conservative lagged-correlation edge
        # rather than making the whole decision engine unavailable.
        if grangercausalitytests is None:
            lagged_corr = float(np.corrcoef(x[:-1], roas_col[1:])[0, 1])
            if not np.isnan(lagged_corr) and abs(lagged_corr) >= _PEARSON_FLOOR:
                graph.add_edge(k, "roas", round(abs(lagged_corr), 4))
            continue
        try:
            test_data = np.column_stack([roas_col, x])
            # suppress the printed table statsmodels writes to stdout
            _sink = io.StringIO()
            _old_stdout, sys.stdout = sys.stdout, _sink
            try:
                result = grangercausalitytests(test_data, maxlag=_LAG)
            finally:
                sys.stdout = _old_stdout
            p_value = result[_LAG][0]["ssr_ftest"][1]  # F-test p-value

            if p_value < _ALPHA:
                # weight = -log10(p) so stronger significance → higher weight
                weight = round(-np.log10(max(p_value, 1e-10)), 4)
                graph.add_edge(k, "roas", weight)
        except Exception as exc:
            logger.debug("Granger test skipped for %s: %s", k, exc)

    return graph

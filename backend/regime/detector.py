import math

import numpy as np


def apply_macro_override(base_regime: str, macro_signals: dict) -> str:
    """Apply FRED macro signal overrides to a base regime classification.

    Rules:
      - VIX > 30  → force ``"volatile"`` (fear gauge above stress threshold)
      - Negative GDP growth + base ``"stable"`` → force ``"decay"``

    Returns the (possibly overridden) regime string.
    """
    if not macro_signals:
        return base_regime

    vix = macro_signals.get("vix")
    gdp_growth = macro_signals.get("gdp_growth")

    if vix is not None and float(vix) > 30:
        return "volatile"

    if gdp_growth is not None and float(gdp_growth) < 0 and base_regime == "stable":
        return "decay"

    return base_regime


# ── Phase 4: CUSUM (Page-Hinkley) changepoint detection defaults ──────────
#
# Two-sided CUSUM is the statistically-optimal sequential test (Lorden 1971,
# Moustakides 1986) for minimizing worst-case detection delay at a fixed
# false-alarm rate, for exactly the alternative a regime flip represents (a
# sustained mean shift). O(1) per observation, no priors, no new
# dependencies. Defaults derived from Siegmund's ARL approximations:
#   ARL0 ~= (e^(2kh) - 2kh - 1) / (2k^2)  — expected cycles between false
#           alarms on a genuinely stable series. k=0.5, h=8.0 -> ARL0 ~= 5940.
#   ARL1 ~= h / (delta - k)               — expected detection delay once a
#           shift of size delta*sigma begins. delta=1 -> ARL1 ~= 16 cycles;
#           delta=2 -> ARL1 ~= 5.3 cycles (bigger shifts caught faster).
CUSUM_K = 0.5
CUSUM_H = 8.0
CUSUM_WARMUP = 15
CUSUM_MIN_SIGMA = 0.05


class RegimeDetector:

    def __init__(self, window=30, cusum_k=CUSUM_K, cusum_h=CUSUM_H,
                 cusum_warmup=CUSUM_WARMUP, cusum_min_sigma=CUSUM_MIN_SIGMA):
        self.window = window
        self.cusum_k = cusum_k
        self.cusum_h = cusum_h
        self.cusum_warmup = cusum_warmup
        self.cusum_min_sigma = cusum_min_sigma

        self._cusum_pos = 0.0
        self._cusum_neg = 0.0
        self._baseline_mean = None
        self._baseline_std = None
        self._wu_n = 0          # Welford warm-up count
        self._wu_mean = 0.0
        self._wu_M2 = 0.0
        self._seen_rows = 0     # index into event_log.rows already consumed
        self._cycles_since_reset = 0

    def detect(self, event_log, macro_signals: dict | None = None):
        """Detect the current market regime from *event_log*.

        When *macro_signals* is provided (dict with ``vix`` and/or
        ``gdp_growth`` keys), FRED macro overrides are applied after the
        base classification.

        Unchanged by Phase 4 — the hardcoded thresholds below are the
        production classification and ~20 existing tests hardcode exact
        expected outputs against them. ``detect_changepoint()`` below is an
        additive, independently-stateful signal that never reads or writes
        any state used here.
        """
        rows = event_log.rows[-self.window:]

        if len(rows) < 10:
            return "unknown"

        roas = np.array([r.get("roas", 0) for r in rows])

        # variance
        var = np.var(roas)

        # trend (slope)
        x = np.arange(len(roas))
        slope = np.polyfit(x, roas, 1)[0]

        # volatility spikes
        diffs = np.diff(roas)
        volatility = np.std(diffs)

        # base classification
        if var < 0.02 and abs(slope) < 0.01:
            base = "stable"
        elif slope > 0.02:
            base = "growth"
        elif slope < -0.02:
            base = "decay"
        elif volatility > 0.1:
            base = "volatile"
        else:
            base = "neutral"

        return apply_macro_override(base, macro_signals or {})

    # ── Phase 4: additive changepoint detection ─────────────────────────

    def _cusum_reset(self):
        self._cusum_pos = 0.0
        self._cusum_neg = 0.0
        self._baseline_mean = None
        self._baseline_std = None
        self._wu_n = 0
        self._wu_mean = 0.0
        self._wu_M2 = 0.0
        self._cycles_since_reset = 0

    def _cusum_observe(self, x: float) -> dict:
        direction = None
        is_cp = False

        if self._baseline_mean is None:
            self._wu_n += 1
            delta = x - self._wu_mean
            self._wu_mean += delta / self._wu_n
            delta2 = x - self._wu_mean
            self._wu_M2 += delta * delta2
            if self._wu_n >= self.cusum_warmup:
                self._baseline_mean = self._wu_mean
                self._baseline_std = max(
                    math.sqrt(self._wu_M2 / (self._wu_n - 1)) if self._wu_n > 1
                    else self.cusum_min_sigma,
                    self.cusum_min_sigma,
                )
        else:
            z = (x - self._baseline_mean) / self._baseline_std
            self._cusum_pos = max(0.0, self._cusum_pos + z - self.cusum_k)
            self._cusum_neg = max(0.0, self._cusum_neg - z - self.cusum_k)
            is_cp = self._cusum_pos > self.cusum_h or self._cusum_neg > self.cusum_h
            if is_cp:
                direction = "up" if self._cusum_pos > self.cusum_h else "down"
                self._cusum_reset()   # re-anchor to the new regime

        self._cycles_since_reset += 1
        return {"is_changepoint": is_cp, "direction": direction}

    def detect_changepoint(self, event_log) -> dict:
        """Stateful, online, two-sided CUSUM (Page-Hinkley) changepoint signal.

        Additive to ``detect()``: consumes only newly-appended event_log
        rows since the previous call (tracked via ``self._seen_rows``),
        never reads or mutates ``detect()``'s state or hardcoded thresholds.

        Returns:
            {is_changepoint, probability, direction, cusum_pos, cusum_neg,
             baseline_mean, baseline_std, status, cycles_since_reset}
        """
        rows = event_log.rows
        # guard against event_log's row cap ever rewinding _seen_rows past
        # the current length (defensive; not expected in normal operation)
        self._seen_rows = min(self._seen_rows, len(rows))
        new_rows = rows[self._seen_rows:]
        self._seen_rows = len(rows)

        last_result = {"is_changepoint": False, "direction": None}
        for r in new_rows:
            last_result = self._cusum_observe(float(r.get("roas", 0.0)))

        status = "warming_up" if self._baseline_mean is None else "monitoring"
        probability = 0.0 if status == "warming_up" else min(
            1.0, max(self._cusum_pos, self._cusum_neg) / self.cusum_h
        )

        return {
            "is_changepoint": last_result["is_changepoint"],
            "probability": probability,
            "direction": last_result["direction"],
            "cusum_pos": round(self._cusum_pos, 4),
            "cusum_neg": round(self._cusum_neg, 4),
            "baseline_mean": self._baseline_mean,
            "baseline_std": self._baseline_std,
            "status": status,
            "cycles_since_reset": self._cycles_since_reset,
        }


detector = RegimeDetector()

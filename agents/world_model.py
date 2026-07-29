import numpy as np
from sklearn.linear_model import Ridge
try:  # MAPIE improves intervals, but must not make the execution loop unimportable.
    from mapie.regression import SplitConformalRegressor
except ImportError:  # pragma: no cover - covered through the fallback behaviour
    SplitConformalRegressor = None  # type: ignore[assignment,misc]

# Minimum rows needed so calibration set has ≥ 1/alpha = 10 samples
# at 40% cal split: need ≥ 10/0.4 = 25 rows; use 30 for margin
_MIN_ROWS = 30
# Fraction used for the conformalization set
_CALIB_FRAC = 0.4
# 90% marginal coverage guarantee (requires ≥ 10 calibration samples)
_CONFIDENCE = 0.9


class WorldModel:

    HORIZONS = ["6h", "12h", "24h"]

    def __init__(self):
        # per-horizon: fitted Ridge (for point prediction) + SplitConformal (for intervals)
        self._ridge: dict[str, Ridge] = {}
        self._conformal: dict[str, object] = {}
        self._residual_quantiles: dict[str, float] = {}
        self._fitted: set[str] = set()

    def _featurize(self, action: dict) -> np.ndarray:
        return np.array([float(v) for v in action.values()], dtype=float)

    def train(self, event_log) -> None:
        rows = event_log.rows
        if len(rows) < _MIN_ROWS:
            return

        features, targets = [], {h: [] for h in self.HORIZONS}
        for r in rows:
            action = {"variant": r.get("variant", 0)}
            features.append(self._featurize(action))
            base = r.get("roas", 0)
            targets["6h"].append(r.get("roas_6h", base))
            targets["12h"].append(r.get("roas_12h", base))
            targets["24h"].append(r.get("roas_24h", base))

        X = np.array(features)
        n = len(X)
        split = max(1, int(n * (1 - _CALIB_FRAC)))
        X_train, X_cal = X[:split], X[split:]

        for h in self.HORIZONS:
            y = np.array(targets[h])
            y_train, y_cal = y[:split], y[split:]

            # 1. fit Ridge on train split
            ridge = Ridge(alpha=1.0)
            ridge.fit(X_train, y_train)
            self._ridge[h] = ridge

            # 2. Use MAPIE when installed; otherwise retain conformal-style
            # residual calibration around the same Ridge point estimator.
            if SplitConformalRegressor is not None:
                conformal = SplitConformalRegressor(
                    estimator=ridge,
                    prefit=True,
                    confidence_level=_CONFIDENCE,
                )
                conformal.conformalize(X_cal, y_cal)
                self._conformal[h] = conformal
            else:
                residuals = np.abs(y_cal - ridge.predict(X_cal))
                self._residual_quantiles[h] = float(np.quantile(residuals, _CONFIDENCE)) if len(residuals) else 0.3
            self._fitted.add(h)

    def predict(self, action: dict) -> dict:
        """
        Returns point estimates + 90%-coverage conformal prediction intervals.

        Keys:
            roas_6h, roas_12h, roas_24h           — point estimates
            lo_6h,   lo_12h,   lo_24h             — interval lower bounds
            hi_6h,   hi_12h,   hi_24h             — interval upper bounds
            width_6h, width_12h, width_24h         — interval widths (uncertainty proxy)
        """
        x = self._featurize(action).reshape(1, -1)
        result = {}

        for h in self.HORIZONS:
            if h not in self._fitted:
                result[f"roas_{h}"] = 1.0
                result[f"lo_{h}"] = 0.7
                result[f"hi_{h}"] = 1.3
                result[f"width_{h}"] = 0.6  # wide default = high uncertainty
                continue

            pt = float(self._ridge[h].predict(x)[0])
            if h in self._residual_quantiles:
                radius = self._residual_quantiles[h]
                lo, hi = pt - radius, pt + radius
            else:
                try:
                    _, intervals = self._conformal[h].predict_interval(x)  # type: ignore[union-attr]
                    lo = float(intervals[0, 0, 0])
                    hi = float(intervals[0, 1, 0])
                except ValueError:
                    # calibration set too small for the requested confidence level
                    lo = pt - 0.3
                    hi = pt + 0.3

            result[f"roas_{h}"] = pt
            result[f"lo_{h}"] = lo
            result[f"hi_{h}"] = hi
            result[f"width_{h}"] = max(0.0, hi - lo)

        return result

    @property
    def mean_uncertainty(self) -> float:
        """Mean interval width across fitted horizons — 0 if not yet fitted."""
        if not self._fitted:
            return 1.0
        widths = []
        dummy = self._featurize({"variant": 1}).reshape(1, -1)
        for h in self._fitted:
            if h in self._residual_quantiles:
                widths.append(max(0.0, 2 * self._residual_quantiles[h]))
            else:
                _, ivs = self._conformal[h].predict_interval(dummy)  # type: ignore[union-attr]
                widths.append(max(0.0, float(ivs[0, 1, 0]) - float(ivs[0, 0, 0])))
        return sum(widths) / len(widths)


world_model = WorldModel()

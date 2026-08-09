"""backend.validation.shadow_flag_report — read-only validation harness for
the shadow-mode ``_LIVE`` flags scattered across the decision/learning/risk
stack (``SCORING_NORMALIZE_LIVE``, ``PRODUCT_BANDIT_LIVE``,
``REGIME_CONFIDENCE_WEIGHTING_LIVE``, ``CALIBRATION_HOLDOUT_LIVE``,
``RISK_ADAPTIVE_LIVE``, ``ORGANIC_GATE_LIVE``, ``CAPITAL_POLICY_LIVE``).

Every one of these flags already journals both its legacy-path and
new-path value to ``event_store`` on every cycle (the "canary diff"
pattern already used throughout this codebase) — this harness reads that
journal back and produces descriptive statistics plus a simple go/no-go
signal per flag, so flipping to live is a decision made from data instead
of a leap of faith.

This module makes NO decisions and flips NO flags itself — it is
read-only reporting. A human (or a future automated gate) reads
``generate_report()``'s output and decides.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, stdev
from typing import Any

from scipy import stats as _scipy_stats

from backend.orchestration.event_store import EventStore, event_store as _default_event_store

_MIN_SAMPLES = 30
_SIGNIFICANCE_LEVEL = 0.05


@dataclass(frozen=True)
class MetricComparison:
    """One legacy-vs-shadow numeric metric extracted from a journaled event."""
    label: str
    legacy_key: str
    shadow_key: str
    # When true, a *smaller* shadow value is the improvement (e.g. calibration
    # uncertainty) — deltas are computed as legacy - shadow instead of
    # shadow - legacy so "positive delta" always means "shadow is better".
    lower_is_better: bool = False


@dataclass(frozen=True)
class FlagSpec:
    flag_name: str          # the env var name, e.g. "PRODUCT_BANDIT_LIVE"
    event_type: str         # event_store "event" field to filter on
    kind: str                # "numeric" | "boolean" | "reallocation"
    metrics: tuple[MetricComparison, ...] = ()   # for kind == "numeric"
    legacy_key: str = ""     # for kind == "boolean"
    shadow_key: str = ""     # for kind == "boolean"


FLAG_SPECS: tuple[FlagSpec, ...] = (
    FlagSpec(
        "SCORING_NORMALIZE_LIVE", "shadow_decision_scoring", "numeric",
        metrics=(MetricComparison("score", "legacy_score", "normalized_score"),),
    ),
    FlagSpec(
        "PRODUCT_BANDIT_LIVE", "shadow_product_bandit_weighting", "numeric",
        metrics=(MetricComparison("bandit_weight", "bandit_w_stub", "bandit_w_used"),),
    ),
    FlagSpec(
        "REGIME_CONFIDENCE_WEIGHTING_LIVE", "shadow_regime_confidence_weighting", "numeric",
        metrics=(MetricComparison("regime_bonus", "regime_bonus_raw", "regime_bonus_adjusted"),),
    ),
    FlagSpec(
        "CALIBRATION_HOLDOUT_LIVE", "shadow_calibration_stats", "numeric",
        metrics=(
            MetricComparison("bias_magnitude", "legacy_bias", "holdout_bias", lower_is_better=True),
            MetricComparison("uncertainty", "legacy_uncertainty", "holdout_uncertainty", lower_is_better=True),
        ),
    ),
    FlagSpec(
        "RISK_ADAPTIVE_LIVE", "shadow_adaptive_risk", "numeric",
        metrics=(
            MetricComparison("max_drawdown", "static_max_drawdown", "adaptive_max_drawdown"),
            MetricComparison("max_daily_spend", "static_max_daily_spend", "adaptive_max_daily_spend"),
        ),
    ),
    FlagSpec(
        "ORGANIC_GATE_LIVE", "shadow_organic_gate", "boolean",
        legacy_key="legacy_verdict", shadow_key="blended_verdict",
    ),
    FlagSpec(
        "CAPITAL_POLICY_LIVE", "shadow_capital_policy", "reallocation",
    ),
)


@dataclass
class MetricResult:
    label: str
    n: int
    mean_delta: float | None = None
    p_value: float | None = None
    significant: bool = False
    recommendation: str = "insufficient_data"

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label, "n": self.n, "mean_delta": self.mean_delta,
            "p_value": self.p_value, "significant": self.significant,
            "recommendation": self.recommendation,
        }


@dataclass
class FlagReport:
    flag_name: str
    event_type: str
    sample_count: int
    metrics: list[MetricResult] = field(default_factory=list)
    agreement_rate: float | None = None       # boolean flags only
    mean_abs_reallocation_frac: float | None = None   # capital_policy only
    overall_recommendation: str = "insufficient_data"

    def to_dict(self) -> dict[str, Any]:
        return {
            "flag_name": self.flag_name, "event_type": self.event_type,
            "sample_count": self.sample_count,
            "metrics": [m.to_dict() for m in self.metrics],
            "agreement_rate": self.agreement_rate,
            "mean_abs_reallocation_frac": self.mean_abs_reallocation_frac,
            "overall_recommendation": self.overall_recommendation,
        }


def _numeric_metric_result(
    events: list[dict], metric: MetricComparison, *, min_samples: int, significance_level: float,
) -> MetricResult:
    deltas: list[float] = []
    for e in events:
        data = e.get("data") or {}
        legacy = data.get(metric.legacy_key)
        shadow = data.get(metric.shadow_key)
        if legacy is None or shadow is None:
            continue
        try:
            legacy_f, shadow_f = float(legacy), float(shadow)
        except (TypeError, ValueError):
            continue
        delta = (shadow_f - legacy_f) if not metric.lower_is_better else (legacy_f - shadow_f)
        deltas.append(delta)

    n = len(deltas)
    if n < min_samples:
        return MetricResult(metric.label, n, recommendation="insufficient_data")

    mean_delta = mean(deltas)
    sample_stdev = stdev(deltas) if n > 1 else 0.0
    if sample_stdev == 0.0:
        p_value = 0.0 if mean_delta != 0.0 else 1.0
    else:
        stderr = sample_stdev / (n ** 0.5)
        t_stat = mean_delta / stderr
        p_value = float(2 * (1 - _scipy_stats.t.cdf(abs(t_stat), df=n - 1)))

    significant = p_value <= significance_level
    if significant and mean_delta > 0:
        recommendation = "recommend_flip"
    elif significant and mean_delta < 0:
        recommendation = "do_not_flip"
    else:
        recommendation = "insufficient_signal"

    return MetricResult(
        metric.label, n, round(mean_delta, 6), round(p_value, 6), significant, recommendation,
    )


def _boolean_flag_report(spec: FlagSpec, events: list[dict], *, min_samples: int) -> FlagReport:
    pairs = []
    for e in events:
        data = e.get("data") or {}
        legacy = data.get(spec.legacy_key)
        shadow = data.get(spec.shadow_key)
        if legacy is None or shadow is None:
            continue
        pairs.append((bool(legacy), bool(shadow)))

    n = len(pairs)
    if n < min_samples:
        return FlagReport(spec.flag_name, spec.event_type, n, overall_recommendation="insufficient_data")

    agreement_rate = round(sum(1 for a, b in pairs if a == b) / n, 4)
    # A low agreement rate means flipping changes real launch decisions
    # often — that needs human review, not an automated flip. A high rate
    # means the new path rarely disagrees with legacy, i.e. flipping is
    # low-risk (though also low-impact).
    recommendation = "low_risk_flip" if agreement_rate >= 0.9 else "review_disagreements"
    return FlagReport(
        spec.flag_name, spec.event_type, n,
        agreement_rate=agreement_rate, overall_recommendation=recommendation,
    )


def _reallocation_flag_report(spec: FlagSpec, events: list[dict], *, min_samples: int) -> FlagReport:
    """capital_policy's shadow event carries whole allocation vectors, not a
    single scalar — there's no legacy "reward" attached to each event to run
    a significance test against, so this reports descriptive reallocation
    magnitude only and always defers the actual go/no-go to a human.
    """
    fracs: list[float] = []
    for e in events:
        data = e.get("data") or {}
        legacy_budgets = data.get("legacy_budgets")
        policy = data.get("policy") or {}
        new_budgets = policy.get("budgets")
        total = data.get("total_budget")
        if not legacy_budgets or not new_budgets or not total:
            continue
        if len(legacy_budgets) != len(new_budgets) or total <= 0:
            continue
        abs_diff = sum(abs(a - b) for a, b in zip(legacy_budgets, new_budgets))
        fracs.append(abs_diff / (2 * total))  # 0 = identical, 1 = fully reallocated

    n = len(fracs)
    if n < min_samples:
        return FlagReport(spec.flag_name, spec.event_type, n, overall_recommendation="insufficient_data")

    return FlagReport(
        spec.flag_name, spec.event_type, n,
        mean_abs_reallocation_frac=round(mean(fracs), 4),
        overall_recommendation="insufficient_signal_requires_human_review",
    )


def _numeric_flag_report(
    spec: FlagSpec, events: list[dict], *, min_samples: int, significance_level: float,
) -> FlagReport:
    metric_results = [
        _numeric_metric_result(events, metric, min_samples=min_samples, significance_level=significance_level)
        for metric in spec.metrics
    ]
    sample_count = max((m.n for m in metric_results), default=0)

    recommendations = {m.recommendation for m in metric_results}
    if not metric_results or recommendations == {"insufficient_data"}:
        overall = "insufficient_data"
    elif "do_not_flip" in recommendations:
        overall = "do_not_flip"
    elif recommendations == {"recommend_flip"}:
        overall = "recommend_flip"
    else:
        overall = "insufficient_signal"

    return FlagReport(
        spec.flag_name, spec.event_type, sample_count,
        metrics=metric_results, overall_recommendation=overall,
    )


def generate_flag_report(spec: FlagSpec, *, store: EventStore | None = None,
                          min_samples: int = _MIN_SAMPLES,
                          significance_level: float = _SIGNIFICANCE_LEVEL) -> FlagReport:
    """Read *store* (defaults to the singleton event_store) for every
    journaled event of *spec*'s type and produce one flag's report.
    """
    events = (store or _default_event_store).events_of_type(spec.event_type)
    if spec.kind == "boolean":
        return _boolean_flag_report(spec, events, min_samples=min_samples)
    if spec.kind == "reallocation":
        return _reallocation_flag_report(spec, events, min_samples=min_samples)
    return _numeric_flag_report(spec, events, min_samples=min_samples, significance_level=significance_level)


def generate_report(*, store: EventStore | None = None, min_samples: int = _MIN_SAMPLES,
                     significance_level: float = _SIGNIFICANCE_LEVEL) -> dict[str, Any]:
    """Full shadow-flag validation report across all seven known flags."""
    reports = [
        generate_flag_report(spec, store=store, min_samples=min_samples, significance_level=significance_level)
        for spec in FLAG_SPECS
    ]
    return {"flags": [r.to_dict() for r in reports]}


__all__ = [
    "FlagSpec", "MetricComparison", "FlagReport", "MetricResult",
    "FLAG_SPECS", "generate_flag_report", "generate_report",
]

"""Advisory regression budgets over canonical + sandbox-pattern paths.

Budget outcomes are pass / regression / unavailable / not_run / malformed.
This file is not a merge authority and not a quality gate.
"""
from __future__ import annotations

import hashlib
import json
import platform
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from evaluation.perf.call_graph import audit as call_graph_audit
from evaluation.perf.canonical_adapters import measure_all_canonical
from evaluation.perf.commerce_engine import CommerceEnginePerfError, measure_algorithms, process_offers


SCHEMA = "commerce-regression-benchmark-v3"
WARMUP = 1
REPEATS = 5

# Advisory only. Hardware in this sandbox is not the operator workstation.
BUDGETS_MS = {
    "sandbox_preprocess_100": 80.0,
    "sandbox_preprocess_500": 250.0,
    "sandbox_preprocess_1500": 900.0,
    "sandbox_preprocess_5000": 3500.0,
    "sandbox_conflict_indexed_1500": 40.0,
    "canonical_supplier_50": 250.0,
    "canonical_synthesis_25": 400.0,
    "canonical_export": 400.0,
    "canonical_commerce_cycle": 2000.0,
    "canonical_existing_cycle_benchmark": 8000.0,
    "replay_hash": 80.0,
}

BUDGETS_OUTPUT_BYTES = {
    "sandbox_preprocess_1500": 2_000_000,
    "canonical_export": 2_000_000,
}

BUDGETS_RSS_KB = {
    "sandbox_preprocess_1500": 512_000,
}


@dataclass(frozen=True)
class BudgetVerdict:
    name: str
    status: str
    observed_ms: float | None
    budget_ms: float | None
    notes: tuple[str, ...]
    observed_output_bytes: int | None = None
    observed_rss_kb: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "observed_ms": self.observed_ms,
            "budget_ms": self.budget_ms,
            "observed_output_bytes": self.observed_output_bytes,
            "observed_rss_kb": self.observed_rss_kb,
            "notes": list(self.notes),
        }


def _mean(samples: list[float]) -> float:
    return round(statistics.fmean(samples), 3)


def _stdev(samples: list[float]) -> float:
    if len(samples) < 2:
        return 0.0
    return round(statistics.pstdev(samples), 3)


def _rss_kb() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    return int(parts[1])
    except OSError:
        return None
    return None


def _time_call(fn: Callable[[], Any], *, warmup: int = WARMUP, repeats: int = REPEATS) -> dict[str, Any]:
    for _ in range(max(0, warmup)):
        fn()
    samples: list[float] = []
    last: Any = None
    fingerprints: list[str] = []
    for _ in range(max(1, repeats)):
        started = time.perf_counter()
        last = fn()
        samples.append((time.perf_counter() - started) * 1000)
        payload = last.to_dict() if hasattr(last, "to_dict") else last
        fingerprints.append(
            hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        )
    return {
        "samples_ms": [round(item, 3) for item in samples],
        "mean_ms": _mean(samples),
        "stdev_ms": _stdev(samples),
        "min_ms": round(min(samples), 3),
        "max_ms": round(max(samples), 3),
        "replay_stable": len(set(fingerprints)) == 1,
        "last": last,
    }


def _rows(size: int, scenario: str = "many_candidates") -> list[dict[str, Any]]:
    from scripts.run_commerce_engine_perf import build_rows

    return build_rows(scenario, size)


def judge(
    name: str,
    observed_ms: float | None,
    *,
    status_hint: str | None = None,
    output_bytes: int | None = None,
    rss_kb: int | None = None,
) -> BudgetVerdict:
    budget = BUDGETS_MS.get(name)
    notes = ["advisory_only", "not_a_merge_gate"]
    if status_hint in {"unavailable", "not_run", "malformed"}:
        return BudgetVerdict(name, status_hint, observed_ms, budget, tuple(notes), output_bytes, rss_kb)
    if observed_ms is None or budget is None:
        return BudgetVerdict(name, "not_run", observed_ms, budget, tuple(notes), output_bytes, rss_kb)
    status = "pass" if observed_ms <= budget else "regression"
    size_budget = BUDGETS_OUTPUT_BYTES.get(name)
    if size_budget is not None and output_bytes is not None and output_bytes > size_budget:
        status = "regression"
        notes.append("output_size_over_advisory_budget")
    rss_budget = BUDGETS_RSS_KB.get(name)
    if rss_budget is not None and rss_kb is not None and rss_kb > rss_budget:
        status = "regression"
        notes.append("rss_over_advisory_budget")
    return BudgetVerdict(name, status, observed_ms, budget, tuple(notes), output_bytes, rss_kb)


def run_sandbox_scale(sizes: tuple[int, ...] = (100, 500, 1500, 5000)) -> dict[str, Any]:
    stages: list[dict[str, Any]] = []
    verdicts: list[BudgetVerdict] = []
    for size in sizes:
        try:
            rows = _rows(size)
        except Exception as exc:  # noqa: BLE001
            stages.append({"size": size, "status": "malformed", "error": str(exc)})
            verdicts.append(judge(f"sandbox_preprocess_{size}", None, status_hint="malformed"))
            continue
        encoded = json.dumps(rows, default=str)
        if size >= 5000 and len(encoded) > 2_000_000:
            stages.append({"size": size, "status": "not_run", "reason": "payload_too_large_for_sandbox"})
            verdicts.append(judge(f"sandbox_preprocess_{size}", None, status_hint="not_run"))
            continue
        try:
            timed = _time_call(
                lambda r=rows, n=size: process_offers(r, job_name=f"scale.{n}", max_rows=max(n, 2048))
            )
        except CommerceEnginePerfError as exc:
            stages.append({"size": size, "status": "not_run", "reason": str(exc)})
            verdicts.append(judge(f"sandbox_preprocess_{size}", None, status_hint="not_run"))
            continue
        last = timed.pop("last")
        output_bytes = len(json.dumps(last.to_dict(), default=str))
        rss = _rss_kb()
        stages.append(
            {
                "size": size,
                "status": "measured",
                "path_class": "sandbox_pattern_not_production",
                "accepted": len(last.accepted),
                "rejected": len(last.rejected),
                "live_attestation": last.live_attestation,
                "replay_identity": last.replay_identity,
                "output_bytes": output_bytes,
                "rss_kb": rss,
                **timed,
            }
        )
        verdicts.append(
            judge(
                f"sandbox_preprocess_{size}",
                timed["mean_ms"],
                output_bytes=output_bytes,
                rss_kb=rss,
            )
        )
    comparison = measure_algorithms(_rows(1500), repeats=3)
    verdicts.append(judge("sandbox_conflict_indexed_1500", comparison["indexed_mean_ms"]))
    return {
        "stages": stages,
        "algorithm_comparison": comparison,
        "verdicts": [item.to_dict() for item in verdicts],
        "disclaimer": "sandbox_pattern timings are not MarketOS production performance",
    }


def run_canonical_matrix() -> dict[str, Any]:
    results = measure_all_canonical(supplier_offers=50, synthesis_candidates=25)
    mapped = {
        "supplier_normalization": "canonical_supplier_50",
        "opportunity_synthesis": "canonical_synthesis_25",
        "client_safe_export": "canonical_export",
        "commerce_cycle": "canonical_commerce_cycle",
        "existing_cycle_benchmark": "canonical_existing_cycle_benchmark",
        "replay_hashing": "replay_hash",
    }
    verdicts = []
    for item in results:
        budget_name = mapped.get(item.path_id)
        if budget_name:
            verdicts.append(
                judge(
                    budget_name,
                    item.wall_ms,
                    status_hint=item.status if item.status != "measured" else None,
                    output_bytes=item.output_size,
                )
            )
        else:
            verdicts.append(
                BudgetVerdict(
                    item.path_id,
                    item.status,
                    item.wall_ms,
                    None,
                    ("no_numeric_budget", "advisory_only"),
                    item.output_size,
                    None,
                )
            )
    return {
        "results": [item.to_dict() for item in results],
        "verdicts": [item.to_dict() for item in verdicts],
        "any_canonical_measured": any(item.status == "measured" for item in results),
    }


def run_stress_equivalence() -> dict[str, Any]:
    scenarios = (
        "duplicate_ids",
        "conflicting_offers",
        "mixed_currency",
        "mixed_lanes",
        "stale_records",
        "malformed",
        "secret_shaped",
        "mixed_evidence",
    )
    records = []
    for scenario in scenarios:
        rows = _rows(80, scenario)
        first = process_offers(rows, job_name=f"eq.{scenario}")
        second = process_offers(rows, job_name=f"eq.{scenario}")
        records.append(
            {
                "scenario": scenario,
                "replay_equal": first.replay_identity == second.replay_identity,
                "live_attestation": first.live_attestation,
                "currencies": list(first.currencies),
                "failure_class": first.failure_class,
                "accepted": len(first.accepted),
                "rejected": len(first.rejected),
                "candidate_loss": first.row_count_in != (len(first.accepted) + len(first.rejected)),
            }
        )
    return {
        "records": records,
        "all_replay_stable": all(item["replay_equal"] for item in records),
        "no_live_upgrade": all(item["live_attestation"] is False for item in records),
        "no_candidate_loss": all(item["candidate_loss"] is False for item in records),
        "no_currency_conversion": all(
            set(item["currencies"]) <= {"MXN", "USD", "CAD", "EUR", "GBP"} for item in records
        ),
    }


def build_report() -> dict[str, Any]:
    sandbox = run_sandbox_scale()
    canonical = run_canonical_matrix()
    equivalence = run_stress_equivalence()
    return {
        "schema": SCHEMA,
        "record_kind": "advisory_benchmark",
        "merge_authority": False,
        "quality_gate": False,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "warmup": WARMUP,
            "repeats": REPEATS,
            "timer": "time.perf_counter",
            "rss_kb": _rss_kb(),
        },
        "disclaimer": (
            "Sandbox-pattern timings are not MarketOS production performance. "
            "Canonical timings are only valid when status=measured on a checkout "
            "that actually imports those modules. Hardware differs across machines. "
            "Passing an advisory budget does not imply commercial viability."
        ),
        "call_graph": call_graph_audit(),
        "sandbox_pattern": sandbox,
        "canonical_paths": canonical,
        "equivalence": equivalence,
    }

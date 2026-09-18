from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.perf.canonical_adapters import (
    measure_all_canonical,
    measure_financial_kernel,
    measure_research_to_decision,
)
from evaluation.perf.regression_benchmark import build_report, judge, run_stress_equivalence


def test_canonical_adapters_never_claim_live_and_classify_missing_paths() -> None:
    results = {item.path_id: item for item in measure_all_canonical(supplier_offers=8, synthesis_candidates=4)}
    assert "supplier_normalization" in results
    assert "opportunity_synthesis" in results
    assert "research_to_decision" in results
    assert "financial_kernel" in results
    for item in results.values():
        assert item.live_attestation is False
        assert item.status in {"measured", "unavailable", "not_run", "malformed"}
    kernel = measure_financial_kernel()
    assert kernel.status in {"unavailable", "not_run"}
    research = measure_research_to_decision()
    assert research.status == "unavailable"


def test_advisory_budgets_are_not_merge_gates() -> None:
    passed = judge("sandbox_preprocess_100", 1.0)
    assert passed.status == "pass"
    slow = judge("sandbox_preprocess_100", 10_000.0)
    assert slow.status == "regression"
    missing = judge("canonical_commerce_cycle", None, status_hint="unavailable")
    assert missing.status == "unavailable"
    assert "advisory_only" in passed.notes


def test_stress_equivalence_no_evidence_upgrade() -> None:
    report = run_stress_equivalence()
    assert report["all_replay_stable"] is True
    assert report["no_live_upgrade"] is True
    mixed = next(item for item in report["records"] if item["scenario"] == "mixed_currency")
    assert set(mixed["currencies"]) <= {"MXN", "USD", "CAD", "EUR", "GBP"}


def test_full_report_schema() -> None:
    report = build_report()
    assert report["schema"] == "commerce-regression-benchmark-v2"
    assert report["merge_authority"] is False
    assert report["quality_gate"] is False
    assert "sandbox_pattern" in report
    assert "canonical_paths" in report
    assert report["equivalence"]["no_live_upgrade"] is True

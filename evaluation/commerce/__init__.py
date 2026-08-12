"""Deterministic evaluation of the Phase 1 Commerce Intelligence stack."""

from .models import ComparisonReport, EngineEvaluation, EvaluationReport, ReproducibilityReport
from .service import (
    EvaluationInput,
    compare_evaluations,
    evaluate_input,
    evaluation_events,
    load_evaluation_input,
)
from .readiness import Phase1ReadinessReport, build_from_paths, build_phase1_readiness
from .benchmark_matrix import BenchmarkMatrixReport, build_benchmark_from_paths, build_benchmark_matrix
from .public_market_benchmark import PublicMarketBenchmarkReport, build_public_market_benchmark
from .intelligence_adapter_plan import IntelligenceAdapterPlanReport, build_intelligence_adapter_plan
from .dataforseo_adapter import DataForSEOAdapterReport, build_dataforseo_adapter_report

__all__ = [
    "ComparisonReport",
    "EngineEvaluation",
    "EvaluationInput",
    "EvaluationReport",
    "ReproducibilityReport",
    "compare_evaluations",
    "evaluate_input",
    "evaluation_events",
    "load_evaluation_input",
    "Phase1ReadinessReport",
    "build_from_paths",
    "build_phase1_readiness",
    "BenchmarkMatrixReport",
    "build_benchmark_from_paths",
    "build_benchmark_matrix",
    "PublicMarketBenchmarkReport",
    "build_public_market_benchmark",
    "IntelligenceAdapterPlanReport",
    "build_intelligence_adapter_plan",
    "DataForSEOAdapterReport",
    "build_dataforseo_adapter_report",
]

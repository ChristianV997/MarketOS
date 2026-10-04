#!/usr/bin/env python3
"""Operator compatibility wrapper for the canonical high-value-path harness."""
from __future__ import annotations

import sys
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from backend.deployment.high_value_path_harness import (
    PATH_IDS,
    ROOT,
    VALID_STATUSES,
    _record,
    inspect_container_files,
    is_colab_available,
    main,
    measure_commerce_cycle,
    measure_competition,
    measure_container_contract,
    measure_dependency_unavailable,
    measure_opportunity_synthesis,
    measure_replay,
    measure_report_export,
    measure_supplier_import,
    measure_unit_economics,
    run_colab_benchmark_matrix,
    run_harness,
)

__all__ = (
    "PATH_IDS",
    "ROOT",
    "VALID_STATUSES",
    "_record",
    "inspect_container_files",
    "is_colab_available",
    "main",
    "measure_commerce_cycle",
    "measure_competition",
    "measure_container_contract",
    "measure_dependency_unavailable",
    "measure_opportunity_synthesis",
    "measure_replay",
    "measure_report_export",
    "measure_supplier_import",
    "measure_unit_economics",
    "run_colab_benchmark_matrix",
    "run_harness",
)


if __name__ == "__main__":
    raise SystemExit(main())

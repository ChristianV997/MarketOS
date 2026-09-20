"""PLACEHOLDER — Contents API truncated this module.

Restore the complete laboratory from the operator artifact before running
scenario tests:

    artifacts/marketos-commercial-replay-lab/scripts/benchmarks/benchmark_commercial_replay_lab.py
    sha256 25c270dca3387128bd4b23bb96ec9ad5fa13b7a1fc13520872d1cfaedc2dc393
    last complete remote blob: 399c5e5ab831aa8937ba7aa898a371f88c6403cb @ 4565cca1

Do not use GitHub Contents API for this file. Draft, do not merge.
"""
from __future__ import annotations

LAB_RESTORE_REQUIRED = True
LAB_RESTORE_SHA256 = "25c270dca3387128bd4b23bb96ec9ad5fa13b7a1fc13520872d1cfaedc2dc393"
LAB_LAST_COMPLETE_BLOB = "399c5e5ab831aa8937ba7aa898a371f88c6403cb"


def _missing():
    raise ImportError(
        "restore scripts/benchmarks/benchmark_commercial_replay_lab.py from "
        "artifacts/marketos-commercial-replay-lab (sha256 25c270dc) or blob 399c5e5a; "
        "Contents API truncated this file"
    )


class _Missing:
    def __getattr__(self, name):
        _missing()


EXPECTED_STAGES = {}
ScenarioReplayLaboratory = _Missing()
SensitivityMatrixLaboratory = _Missing()
ScalingAndProfilerLaboratory = _Missing()
StatisticalComparisonLaboratory = _Missing()

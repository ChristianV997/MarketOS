"""Read-only measurement adapters for canonical MarketOS paths.

This module deliberately does not reimplement any production authority.  A
path is reported as ``unavailable`` when its canonical runtime needs inputs or
an integration that this bounded performance lane does not own.  In
particular, no provider, model, network, or client export is activated here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CanonicalMeasurement:
    path_id: str
    status: str
    wall_ms: float | None = None
    output_size: int | None = None
    live_attestation: bool = False
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["notes"] = list(self.notes)
        return result


def _unavailable(path_id: str, *notes: str) -> CanonicalMeasurement:
    return CanonicalMeasurement(
        path_id=path_id,
        status="unavailable",
        live_attestation=False,
        notes=tuple(notes) or ("canonical path not driven by this lane",),
    )


def measure_financial_kernel() -> CanonicalMeasurement:
    """Classify the canonical money kernel without executing it."""
    return _unavailable(
        "financial_kernel",
        "owned by backend.economics.kernel",
        "performance lane does not compute money",
    )


def measure_research_to_decision() -> CanonicalMeasurement:
    """Classify the research-to-decision runtime without provider access."""
    return _unavailable(
        "research_to_decision",
        "owned by the research-to-decision lane",
        "provider and network access disabled",
    )


def measure_all_canonical(*, supplier_offers: int = 50, synthesis_candidates: int = 25) -> tuple[CanonicalMeasurement, ...]:
    """Return bounded classifications for canonical paths.

    The size arguments are retained in the contract for future fixture-only
    measurements, but this lane must not turn them into live or synthetic
    production claims.
    """
    del supplier_offers, synthesis_candidates
    return (
        _unavailable(
            "supplier_normalization",
            "canonical supplier adapter not executed by this lane",
            "offline evidence only",
        ),
        _unavailable(
            "opportunity_synthesis",
            "canonical synthesis adapter not executed by this lane",
            "does not grant launch authority",
        ),
        measure_research_to_decision(),
        measure_financial_kernel(),
    )


__all__ = ["CanonicalMeasurement", "measure_all_canonical", "measure_financial_kernel", "measure_research_to_decision"]

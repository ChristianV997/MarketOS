"""services.market_research_evidence.conflict — deterministic, field-level
conflict detection across independently sourced observations.

`evaluation.commerce.opportunity_synthesis`'s `alias_notes` only fires when
two *candidate rows* share an explicit `source_family` tag and the same
`query` text (SYN-ALIAS-NO-COLLAPSE) — it never compares the same
`candidate_id` reported by two different pillars, and it produces zero
notes whenever `source_family` is simply absent, which understates
disagreement rather than proving its absence. This module is a disjoint,
additive check: for one candidate, it diffs the numeric value each pillar
independently reported for the same named field and flags any real
disagreement, whether or not `source_family` was ever tagged. It is a data-
quality audit, not a second ranker or scorer: it never combines, weights,
or resolves the disagreement, only reports it.
"""
from __future__ import annotations

from typing import Any

from .schemas import ConflictFinding, FieldObservation

DEFAULT_TOLERANCE = 1e-9


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, "missing", "unknown", ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def detect_field_conflicts(
    candidate_id: str,
    observations: tuple[FieldObservation, ...],
    *,
    tolerance: float = DEFAULT_TOLERANCE,
) -> tuple[ConflictFinding, ...]:
    """Groups `observations` by field name and flags any field where two or
    more pillars reported numerically different values for the same
    candidate. Deterministic: iterates fields and observations in stable
    (sorted) order, so identical input always yields identical output."""
    by_field: dict[str, list[FieldObservation]] = {}
    for item in observations:
        by_field.setdefault(item.field, []).append(item)

    findings: list[ConflictFinding] = []
    for field_name in sorted(by_field):
        items = sorted(by_field[field_name], key=lambda item: item.provenance.pillar)
        numeric_items = [(item, _numeric(item.value)) for item in items]
        numeric_items = [(item, value) for item, value in numeric_items if value is not None]
        if len(numeric_items) < 2:
            continue
        values = [value for _, value in numeric_items]
        delta = max(values) - min(values)
        if delta <= tolerance:
            continue
        rendered = tuple(
            {
                "pillar": item.provenance.pillar,
                "source_ref": item.provenance.source.source_ref,
                "value": value,
                "observed_at": item.provenance.observed_at,
            }
            for item, value in numeric_items
        )
        findings.append(
            ConflictFinding(
                candidate_id=candidate_id,
                field=field_name,
                observations=rendered,
                delta=delta,
                note=(
                    f"{len(numeric_items)} independently sourced observations of "
                    f"'{field_name}' for candidate '{candidate_id}' disagree by {delta}; "
                    "reported as an unresolved conflict, not averaged or resolved."
                ),
            )
        )
    return tuple(findings)


__all__ = ["DEFAULT_TOLERANCE", "detect_field_conflicts"]

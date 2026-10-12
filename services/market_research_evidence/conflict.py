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

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from backend.economics.kernel import EconomicsError, Money

from .schemas import ConflictFinding, FieldObservation

DEFAULT_TOLERANCE = 1e-9
DEFAULT_DECIMAL_TOLERANCE = Decimal("0.000000001")
COMPARISON_STATES = (
    "comparable",
    "conflict",
    "currency-mismatch",
    "currency-missing",
    "unit-mismatch",
    "insufficient-evidence",
)
_COMPARISON_ISSUES = frozenset({"conflict", "currency-mismatch", "currency-missing", "unit-mismatch"})
_MONEY_FIELD_NAMES = frozenset({
    "amount",
    "cogs",
    "cost",
    "fee",
    "price",
    "revenue",
    "shipping",
    "shipping_cost",
    "tax",
})


@dataclass(frozen=True)
class _ParsedValue:
    amount: Decimal
    currency: str | None
    unit: str | None


def _is_money_field(field: str) -> bool:
    name = field.rsplit(".", 1)[-1].lower()
    return name in _MONEY_FIELD_NAMES or name.endswith(("_cost", "_fee", "_amount"))


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and (value == "" or value in {"missing", "unknown"}))


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Money):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _source_key(item: FieldObservation) -> tuple[str, str, str]:
    source = item.provenance.source
    return source.source_family, source.source_ref, source.fingerprint


def _sort_key(item: FieldObservation) -> tuple[str, str, str, str, str]:
    source = item.provenance.source
    return (source.source_family, source.source_ref, source.fingerprint, item.provenance.observed_at, repr(item.value))


def _metadata(item: FieldObservation) -> tuple[Any, Any]:
    value = item.value
    currency = item.currency
    unit = item.unit
    if isinstance(value, Money):
        currency = currency or value.currency
    elif isinstance(value, Mapping):
        currency = currency or value.get("currency") or value.get("currency_code")
        unit = unit or value.get("unit") or value.get("quantity_unit")
    return currency, unit


def _parse_value(item: FieldObservation, *, monetary: bool) -> tuple[_ParsedValue | None, str | None]:
    value = item.value
    if _is_missing(value):
        return None, None

    currency, unit = _metadata(item)
    if isinstance(value, Money):
        if item.currency is not None and (not isinstance(item.currency, str) or item.currency.strip().upper() != value.currency):
            return None, "currency-mismatch"
        if value.evidence_state in {"missing", "stale", "rejected", "unknown"}:
            return None, "stale"
        return _ParsedValue(value.amount, value.currency, unit), None

    if isinstance(value, Mapping):
        if "amount" not in value:
            return None, "invalid"
        value = value["amount"]

    if monetary:
        if not isinstance(currency, str) or not currency.strip():
            return None, "currency-missing"
        try:
            money = Money(value, currency, source="comparison", provenance="comparison", evidence_state="observed")
        except EconomicsError as error:
            return None, "currency-missing" if str(error) == "invalid currency" else "invalid"
        return _ParsedValue(money.amount, money.currency, unit), None

    if isinstance(value, bool):
        return None, "invalid"
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None, "invalid"
    if not amount.is_finite():
        return None, "invalid"
    return _ParsedValue(amount, None, unit), None


def _render_observation(item: FieldObservation) -> dict[str, Any]:
    source = item.provenance.source
    currency, unit = _metadata(item)
    return {
        "pillar": item.provenance.pillar,
        "source_ref": source.source_ref,
        "value": _json_value(item.value),
        "currency": currency,
        "unit": unit,
        "freshness_status": item.provenance.freshness_status,
        "observed_at": item.provenance.observed_at,
    }


def _finding(
    candidate_id: str,
    field: str,
    items: list[FieldObservation],
    *,
    status: str,
    delta: Any = None,
    currency: str | None = None,
    unit: str | None = None,
    note: str,
) -> ConflictFinding:
    return ConflictFinding(
        candidate_id=candidate_id,
        field=field,
        observations=tuple(_render_observation(item) for item in items),
        delta=delta,
        note=note,
        status=status,
        currency=currency,
        unit=unit,
    )


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


def compare_field_observations(
    candidate_id: str,
    observations: tuple[FieldObservation, ...],
    *,
    tolerance: Decimal | int | str | float = DEFAULT_DECIMAL_TOLERANCE,
) -> tuple[ConflictFinding, ...]:
    """Compare evidence values without guessing currency, units, or freshness.

    This is the strict successor path for report consumers. Monetary values are
    parsed through the canonical ``Money`` contract and are never subtracted
    unless both currency and unit metadata agree and every observation is
    current. The existing ``detect_field_conflicts`` function remains the
    legacy dimensionless float path for callers that have not migrated.
    """
    try:
        decimal_tolerance = tolerance if isinstance(tolerance, Decimal) else Decimal(str(tolerance))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("invalid comparison tolerance") from None
    if decimal_tolerance < 0 or not decimal_tolerance.is_finite():
        raise ValueError("invalid comparison tolerance")

    by_field: dict[str, list[FieldObservation]] = {}
    for item in observations:
        by_field.setdefault(item.field, []).append(item)

    results: list[ConflictFinding] = []
    for field in sorted(by_field):
        items = sorted(by_field[field], key=_sort_key)
        present = [item for item in items if not _is_missing(item.value)]
        if len(present) < 2:
            results.append(
                _finding(
                    candidate_id,
                    field,
                    items,
                    status="insufficient-evidence",
                    note="at least two supplied values are required; missing is not zero",
                )
            )
            continue

        parsed: list[tuple[FieldObservation, _ParsedValue]] = []
        parse_errors: set[str] = set()
        for item in present:
            value, error = _parse_value(item, monetary=_is_money_field(field))
            if error:
                parse_errors.add(error)
            elif value is not None:
                parsed.append((item, value))

        if "currency-mismatch" in parse_errors:
            results.append(_finding(candidate_id, field, items, status="currency-mismatch", note="currency metadata disagrees with the typed monetary value"))
            continue
        if "currency-missing" in parse_errors:
            results.append(_finding(candidate_id, field, items, status="currency-missing", note="every monetary observation needs a valid explicit currency"))
            continue
        if "stale" in parse_errors:
            results.append(
                _finding(
                    candidate_id,
                    field,
                    items,
                    status="insufficient-evidence",
                    note="stale, rejected, unknown, or missing typed Money evidence_state cannot support comparison",
                )
            )
            continue
        if len(parsed) < 2 or "invalid" in parse_errors:
            results.append(_finding(candidate_id, field, items, status="insufficient-evidence", note="numeric comparison requires two finite supplied values"))
            continue

        currencies = {value.currency for _, value in parsed}
        if len(currencies) > 1:
            results.append(_finding(candidate_id, field, items, status="currency-mismatch", note="currency codes differ; no implicit FX conversion is performed"))
            continue

        units = {value.unit for _, value in parsed}
        if len(units) > 1:
            results.append(_finding(candidate_id, field, items, status="unit-mismatch", note="observations must use one explicit unit before comparison"))
            continue
        if "unknown" in units or "" in units:
            results.append(
                _finding(
                    candidate_id,
                    field,
                    items,
                    status="insufficient-evidence",
                    note="unknown or empty unit cannot support comparison",
                )
            )
            continue
        if _is_money_field(field) and None in units:
            results.append(_finding(candidate_id, field, items, status="insufficient-evidence", note="monetary comparison requires an explicit unit"))
            continue

        if any(item.provenance.freshness_status != "supplied" for item, _ in parsed):
            results.append(_finding(candidate_id, field, items, status="insufficient-evidence", note="stale, future, unknown, or missing freshness cannot support comparison"))
            continue

        source_counts: dict[tuple[str, str, str], int] = {}
        for item, _ in parsed:
            source_counts[_source_key(item)] = source_counts.get(_source_key(item), 0) + 1
        if any(count > 1 for count in source_counts.values()):
            results.append(_finding(candidate_id, field, items, status="insufficient-evidence", note="duplicate values from one source are not independent evidence"))
            continue

        amounts = [value.amount for _, value in parsed]
        currency = next(iter(currencies))
        unit = next(iter(units))
        # Span every accepted observation (max − min). Do not reduce to the
        # first two sorted sources — with three-plus values that under-reports
        # disagreement. Money construction still validates the extremes.
        low = min(amounts)
        high = max(amounts)
        if _is_money_field(field):
            left = Money(low, currency, source="comparison", provenance="comparison", evidence_state="observed")
            right = Money(high, currency, source="comparison", provenance="comparison", evidence_state="observed")
            delta = abs((left - right).amount)
        else:
            delta = high - low
        status = "comparable" if delta <= decimal_tolerance else "conflict"
        results.append(
            _finding(
                candidate_id,
                field,
                items,
                status=status,
                delta=delta,
                currency=currency,
                unit=unit,
                note="values agree within the explicit tolerance" if status == "comparable" else "finite values in the same explicit unit disagree",
            )
        )
    return tuple(results)


def comparison_has_issue(result: ConflictFinding) -> bool:
    """Return whether a comparison blocks treating values as reconciled."""
    return result.status in _COMPARISON_ISSUES


__all__ = [
    "COMPARISON_STATES",
    "DEFAULT_DECIMAL_TOLERANCE",
    "DEFAULT_TOLERANCE",
    "compare_field_observations",
    "comparison_has_issue",
    "detect_field_conflicts",
]

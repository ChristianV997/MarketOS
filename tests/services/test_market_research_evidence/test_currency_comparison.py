import json
from decimal import Decimal

import pytest

from backend.economics.kernel import Money
from services.market_research_evidence import (
    MISSING,
    build_evidence_integrity_report,
    build_observation_identity,
    build_source_identity,
    compare_field_observations,
)
from services.market_research_evidence.schemas import EvidenceProvenance, FieldObservation


def _provenance(source_ref: str, *, freshness_status: str = "supplied") -> EvidenceProvenance:
    return EvidenceProvenance(
        pillar="supplier",
        source=build_source_identity("supplier", source_ref),
        observation=build_observation_identity("cand-1", "ws-1", "shipping_cost"),
        evidence_mode="manual",
        observed_at="2026-09-01",
        freshness_status=freshness_status,
        capture_method="offline_report",
    )


def _observation(
    value,
    source_ref: str,
    *,
    currency: str | None = "USD",
    unit: str | None = "shipment",
    field: str = "shipping_cost",
    freshness_status: str = "supplied",
) -> FieldObservation:
    return FieldObservation(
        field,
        value,
        _provenance(source_ref, freshness_status=freshness_status),
        currency=currency,
        unit=unit,
    )


def _status(*observations: FieldObservation):
    results = compare_field_observations("cand-1", tuple(observations))
    assert len(results) == 1
    return results[0]


def test_same_currency_values_are_comparable_without_float_rounding():
    result = _status(
        _observation("10.000000000", "supplier-a"),
        _observation("10.0000000004", "supplier-b"),
    )

    assert result.status == "comparable"
    assert result.delta == Decimal("0.0000000004")
    assert result.currency == "USD"
    assert result.unit == "shipment"


def test_same_currency_difference_is_an_explicit_conflict():
    result = _status(_observation("10", "supplier-a"), _observation("12", "supplier-b"))

    assert result.status == "conflict"
    assert result.delta == Decimal("2")


def test_three_source_span_uses_max_minus_min_not_first_two_sorted():
    """Regression: Money delta must span every accepted observation."""
    result = _status(
        _observation("15", "supplier-m"),
        _observation("10", "supplier-a"),
        _observation("20", "supplier-z"),
    )

    assert result.status == "conflict"
    assert result.delta == Decimal("10")


def test_cross_currency_values_are_not_compared_or_silently_converted():
    result = _status(
        _observation("10", "supplier-a", currency="USD"),
        _observation("10", "supplier-b", currency="MXN"),
    )

    assert result.status == "currency-mismatch"
    assert result.delta is None
    assert result.currency is None
    assert "no implicit fx conversion" in result.note.lower()


@pytest.mark.parametrize("currency", [None, "", "NOT-A-CURRENCY"])
def test_missing_or_invalid_currency_is_not_filled_by_a_default(currency):
    result = _status(
        _observation("10", "supplier-a", currency=currency),
        _observation("12", "supplier-b", currency=currency),
    )

    assert result.status == "currency-missing"
    assert result.delta is None


def test_non_finite_amount_is_insufficient_evidence_not_a_currency_result():
    result = _status(
        _observation("NaN", "supplier-a"),
        _observation("12", "supplier-b"),
    )

    assert result.status == "insufficient-evidence"
    assert result.delta is None


def test_unit_mismatch_is_not_a_numeric_conflict():
    result = _status(
        _observation("10", "supplier-a", unit="item"),
        _observation("10", "supplier-b", unit="shipment"),
    )

    assert result.status == "unit-mismatch"
    assert result.delta is None


def test_missing_and_explicit_zero_remain_distinct():
    result = _status(
        _observation(MISSING, "supplier-a"),
        _observation("0", "supplier-b"),
    )

    assert result.status == "insufficient-evidence"
    assert result.delta is None
    assert result.observations[0]["value"] == MISSING
    assert result.observations[1]["value"] == "0"


def test_stale_evidence_cannot_produce_a_comparable_or_conflict_result():
    result = _status(
        _observation("10", "supplier-a", freshness_status="stale"),
        _observation("12", "supplier-b"),
    )

    assert result.status == "insufficient-evidence"
    assert result.delta is None


def test_duplicate_source_observations_are_not_treated_as_independent_evidence():
    result = _status(
        _observation("10", "supplier-a"),
        _observation("12", "supplier-a"),
    )

    assert result.status == "insufficient-evidence"
    assert result.delta is None


def test_typed_money_uses_the_canonical_money_contract():
    result = _status(
        FieldObservation(
            "shipping_cost",
            Money("10.00", "USD", source="manual", provenance="supplier-a", evidence_state="observed"),
            _provenance("supplier-a"),
            unit="shipment",
        ),
        FieldObservation(
            "shipping_cost",
            Money("12.00", "USD", source="manual", provenance="supplier-b", evidence_state="observed"),
            _provenance("supplier-b"),
            unit="shipment",
        ),
    )

    assert result.status == "conflict"
    assert result.delta == Decimal("2.00")


def test_stale_typed_money_is_not_rehabilitated_by_fresh_provenance():
    stale = Money("10.00", "USD", source="manual", provenance="supplier-a", evidence_state="stale")
    result = _status(
        FieldObservation("shipping_cost", stale, _provenance("supplier-a"), unit="shipment"),
        _observation("12", "supplier-b"),
    )

    assert result.status == "insufficient-evidence"
    assert result.delta is None


def test_stale_typed_money_fails_closed_even_when_other_values_remain():
    """Stale Money must not be dropped so remaining values can still reconcile."""
    stale = Money("10.00", "USD", source="manual", provenance="supplier-a", evidence_state="stale")
    result = _status(
        FieldObservation("shipping_cost", stale, _provenance("supplier-a"), unit="shipment"),
        _observation("12", "supplier-b"),
        _observation("12", "supplier-c"),
    )

    assert result.status == "insufficient-evidence"
    assert result.delta is None


def test_unknown_unit_is_insufficient_evidence_not_comparable():
    result = _status(
        _observation("10", "supplier-a", unit="unknown"),
        _observation("10", "supplier-b", unit="unknown"),
    )

    assert result.status == "insufficient-evidence"
    assert result.delta is None


def test_conflicting_typed_money_metadata_fails_closed():
    value = Money("10.00", "USD", source="manual", provenance="supplier-a", evidence_state="observed")
    result = _status(
        FieldObservation("shipping_cost", value, _provenance("supplier-a"), currency="MXN", unit="shipment"),
        _observation("12", "supplier-b"),
    )

    assert result.status == "currency-mismatch"
    assert result.delta is None


def test_typed_money_metadata_accepts_canonical_case_normalization():
    value = Money("10.00", "USD", source="manual", provenance="supplier-a", evidence_state="observed")
    result = _status(
        FieldObservation("shipping_cost", value, _provenance("supplier-a"), currency="usd", unit="shipment"),
        _observation("12", "supplier-b"),
    )

    assert result.status == "conflict"
    assert result.currency == "USD"


def test_typed_money_field_observation_is_json_safe():
    value = Money("10.00", "USD", source="manual", provenance="supplier-a", evidence_state="observed")
    observation = FieldObservation("shipping_cost", value, _provenance("supplier-a"), unit="shipment")

    payload = observation.to_dict()
    json.dumps(payload)
    assert payload["value"]["amount"] == "10.00"


def test_report_preserves_currency_state_and_serializes_deterministically():
    supplier = {
        "evidence_mode": "manual",
        "candidates": [
            {
                "candidate_id": "cand-1",
                "observed_at": "2026-09-01",
                "score": {"overall_supplier_feasibility": 0.6},
                "offers": [
                    {"supplier": "supplier-a", "shipping_cost": "10", "currency": "USD", "unit": "shipment"},
                    {"supplier": "supplier-b", "shipping_cost": "12", "currency": "MXN", "unit": "shipment"},
                ],
            }
        ],
    }

    first = build_evidence_integrity_report(candidate_id="cand-1", workspace_id="ws-1", as_of="2026-09-02", supplier_report=supplier)
    second = build_evidence_integrity_report(candidate_id="cand-1", workspace_id="ws-1", as_of="2026-09-02", supplier_report=supplier)
    data = first.to_dict()

    assert first.fingerprint == second.fingerprint
    assert data["comparison_results"]
    shipping = [item for item in data["comparison_results"] if item["field"] == "shipping_cost"]
    assert shipping[0]["status"] == "currency-mismatch"
    assert shipping[0]["delta"] is None
    json.dumps(data)


def test_report_keeps_legacy_conflict_delta_numeric_and_strict_delta_exact():
    supplier = {
        "evidence_mode": "manual",
        "candidates": [
            {
                "candidate_id": "cand-1",
                "observed_at": "2026-09-01",
                "score": {"overall_supplier_feasibility": 0.6},
                "offers": [
                    {"supplier": "supplier-a", "shipping_cost": "10", "currency": "USD", "unit": "shipment"},
                    {"supplier": "supplier-b", "shipping_cost": "12", "currency": "USD", "unit": "shipment"},
                ],
            }
        ],
    }

    data = build_evidence_integrity_report(candidate_id="cand-1", workspace_id="ws-1", as_of="2026-09-02", supplier_report=supplier).to_dict()
    strict = [item for item in data["comparison_results"] if item["field"] == "shipping_cost"][0]
    legacy = [item for item in data["deterministic_conflicts"] if item["field"] == "shipping_cost"][0]

    assert strict["delta"] == "2"
    assert legacy["delta"] == 2.0

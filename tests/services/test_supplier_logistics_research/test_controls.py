"""Negative-control tests for services.supplier_logistics_research.controls.

Covers all six negative controls the mission requires: credential-shaped
input, raw HTML, cross-client fields, mismatched currency, missing money,
and a supplier claim being mistaken for verified evidence.
"""
from decimal import Decimal

import pytest

from backend.economics.kernel import CurrencyMismatchError, EvidenceRef, Money
from services.supplier_logistics_research import controls
from services.supplier_logistics_research.schemas import FieldEvidence

from .conftest import load_fixture_json


@pytest.fixture(scope="module")
def unsafe_inputs():
    return load_fixture_json("unsafe_field_inputs.json")


class TestCredentialShapedInput:
    def test_rejects_a_bearer_style_secret_value(self, unsafe_inputs):
        with pytest.raises(controls.NegativeControlError):
            controls.reject_unsafe_input(unsafe_inputs["credential_shaped"])

    def test_rejects_a_secret_shaped_key_name_even_with_an_innocuous_value(self, unsafe_inputs):
        with pytest.raises(controls.NegativeControlError):
            controls.reject_unsafe_input(unsafe_inputs["credential_shaped_key"])

    def test_safe_note_passes(self, unsafe_inputs):
        controls.reject_unsafe_input(unsafe_inputs["safe_note"])  # must not raise


class TestRawHtml:
    def test_rejects_a_raw_html_document(self, unsafe_inputs):
        with pytest.raises(controls.NegativeControlError):
            controls.reject_unsafe_input(unsafe_inputs["raw_html"])

    def test_a_lone_angle_bracket_is_not_flagged_as_html(self):
        assert controls.contains_html("price < 10 units remaining") is False


class TestCrossClientFields:
    def test_rejects_a_reference_to_another_clients_data(self, unsafe_inputs):
        with pytest.raises(controls.NegativeControlError):
            controls.reject_unsafe_input(unsafe_inputs["cross_client_reference"])

    def test_detects_cross_client_markers_nested_in_a_mapping(self):
        assert controls.contains_cross_client_reference({"note": "copied from another_client engagement"}) is True


class TestMismatchedCurrency:
    def test_rejects_two_monies_in_different_currencies(self):
        with pytest.raises(CurrencyMismatchError):
            controls.require_matching_currency(Money(Decimal("10"), "USD"), Money(Decimal("10"), "EUR"))

    def test_allows_matching_currencies(self):
        controls.require_matching_currency(Money(Decimal("10"), "USD"), Money(Decimal("5"), "USD"))  # must not raise

    def test_ignores_none_values(self):
        controls.require_matching_currency(Money(Decimal("10"), "USD"), None)  # must not raise


class TestMissingMoney:
    def test_rejects_a_missing_value(self):
        with pytest.raises(controls.NegativeControlError):
            controls.require_present(None, field_name="quoted_price")

    def test_passes_through_a_present_value(self):
        money = Money(Decimal("1"), "USD")
        assert controls.require_present(money, field_name="quoted_price") is money


class TestSupplierClaimIsNeverMistakenForVerified:
    def test_a_manual_supplier_claim_is_never_verified(self):
        assert controls.is_verified(FieldEvidence(quality="manual")) is False

    def test_a_fixture_value_is_never_verified(self):
        assert controls.is_verified(FieldEvidence(quality="fixture")) is False

    def test_an_observed_field_without_an_evidence_ref_is_not_verified(self):
        assert controls.is_verified(FieldEvidence(quality="observed")) is False

    def test_an_observed_field_with_an_unconfirmed_evidence_ref_is_not_verified(self):
        ref = EvidenceRef(evidence_id="e1", evidence_state="observed", human_confirmed=False)
        assert controls.is_verified(FieldEvidence(quality="observed", evidence_ref=ref)) is False

    def test_an_observed_field_with_a_confirmed_but_stale_evidence_state_is_not_verified(self):
        ref = EvidenceRef(evidence_id="e1", evidence_state="stale", human_confirmed=True)
        assert controls.is_verified(FieldEvidence(quality="observed", evidence_ref=ref)) is False

    def test_only_observed_plus_confirmed_plus_verified_like_state_counts_as_verified(self):
        ref = EvidenceRef(evidence_id="e1", evidence_state="verified", human_confirmed=True)
        assert controls.is_verified(FieldEvidence(quality="observed", evidence_ref=ref)) is True

"""Negative-control tests for services.geographic_opportunity.controls."""
from decimal import Decimal

import pytest

from backend.economics.kernel import CurrencyMismatchError, EvidenceRef, Money
from services.geographic_opportunity import controls
from services.geographic_opportunity.schemas import FieldEvidence


class TestCredentialShapedInputAndHtml:
    def test_rejects_a_bearer_style_secret_value(self):
        with pytest.raises(controls.NegativeControlError):
            controls.reject_unsafe_input("Authorization: Bearer sk_live_51H8xyzAAAAAAAAAAAAAAAAAA")

    def test_rejects_raw_html(self):
        with pytest.raises(controls.NegativeControlError):
            controls.reject_unsafe_input("<html><body><script>alert(1)</script></body></html>")

    def test_a_lone_angle_bracket_is_not_flagged_as_html(self):
        controls.reject_unsafe_input("price < 10 units remaining")  # must not raise

    def test_safe_note_passes(self):
        controls.reject_unsafe_input("supplier confirmed MOQ of 50 units via signed quote dated 2026-01-04")


class TestMismatchedCurrency:
    def test_rejects_two_monies_in_different_currencies(self):
        with pytest.raises(CurrencyMismatchError):
            controls.require_matching_currency(Money(Decimal("10"), "USD"), Money(Decimal("10"), "EUR"))

    def test_allows_matching_currencies(self):
        controls.require_matching_currency(Money(Decimal("10"), "USD"), Money(Decimal("5"), "USD"))

    def test_ignores_none_values(self):
        controls.require_matching_currency(Money(Decimal("10"), "USD"), None)


class TestMissingMoney:
    def test_rejects_a_missing_value(self):
        with pytest.raises(controls.NegativeControlError):
            controls.require_present(None, field_name="origin_supplier_cost")

    def test_passes_through_a_present_value(self):
        money = Money(Decimal("1"), "USD")
        assert controls.require_present(money, field_name="origin_supplier_cost") is money


class TestFxProvenance:
    def test_rejects_a_conversion_with_no_explicit_rate_source(self):
        bad = Money(Decimal("10"), "USD", exchange_rate=Decimal("1.1"), exchange_rate_timestamp="2026-01-01", source="assumed")
        with pytest.raises(controls.FxProvenanceError):
            controls.require_fx_provenance(bad)

    def test_rejects_unknown_source(self):
        bad = Money(Decimal("10"), "USD", exchange_rate=Decimal("1.1"), exchange_rate_timestamp="2026-01-01", source="unknown")
        with pytest.raises(controls.FxProvenanceError):
            controls.require_fx_provenance(bad)

    def test_accepts_an_explicit_acceptable_rate_source(self):
        good = Money(Decimal("10"), "USD", exchange_rate=Decimal("1.1"), exchange_rate_timestamp="2026-01-01", source="central_bank_reference_rate")
        assert controls.require_fx_provenance(good) is good

    def test_a_money_with_no_conversion_at_all_always_passes(self):
        plain = Money(Decimal("10"), "USD", source="assumed")
        assert controls.require_fx_provenance(plain) is plain


class TestUnsupportedRegulatoryInference:
    @pytest.mark.parametrize("status", ["compliant", "cleared", "approved", "not_a_real_status"])
    def test_rejects_unsupported_status(self, status):
        with pytest.raises(controls.UnsupportedRegulatoryInferenceError):
            controls.reject_unsupported_regulatory_claim(status)

    @pytest.mark.parametrize("status", ["unassessed", "requires_evidence", "documented_requirement"])
    def test_accepts_supported_status(self, status):
        controls.reject_unsupported_regulatory_claim(status)  # must not raise


class TestSupplierClaimIsNeverMistakenForVerified:
    def test_a_manual_claim_is_never_verified(self):
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

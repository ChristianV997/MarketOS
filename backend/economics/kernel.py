"""Canonical, offline Decimal contracts for MarketOS commercial economics.

This module is the single authority for new money arithmetic.  Existing
float-shaped reports may adapt its results at their public boundary, but must
not reimplement the formulas.  FX conversion is deliberately explicit: a
currency value cannot be converted with a hidden table or a universal rate.
"""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping


SUPPORTED_CURRENCIES = frozenset({"CAD", "EUR", "GBP", "MXN", "USD"})
EVIDENCE_STATES = frozenset({
    "unknown", "missing", "assumed", "derived", "fixture", "simulated",
    "observed", "live_readonly", "verified", "stale", "rejected",
})
TAX_INCLUSION_STATES = frozenset({"unknown", "inclusive", "exclusive", "not_applicable"})
_ZERO = Decimal("0")
_ONE = Decimal("1")
_THIRTY = Decimal("30")


class EconomicsError(ValueError):
    """Stable, non-reflective validation error for the economics boundary."""


class CurrencyMismatchError(EconomicsError):
    """Raised when money values would be combined without an explicit FX step."""

    def __init__(self) -> None:
        super().__init__("money currencies must match")


def _decimal(value: Any, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise EconomicsError(f"invalid {field_name}")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise EconomicsError(f"invalid {field_name}") from None
    if not result.is_finite():
        raise EconomicsError(f"invalid {field_name}")
    return result


def _text(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise EconomicsError(f"invalid {field_name}")
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise EconomicsError(f"invalid {field_name}")
    return value


def _currency(value: Any) -> str:
    if not isinstance(value, str):
        raise EconomicsError("invalid currency")
    currency = value.upper()
    if len(currency) != 3 or not currency.isalpha() or currency not in SUPPORTED_CURRENCIES:
        raise EconomicsError("invalid currency")
    return currency


def _rate(value: Any, field_name: str, *, allow_none: bool = True) -> Decimal | None:
    if value is None and allow_none:
        return None
    result = _decimal(value, field_name)
    if result < _ZERO or result > _ONE:
        raise EconomicsError(f"invalid {field_name}")
    return result


def _positive_rate(value: Any, field_name: str) -> Decimal:
    result = _decimal(value, field_name)
    if result <= _ZERO:
        raise EconomicsError(f"invalid {field_name}")
    return result


@dataclass(frozen=True)
class EvidenceRef:
    """Evidence metadata that never upgrades unknown data implicitly."""

    evidence_id: str
    source_type: str = "unknown"
    source_url: str = ""
    document_ref: str = ""
    sku_variant: str = ""
    origin: str = ""
    destination: str = ""
    captured_at: str = ""
    valid_until: str = ""
    extraction_method: str = "unknown"
    evidence_state: str = "unknown"
    confidence: Decimal | None = None
    human_confirmed: bool = False
    warnings: tuple[str, ...] = ()
    snapshot_hash: str = ""

    def __post_init__(self) -> None:
        for name in ("evidence_id", "source_type", "source_url", "document_ref", "sku_variant", "origin", "destination", "captured_at", "valid_until", "extraction_method", "snapshot_hash"):
            value = getattr(self, name)
            _text(value, name, allow_empty=name not in {"evidence_id", "source_type", "extraction_method"})
        if self.evidence_state not in EVIDENCE_STATES:
            raise EconomicsError("invalid evidence state")
        if self.confidence is not None:
            confidence = _rate(self.confidence, "confidence", allow_none=False)
            object.__setattr__(self, "confidence", confidence)
        if not isinstance(self.human_confirmed, bool):
            raise EconomicsError("invalid human confirmation")
        if not isinstance(self.warnings, tuple) or any(not isinstance(item, str) for item in self.warnings):
            raise EconomicsError("invalid evidence warnings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_type": self.source_type,
            "source_url": self.source_url,
            "document_ref": self.document_ref,
            "sku_variant": self.sku_variant,
            "origin": self.origin,
            "destination": self.destination,
            "captured_at": self.captured_at,
            "valid_until": self.valid_until,
            "extraction_method": self.extraction_method,
            "evidence_state": self.evidence_state,
            "confidence": str(self.confidence) if self.confidence is not None else "unknown",
            "human_confirmed": self.human_confirmed,
            "warnings": list(self.warnings),
            "snapshot_hash": self.snapshot_hash,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceRef":
        if not isinstance(value, Mapping):
            raise EconomicsError("invalid evidence reference")
        return cls(
            evidence_id=value.get("evidence_id", ""),
            source_type=value.get("source_type", "unknown"),
            source_url=value.get("source_url", ""),
            document_ref=value.get("document_ref", ""),
            sku_variant=value.get("sku_variant", ""),
            origin=value.get("origin", ""),
            destination=value.get("destination", ""),
            captured_at=value.get("captured_at", ""),
            valid_until=value.get("valid_until", ""),
            extraction_method=value.get("extraction_method", "unknown"),
            evidence_state=value.get("evidence_state", "unknown"),
            confidence=None if value.get("confidence") in (None, "unknown") else value.get("confidence"),
            human_confirmed=value.get("human_confirmed", False),
            warnings=tuple(value.get("warnings", ())),
            snapshot_hash=value.get("snapshot_hash", ""),
        )


@dataclass(frozen=True)
class Money:
    """A Decimal amount whose currency and conversion provenance are explicit."""

    amount: Decimal | int | str | float
    currency: str
    source: str = "explicit"
    exchange_rate: Decimal | None = None
    exchange_rate_timestamp: str | None = None
    uncertainty: Decimal | None = None
    tax_inclusion_state: str = "unknown"
    evidence_ref: EvidenceRef | None = None
    provenance: str = "unknown"
    evidence_state: str = "unknown"

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _decimal(self.amount, "amount"))
        object.__setattr__(self, "currency", _currency(self.currency))
        _text(self.source, "source")
        _text(self.provenance, "provenance")
        if self.evidence_state not in EVIDENCE_STATES:
            raise EconomicsError("invalid evidence state")
        if self.exchange_rate is not None:
            object.__setattr__(self, "exchange_rate", _positive_rate(self.exchange_rate, "exchange rate"))
            if not self.exchange_rate_timestamp:
                raise EconomicsError("exchange rate timestamp required")
            _text(self.exchange_rate_timestamp, "exchange rate timestamp")
        elif self.exchange_rate_timestamp is not None:
            raise EconomicsError("exchange rate required")
        if self.uncertainty is not None:
            object.__setattr__(self, "uncertainty", _rate(self.uncertainty, "uncertainty", allow_none=False))
        if self.tax_inclusion_state not in TAX_INCLUSION_STATES:
            raise EconomicsError("invalid tax inclusion state")
        if self.evidence_ref is not None and not isinstance(self.evidence_ref, EvidenceRef):
            raise EconomicsError("invalid evidence reference")

    @property
    def tax_inclusion(self) -> str:
        return self.tax_inclusion_state

    @property
    def currency_source(self) -> str:
        return self.source

    @property
    def conversion_uncertainty(self) -> Decimal | None:
        return self.uncertainty

    def _assert_same_currency(self, other: "Money") -> None:
        if not isinstance(other, Money) or self.currency != other.currency:
            raise CurrencyMismatchError()

    def _derived(self, amount: Decimal) -> "Money":
        return Money(
            amount,
            self.currency,
            source="derived",
            tax_inclusion_state=self.tax_inclusion_state,
            evidence_ref=self.evidence_ref,
            provenance="derived",
            evidence_state=self.evidence_state,
        )

    def __add__(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        return self._derived(self.amount + other.amount)

    def __sub__(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        return self._derived(self.amount - other.amount)

    def multiply(self, factor: Decimal | int | str | float) -> "Money":
        return self._derived(self.amount * _decimal(factor, "factor"))

    def divide(self, divisor: Decimal | int | str | float) -> "Money":
        value = _decimal(divisor, "divisor")
        if value == _ZERO:
            raise EconomicsError("invalid divisor")
        return self._derived(self.amount / value)

    @classmethod
    def zero(cls, currency: str, *, source: str = "assumed") -> "Money":
        return cls(_ZERO, currency, source=source, provenance=source, evidence_state="unknown")

    def convert(
        self,
        target_currency: str,
        *,
        exchange_rate: Decimal | int | str | float,
        exchange_rate_timestamp: str,
        uncertainty: Decimal | int | str | float,
        source: str,
    ) -> "Money":
        target = _currency(target_currency)
        if target == self.currency:
            return self
        rate = _positive_rate(exchange_rate, "exchange rate")
        if not exchange_rate_timestamp:
            raise EconomicsError("exchange rate timestamp required")
        _text(exchange_rate_timestamp, "exchange rate timestamp")
        _rate(uncertainty, "uncertainty", allow_none=False)
        _text(source, "source")
        return Money(
            self.amount * rate,
            target,
            source=source,
            exchange_rate=rate,
            exchange_rate_timestamp=exchange_rate_timestamp,
            uncertainty=_decimal(uncertainty, "uncertainty"),
            tax_inclusion_state=self.tax_inclusion_state,
            evidence_ref=self.evidence_ref,
            provenance="explicit_fx",
            evidence_state=self.evidence_state,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": str(self.amount),
            "currency": self.currency,
            "source": self.source,
            "exchange_rate": str(self.exchange_rate) if self.exchange_rate is not None else "unknown",
            "exchange_rate_timestamp": self.exchange_rate_timestamp or "unknown",
            "uncertainty": str(self.uncertainty) if self.uncertainty is not None else "unknown",
            "tax_inclusion_state": self.tax_inclusion_state,
            "evidence_ref": self.evidence_ref.to_dict() if self.evidence_ref else None,
            "provenance": self.provenance,
            "evidence_state": self.evidence_state,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Money":
        if not isinstance(value, Mapping):
            raise EconomicsError("invalid money")
        evidence = value.get("evidence_ref")
        return cls(
            amount=value.get("amount"),
            currency=value.get("currency", ""),
            source=value.get("source", "explicit"),
            exchange_rate=None if value.get("exchange_rate") in (None, "unknown") else value.get("exchange_rate"),
            exchange_rate_timestamp=None if value.get("exchange_rate_timestamp") in (None, "unknown") else value.get("exchange_rate_timestamp"),
            uncertainty=None if value.get("uncertainty") in (None, "unknown") else value.get("uncertainty"),
            tax_inclusion_state=value.get("tax_inclusion_state", "unknown"),
            evidence_ref=EvidenceRef.from_dict(evidence) if evidence else None,
            provenance=value.get("provenance", "unknown"),
            evidence_state=value.get("evidence_state", "unknown"),
        )


@dataclass(frozen=True)
class MarketLane:
    """Market-specific logistics, tax, payment, and evidence assumptions."""

    lane_id: str
    origin: str
    ship_from: str
    warehouse: str
    destination_country: str
    destination_region: str = ""
    currency: str = "MXN"
    tax_rate: Decimal | int | str | float = _ZERO
    duty_rate: Decimal | int | str | float = _ZERO
    brokerage_fee: Money | None = None
    payment_fee_rate: Decimal | None = None
    payment_fee_fixed: Money | None = None
    platform_fee_rate: Decimal | None = None
    marketplace_fee_rate: Decimal | None = None
    return_destination: str = ""
    delivery_promise: str = ""
    support_language: str = "es"
    marketplace_permissions: tuple[str, ...] = ()
    compliance: tuple[str, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    tax_inclusion_state: str = "unknown"

    @property
    def origin_country(self) -> str:
        """Descriptive alias for callers using the full lane vocabulary."""
        return self.origin

    @property
    def ship_from_country(self) -> str:
        """Descriptive alias for callers using the full lane vocabulary."""
        return self.ship_from

    def __post_init__(self) -> None:
        for name in ("lane_id", "origin", "ship_from", "warehouse", "destination_country", "destination_region", "return_destination", "delivery_promise", "support_language"):
            _text(getattr(self, name), name, allow_empty=name in {"destination_region", "return_destination", "delivery_promise"})
        object.__setattr__(self, "currency", _currency(self.currency))
        object.__setattr__(self, "tax_rate", _rate(self.tax_rate, "tax rate", allow_none=False))
        object.__setattr__(self, "duty_rate", _rate(self.duty_rate, "duty rate", allow_none=False))
        for name in ("payment_fee_rate", "platform_fee_rate", "marketplace_fee_rate"):
            object.__setattr__(self, name, _rate(getattr(self, name), name, allow_none=True))
        for fee_name in ("brokerage_fee", "payment_fee_fixed"):
            fee = getattr(self, fee_name)
            if fee is not None:
                if not isinstance(fee, Money):
                    raise EconomicsError(f"invalid {fee_name}")
                if fee.currency != self.currency:
                    raise CurrencyMismatchError()
        if self.tax_inclusion_state not in TAX_INCLUSION_STATES:
            raise EconomicsError("invalid tax inclusion state")
        if not isinstance(self.evidence_refs, tuple) or any(not isinstance(item, EvidenceRef) for item in self.evidence_refs):
            raise EconomicsError("invalid lane evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "lane_id": self.lane_id,
            "origin": self.origin,
            "origin_country": self.origin_country,
            "ship_from": self.ship_from,
            "ship_from_country": self.ship_from_country,
            "warehouse": self.warehouse,
            "destination_country": self.destination_country,
            "destination_region": self.destination_region,
            "currency": self.currency,
            "tax_rate": str(self.tax_rate),
            "duty_rate": str(self.duty_rate),
            "brokerage_fee": self.brokerage_fee.to_dict() if self.brokerage_fee else None,
            "payment_fee_rate": str(self.payment_fee_rate) if self.payment_fee_rate is not None else "unknown",
            "payment_fee_fixed": self.payment_fee_fixed.to_dict() if self.payment_fee_fixed else None,
            "platform_fee_rate": str(self.platform_fee_rate) if self.platform_fee_rate is not None else "unknown",
            "marketplace_fee_rate": str(self.marketplace_fee_rate) if self.marketplace_fee_rate is not None else "unknown",
            "return_destination": self.return_destination,
            "delivery_promise": self.delivery_promise,
            "support_language": self.support_language,
            "marketplace_permissions": list(self.marketplace_permissions),
            "compliance": list(self.compliance),
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "tax_inclusion_state": self.tax_inclusion_state,
        }


@dataclass(frozen=True)
class UnitEconomicsAssumptions:
    """Explicit optional costs and reserves for one market lane."""

    supplier_shipping: Money | None = None
    domestic_shipping: Money | None = None
    international_shipping: Money | None = None
    brokerage_fee: Money | None = None
    payment_fee_rate: Decimal | None = None
    payment_fee_fixed: Money | None = None
    platform_fee_rate: Decimal | None = None
    platform_fee_fixed: Money | None = None
    marketplace_fee_rate: Decimal | None = None
    affiliate_fee_rate: Decimal | None = None
    tax_rate: Decimal | None = None
    duty_rate: Decimal | None = None
    return_rate: Decimal | None = None
    defect_rate: Decimal | None = None
    warranty_rate: Decimal | None = None
    support_reserve_rate: Decimal | None = None
    chargeback_rate: Decimal | None = None
    fx_reserve_rate: Decimal | None = None
    discount_rate: Decimal | None = None
    conversion_rate: Decimal | None = None
    ad_spend: Money | None = None
    cac: Money | None = None
    refund_lag_days: Decimal | int | str | float = _ZERO
    target_margin_rate: Decimal | int | str | float = Decimal("0.20")
    evidence_refs: tuple[EvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        for name in ("payment_fee_rate", "platform_fee_rate", "marketplace_fee_rate", "affiliate_fee_rate", "tax_rate", "duty_rate", "return_rate", "defect_rate", "warranty_rate", "support_reserve_rate", "chargeback_rate", "fx_reserve_rate", "discount_rate", "conversion_rate", "target_margin_rate"):
            value = _rate(getattr(self, name), name, allow_none=True)
            object.__setattr__(self, name, value)
        lag = _decimal(self.refund_lag_days, "refund lag days")
        if lag < _ZERO:
            raise EconomicsError("invalid refund lag days")
        object.__setattr__(self, "refund_lag_days", lag)
        for name in ("supplier_shipping", "domestic_shipping", "international_shipping", "brokerage_fee", "payment_fee_fixed", "platform_fee_fixed", "ad_spend", "cac"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, Money):
                raise EconomicsError(f"invalid {name}")
        if not isinstance(self.evidence_refs, tuple) or any(not isinstance(item, EvidenceRef) for item in self.evidence_refs):
            raise EconomicsError("invalid economics evidence")


@dataclass(frozen=True)
class UnitEconomicsResult:
    """Exact per-order economics and explicit missing-evidence state."""

    scenario: str
    currency: str
    net_sales: Money
    product_cost: Money
    supplier_shipping: Money
    domestic_shipping: Money
    international_shipping: Money
    duty: Money
    tax: Money
    brokerage: Money
    payment_fees: Money
    platform_fees: Money
    marketplace_fees: Money
    affiliate_fees: Money
    return_reserve: Money
    defect_reserve: Money
    warranty_reserve: Money
    support_reserve: Money
    chargeback_reserve: Money
    fx_reserve: Money
    cac: Money
    contribution_before_cac: Money
    contribution_after_cac: Money
    contribution_margin: Decimal | None
    contribution_margin_after_cac: Decimal | None
    break_even_cac: Money
    target_cac: Money
    break_even_roas: Decimal | None
    target_roas: Decimal | None
    cash_required_per_order: Money
    refund_lag_exposure: Money
    evidence_state: str
    evidence_refs: tuple[EvidenceRef, ...]
    missing_inputs: tuple[str, ...] = ()

    @property
    def margin(self) -> Decimal | None:
        return self.contribution_margin

    @property
    def expected_return_cost(self) -> Money:
        return self.return_reserve

    @property
    def refund_loss(self) -> Money:
        return self.return_reserve

    @property
    def defect_cost(self) -> Money:
        return self.defect_reserve

    @property
    def warranty_cost(self) -> Money:
        return self.warranty_reserve

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"scenario": self.scenario, "currency": self.currency}
        for name in (
            "net_sales", "product_cost", "supplier_shipping", "domestic_shipping", "international_shipping", "duty", "tax", "brokerage", "payment_fees", "platform_fees", "marketplace_fees", "affiliate_fees", "return_reserve", "defect_reserve", "warranty_reserve", "support_reserve", "chargeback_reserve", "fx_reserve", "cac", "contribution_before_cac", "contribution_after_cac", "break_even_cac", "target_cac", "cash_required_per_order", "refund_lag_exposure",
        ):
            result[name] = getattr(self, name).to_dict()
        for name in ("contribution_margin", "contribution_margin_after_cac", "break_even_roas", "target_roas"):
            value = getattr(self, name)
            result[name] = str(value) if value is not None else "unknown"
        result.update({
            "expected_return_cost": self.expected_return_cost.to_dict(),
            "refund_loss": self.refund_loss.to_dict(),
            "defect_cost": self.defect_cost.to_dict(),
            "warranty_cost": self.warranty_cost.to_dict(),
            "evidence_state": self.evidence_state,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "missing_inputs": list(self.missing_inputs),
        })
        return result


def _zero(currency: str, name: str) -> Money:
    return Money.zero(currency, source=f"assumed_{name}")


def _resolve_money(value: Money | None, currency: str, name: str, missing: list[str]) -> Money:
    if value is None:
        missing.append(name)
        return _zero(currency, name)
    if value.currency != currency:
        raise CurrencyMismatchError()
    if value.amount < _ZERO:
        raise EconomicsError(f"invalid {name}")
    return value


def _resolve_rate(value: Decimal | None, fallback: Decimal | None, name: str, missing: list[str]) -> Decimal:
    if value is not None:
        return value
    if fallback is not None:
        return fallback
    missing.append(name)
    return _ZERO


def _evidence_state(refs: Iterable[EvidenceRef]) -> str:
    states = [item.evidence_state for item in refs]
    if not states:
        return "unknown"
    if any(item in {"missing", "unknown", "stale", "rejected"} for item in states):
        return "unknown"
    if any(item in {"fixture", "simulated", "assumed", "derived"} for item in states):
        return "assumed"
    if all(item == "verified" for item in states):
        return "verified"
    if any(item == "live_readonly" for item in states):
        return "live_readonly"
    return "observed"


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    return numerator / denominator if denominator > _ZERO else None


def calculate_unit_economics(
    price: Money,
    product_cost: Money,
    *,
    lane: MarketLane | None = None,
    assumptions: UnitEconomicsAssumptions | None = None,
    scenario: str = "base",
) -> UnitEconomicsResult:
    """Calculate one exact Decimal scenario without hidden FX or assumptions."""
    if not isinstance(price, Money) or not isinstance(product_cost, Money):
        raise EconomicsError("price and product cost must be money")
    if price.currency != product_cost.currency:
        raise CurrencyMismatchError()
    if price.amount < _ZERO or product_cost.amount < _ZERO:
        raise EconomicsError("invalid price or product cost")
    _text(scenario, "scenario")
    assumptions = assumptions or UnitEconomicsAssumptions()
    if lane is not None and not isinstance(lane, MarketLane):
        raise EconomicsError("invalid market lane")
    if lane is not None and lane.currency != price.currency:
        raise CurrencyMismatchError()

    missing: list[str] = []
    currency = price.currency
    supplier_shipping = _resolve_money(assumptions.supplier_shipping, currency, "supplier_shipping", missing)
    domestic_shipping = _resolve_money(assumptions.domestic_shipping, currency, "domestic_shipping", missing)
    international_shipping = _resolve_money(assumptions.international_shipping, currency, "international_shipping", missing)
    brokerage_value = assumptions.brokerage_fee if assumptions.brokerage_fee is not None else (lane.brokerage_fee if lane else None)
    brokerage = _resolve_money(brokerage_value, currency, "brokerage_fee", missing)
    payment_fixed = _resolve_money(assumptions.payment_fee_fixed, currency, "payment_fee_fixed", missing)
    if assumptions.payment_fee_fixed is None and lane and lane.payment_fee_fixed is not None:
        payment_fixed = _resolve_money(lane.payment_fee_fixed, currency, "payment_fee_fixed", missing)
        missing.pop() if missing and missing[-1] == "payment_fee_fixed" else None
    platform_fixed = _resolve_money(assumptions.platform_fee_fixed, currency, "platform_fee_fixed", missing)
    calculated_cac = assumptions.cac
    if calculated_cac is None and assumptions.ad_spend is not None and assumptions.conversion_rate is not None and assumptions.conversion_rate > _ZERO:
        if assumptions.ad_spend.currency != currency:
            raise CurrencyMismatchError()
        calculated_cac = assumptions.ad_spend.divide(assumptions.conversion_rate)
    cac = _resolve_money(calculated_cac, currency, "cac", missing)

    tax_rate = _resolve_rate(assumptions.tax_rate, lane.tax_rate if lane else None, "tax_rate", missing)
    duty_rate = _resolve_rate(assumptions.duty_rate, lane.duty_rate if lane else None, "duty_rate", missing)
    payment_rate = _resolve_rate(assumptions.payment_fee_rate, lane.payment_fee_rate if lane else None, "payment_fee_rate", missing)
    platform_rate = _resolve_rate(assumptions.platform_fee_rate, lane.platform_fee_rate if lane else None, "platform_fee_rate", missing)
    marketplace_rate = _resolve_rate(assumptions.marketplace_fee_rate, lane.marketplace_fee_rate if lane else None, "marketplace_fee_rate", missing)
    affiliate_rate = assumptions.affiliate_fee_rate if assumptions.affiliate_fee_rate is not None else _ZERO
    if assumptions.affiliate_fee_rate is None:
        missing.append("affiliate_fee_rate")
    return_rate = assumptions.return_rate if assumptions.return_rate is not None else _ZERO
    if assumptions.return_rate is None:
        missing.append("return_rate")
    defect_rate = assumptions.defect_rate if assumptions.defect_rate is not None else _ZERO
    if assumptions.defect_rate is None:
        missing.append("defect_rate")
    warranty_rate = assumptions.warranty_rate if assumptions.warranty_rate is not None else _ZERO
    if assumptions.warranty_rate is None:
        missing.append("warranty_rate")
    support_rate = assumptions.support_reserve_rate if assumptions.support_reserve_rate is not None else _ZERO
    if assumptions.support_reserve_rate is None:
        missing.append("support_reserve_rate")
    chargeback_rate = assumptions.chargeback_rate if assumptions.chargeback_rate is not None else _ZERO
    if assumptions.chargeback_rate is None:
        missing.append("chargeback_rate")
    fx_rate = assumptions.fx_reserve_rate if assumptions.fx_reserve_rate is not None else _ZERO
    if assumptions.fx_reserve_rate is None:
        missing.append("fx_reserve_rate")
    discount_rate = assumptions.discount_rate if assumptions.discount_rate is not None else _ZERO
    if assumptions.discount_rate is None:
        missing.append("discount_rate")

    lane_tax_state = lane.tax_inclusion_state if lane else "unknown"
    price_tax_state = price.tax_inclusion_state if price.tax_inclusion_state != "unknown" else lane_tax_state
    net_sales = price.multiply(_ONE - discount_rate)
    landed = product_cost + supplier_shipping + domestic_shipping + international_shipping
    duty = landed.multiply(duty_rate)
    tax = _zero(currency, "tax") if price_tax_state == "inclusive" else net_sales.multiply(tax_rate)
    payment_fees = net_sales.multiply(payment_rate) + payment_fixed
    platform_fees = net_sales.multiply(platform_rate) + platform_fixed
    marketplace_fees = net_sales.multiply(marketplace_rate)
    affiliate_fees = net_sales.multiply(affiliate_rate)
    return_reserve = net_sales.multiply(return_rate)
    defect_reserve = product_cost.multiply(defect_rate)
    warranty_reserve = product_cost.multiply(warranty_rate)
    support_reserve = net_sales.multiply(support_rate)
    chargeback_reserve = net_sales.multiply(chargeback_rate)
    pre_fx_costs = landed + duty + tax + brokerage + payment_fees + platform_fees + marketplace_fees + affiliate_fees + return_reserve + defect_reserve + warranty_reserve + support_reserve + chargeback_reserve
    fx_reserve = pre_fx_costs.multiply(fx_rate)
    contribution_before = net_sales - (pre_fx_costs + fx_reserve)
    contribution_after = contribution_before - cac
    break_even_cac = Money(max(_ZERO, contribution_before.amount), currency, source="derived", provenance="derived")
    target_cac = Money(max(_ZERO, contribution_before.amount - (net_sales.amount * assumptions.target_margin_rate)), currency, source="derived", provenance="derived")
    break_even_roas = _ratio(net_sales.amount, break_even_cac.amount)
    target_roas = _ratio(net_sales.amount, target_cac.amount)
    cash_required = pre_fx_costs + fx_reserve + cac
    refund_lag_exposure = return_reserve.multiply(assumptions.refund_lag_days / _THIRTY)
    input_refs = [price.evidence_ref, product_cost.evidence_ref, *(item.evidence_ref for item in (supplier_shipping, domestic_shipping, international_shipping, cac) if item.evidence_ref)]
    refs = tuple(item for item in (*input_refs, *assumptions.evidence_refs, *(lane.evidence_refs if lane else ())) if item is not None)
    if price_tax_state == "unknown":
        missing.append("tax_inclusion_state")
    return UnitEconomicsResult(
        scenario=scenario,
        currency=currency,
        net_sales=net_sales,
        product_cost=product_cost,
        supplier_shipping=supplier_shipping,
        domestic_shipping=domestic_shipping,
        international_shipping=international_shipping,
        duty=duty,
        tax=tax,
        brokerage=brokerage,
        payment_fees=payment_fees,
        platform_fees=platform_fees,
        marketplace_fees=marketplace_fees,
        affiliate_fees=affiliate_fees,
        return_reserve=return_reserve,
        defect_reserve=defect_reserve,
        warranty_reserve=warranty_reserve,
        support_reserve=support_reserve,
        chargeback_reserve=chargeback_reserve,
        fx_reserve=fx_reserve,
        cac=cac,
        contribution_before_cac=contribution_before,
        contribution_after_cac=contribution_after,
        contribution_margin=_ratio(contribution_before.amount, net_sales.amount),
        contribution_margin_after_cac=_ratio(contribution_after.amount, net_sales.amount),
        break_even_cac=break_even_cac,
        target_cac=target_cac,
        break_even_roas=break_even_roas,
        target_roas=target_roas,
        cash_required_per_order=cash_required,
        refund_lag_exposure=refund_lag_exposure,
        evidence_state=_evidence_state(refs),
        evidence_refs=refs,
        missing_inputs=tuple(dict.fromkeys(missing)),
    )


def _scale_money(value: Money | None, factor: Decimal) -> Money | None:
    return value.multiply(factor) if value is not None else None


def calculate_scenarios(
    price: Money,
    product_cost: Money,
    *,
    lane: MarketLane | None = None,
    assumptions: UnitEconomicsAssumptions | None = None,
    overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, UnitEconomicsResult]:
    """Return deterministic base, downside, and upside scenarios."""
    base = assumptions or UnitEconomicsAssumptions()
    defaults: dict[str, dict[str, Any]] = {
        "base": {},
        "downside": {"price_factor": Decimal("0.90"), "shipping_factor": Decimal("1.20"), "cac_factor": Decimal("1.25"), "return_delta": Decimal("0.05")},
        "upside": {"price_factor": Decimal("1.05"), "shipping_factor": Decimal("0.90"), "cac_factor": Decimal("0.85"), "return_delta": Decimal("-0.02")},
    }
    for name, supplied in (overrides or {}).items():
        defaults[name] = {**defaults.get(name, {}), **dict(supplied)}
    results: dict[str, UnitEconomicsResult] = {}
    for name, config in defaults.items():
        scenario_price = price.multiply(config.get("price_factor", _ONE))
        scenario_assumptions = base
        shipping_factor = _decimal(config.get("shipping_factor", _ONE), "shipping factor")
        cac_factor = _decimal(config.get("cac_factor", _ONE), "cac factor")
        return_delta = _decimal(config.get("return_delta", _ZERO), "return delta")
        scenario_assumptions = replace(
            scenario_assumptions,
            supplier_shipping=_scale_money(base.supplier_shipping, shipping_factor),
            domestic_shipping=_scale_money(base.domestic_shipping, shipping_factor),
            international_shipping=_scale_money(base.international_shipping, shipping_factor),
            cac=_scale_money(base.cac, cac_factor),
            return_rate=(None if base.return_rate is None and return_delta == _ZERO else min(_ONE, max(_ZERO, (base.return_rate or _ZERO) + return_delta))),
        )
        results[name] = calculate_unit_economics(scenario_price, product_cost, lane=lane, assumptions=scenario_assumptions, scenario=name)
    return results


def sensitivity_matrix(
    price: Money,
    product_cost: Money,
    parameter_values: Mapping[str, Iterable[Any]],
    *,
    lane: MarketLane | None = None,
    assumptions: UnitEconomicsAssumptions | None = None,
) -> dict[str, tuple[UnitEconomicsResult, ...]]:
    """Evaluate an allowlisted sensitivity set without accepting arbitrary fields."""
    base = assumptions or UnitEconomicsAssumptions()
    allowed_rates = {"payment_fee_rate", "platform_fee_rate", "marketplace_fee_rate", "affiliate_fee_rate", "tax_rate", "duty_rate", "return_rate", "defect_rate", "warranty_rate", "support_reserve_rate", "chargeback_rate", "fx_reserve_rate", "discount_rate", "conversion_rate", "fx", "returns", "defects", "discounts", "marketplace_fees"}
    allowed_money = {"cac", "supplier_shipping", "domestic_shipping", "international_shipping", "shipping", "supplier_cost"}
    output: dict[str, tuple[UnitEconomicsResult, ...]] = {}
    for name, values in parameter_values.items():
        if name not in allowed_rates and name not in allowed_money and name not in {"price", "conversion"}:
            raise EconomicsError("unsupported sensitivity parameter")
        rows: list[UnitEconomicsResult] = []
        for index, value in enumerate(values):
            scenario_price = price
            scenario_product_cost = product_cost
            scenario_assumptions = base
            if name == "price":
                scenario_price = value if isinstance(value, Money) else Money(value, price.currency, source="sensitivity", provenance="assumed")
            elif name == "supplier_cost":
                scenario_product_cost = value if isinstance(value, Money) else Money(value, product_cost.currency, source="sensitivity", provenance="assumed")
            elif name in {"shipping", "supplier_shipping"}:
                shipping_value = value if isinstance(value, Money) else Money(value, price.currency, source="sensitivity", provenance="assumed")
                scenario_assumptions = replace(base, supplier_shipping=shipping_value)
            elif name in {"fx", "fx_reserve_rate", "returns", "return_rate", "defects", "defect_rate", "discounts", "discount_rate", "marketplace_fees", "marketplace_fee_rate"}:
                field_name = {"fx": "fx_reserve_rate", "returns": "return_rate", "defects": "defect_rate", "discounts": "discount_rate", "marketplace_fees": "marketplace_fee_rate"}.get(name, name)
                scenario_assumptions = replace(base, **{field_name: _rate(value, field_name, allow_none=False)})
            elif name == "conversion":
                conversion = _rate(value, "conversion rate", allow_none=False)
                scenario_assumptions = replace(base, conversion_rate=conversion, cac=None if base.ad_spend is not None else base.cac)
            elif name in allowed_rates:
                scenario_assumptions = replace(base, **{name: _rate(value, name, allow_none=False)})
            else:
                scenario_assumptions = replace(base, **{name: value if isinstance(value, Money) else Money(value, price.currency, source="sensitivity", provenance="assumed")})
            rows.append(calculate_unit_economics(scenario_price, scenario_product_cost, lane=lane, assumptions=scenario_assumptions, scenario=f"sensitivity:{name}:{index}"))
        output[name] = tuple(rows)
    return output


def incremental_contribution(
    ad_spend: Money | Decimal | int | str | float,
    contribution_margin: Decimal | int | str | float,
    roas_after: Decimal | int | str | float,
    roas_before: Decimal | int | str | float,
    service_fee: Money | Decimal | int | str | float,
    *,
    currency: str = "USD",
) -> Money:
    """Exact service formula: ad spend * margin * ROAS lift - service fee."""
    if isinstance(ad_spend, Money):
        spend = ad_spend
    else:
        spend = Money(ad_spend, currency, source="assumed", provenance="assumed")
    if isinstance(service_fee, Money):
        fee = service_fee
    else:
        fee = Money(service_fee, spend.currency, source="assumed", provenance="assumed")
    if spend.currency != fee.currency:
        raise CurrencyMismatchError()
    margin = _rate(contribution_margin, "contribution margin", allow_none=False) or _ZERO
    after = _decimal(roas_after, "ROAS after")
    before = _decimal(roas_before, "ROAS before")
    if after < _ZERO or before < _ZERO:
        raise EconomicsError("invalid ROAS")
    return Money(spend.amount * margin * (after - before) - fee.amount, spend.currency, source="derived", provenance="derived")


def orders_required_to_recover_fee(
    service_fee: Money | Decimal | int | str | float,
    cac_before: Money | Decimal | int | str | float,
    cac_after: Money | Decimal | int | str | float,
    *,
    currency: str = "USD",
) -> Decimal | None:
    """Return fee / CAC reduction, or unknown when the reduction is non-positive."""
    if isinstance(service_fee, Money):
        fee = service_fee
    else:
        fee = Money(service_fee, currency, source="assumed", provenance="assumed")
    before = cac_before if isinstance(cac_before, Money) else Money(cac_before, fee.currency, source="assumed", provenance="assumed")
    after = cac_after if isinstance(cac_after, Money) else Money(cac_after, fee.currency, source="assumed", provenance="assumed")
    if before.currency != fee.currency or after.currency != fee.currency:
        raise CurrencyMismatchError()
    reduction = before.amount - after.amount
    return fee.amount / reduction if reduction > _ZERO else None


@dataclass(frozen=True)
class ServiceEconomics:
    service_id: str
    service_fee: Money
    incremental_contribution: Money | None
    orders_required_to_recover_fee: Decimal | None
    delivery_hours: Decimal
    capacity_hours: Decimal | None
    capacity_utilization: Decimal | None
    roi: Decimal | None
    evidence_state: str = "unknown"
    evidence_refs: tuple[EvidenceRef, ...] = ()
    service_revenue: Money | None = None
    delivery_cost: Money | None = None
    tooling_cost: Money | None = None
    pass_through_cost: Money | None = None
    refund_revision_reserve: Money | None = None
    contribution: Money | None = None
    contribution_margin: Decimal | None = None
    contribution_per_hour: Money | None = None
    maximum_simultaneous_clients: Decimal | None = None
    required_clients_for_target_monthly_contribution: Decimal | None = None
    client_value_created: Money | None = None
    client_value_multiple: Decimal | None = None
    minimum_acceptable_value_multiple: Decimal = Decimal("1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "service_id": self.service_id,
            "service_fee": self.service_fee.to_dict(),
            "incremental_contribution": self.incremental_contribution.to_dict() if self.incremental_contribution else None,
            "orders_required_to_recover_fee": str(self.orders_required_to_recover_fee) if self.orders_required_to_recover_fee is not None else "unknown",
            "delivery_hours": str(self.delivery_hours),
            "capacity_hours": str(self.capacity_hours) if self.capacity_hours is not None else "unknown",
            "capacity_utilization": str(self.capacity_utilization) if self.capacity_utilization is not None else "unknown",
            "roi": str(self.roi) if self.roi is not None else "unknown",
            "evidence_state": self.evidence_state,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "service_revenue": self.service_revenue.to_dict() if self.service_revenue else None,
            "delivery_cost": self.delivery_cost.to_dict() if self.delivery_cost else None,
            "tooling_cost": self.tooling_cost.to_dict() if self.tooling_cost else None,
            "pass_through_cost": self.pass_through_cost.to_dict() if self.pass_through_cost else None,
            "refund_revision_reserve": self.refund_revision_reserve.to_dict() if self.refund_revision_reserve else None,
            "contribution": self.contribution.to_dict() if self.contribution else None,
            "contribution_margin": str(self.contribution_margin) if self.contribution_margin is not None else "unknown",
            "contribution_per_hour": self.contribution_per_hour.to_dict() if self.contribution_per_hour else None,
            "maximum_simultaneous_clients": str(self.maximum_simultaneous_clients) if self.maximum_simultaneous_clients is not None else "unknown",
            "required_clients_for_target_monthly_contribution": str(self.required_clients_for_target_monthly_contribution) if self.required_clients_for_target_monthly_contribution is not None else "unknown",
            "client_value_created": self.client_value_created.to_dict() if self.client_value_created else None,
            "client_value_multiple": str(self.client_value_multiple) if self.client_value_multiple is not None else "unknown",
            "minimum_acceptable_value_multiple": str(self.minimum_acceptable_value_multiple),
        }


def calculate_service_economics(
    service_id: str,
    service_fee: Money,
    *,
    ad_spend: Money | None = None,
    contribution_margin: Decimal | int | str | float | None = None,
    roas_before: Decimal | int | str | float | None = None,
    roas_after: Decimal | int | str | float | None = None,
    cac_before: Money | None = None,
    cac_after: Money | None = None,
    delivery_hours: Decimal | int | str | float,
    capacity_hours: Decimal | int | str | float | None = None,
    evidence_refs: tuple[EvidenceRef, ...] = (),
    delivery_cost: Money | None = None,
    tooling_cost: Money | None = None,
    pass_through_cost: Money | None = None,
    refund_revision_reserve: Money | None = None,
    target_monthly_contribution: Money | None = None,
    client_value_created: Money | None = None,
    minimum_acceptable_value_multiple: Decimal | int | str | float = Decimal("1"),
) -> ServiceEconomics:
    _text(service_id, "service id")
    if not isinstance(service_fee, Money):
        raise EconomicsError("service economics requires a service fee")
    performance_inputs = (ad_spend, contribution_margin, roas_before, roas_after, cac_before, cac_after)
    performance_inputs_provided = tuple(value is not None for value in performance_inputs)
    if any(performance_inputs_provided) and not all(performance_inputs_provided):
        raise EconomicsError("service performance evidence must be complete")
    if all(performance_inputs_provided):
        if not all(isinstance(value, Money) for value in (ad_spend, cac_before, cac_after)):
            raise EconomicsError("service performance economics requires money")
        for value in (ad_spend, cac_before, cac_after):
            if value.currency != service_fee.currency:
                raise CurrencyMismatchError()
    for name, value in (("delivery cost", delivery_cost), ("tooling cost", tooling_cost), ("pass-through cost", pass_through_cost), ("refund revision reserve", refund_revision_reserve), ("target monthly contribution", target_monthly_contribution), ("client value", client_value_created)):
        if value is not None:
            if value.currency != service_fee.currency or value.amount < _ZERO:
                raise CurrencyMismatchError() if value.currency != service_fee.currency else EconomicsError(f"invalid {name}")
    delivery_hours_value = _decimal(delivery_hours, "delivery hours")
    if delivery_hours_value < _ZERO:
        raise EconomicsError("invalid delivery hours")
    capacity = None if capacity_hours is None else _decimal(capacity_hours, "capacity hours")
    if capacity is not None and capacity < _ZERO:
        raise EconomicsError("invalid capacity hours")
    utilization = delivery_hours_value / capacity if capacity and capacity > _ZERO else None
    performance_contribution = None
    orders = None
    roi = None
    if all(performance_inputs_provided):
        performance_contribution = incremental_contribution(ad_spend, contribution_margin, roas_after, roas_before, service_fee)
        orders = orders_required_to_recover_fee(service_fee, cac_before, cac_after)
        roi = performance_contribution.amount / service_fee.amount if service_fee.amount != _ZERO else None
    delivery_cost_value = delivery_cost or Money.zero(service_fee.currency, source="assumed_delivery_cost")
    tooling = tooling_cost or Money.zero(service_fee.currency, source="assumed_tooling_cost")
    pass_through = pass_through_cost or Money.zero(service_fee.currency, source="assumed_pass_through_cost")
    reserve = refund_revision_reserve or Money.zero(service_fee.currency, source="assumed_refund_revision_reserve")
    contribution_amount = service_fee - (delivery_cost_value + tooling + pass_through + reserve)
    contribution_margin_value = _ratio(contribution_amount.amount, service_fee.amount)
    contribution_per_hour = contribution_amount.divide(delivery_hours_value) if delivery_hours_value > _ZERO else None
    target_clients = None
    if target_monthly_contribution is not None and contribution_amount.amount > _ZERO:
        target_clients = target_monthly_contribution.amount / contribution_amount.amount
    client_multiple = None
    if client_value_created is not None and service_fee.amount > _ZERO:
        client_multiple = client_value_created.amount / service_fee.amount
    return ServiceEconomics(
        service_id, service_fee, performance_contribution, orders, delivery_hours=delivery_hours_value, capacity_hours=capacity,
        capacity_utilization=utilization, roi=roi, evidence_state=_evidence_state(evidence_refs), evidence_refs=evidence_refs,
        service_revenue=service_fee, delivery_cost=delivery_cost_value, tooling_cost=tooling, pass_through_cost=pass_through,
        refund_revision_reserve=reserve, contribution=contribution_amount, contribution_margin=contribution_margin_value,
        contribution_per_hour=contribution_per_hour,
        maximum_simultaneous_clients=(capacity / delivery_hours_value if capacity and delivery_hours_value > _ZERO else None),
        required_clients_for_target_monthly_contribution=target_clients, client_value_created=client_value_created,
        client_value_multiple=client_multiple, minimum_acceptable_value_multiple=_decimal(minimum_acceptable_value_multiple, "minimum value multiple"),
    )


def canonical_json(value: Any) -> str:
    """Serialize kernel values with stable key order and Decimal strings."""
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    elif isinstance(value, Decimal):
        value = str(value)
    elif isinstance(value, Mapping):
        value = {str(key): json.loads(canonical_json(value_for_json)) for key, value_for_json in value.items()}
    elif isinstance(value, (tuple, list)):
        value = [json.loads(canonical_json(item)) for item in value]
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


UnitEconomicsInputs = UnitEconomicsAssumptions
CanonicalUnitEconomics = UnitEconomicsResult
calculate_unit_economics_scenarios = calculate_scenarios
sensitivity = sensitivity_matrix


__all__ = [
    "SUPPORTED_CURRENCIES", "EVIDENCE_STATES", "EconomicsError", "CurrencyMismatchError",
    "EvidenceRef", "Money", "MarketLane", "UnitEconomicsAssumptions", "UnitEconomicsInputs", "UnitEconomicsResult", "CanonicalUnitEconomics",
    "calculate_unit_economics", "calculate_scenarios", "calculate_unit_economics_scenarios", "sensitivity_matrix", "sensitivity",
    "incremental_contribution", "orders_required_to_recover_fee", "ServiceEconomics",
    "calculate_service_economics", "canonical_json",
]

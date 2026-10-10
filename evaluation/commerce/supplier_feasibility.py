"""Offline supplier feasibility and unit-economics intelligence.

Supplier feasibility is intentionally distinct from marketplace demand evidence.
It estimates whether a candidate appears sourceable from sanitized supplier
snapshots or manual imports; it never authorizes an order, inventory mutation,
fulfillment action, or provider write.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any, Iterable, Mapping

from backend.economics import CurrencyMismatchError, MarketLane, Money, UnitEconomicsAssumptions
from backend.economics import calculate_unit_economics as calculate_canonical_unit_economics
from backend.economics.kernel import SUPPORTED_CURRENCIES

PROVENANCE = frozenset(
    {
        "observed",
        "derived",
        "assumed",
        "unavailable",
        "malformed",
        "blocked",
        "manual_import",
        "fixture",
        "live_readonly",
    }
)
SUPPLIERS = frozenset({"cj", "alibaba", "aliexpress", "zendrop", "autods", "dsers", "spocket", "manual"})
SOURCE_TYPES = frozenset(
    {
        "cj_readonly_fixture",
        "cj_validation_pack_report",
        "cj_manual_import",
        "alibaba_supplier_snapshot",
        "alibaba_dropshipping_trending_snapshot",
        "alibaba_high_profit_snapshot",
        "aliexpress_supplier_snapshot",
        "zendrop_manual_import",
        "autods_manual_import",
        "dsers_manual_import",
        "spocket_manual_import",
        "manual_csv_import",
        "fixture_demo",
    }
)
FIXTURE_SOURCE_TYPES = frozenset({"cj_readonly_fixture", "fixture_demo"})
_NON_CURRENCY_AMOUNT_TOKENS = frozenset({"PER", "PCS", "FOB", "EXW", "MOQ", "SKU", "VAT", "INC", "SET", "CBM"})


class _ParsedNumber(float):
    """Float-compatible parsed value retaining exact Decimal and currency hints."""

    display_currencies: tuple[str, ...]
    decimal_amount: Decimal
    raw_text: str

    def __new__(
        cls,
        value: float,
        display_currencies: tuple[str, ...],
        decimal_amount: Decimal,
        raw_text: str,
    ) -> "_ParsedNumber":
        result = super().__new__(cls, value)
        result.display_currencies = display_currencies
        result.decimal_amount = decimal_amount
        result.raw_text = raw_text
        return result

    def __deepcopy__(self, memo: dict[int, Any]) -> "_ParsedNumber":
        return self


def _display_currency_markers(value: Any) -> tuple[str, ...]:
    if isinstance(value, _ParsedNumber):
        return value.display_currencies
    if not isinstance(value, str):
        return ()
    text = value.upper()
    markers = (
        {
            token.upper()
            for token in re.findall(r"(?<![A-Za-z])([A-Za-z]{3})(?![A-Za-z])", value)
            if token.isupper() or token.upper() in SUPPORTED_CURRENCIES
        }
        - {"NAN", "INF"}
        - _NON_CURRENCY_AMOUNT_TOKENS
    )
    if "US$" in text:
        markers.add("USD")
    if "CA$" in text or "C$" in text:
        markers.add("CAD")
    if "MX$" in text:
        markers.add("MXN")
    if "€" in value:
        markers.add("EUR")
    if "£" in value:
        markers.add("GBP")
    if "$" in value and not any(prefix in text for prefix in ("US$", "CA$", "C$", "MX$")):
        markers.add("DOLLAR")
    return tuple(sorted(markers))


def _display_currency_issue(value: Any, declared_currency: str | None) -> str | None:
    markers = set(_display_currency_markers(value))
    if not markers:
        return None
    if markers - set(SUPPORTED_CURRENCIES) - {"DOLLAR"}:
        return "unsupported_currency"
    explicit = markers & set(SUPPORTED_CURRENCIES)
    if len(explicit) > 1:
        return "currency_mismatch"
    if not isinstance(declared_currency, str) or not declared_currency.strip():
        return "currency_missing"
    declared = declared_currency.strip().upper()
    if declared not in SUPPORTED_CURRENCIES:
        return "unsupported_currency"
    if explicit and declared not in explicit:
        return "currency_mismatch"
    if "DOLLAR" in markers and declared not in {"USD", "CAD", "MXN"}:
        return "currency_mismatch"
    if "DOLLAR" in markers and explicit and declared not in explicit:
        return "currency_mismatch"
    return None


def _without_display_currency(value: str) -> str:
    text = value
    text = re.sub(r"(?<![A-Za-z])[A-Za-z]{3}(?![A-Za-z])", " ", text)
    for marker in ("US$", "CA$", "C$", "MX$", "$", "€", "£"):
        text = text.replace(marker, " ")
    return text


def _decimal_from_text(value: str, *, reject_extra_numbers: bool = True) -> tuple[Decimal | None, bool]:
    parts = value.strip().split()
    if not parts:
        return None, True
    amount_text = parts[0]
    if "," in amount_text:
        if not re.fullmatch(r"[+-]?(?:\d{1,3}(?:,\d{3})+)(?:\.\d+)?(?:[eE][+-]?\d+)?", amount_text):
            return None, True
        amount_text = amount_text.replace(",", "")
    try:
        amount = Decimal(amount_text)
    except InvalidOperation:
        return None, True
    if reject_extra_numbers:
        for extra in parts[1:]:
            try:
                Decimal(extra)
            except InvalidOperation:
                continue
            return None, True
    return amount, False


def _decimal_money_amount(value: Any) -> tuple[Decimal | None, bool]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, False
    if isinstance(value, bool):
        return None, True
    try:
        if isinstance(value, _ParsedNumber):
            amount, invalid_text = _decimal_from_text(
                _without_display_currency(value.raw_text)
            )
            if invalid_text or amount is None:
                return None, True
        elif isinstance(value, Decimal):
            amount = value
        elif isinstance(value, int):
            amount = Decimal(value)
        elif isinstance(value, float):
            amount = Decimal(str(value))
        else:
            amount, invalid_text = _decimal_from_text(_without_display_currency(str(value)))
            if invalid_text:
                return None, True
    except (InvalidOperation, TypeError, ValueError):
        return None, True
    if not amount.is_finite() or amount < 0:
        return None, True
    return amount, False


def _decimal_rate(value: Any) -> tuple[Decimal | None, bool]:
    if isinstance(value, bool):
        return None, True
    try:
        rate = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None, True
    if not rate.is_finite() or rate < 0 or rate > 1:
        return None, True
    return rate, False


def _finite_float(value: Any) -> tuple[float | None, bool]:
    if value is None:
        return None, False
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
        if not amount.is_finite():
            return None, True
        result = float(amount)
    except (InvalidOperation, OverflowError, TypeError, ValueError):
        return None, True
    if not math.isfinite(result) or (amount != 0 and result == 0):
        return None, True
    return result, False


def number(value: Any) -> float | None:
    if isinstance(value, _ParsedNumber):
        return value
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            result = float(value)
        except (OverflowError, TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None
    text = str(value)
    markers = _display_currency_markers(text)
    decimal_amount, invalid_text = _decimal_from_text(
        _without_display_currency(text), reject_extra_numbers=True
    )
    if invalid_text or decimal_amount is None:
        return None
    if not decimal_amount.is_finite():
        return None
    result = float(decimal_amount)
    if not math.isfinite(result):
        return None
    return _ParsedNumber(result, markers, decimal_amount, text)


def bounded(value: Any) -> float:
    return round(max(0.0, min(1.0, number(value) or 0.0)), 4)


def integer(value: Any) -> int | None:
    result = number(value)
    return int(result) if result is not None else None


def normalize_delivery_window(value: Any) -> tuple[int | None, int | None]:
    """Normalize ``7-15 days``/``10`` into minimum and maximum days."""
    if value in (None, ""):
        return None, None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return integer(value[0]), integer(value[1])
    text = str(value).lower().replace("days", "").replace("day", "").strip()
    numbers = []
    for token in text.replace("–", "-").split("-"):
        parsed = integer(token.strip())
        if parsed is not None:
            numbers.append(parsed)
    if not numbers:
        parsed = integer(text)
        return parsed, parsed
    return numbers[0], numbers[-1]


def normalize_inventory_status(value: Any, quantity: Any = None) -> str:
    text = str(value or "").strip().lower().replace(" ", "_")
    if text in {"in_stock", "available", "yes", "ready", "stocked"}:
        return "in_stock"
    if text in {"out_of_stock", "unavailable", "no", "sold_out"}:
        return "out_of_stock"
    if integer(quantity) is not None:
        return "in_stock" if integer(quantity) > 0 else "out_of_stock"
    return "unknown"


def _provenance(value: Any, fallback: str) -> str:
    return str(value) if str(value) in PROVENANCE else fallback


@dataclass(frozen=True)
class SupplierRiskFlag:
    code: str
    severity: str
    explanation: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class SupplierOfferSnapshot:
    supplier_product_id: str = ""
    supplier_title: str = ""
    supplier_sku: str = ""
    variant_count: int | None = None
    moq: int | None = None
    unit_cost: float | None = None
    currency: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SupplierLogisticsSnapshot:
    shipping_cost: float | None = None
    estimated_landed_cost: float | None = None
    delivery_min_days: int | None = None
    delivery_max_days: int | None = None
    warehouse_region: str = ""
    destination_region: str = ""
    fulfillment_method: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UnitEconomicsScenario:
    target_sell_price: float | None
    unit_cost: float | None
    shipping_cost: float | None
    estimated_landed_cost: float | None
    payment_fee_rate: float | None
    platform_fee_rate: float | None
    gross_margin: float | None
    gross_margin_percent: float | None
    break_even_cpa: float | None
    break_even_roas: float | None
    profit_per_order_before_ad_spend: float | None
    assumptions: tuple[str, ...] = ()
    canonical_economics: Mapping[str, Any] | None = None
    currency: str | None = None
    cost_currency: str | None = None
    shipping_currency: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["assumptions"] = list(self.assumptions)
        return result


def calculate_unit_economics(
    *,
    target_sell_price: Any,
    unit_cost: Any,
    shipping_cost: Any = None,
    estimated_landed_cost: Any = None,
    payment_fee_rate: float = 0.029,
    platform_fee_rate: float = 0.05,
    lane: MarketLane | None = None,
    currency: str | None = None,
    cost_currency: str | None = None,
    shipping_currency: str | None = None,
    sell_currency: str | None = None,
) -> UnitEconomicsScenario:
    """Compatibility adapter over the canonical Decimal economics model."""
    sell_amount, invalid_sell = _decimal_money_amount(target_sell_price)
    cost_amount, invalid_cost = _decimal_money_amount(unit_cost)
    shipping_amount, invalid_shipping = _decimal_money_amount(shipping_cost)
    landed_amount, invalid_landed = _decimal_money_amount(estimated_landed_cost)
    payment_rate, invalid_payment_rate = _decimal_rate(payment_fee_rate)
    platform_rate, invalid_platform_rate = _decimal_rate(platform_fee_rate)
    sell, unrepresentable_sell = _finite_float(sell_amount)
    cost, unrepresentable_cost = _finite_float(cost_amount)
    shipping, unrepresentable_shipping = _finite_float(shipping_amount)
    landed, unrepresentable_landed = _finite_float(landed_amount)
    payment_rate_value, unrepresentable_payment_rate = _finite_float(payment_rate)
    platform_rate_value, unrepresentable_platform_rate = _finite_float(platform_rate)
    invalid_input = any(
        (
            invalid_sell,
            invalid_cost,
            invalid_shipping,
            invalid_landed,
            invalid_payment_rate,
            invalid_platform_rate,
            unrepresentable_sell,
            unrepresentable_cost,
            unrepresentable_shipping,
            unrepresentable_landed,
            unrepresentable_payment_rate,
            unrepresentable_platform_rate,
        )
    )
    assumptions: list[str] = []

    resolved_sell_currency: str | None = None
    if sell_currency is not None and str(sell_currency).strip():
        resolved_sell_currency = str(sell_currency).strip().upper()
    elif lane and lane.currency:
        resolved_sell_currency = str(lane.currency).strip().upper()

    resolved_cost_currency: str | None = None
    if cost_currency is not None:
        val = str(cost_currency).strip().upper()
        resolved_cost_currency = val if val else None
    elif currency is not None:
        val = str(currency).strip().upper()
        resolved_cost_currency = val if val else None

    if resolved_sell_currency is None and resolved_cost_currency is not None:
        resolved_sell_currency = resolved_cost_currency

    resolved_shipping_currency: str | None = None
    if shipping_currency is not None:
        val = str(shipping_currency).strip().upper()
        resolved_shipping_currency = val if val else None
    elif currency is not None:
        val = str(currency).strip().upper()
        resolved_shipping_currency = val if val else None

    def currency_blocked(reason: str, *, output_currency: str | None = None) -> UnitEconomicsScenario:
        blocked_assumptions = list(assumptions)
        if shipping_amount is None:
            blocked_assumptions.append("shipping_cost_missing")
        blocked_landed = landed
        if blocked_landed is None and cost == 0 and shipping == 0:
            blocked_landed = 0.0
        return UnitEconomicsScenario(
            sell, cost, shipping, blocked_landed, payment_rate_value, platform_rate_value,
            None, None, None, None, None,
            tuple(dict.fromkeys([*blocked_assumptions, reason])),
            currency=output_currency or resolved_sell_currency,
            cost_currency=resolved_cost_currency,
            shipping_currency=resolved_shipping_currency,
        )

    # Let the canonical Money contract validate currency support; do not maintain
    # a second list or treat unsupported currencies as ordinary bad arithmetic.
    for candidate_currency in (resolved_sell_currency, resolved_cost_currency, resolved_shipping_currency):
        if candidate_currency is None:
            continue
        try:
            Money(Decimal("0"), candidate_currency, source="supplier_feasibility", provenance="assumed")
        except (TypeError, ValueError):
            return currency_blocked("unsupported_currency")

    # 1. Missing currency check
    if cost_amount is not None and not resolved_cost_currency:
        return currency_blocked("currency_missing")

    if shipping_amount is not None and not resolved_shipping_currency:
        return currency_blocked("currency_missing")

    if sell_amount is not None and not resolved_sell_currency:
        return currency_blocked("currency_missing")

    for value, declared_currency in (
        (target_sell_price, resolved_sell_currency),
        (unit_cost, resolved_cost_currency),
        (shipping_cost, resolved_shipping_currency),
        (estimated_landed_cost, resolved_cost_currency),
    ):
        issue = _display_currency_issue(value, declared_currency)
        if issue:
            return currency_blocked(issue)

    # 2. Currency mismatch check
    if lane and lane.currency and resolved_sell_currency and lane.currency.strip().upper() != resolved_sell_currency:
        return currency_blocked("currency_mismatch", output_currency=lane.currency)

    if resolved_cost_currency and resolved_sell_currency and resolved_cost_currency != resolved_sell_currency:
        return currency_blocked("currency_mismatch")

    if shipping_amount is not None and resolved_shipping_currency and resolved_sell_currency and resolved_shipping_currency != resolved_sell_currency:
        return currency_blocked("currency_mismatch")

    if (
        not invalid_input
        and landed_amount is not None
        and cost_amount is not None
        and shipping_amount is not None
    ):
        try:
            component_total = (
                Money(cost_amount, resolved_sell_currency, source="supplier_feasibility", provenance="assumed")
                + Money(shipping_amount, resolved_sell_currency, source="supplier_feasibility", provenance="assumed")
            ).amount
        except (CurrencyMismatchError, TypeError, ValueError):
            return currency_blocked("invalid_economics_input")
        if landed_amount != component_total:
            return UnitEconomicsScenario(
                sell, cost, shipping, None, payment_rate_value, platform_rate_value,
                None, None, None, None, None,
                tuple(assumptions + ["invalid_economics_input"]),
                currency=resolved_sell_currency,
                cost_currency=resolved_cost_currency,
                shipping_currency=resolved_shipping_currency,
            )

    if invalid_input:
        return UnitEconomicsScenario(
            sell, cost, shipping, None, payment_rate_value, platform_rate_value,
            None, None, None, None, None,
            tuple(assumptions + ["invalid_economics_input"]),
            currency=resolved_sell_currency,
            cost_currency=resolved_cost_currency,
            shipping_currency=resolved_shipping_currency,
        )

    if sell_amount == 0:
        return UnitEconomicsScenario(
            sell, cost, shipping, None, payment_rate_value, platform_rate_value,
            None, None, None, None, None,
            tuple(assumptions + ["sell_price_nonpositive"]),
            currency=resolved_sell_currency,
            cost_currency=resolved_cost_currency,
            shipping_currency=resolved_shipping_currency,
        )

    if landed_amount is None and cost_amount is not None:
        if shipping_amount is not None:
            try:
                landed_amount = (
                    Money(cost_amount, resolved_sell_currency, source="supplier_feasibility", provenance="assumed")
                    + Money(shipping_amount, resolved_sell_currency, source="supplier_feasibility", provenance="assumed")
                ).amount
                landed, unrepresentable_landed = _finite_float(landed_amount)
                if unrepresentable_landed:
                    return UnitEconomicsScenario(
                        sell, cost, shipping, None, payment_rate_value, platform_rate_value,
                        None, None, None, None, None,
                        tuple(assumptions + ["invalid_economics_input"]),
                        currency=resolved_sell_currency,
                        cost_currency=resolved_cost_currency,
                        shipping_currency=resolved_shipping_currency,
                    )
            except CurrencyMismatchError:
                return currency_blocked("currency_mismatch")
            except (TypeError, ValueError):
                return UnitEconomicsScenario(
                    sell, cost, shipping, None, payment_rate_value, platform_rate_value,
                    None, None, None, None, None,
                    tuple(assumptions + ["invalid_economics_input"]),
                    currency=resolved_sell_currency,
                    cost_currency=resolved_cost_currency,
                    shipping_currency=resolved_shipping_currency,
                )
        else:
            assumptions.append("shipping_cost_missing")
    elif shipping_amount is None:
        assumptions.append("shipping_cost_missing")

    if sell_amount is None or cost_amount is None:
        missing_assumptions = ["sell_price_or_landed_cost_missing"]
        if sell_amount is None:
            missing_assumptions.append("sell_price_missing")
        return UnitEconomicsScenario(
            sell, cost, shipping, None, payment_rate_value, platform_rate_value,
            None, None, None, None, None,
            tuple(assumptions + missing_assumptions),
            currency=resolved_sell_currency,
            cost_currency=resolved_cost_currency,
            shipping_currency=resolved_shipping_currency,
        )

    if shipping_amount is None:
        return UnitEconomicsScenario(
            sell, cost, shipping, None, payment_rate_value, platform_rate_value,
            None, None, None, None, None,
            tuple(assumptions + ["shipping_cost_missing"]),
            currency=resolved_sell_currency,
            cost_currency=resolved_cost_currency,
            shipping_currency=resolved_shipping_currency,
        )

    assert resolved_sell_currency is not None and resolved_cost_currency is not None
    try:
        canonical = calculate_canonical_unit_economics(
            Money(sell_amount, resolved_sell_currency, source="supplier_feasibility", provenance="assumed"),
            Money(cost_amount, resolved_sell_currency, source="supplier_feasibility", provenance="assumed"),
            lane=lane,
            assumptions=UnitEconomicsAssumptions(
                supplier_shipping=Money(shipping_amount, resolved_sell_currency, source="supplier_feasibility", provenance="assumed") if shipping_amount is not None else None,
                payment_fee_rate=None if lane and lane.payment_fee_rate is not None else payment_rate,
                platform_fee_rate=None if lane and lane.platform_fee_rate is not None else platform_rate,
                tax_rate=None if lane else Decimal("0"),
                duty_rate=None if lane else Decimal("0"),
                return_rate=Decimal("0"),
                defect_rate=Decimal("0"),
                warranty_rate=Decimal("0"),
                support_reserve_rate=Decimal("0"),
                chargeback_rate=Decimal("0"),
                fx_reserve_rate=Decimal("0"),
                discount_rate=Decimal("0"),
                affiliate_fee_rate=Decimal("0"),
                marketplace_fee_rate=Decimal("0"),
            ),
        )
    except CurrencyMismatchError:
        return currency_blocked("currency_mismatch")
    except (TypeError, ValueError):
        return UnitEconomicsScenario(
            sell, cost, shipping, None, payment_rate_value, platform_rate_value,
            None, None, None, None, None,
            tuple(assumptions + ["invalid_economics_input"]),
            currency=resolved_sell_currency,
            cost_currency=resolved_cost_currency,
            shipping_currency=resolved_shipping_currency,
        )
    profit, invalid_profit = _finite_float(canonical.contribution_before_cac.amount)
    margin_percent, invalid_margin_percent = _finite_float(canonical.contribution_margin)
    cpa, invalid_cpa = _finite_float(canonical.break_even_cac.amount)
    roas, invalid_roas = _finite_float(canonical.break_even_roas)
    if any((invalid_profit, invalid_margin_percent, invalid_cpa, invalid_roas)):
        return UnitEconomicsScenario(
            sell, cost, shipping, None, payment_rate_value, platform_rate_value,
            None, None, None, None, None,
            tuple(assumptions + ["invalid_economics_input"]),
            None,
            resolved_sell_currency,
            cost_currency=resolved_cost_currency,
            shipping_currency=resolved_shipping_currency,
        )
    return UnitEconomicsScenario(
        sell, cost, shipping, landed, payment_rate_value, platform_rate_value,
        profit, margin_percent, cpa, roas, profit,
        tuple(assumptions),
        canonical.to_dict(),
        resolved_sell_currency,
        cost_currency=resolved_cost_currency,
        shipping_currency=resolved_shipping_currency,
    )


@dataclass(frozen=True)
class SupplierFeasibilityEvidence:
    candidate_id: str
    query: str
    supplier: str
    source_type: str
    source_url: str = ""
    evidence_mode: str = "fixture"
    supplier_product_id: str = ""
    supplier_title: str = ""
    supplier_brand: str = ""
    supplier_sku: str = ""
    variant_count: int | None = None
    moq: int | None = None
    unit_cost: float | None = None
    currency: str | None = None
    shipping_cost: float | None = None
    shipping_currency: str | None = None
    estimated_landed_cost: float | None = None
    delivery_min_days: int | None = None
    delivery_max_days: int | None = None
    inventory_status: str = "unknown"
    inventory_quantity: int | None = None
    warehouse_region: str = ""
    destination_region: str = ""
    fulfillment_method: str = ""
    supplier_rating: float | None = None
    supplier_review_count: int | None = None
    order_count_text: str = ""
    best_seller_badge: bool = False
    trend_label: str = ""
    return_policy_signal: str = ""
    refund_policy_signal: str = ""
    source_confidence: float = 0.0
    field_provenance: Mapping[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    observed_at: str = "deterministic"
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False

    def __post_init__(self) -> None:
        if self.supplier not in SUPPLIERS:
            raise ValueError(f"unsupported supplier: {self.supplier}")
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"unsupported source_type: {self.source_type}")
        provenance_fallback: str | None = None
        if self.source_type in FIXTURE_SOURCE_TYPES:
            provenance_fallback = "fixture"
        elif self.source_type == "manual_csv_import" or self.source_type.endswith("_manual_import"):
            provenance_fallback = "manual_import"
        if provenance_fallback is not None:
            if self.evidence_mode == "live_readonly":
                object.__setattr__(self, "evidence_mode", provenance_fallback)
            if any(value == "live_readonly" for value in self.field_provenance.values()):
                object.__setattr__(
                    self,
                    "field_provenance",
                    {
                        key: provenance_fallback if value == "live_readonly" else value
                        for key, value in self.field_provenance.items()
                    },
                )
        if set(self.field_provenance.values()) - PROVENANCE:
            raise ValueError("invalid supplier evidence provenance")
        warnings = set(self.warnings)
        if "currency_assumed_usd" in warnings:
            object.__setattr__(self, "currency", None)
            warnings.discard("currency_assumed_usd")
            warnings.add("currency_missing")
        for field_name in ("unit_cost", "estimated_landed_cost"):
            status = self.field_provenance.get(field_name)
            if getattr(self, field_name) is None and status not in (None, "unavailable", "blocked"):
                warnings.add("invalid_economics_input")
        landed_status = self.field_provenance.get("estimated_landed_cost")
        if "landed_cost_derived" in warnings and landed_status not in (None, "derived"):
            object.__setattr__(self, "estimated_landed_cost", None)
            warnings.add("invalid_economics_input")
        for amount, declared_currency in (
            (self.unit_cost, self.currency),
            (self.shipping_cost, self.shipping_currency or self.currency),
            (self.estimated_landed_cost, self.currency),
        ):
            issue = _display_currency_issue(amount, declared_currency)
            if issue:
                warnings.add(issue)
        if warnings != set(self.warnings):
            object.__setattr__(self, "warnings", tuple(sorted(warnings)))
        if not self.read_only or self.network_calls or self.mutated:
            raise ValueError("supplier feasibility evidence must be offline and read-only")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["field_provenance"] = dict(self.field_provenance)
        result["warnings"] = list(self.warnings)
        return result


@dataclass(frozen=True)
class SupplierFeasibilityScore:
    candidate_id: str
    supplier_cost_confidence: float
    landed_cost_confidence: float
    inventory_confidence: float
    shipping_speed_score: float
    delivery_risk_score: float
    supplier_reliability_score: float
    fulfillment_confidence: float
    margin_feasibility_proxy: float
    source_diversity_score: float
    supplier_option_count: float
    overall_supplier_feasibility: float
    recommendation: str
    contributions: Mapping[str, float]
    reasons: tuple[str, ...] = ()
    economics: UnitEconomicsScenario | None = None
    risk_flags: tuple[SupplierRiskFlag, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["contributions"] = dict(self.contributions)
        result["reasons"] = list(self.reasons)
        result["risk_flags"] = [flag.to_dict() for flag in self.risk_flags]
        result["economics"] = self.economics.to_dict() if self.economics else None
        return result


@dataclass(frozen=True)
class SupplierFeasibilityCandidateResult:
    candidate_id: str
    query: str
    offers: tuple[SupplierFeasibilityEvidence, ...]
    score: SupplierFeasibilityScore
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "query": self.query,
            "offers": [offer.to_dict() for offer in self.offers],
            "score": self.score.to_dict(),
            "suppliers": sorted({offer.supplier for offer in self.offers}),
            "source_types": sorted({offer.source_type for offer in self.offers}),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class SupplierFeasibilityReport:
    report_version: str
    evidence_mode: str
    candidate_count: int
    offer_count: int
    suppliers_observed: tuple[str, ...]
    top_candidate_id: str | None
    next_best_action: str
    candidates: tuple[SupplierFeasibilityCandidateResult, ...]
    warnings: tuple[str, ...] = ()
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "evidence_mode": self.evidence_mode,
            "candidate_count": self.candidate_count,
            "offer_count": self.offer_count,
            "suppliers_observed": list(self.suppliers_observed),
            "top_candidate_id": self.top_candidate_id,
            "next_best_action": self.next_best_action,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "warnings": list(self.warnings),
            "read_only": self.read_only,
            "network_calls": self.network_calls,
            "mutated": self.mutated,
        }


def collapse_duplicates(records: Iterable[SupplierFeasibilityEvidence]) -> list[SupplierFeasibilityEvidence]:
    selected: dict[tuple[str, str, str], SupplierFeasibilityEvidence] = {}
    blocking_warnings = {
        "currency_mismatch",
        "currency_missing",
        "unsupported_currency",
        "invalid_economics_input",
    }
    ordered_records = sorted(
        records,
        key=lambda record: (
            -record.source_confidence,
            record.unit_cost is None,
            record.shipping_cost is None,
            repr(record),
        ),
    )
    for record in ordered_records:
        key = (record.candidate_id, record.supplier, record.supplier_product_id or record.source_url)
        old = selected.get(key)
        if old is None:
            selected[key] = record
            continue
        old_economics = (
            old.unit_cost,
            old.currency,
            old.shipping_cost,
            old.shipping_currency,
            old.estimated_landed_cost,
            tuple(sorted(set(old.warnings) & blocking_warnings)),
        )
        new_economics = (
            record.unit_cost,
            record.currency,
            record.shipping_cost,
            record.shipping_currency,
            record.estimated_landed_cost,
            tuple(sorted(set(record.warnings) & blocking_warnings)),
        )
        if old_economics != new_economics:
            warnings = set(old.warnings) | set(record.warnings) | {"conflicting_supplier_offer"}
            selected[key] = replace(old, warnings=tuple(sorted(warnings)))
    return sorted(selected.values(), key=lambda item: (item.candidate_id, item.supplier, item.supplier_product_id, item.source_url))


def _confidence(record: SupplierFeasibilityEvidence, field_name: str) -> float:
    value = getattr(record, field_name, None)
    if value in (None, "", "unknown"):
        return 0.0
    status = record.field_provenance.get(field_name)
    base = {"live_readonly": 1.0, "observed": 0.9, "manual_import": 0.7, "derived": 0.62, "fixture": 0.5, "assumed": 0.25}.get(status or record.evidence_mode, 0.35)
    return round(base * max(0.25, record.source_confidence), 4)


def _risk_flags(
    records: list[SupplierFeasibilityEvidence],
    economics: UnitEconomicsScenario | None,
    issue_codes: Iterable[str] = (),
) -> tuple[SupplierRiskFlag, ...]:
    flags: list[SupplierRiskFlag] = []
    if not records or all(record.unit_cost is None for record in records):
        flags.append(SupplierRiskFlag("supplier_cost_missing", "blocker", "No supplier unit cost is observed."))
    if any(record.shipping_cost is None for record in records):
        flags.append(SupplierRiskFlag("shipping_cost_missing", "blocker", "At least one offer lacks shipping cost."))
    if any(record.delivery_max_days is None for record in records):
        flags.append(SupplierRiskFlag("delivery_window_missing", "warning", "At least one offer lacks an estimated delivery window."))
    if any(record.moq is not None and record.moq > 10 for record in records):
        flags.append(SupplierRiskFlag("high_moq", "warning", "MOQ is high for a dropshipping-style test."))
    if economics and economics.gross_margin_percent is not None and economics.gross_margin_percent < 0.15:
        flags.append(SupplierRiskFlag("low_margin_proxy", "blocker", "Scenario margin is below the 15% feasibility floor."))
    if economics and "currency_mismatch" in economics.assumptions:
        flags.append(SupplierRiskFlag("currency_mismatch", "blocker", "Supplier and market lane currencies do not match."))
    elif economics and "currency_missing" in economics.assumptions:
        flags.append(SupplierRiskFlag("currency_missing", "blocker", "Currency is missing or unspecified."))
    elif economics and "unsupported_currency" in economics.assumptions:
        flags.append(SupplierRiskFlag("unsupported_currency", "blocker", "Currency is unsupported by canonical economics."))
    if economics and "invalid_economics_input" in economics.assumptions:
        issue_codes = (*issue_codes, "invalid_economics_input")
    if economics and "sell_price_missing" in economics.assumptions:
        issue_codes = (*issue_codes, "sell_price_missing")
    if economics and "sell_price_nonpositive" in economics.assumptions:
        issue_codes = (*issue_codes, "sell_price_nonpositive")
    explanations = {
        "currency_mismatch": "Supplier and market lane currencies do not match.",
        "currency_missing": "Currency is missing, assumed, or unspecified.",
        "unsupported_currency": "Currency is unsupported by canonical economics.",
        "invalid_economics_input": "At least one offer has an invalid money or fee-rate input.",
        "conflicting_supplier_offer": "Duplicate supplier offers contain conflicting economics evidence.",
        "sell_price_missing": "A positive sell price is required before launch-draft readiness.",
        "sell_price_nonpositive": "A sell price must be greater than zero before launch-draft readiness.",
    }
    present = {flag.code for flag in flags}
    for code in sorted(set(issue_codes)):
        if code in explanations and code not in present:
            flags.append(SupplierRiskFlag(code, "blocker", explanations[code]))
    return tuple(flags)


def _offer_economics_issue(
    record: SupplierFeasibilityEvidence,
    expected_currency: str | None,
) -> str | None:
    if "conflicting_supplier_offer" in record.warnings:
        return "conflicting_supplier_offer"
    if "invalid_economics_input" in record.warnings:
        return "invalid_economics_input"
    declared_currency = record.currency.strip().upper() if isinstance(record.currency, str) else ""
    if declared_currency:
        try:
            Money(Decimal("0"), declared_currency, source="supplier_feasibility", provenance="assumed")
        except (TypeError, ValueError):
            return "unsupported_currency"
    elif record.unit_cost is not None or record.estimated_landed_cost is not None:
        return "currency_missing"

    shipping_currency = record.shipping_currency.strip().upper() if isinstance(record.shipping_currency, str) else ""
    if shipping_currency:
        try:
            Money(Decimal("0"), shipping_currency, source="supplier_feasibility", provenance="assumed")
        except (TypeError, ValueError):
            return "unsupported_currency"

    has_money = any(
        amount is not None
        for amount in (record.unit_cost, record.shipping_cost, record.estimated_landed_cost)
    )
    if has_money and "currency_missing" in record.warnings:
        return "currency_missing"
    if expected_currency and declared_currency and declared_currency != expected_currency:
        return "currency_mismatch"
    effective_shipping_currency = shipping_currency or declared_currency
    if record.shipping_cost is not None and not effective_shipping_currency:
        return "currency_missing"
    if expected_currency and record.shipping_cost is not None and effective_shipping_currency != expected_currency:
        return "currency_mismatch"

    for field_name, amount, amount_currency in (
        ("unit_cost", record.unit_cost, declared_currency),
        ("shipping_cost", record.shipping_cost, effective_shipping_currency),
        ("estimated_landed_cost", record.estimated_landed_cost, declared_currency),
    ):
        if amount is None:
            status = record.field_provenance.get(field_name)
            if field_name != "shipping_cost" and status not in (None, "unavailable", "blocked"):
                return "invalid_economics_input"
            continue
        issue = _display_currency_issue(amount, amount_currency)
        if issue:
            return issue
        _, invalid = _decimal_money_amount(amount)
        if invalid:
            return "invalid_economics_input"
    if (
        "landed_cost_derived" in record.warnings
        and record.field_provenance.get("estimated_landed_cost") not in (None, "derived")
    ):
        return "invalid_economics_input"
    return None


def score_candidate(
    candidate_id: str,
    evidence: list[SupplierFeasibilityEvidence],
    *,
    target_sell_price: Any = None,
    payment_fee_rate: float = 0.029,
    platform_fee_rate: float = 0.05,
    lane: MarketLane | None = None,
) -> SupplierFeasibilityScore:
    evidence = collapse_duplicates(evidence)
    best = sorted(evidence, key=lambda item: (-item.source_confidence, item.unit_cost is None, item.shipping_cost is None))[0] if evidence else None
    expected_currency = lane.currency.strip().upper() if lane and lane.currency else None
    if expected_currency is None and best and best.currency:
        expected_currency = best.currency.strip().upper() if best.currency else None
    offer_issues = tuple(
        issue for record in evidence if (issue := _offer_economics_issue(record, expected_currency)) is not None
    )
    economics = calculate_unit_economics(
        target_sell_price=target_sell_price,
        unit_cost=best.unit_cost if best else None,
        shipping_cost=best.shipping_cost if best else None,
        estimated_landed_cost=(
            None
            if best
            and (
                "landed_cost_derived" in best.warnings
                or best.field_provenance.get("estimated_landed_cost") == "derived"
            )
            else best.estimated_landed_cost if best else None
        ),
        payment_fee_rate=payment_fee_rate,
        platform_fee_rate=platform_fee_rate,
        lane=lane,
        currency=best.currency if best else None,
        cost_currency=best.currency if best else None,
        shipping_currency=getattr(best, "shipping_currency", None) if best else None,
    )
    if economics and offer_issues:
        zero_cost_boundary = bool(
            best
            and best.unit_cost == 0
            and best.shipping_cost == 0
            and best.estimated_landed_cost == 0
        )
        economics = replace(
            economics,
            estimated_landed_cost=economics.estimated_landed_cost if zero_cost_boundary else None,
            gross_margin=None,
            gross_margin_percent=None,
            break_even_cpa=None,
            break_even_roas=None,
            profit_per_order_before_ad_spend=None,
            assumptions=tuple(sorted(set(economics.assumptions) | set(offer_issues))),
            canonical_economics=None,
        )
    if not best:
        return SupplierFeasibilityScore(candidate_id, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, "validate_live_supplier_first", {}, ("no_supplier_evidence",), economics, _risk_flags([], economics))
    costs = _confidence(best, "unit_cost")
    landed = _confidence(best, "estimated_landed_cost")
    inventory = _confidence(best, "inventory_status")
    max_days = best.delivery_max_days
    speed = 0.9 if max_days is not None and max_days <= 7 else 0.75 if max_days is not None and max_days <= 14 else 0.5 if max_days is not None and max_days <= 30 else 0.2 if max_days is not None else 0.0
    delivery_risk = 1.0 - speed if max_days is not None else 0.8
    reliability = bounded((best.supplier_rating or 0) / 5) * (0.5 + bounded((best.supplier_review_count or 0) / 1000) * 0.5)
    fulfillment = _confidence(best, "fulfillment_method")
    if set(offer_issues) & {
        "currency_mismatch", "currency_missing", "unsupported_currency",
        "invalid_economics_input", "conflicting_supplier_offer",
    }:
        margin = 0.0
    elif economics and economics.gross_margin_percent is not None:
        margin = bounded(((economics.gross_margin_percent or 0) + 0.1) / 0.6)
    elif economics and any(
        marker in economics.assumptions
        for marker in (
            "currency_mismatch",
            "currency_missing",
            "unsupported_currency",
            "invalid_economics_input",
            "sell_price_missing",
            "sell_price_nonpositive",
            "shipping_cost_missing",
            "sell_price_or_landed_cost_missing",
        )
    ):
        margin = 0.0
    else:
        margin = 0.25
    options = bounded(len({(item.supplier, item.supplier_product_id) for item in evidence}) / 3)
    diversity = bounded(len({item.supplier for item in evidence}) / 3)
    contributions = {
        "supplier_cost_confidence": costs,
        "landed_cost_confidence": landed,
        "inventory_confidence": inventory,
        "shipping_speed_score": speed,
        "delivery_risk_score": delivery_risk,
        "supplier_reliability_score": reliability,
        "fulfillment_confidence": fulfillment,
        "margin_feasibility_proxy": margin,
        "source_diversity_score": diversity,
        "supplier_option_count": options,
    }
    overall = bounded(
        costs * 0.16 + landed * 0.14 + inventory * 0.12 + speed * 0.1 + (1 - delivery_risk) * 0.1 + reliability * 0.12 + fulfillment * 0.08 + margin * 0.14 + diversity * 0.04
    )
    flags = _risk_flags(evidence, economics, offer_issues)
    reasons = [flag.code for flag in flags]
    if any(
        flag.code in {
            "currency_mismatch", "currency_missing", "unsupported_currency",
            "invalid_economics_input", "sell_price_missing", "sell_price_nonpositive",
            "conflicting_supplier_offer", "shipping_cost_missing",
        }
        for flag in flags
    ):
        recommendation = "hold_for_manual_review"
    elif costs == 0:
        recommendation = "validate_live_supplier_first"
    elif economics.gross_margin_percent is not None and economics.gross_margin_percent < 0.15:
        recommendation = "reject_poor_margin"
    elif max_days is not None and max_days > 30:
        recommendation = "reject_logistics_risk"
    elif best.inventory_status == "out_of_stock":
        recommendation = "reject_inventory_risk"
    elif best.evidence_mode == "live_readonly" and overall >= 0.68:
        recommendation = "advance_to_launch_draft"
    elif len(evidence) < 2 or best.shipping_cost is None or max_days is None:
        recommendation = "expand_supplier_research"
    else:
        recommendation = "hold_for_manual_review"
    return SupplierFeasibilityScore(candidate_id, costs, landed, inventory, speed, delivery_risk, reliability, fulfillment, margin, diversity, options, round(overall, 4), recommendation, {key: round(value, 4) for key, value in contributions.items()}, tuple(sorted(set(reasons))), economics, flags)


def build_report(records: list[SupplierFeasibilityEvidence], *, evidence_mode: str = "fixture", target_sell_prices: Mapping[str, Any] | None = None, lane: MarketLane | None = None) -> SupplierFeasibilityReport:
    records = collapse_duplicates(records)
    record_modes = {record.evidence_mode for record in records}
    report_evidence_mode = evidence_mode
    if "unknown" in record_modes:
        report_evidence_mode = "unknown"
    elif "fixture" in record_modes:
        report_evidence_mode = "fixture"
    elif "manual_import" in record_modes:
        report_evidence_mode = "manual_import"
    elif report_evidence_mode == "live_readonly" and record_modes != {"live_readonly"}:
        report_evidence_mode = "unknown"
    grouped: dict[str, list[SupplierFeasibilityEvidence]] = {}
    for record in records:
        if record.candidate_id:
            grouped.setdefault(record.candidate_id, []).append(record)
    prices = target_sell_prices or {}
    results = []
    for candidate_id, rows in sorted(grouped.items()):
        results.append(SupplierFeasibilityCandidateResult(candidate_id, rows[0].query, tuple(rows), score_candidate(candidate_id, rows, target_sell_price=prices.get(candidate_id), lane=lane), tuple(sorted({warning for row in rows for warning in row.warnings}))))
    results = tuple(sorted(results, key=lambda item: (-item.score.overall_supplier_feasibility, item.candidate_id)))
    top = results[0] if results else None
    warnings = ("supplier_feasibility_is_not_live_supplier_authorization",) if records else ("supplier_feasibility_not_supplied",)
    return SupplierFeasibilityReport("supplier-feasibility-v1", report_evidence_mode, len(results), len(records), tuple(sorted({record.supplier for record in records})), top.candidate_id if top else None, f"{top.score.recommendation}:{top.candidate_id}" if top else "validate_live_supplier_first", results, warnings)

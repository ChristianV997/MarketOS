"""Offline supplier feasibility and unit-economics intelligence.

Supplier feasibility is intentionally distinct from marketplace demand evidence.
It estimates whether a candidate appears sourceable from sanitized supplier
snapshots or manual imports; it never authorizes an order, inventory mutation,
fulfillment action, or provider write.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Mapping

from backend.economics import CurrencyMismatchError, MarketLane, Money, UnitEconomicsAssumptions
from backend.economics import calculate_unit_economics as calculate_canonical_unit_economics

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


def number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "")
    for marker in ("USD", "MXN", "EUR", "GBP", "$", "€", "£"):
        text = text.replace(marker, "")
    try:
        return float(text.strip().split()[0])
    except (IndexError, TypeError, ValueError):
        return None


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
    currency: str = "USD"

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
    payment_fee_rate: float
    platform_fee_rate: float
    gross_margin: float | None
    gross_margin_percent: float | None
    break_even_cpa: float | None
    break_even_roas: float | None
    profit_per_order_before_ad_spend: float | None
    assumptions: tuple[str, ...] = ()
    canonical_economics: Mapping[str, Any] | None = None
    currency: str = "USD"
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
    sell = number(target_sell_price)
    cost = number(unit_cost)
    shipping = number(shipping_cost)
    landed = number(estimated_landed_cost)
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

    if resolved_sell_currency is None:
        if resolved_cost_currency is not None:
            resolved_sell_currency = resolved_cost_currency
        else:
            resolved_sell_currency = "USD"
            resolved_cost_currency = "USD"
    elif resolved_cost_currency is None and cost_currency is None and currency is None:
        resolved_cost_currency = resolved_sell_currency

    resolved_shipping_currency: str | None = None
    if shipping is not None:
        if shipping_currency is not None:
            val = str(shipping_currency).strip().upper()
            resolved_shipping_currency = val if val else None
        else:
            resolved_shipping_currency = resolved_cost_currency

    if landed is None and cost is not None:
        if shipping is not None:
            landed = cost + shipping
        else:
            assumptions.append("shipping_cost_missing")
            landed = cost

    if sell is None or landed is None:
        return UnitEconomicsScenario(
            sell, cost, shipping, landed, payment_fee_rate, platform_fee_rate,
            None, None, None, None, None,
            tuple(assumptions + ["sell_price_or_landed_cost_missing"]),
            currency=resolved_sell_currency or "USD",
            cost_currency=resolved_cost_currency,
            shipping_currency=resolved_shipping_currency,
        )

    # 1. Missing currency check
    if cost is not None and not resolved_cost_currency:
        return UnitEconomicsScenario(
            sell, cost, shipping, landed, payment_fee_rate, platform_fee_rate,
            None, None, None, None, None,
            tuple(assumptions + ["currency_missing"]),
            currency=resolved_sell_currency or "USD",
            cost_currency=None,
            shipping_currency=resolved_shipping_currency,
        )

    if shipping is not None and not resolved_shipping_currency:
        return UnitEconomicsScenario(
            sell, cost, shipping, landed, payment_fee_rate, platform_fee_rate,
            None, None, None, None, None,
            tuple(assumptions + ["currency_missing"]),
            currency=resolved_sell_currency or "USD",
            cost_currency=resolved_cost_currency,
            shipping_currency=None,
        )

    if sell is not None and not resolved_sell_currency:
        return UnitEconomicsScenario(
            sell, cost, shipping, landed, payment_fee_rate, platform_fee_rate,
            None, None, None, None, None,
            tuple(assumptions + ["currency_missing"]),
            currency="USD",
            cost_currency=resolved_cost_currency,
            shipping_currency=resolved_shipping_currency,
        )

    # 2. Currency mismatch check
    if lane and lane.currency and resolved_sell_currency and lane.currency.strip().upper() != resolved_sell_currency:
        return UnitEconomicsScenario(
            sell, cost, shipping, landed, payment_fee_rate, platform_fee_rate,
            None, None, None, None, None,
            tuple(assumptions + ["currency_mismatch"]),
            currency=lane.currency,
            cost_currency=resolved_cost_currency,
            shipping_currency=resolved_shipping_currency,
        )

    if resolved_cost_currency and resolved_sell_currency and resolved_cost_currency != resolved_sell_currency:
        return UnitEconomicsScenario(
            sell, cost, shipping, landed, payment_fee_rate, platform_fee_rate,
            None, None, None, None, None,
            tuple(assumptions + ["currency_mismatch"]),
            currency=resolved_sell_currency,
            cost_currency=resolved_cost_currency,
            shipping_currency=resolved_shipping_currency,
        )

    if shipping is not None and resolved_shipping_currency and resolved_sell_currency and resolved_shipping_currency != resolved_sell_currency:
        return UnitEconomicsScenario(
            sell, cost, shipping, landed, payment_fee_rate, platform_fee_rate,
            None, None, None, None, None,
            tuple(assumptions + ["currency_mismatch"]),
            currency=resolved_sell_currency,
            cost_currency=resolved_cost_currency,
            shipping_currency=resolved_shipping_currency,
        )

    try:
        canonical = calculate_canonical_unit_economics(
            Money(sell, resolved_sell_currency, source="supplier_feasibility", provenance="assumed"),
            Money(cost, resolved_sell_currency, source="supplier_feasibility", provenance="assumed"),
            lane=lane,
            assumptions=UnitEconomicsAssumptions(
                supplier_shipping=Money(shipping, resolved_sell_currency, source="supplier_feasibility", provenance="assumed") if shipping is not None else None,
                payment_fee_rate=None if lane and lane.payment_fee_rate is not None else Decimal(str(payment_fee_rate)),
                platform_fee_rate=None if lane and lane.platform_fee_rate is not None else Decimal(str(platform_fee_rate)),
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
        return UnitEconomicsScenario(
            sell, cost, shipping, landed, payment_fee_rate, platform_fee_rate,
            None, None, None, None, None,
            tuple(assumptions + ["currency_mismatch"]),
            currency=resolved_sell_currency,
            cost_currency=resolved_cost_currency,
            shipping_currency=resolved_shipping_currency,
        )
    except (TypeError, ValueError):
        return UnitEconomicsScenario(
            sell, cost, shipping, landed, payment_fee_rate, platform_fee_rate,
            None, None, None, None, None,
            tuple(assumptions + ["invalid_economics_input"]),
            currency=resolved_sell_currency,
            cost_currency=resolved_cost_currency,
            shipping_currency=resolved_shipping_currency,
        )
    profit = float(canonical.contribution_before_cac.amount)
    margin_percent = float(canonical.contribution_margin) if canonical.contribution_margin is not None else None
    cpa = float(canonical.break_even_cac.amount)
    roas = float(canonical.break_even_roas) if canonical.break_even_roas is not None else None
    return UnitEconomicsScenario(
        sell, cost, shipping, landed, payment_fee_rate, platform_fee_rate,
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
    currency: str = "USD"
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
        if set(self.field_provenance.values()) - PROVENANCE:
            raise ValueError("invalid supplier evidence provenance")
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
    for record in records:
        key = (record.candidate_id, record.supplier, record.supplier_product_id or record.source_url)
        old = selected.get(key)
        if old is None or (record.source_confidence, record.unit_cost is not None, record.shipping_cost is not None) > (old.source_confidence, old.unit_cost is not None, old.shipping_cost is not None):
            selected[key] = record
    return sorted(selected.values(), key=lambda item: (item.candidate_id, item.supplier, item.supplier_product_id, item.source_url))


def _confidence(record: SupplierFeasibilityEvidence, field_name: str) -> float:
    value = getattr(record, field_name, None)
    if value in (None, "", "unknown"):
        return 0.0
    status = record.field_provenance.get(field_name)
    base = {"live_readonly": 1.0, "observed": 0.9, "manual_import": 0.7, "derived": 0.62, "fixture": 0.5, "assumed": 0.25}.get(status or record.evidence_mode, 0.35)
    return round(base * max(0.25, record.source_confidence), 4)


def _risk_flags(records: list[SupplierFeasibilityEvidence], economics: UnitEconomicsScenario | None) -> tuple[SupplierRiskFlag, ...]:
    flags: list[SupplierRiskFlag] = []
    if not records or all(record.unit_cost is None for record in records):
        flags.append(SupplierRiskFlag("supplier_cost_missing", "blocker", "No supplier unit cost is observed."))
    if any(record.shipping_cost is None for record in records):
        flags.append(SupplierRiskFlag("shipping_cost_missing", "warning", "At least one offer lacks shipping cost."))
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
    return tuple(flags)


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
    economics = calculate_unit_economics(
        target_sell_price=target_sell_price,
        unit_cost=best.unit_cost if best else None,
        shipping_cost=best.shipping_cost if best else None,
        estimated_landed_cost=best.estimated_landed_cost if best else None,
        payment_fee_rate=payment_fee_rate,
        platform_fee_rate=platform_fee_rate,
        lane=lane,
        cost_currency=best.currency if best else None,
        shipping_currency=getattr(best, "shipping_currency", None) if best else None,
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
    if economics and economics.gross_margin_percent is not None:
        margin = bounded(((economics.gross_margin_percent or 0) + 0.1) / 0.6)
    elif economics and any(marker in economics.assumptions for marker in ("currency_mismatch", "currency_missing", "unsupported_currency")):
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
    flags = _risk_flags(evidence, economics)
    reasons = [flag.code for flag in flags]
    if costs == 0:
        recommendation = "validate_live_supplier_first"
    elif any(flag.code in {"currency_mismatch", "currency_missing", "unsupported_currency"} for flag in flags):
        recommendation = "hold_for_manual_review"
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
    return SupplierFeasibilityReport("supplier-feasibility-v1", evidence_mode, len(results), len(records), tuple(sorted({record.supplier for record in records})), top.candidate_id if top else None, f"{top.score.recommendation}:{top.candidate_id}" if top else "validate_live_supplier_first", results, warnings)

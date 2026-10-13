"""Candidate-to-CJ supplier evidence integration.

The default path is blocked by the current TrustOS/Approval Ledger policy.
The injected transport seam is fixture-only and always emits fixture evidence;
it never turns a fake response into a live observation.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import math
import re
import time
from typing import Any, Callable, Mapping

from backend.adapters.research.cj_readonly_api import (
    CjReadOnlySupplierAdapter,
    explain_cj_read_only_readiness,
)
from backend.adapters.research.supplier_feasibility import normalize_record
from backend.economics.kernel import EvidenceRef, Money, SUPPORTED_CURRENCIES
from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis
from evaluation.commerce.supplier_feasibility import build_report as build_supplier_feasibility_report
from evaluation.companyos.approval_ledger import simulate_action
from evaluation.trustos.gate_runner import evaluate_action
from services.supplier_logistics_research.controls import reject_unsafe_input
from services.supplier_logistics_research.report import build_supplier_logistics_report
from services.supplier_logistics_research.schemas import (
    AVAILABILITY_STATUSES,
    CandidateBoundSupplierIdentity,
    CustomsDutyTaxProfile,
    FieldEvidence,
    GoodsLogisticsProfile,
    LeadTimeWindow,
    MoqAvailability,
    ReturnsDefectAssumptions,
    ShippingCostProfile,
    SupplierLogisticsOffer,
)
from evaluation.commerce.canonical import SupplierOfferIdentity

DEFAULT_STALE_AFTER_SECONDS = 86_400.0
_LIVE_FIELD_NAMES = (
    "unit_cost",
    "currency",
    "moq",
    "inventory_status",
    "inventory_quantity",
    "warehouse_region",
    "shipping_cost",
    "shipping_currency",
    "delivery_min_days",
    "delivery_max_days",
    "fulfillment_method",
)
_SEARCH_WORD = re.compile(r"[\w]+(?:[-'][\w]+)*", re.UNICODE)


def _candidate_query(candidate: Mapping[str, Any]) -> tuple[str, str]:
    candidate_id = str(candidate.get("candidate_id") or candidate.get("id") or "").strip()
    ordered_values: list[Any] = [
        candidate.get("query"),
        candidate.get("title"),
        candidate.get("product_name"),
        candidate.get("name"),
        candidate.get("category"),
    ]
    for key in ("keywords", "search_terms"):
        values = candidate.get(key)
        if isinstance(values, str):
            ordered_values.append(values)
        elif isinstance(values, (list, tuple)):
            ordered_values.extend(values)
    description = candidate.get("description")
    if isinstance(description, str):
        ordered_values.append(description[:160])

    terms: list[str] = []
    seen: set[str] = set()
    for value in ordered_values:
        if not isinstance(value, str):
            continue
        cleaned = " ".join(value.split())
        if not cleaned:
            continue
        reject_unsafe_input(cleaned, field_name="candidate search terms")
        for token in _SEARCH_WORD.findall(cleaned):
            normalized = token.casefold()
            if normalized not in seen:
                seen.add(normalized)
                terms.append(token)
            if len(terms) >= 18:
                break
        if len(terms) >= 18:
            break
    query = " ".join(terms)[:200]
    if not candidate_id or not query:
        raise ValueError("candidate id and searchable product terms are required")
    if any(ord(char) < 32 for char in candidate_id) or len(candidate_id) > 120:
        raise ValueError("candidate id is invalid")
    return candidate_id, query


def _destination_values(destination: Mapping[str, Any]) -> tuple[str, str | None]:
    country = str(destination.get("country_code") or destination.get("country") or "").strip().upper()
    if len(country) != 2 or not country.isascii() or not country.isalpha():
        raise ValueError("destination country_code must be a two-letter code")
    postal = destination.get("postal_code")
    if postal in (None, ""):
        return country, None
    if not isinstance(postal, str):
        raise ValueError("destination postal_code must be text")
    postal = postal.strip()
    if not postal or len(postal) > 20 or any(ord(char) < 32 for char in postal):
        raise ValueError("destination postal_code is invalid")
    reject_unsafe_input(postal, field_name="destination postal code")
    return country, postal


def _safe_provider_text(value: Any, *, field_name: str, limit: int = 160) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} is invalid")
    cleaned = " ".join(value.split())[:limit]
    reject_unsafe_input(cleaned, field_name=field_name)
    if any(ord(char) < 32 for char in cleaned):
        raise ValueError(f"{field_name} is invalid")
    return cleaned


def _iso_timestamp(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return ""
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _numeric_timestamp(values: Mapping[str, Any], field_name: str) -> float | None:
    value = values.get(field_name)
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _field_evidence(
    quality: str,
    *,
    field_name: str,
    timestamp: float | None,
    note: str = "",
) -> FieldEvidence:
    allowed_quality = quality if quality in {"fixture", "stale", "missing", "conflicting"} else "missing"
    evidence_ref = None
    if allowed_quality != "missing":
        stamp = _iso_timestamp(timestamp) or "unknown-time"
        evidence_ref = EvidenceRef(
            evidence_id=f"cj-fixture-{field_name}-{stamp}",
            source_type="cj_readonly_fixture",
            evidence_state="fixture",
            human_confirmed=False,
        )
    return FieldEvidence(
        quality=allowed_quality,
        evidence_ref=evidence_ref,
        observed_at=_iso_timestamp(timestamp),
        note=note,
    )


def _shipping_choice(offer: Mapping[str, Any]) -> tuple[float | None, str | None, Mapping[str, Any] | None, bool]:
    quotes = offer.get("shipping_quotes")
    if not isinstance(quotes, (list, tuple)) or not quotes:
        return None, None, None, False
    if len(quotes) != 1:
        return None, None, None, True
    quote_row = quotes[0]
    if not isinstance(quote_row, Mapping):
        return None, None, None, False
    cost_usd = quote_row.get("shipping_cost_usd")
    if cost_usd is not None:
        return float(cost_usd), "USD", quote_row, False
    cost_cny = quote_row.get("shipping_cost_cny")
    if cost_cny is not None:
        return float(cost_cny), "CNY", quote_row, False
    return None, None, quote_row, False


def _normalize_offer(
    candidate_id: str,
    query: str,
    destination_country: str,
    offer: Mapping[str, Any],
    *,
    now: float,
    stale_after_seconds: float,
) -> tuple[Any | None, dict[str, str], tuple[str, ...]]:
    timestamps = offer.get("field_timestamps")
    timestamps = timestamps if isinstance(timestamps, Mapping) else {}
    provenance = offer.get("field_provenance")
    provenance = dict(provenance) if isinstance(provenance, Mapping) else {}
    warnings = [str(item) for item in offer.get("warnings", ()) if isinstance(item, str)]
    warnings.append("supplier_reliability_unknown_until_fulfillment_outcomes")
    for field_name in _LIVE_FIELD_NAMES:
        timestamp = timestamps.get(field_name)
        if timestamp is None:
            if provenance.get(field_name) not in {None, "unavailable", "blocked"}:
                provenance[field_name] = "unavailable"
                warnings.append(f"{field_name}_timestamp_unavailable")
            continue
        try:
            age = now - float(timestamp)
        except (TypeError, ValueError):
            age = math.inf
        if age > stale_after_seconds and provenance.get(field_name) in {"fixture", "derived"}:
            provenance[field_name] = "stale"

    source_provenance = dict(provenance)
    canonical_provenance = dict(provenance)
    shipping_cost, shipping_currency, quote, multiple_quotes = _shipping_choice(offer)
    source_shipping_cost, source_shipping_currency = shipping_cost, shipping_currency
    unit_cost = offer.get("unit_cost")
    unit_currency = offer.get("currency")
    unit_currency = str(unit_currency).strip().upper() if isinstance(unit_currency, str) and unit_currency.strip() else None
    cost_currency_mismatch = (
        shipping_cost is not None
        and unit_cost is not None
        and unit_currency is not None
        and shipping_currency is not None
        and unit_currency != shipping_currency
    )
    if multiple_quotes:
        shipping_cost = None
        shipping_currency = None
        canonical_provenance["shipping_cost"] = "unavailable"
        canonical_provenance["shipping_currency"] = "unavailable"
        warnings.append("multiple_logistics_options_not_collapsed")
    elif cost_currency_mismatch:
        # The shared importer derives landed cost from unit + shipping. Keep
        # currencies separate and attach the quote only after that derivation.
        shipping_cost = None
        shipping_currency = None
        canonical_provenance["shipping_cost"] = "unavailable"
        canonical_provenance["shipping_currency"] = "unavailable"
        warnings.append("shipping_cost_currency_mismatch")

    product_id = str(offer.get("product_id") or "").strip()
    variant_id = str(offer.get("variant_id") or "").strip()
    supplier_product_id = variant_id or product_id
    if not supplier_product_id:
        return None, source_provenance, tuple(sorted(set(warnings + ["supplier_product_identity_unavailable"])))

    stale_fields = {field for field in _LIVE_FIELD_NAMES if source_provenance.get(field) == "stale"}
    if isinstance(unit_cost, bool) or "unit_cost" in stale_fields:
        unit_cost = None
    if "shipping_cost" in stale_fields or "shipping_currency" in stale_fields:
        shipping_cost = None
        shipping_currency = None
    if unit_cost is not None:
        try:
            unit_cost = float(unit_cost)
            if not math.isfinite(unit_cost) or unit_cost < 0:
                unit_cost = None
        except (TypeError, ValueError):
            unit_cost = None
    product_payload = offer.get("product")
    product_confidence = product_payload.get("confidence", 0.0) if isinstance(product_payload, Mapping) else 0.0
    row = {
        "candidate_id": candidate_id,
        "query": query,
        "supplier": "cj",
        "source_type": "cj_readonly_fixture",
        "evidence_mode": "fixture",
        "source_url": "https://developers.cjdropshipping.com/en/api/api2/api/product.html",
        "supplier_product_id": supplier_product_id,
        "supplier_title": str(offer.get("supplier_title") or ""),
        "supplier_sku": str(offer.get("supplier_sku") or ""),
        "unit_cost": unit_cost,
        "currency": unit_currency if "currency" not in stale_fields else None,
        "moq": None if "moq" in stale_fields else offer.get("minimum_order_quantity"),
        "inventory_status": "unknown" if "inventory_status" in stale_fields else offer.get("destination_inventory_status") or "unknown",
        "inventory_quantity": None if "inventory_quantity" in stale_fields else offer.get("destination_inventory_quantity"),
        "warehouse_region": "" if "warehouse_region" in stale_fields else str(offer.get("warehouse_region") or ""),
        "destination_region": destination_country,
        "fulfillment_method": "" if "fulfillment_method" in stale_fields else str(offer.get("fulfillment_method") or ""),
        "shipping_cost": shipping_cost,
        "shipping_currency": shipping_currency,
        "delivery_min_days": quote.get("delivery_min_days") if quote and "delivery_min_days" not in stale_fields else None,
        "delivery_max_days": quote.get("delivery_max_days") if quote and "delivery_max_days" not in stale_fields else None,
        "source_confidence": product_confidence,
        "field_provenance": {
            key: ("unavailable" if value == "stale" else value)
            for key, value in canonical_provenance.items()
        },
        "warnings": warnings + [f"stale_{field}" for field in sorted(stale_fields)],
        "observed_at": _iso_timestamp(max((float(value) for value in timestamps.values() if value is not None), default=now)),
    }
    # Do not expose descriptions or arbitrary provider response keys through
    # this integration. The existing supplier normalizer accepts this field set.
    try:
        record = normalize_record(row, default_supplier="cj", default_source_type="cj_readonly_fixture", mode="fixture")
    except Exception:
        return None, source_provenance, tuple(sorted(set(warnings + ["supplier_record_normalization_failed"])))
    if record is None:
        return None, source_provenance, tuple(sorted(set(warnings + ["supplier_record_rejected"])))
    if (
        cost_currency_mismatch
        and source_shipping_cost is not None
        and source_shipping_currency is not None
        and "shipping_cost" not in stale_fields
        and "shipping_currency" not in stale_fields
    ):
        next_provenance = dict(record.field_provenance)
        next_provenance["shipping_cost"] = "fixture"
        next_provenance["shipping_currency"] = "derived"
        next_warnings = tuple(item for item in record.warnings if item != "shipping_cost_unavailable")
        record = replace(
            record,
            shipping_cost=source_shipping_cost,
            shipping_currency=source_shipping_currency,
            estimated_landed_cost=None,
            field_provenance=next_provenance,
            warnings=tuple(sorted(set(next_warnings + ("shipping_cost_currency_mismatch",)))),
        )
    return record, source_provenance, tuple(sorted(set(warnings)))


def _logistics_reports(
    candidate_id: str,
    records: list[Any],
    offers: list[Mapping[str, Any]],
    *,
    generated_at: str,
    now: float,
    stale_after_seconds: float,
) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for record, offer in zip(records, offers):
        quotes = offer.get("shipping_quotes")
        quote_rows = [item for item in quotes if isinstance(item, Mapping)] if isinstance(quotes, (list, tuple)) else []
        if not quote_rows:
            quote_rows = [{}]
        timestamps_value = offer.get("field_timestamps")
        timestamps: Mapping[str, Any] = timestamps_value if isinstance(timestamps_value, Mapping) else {}
        for quote_index, quote in enumerate(quote_rows):
            cost = None
            currency = None
            logistic_name = ""
            delivery_min = delivery_max = None
            quote_at = None
            if quote.get("shipping_cost_usd") is not None:
                cost, currency = float(quote["shipping_cost_usd"]), "USD"
            elif quote.get("shipping_cost_cny") is not None:
                cost, currency = float(quote["shipping_cost_cny"]), "CNY"
            logistic_name = str(quote.get("logistic_name") or "")
            delivery_min, delivery_max = quote.get("delivery_min_days"), quote.get("delivery_max_days")
            quote_at = quote.get("captured_at")
            stale = quote_at is not None and now - float(quote_at) > stale_after_seconds
            supplier_currency = offer.get("currency")
            supplier_price = offer.get("unit_cost")
            if isinstance(supplier_price, bool):
                supplier_price = None
            if supplier_price is not None:
                try:
                    supplier_price = float(supplier_price)
                except (TypeError, ValueError):
                    supplier_price = None
            mismatched = cost is not None and supplier_currency and currency and supplier_currency != currency
            can_use_price = supplier_price is not None and supplier_currency is not None and not mismatched
            unit_timestamp = _numeric_timestamp(timestamps, "unit_cost")
            unit_stale = unit_timestamp is not None and now - unit_timestamp > stale_after_seconds
            moq_timestamp = _numeric_timestamp(timestamps, "moq")
            moq_stale = moq_timestamp is not None and now - moq_timestamp > stale_after_seconds
            inventory_timestamp = _numeric_timestamp(timestamps, "inventory_quantity")
            inventory_stale = inventory_timestamp is not None and now - inventory_timestamp > stale_after_seconds
            price_money = None
            if supplier_price is not None and supplier_currency in SUPPORTED_CURRENCIES and not mismatched:
                price_money = Money(Decimal(str(supplier_price)), supplier_currency)
            unsupported_shipping_currency = currency is not None and currency not in SUPPORTED_CURRENCIES
            shipping_money = (
                Money(Decimal(str(cost)), currency)
                if cost is not None and currency in SUPPORTED_CURRENCIES
                else None
            )
            captured = _iso_timestamp(float(quote_at)) if quote_at is not None else record.observed_at
            price_evidence = _field_evidence(
                "stale" if unit_stale else "conflicting" if mismatched else "fixture" if can_use_price else "missing",
                field_name="unit_cost",
                timestamp=unit_timestamp,
                note="Supplier price remains separate from any non-matching shipping currency." if mismatched else "CJ catalog price; fixture transport only.",
            )
            shipping_evidence = _field_evidence(
                "stale" if stale else "conflicting" if unsupported_shipping_currency and cost is not None else "fixture" if shipping_money is not None else "missing",
                field_name="shipping_cost",
                timestamp=float(quote_at) if quote_at is not None else None,
                note=(
                    f"CJ freight method {logistic_name}; quantity=1; currencies are not converted."
                    if shipping_money is not None
                    else f"CJ returned {cost} {currency}; canonical Money does not support this currency, so no conversion was attempted."
                    if unsupported_shipping_currency and cost is not None
                    else "No destination-bound freight quote was returned."
                ),
            )
            moq_evidence = _field_evidence(
                "stale" if moq_stale
                else "fixture" if offer.get("minimum_order_quantity") is not None else "missing",
                field_name="moq",
                timestamp=moq_timestamp,
                note="Minimum order quantity from the catalog response." if offer.get("minimum_order_quantity") is not None else "MOQ unavailable in the catalog response.",
            )
            inventory_evidence = _field_evidence(
                "stale" if inventory_stale
                else "fixture" if offer.get("destination_inventory_quantity") is not None else "missing",
                field_name="inventory",
                timestamp=inventory_timestamp,
                note=f"Destination inventory status: {offer.get('destination_inventory_status') or 'unknown'}.",
            )
            lead_evidence = _field_evidence(
                "stale" if stale else "fixture" if delivery_min is not None or delivery_max is not None else "missing",
                field_name="delivery_window",
                timestamp=float(quote_at) if quote_at is not None else None,
                note=f"CJ freight method {logistic_name}; destination-bound quote." if quote_at is not None else "Delivery window unavailable.",
            )
            identity = CandidateBoundSupplierIdentity(
                candidate_id=candidate_id,
                supplier_offer=SupplierOfferIdentity(
                    supplier_id="cj",
                    offer_id=f"{record.supplier_product_id}:{logistic_name or 'unquoted'}:{quote_index}",
                    supplier_sku=record.supplier_sku or record.supplier_product_id,
                    variant_id=str(offer.get("variant_id") or ""),
                ),
            )
            availability_status = offer.get("destination_inventory_status")
            if availability_status not in AVAILABILITY_STATUSES:
                availability_status = "unknown"
            logistics_offer = SupplierLogisticsOffer(
                identity=identity,
                offering_kind="goods",
                quoted_price=price_money,
                price_evidence=price_evidence,
                goods=GoodsLogisticsProfile(
                    moq_availability=MoqAvailability(
                        minimum_order_quantity=offer.get("minimum_order_quantity"),
                        available_quantity=offer.get("destination_inventory_quantity"),
                        availability_status=availability_status,
                        evidence=inventory_evidence if offer.get("destination_inventory_quantity") is not None else moq_evidence,
                    ),
                    lead_time=LeadTimeWindow(
                        minimum_days=delivery_min,
                        maximum_days=delivery_max,
                        evidence=lead_evidence,
                    ),
                    fulfillment_mode="unknown",
                    customs=CustomsDutyTaxProfile(evidence=FieldEvidence(quality="missing")),
                    returns_defects=ReturnsDefectAssumptions(evidence=FieldEvidence(quality="missing")),
                    shipping=ShippingCostProfile(
                        supplier_shipping=shipping_money,
                        evidence=shipping_evidence,
                    ),
                    supplier_evidence=_field_evidence(
                        "stale" if stale else "fixture",
                        field_name="supplier_terms",
                        timestamp=_numeric_timestamp(timestamps, "unit_cost"),
                        note=f"CJ productType={offer.get('product_type') or 'unavailable'}; reliability remains unknown.",
                    ),
                    logistics_evidence=shipping_evidence,
                ),
                captured_at=captured or generated_at,
            )
            report = build_supplier_logistics_report(logistics_offer, generated_at=generated_at)
            reports.append(report.to_dict())
    return reports


def research_cj_candidate(
    candidate: Mapping[str, Any],
    destination: Mapping[str, Any],
    *,
    fixture_transport: Any | None = None,
    clock: Callable[[], float] = time.time,
    now: float | None = None,
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
    limit: int = 5,
) -> dict[str, Any]:
    """Search a candidate brief and compose existing supplier/logistics reports.

    With no explicitly injected fixture transport, no provider request is made:
    current TrustOS and Approval Ledger policy blocks provider reads. This
    function never enables an external action or exposes a credential value.
    """
    current = float(clock() if now is None else now)
    if not math.isfinite(current) or not math.isfinite(float(stale_after_seconds)) or stale_after_seconds < 0:
        return {"status": "invalid_input", "warnings": ["freshness_window_invalid"], "read_only": True, "network_calls": False, "mutated": False}
    try:
        candidate_id, query = _candidate_query(candidate)
        destination_country, postal_code = _destination_values(destination)
    except (TypeError, ValueError) as exc:
        return {"status": "invalid_input", "warnings": [str(exc)], "read_only": True, "network_calls": False, "mutated": False}

    if fixture_transport is None:
        readiness = explain_cj_read_only_readiness()
        trust_gate = evaluate_action("run_provider_readonly_call")
        approval_simulation = simulate_action("provider_call")
        blockers = ["provider_read_only_gate_blocked"]
        if not readiness.get("credentials_present_redacted"):
            blockers.append("cj_credentials_missing")
        if trust_gate.decision != "allow":
            blockers.extend(f"trustos:{item}" for item in trust_gate.blockers)
        if approval_simulation.result != "would_auto_allow_draft":
            blockers.extend(f"approval_ledger:{item}" for item in approval_simulation.blocking_reasons)
        blockers.append("canonical_supplier_evidence_is_fixture_or_manual_only")
        blockers.append("cj_auth_contract_mismatch_requires_owner_update")
        return {
            "status": "blocked",
            "candidate_id": candidate_id,
            "search_query": query,
            "destination_country_code": destination_country,
            "evidence_mode": "blocked",
            "provider_readiness": readiness,
            "trust_gate": trust_gate.to_dict(),
            "approval_simulation": approval_simulation.to_dict(),
            "supplier_records": [],
            "supplier_report": None,
            "logistics_reports": [],
            "opportunity_synthesis": None,
            "shipping_quotes": [],
            "source_field_evidence": [],
            "blockers": sorted(set(blockers)),
            "warnings": ["No CJ provider request was attempted."],
            "attempted": False,
            "read_only": True,
            "network_calls": False,
            "mutated": False,
        }

    if (
        not callable(getattr(fixture_transport, "read_only_get", None))
        or not callable(getattr(fixture_transport, "read_only_post", None))
        or getattr(fixture_transport, "offline_fixture", False) is not True
        or getattr(fixture_transport, "network_calls", True) is not False
        or getattr(fixture_transport, "mutated", True) is not False
    ):
        return {
            "status": "invalid_fixture_transport",
            "candidate_id": candidate_id,
            "search_query": query,
            "destination_country_code": destination_country,
            "warnings": ["fixture_transport_must_inject_read_only_get_and_post"],
            "attempted": False,
            "read_only": True,
            "network_calls": False,
            "mutated": False,
        }
    adapter = CjReadOnlySupplierAdapter(client=fixture_transport, clock=clock)
    provider_result = adapter.search_fixture(
        query,
        destination_country_code=destination_country,
        postal_code=postal_code,
        limit=limit,
    )
    if provider_result.status != "fixture":
        return {
            "status": provider_result.status,
            "candidate_id": candidate_id,
            "search_query": query,
            "destination_country_code": destination_country,
            "evidence_mode": "fixture",
            "provider_status": provider_result.status,
            "supplier_records": [],
            "supplier_report": None,
            "logistics_reports": [],
            "opportunity_synthesis": None,
            "blockers": [],
            "warnings": list(provider_result.warnings),
            "shipping_quotes": [],
            "source_field_evidence": [],
            "attempted": False,
            "read_only": True,
            "network_calls": False,
            "mutated": False,
        }

    records: list[Any] = []
    selected_offers: list[Mapping[str, Any]] = []
    source_field_evidence: list[dict[str, Any]] = []
    warnings: list[str] = list(provider_result.warnings)
    for offer in provider_result.to_dict().get("offers", []):
        if not isinstance(offer, Mapping):
            continue
        try:
            offer = dict(offer)
            for key in ("product_id", "variant_id", "supplier_sku", "supplier_title", "product_type", "fulfillment_method", "warehouse_region", "source_country_code"):
                offer[key] = _safe_provider_text(offer.get(key), field_name=f"CJ {key}")
            safe_quotes = []
            for raw_quote in offer.get("shipping_quotes", ()):
                if not isinstance(raw_quote, Mapping):
                    continue
                quote = dict(raw_quote)
                for key in ("origin_country_code", "destination_country_code", "logistic_name"):
                    quote[key] = _safe_provider_text(quote.get(key), field_name=f"CJ quote {key}")
                safe_quotes.append(quote)
            offer["shipping_quotes"] = safe_quotes
        except ValueError:
            warnings.append("unsafe_supplier_identity_rejected")
            continue
        record, provenance, record_warnings = _normalize_offer(
            candidate_id,
            query,
            destination_country,
            offer,
            now=current,
            stale_after_seconds=float(stale_after_seconds),
        )
        warnings.extend(record_warnings)
        if record is None:
            continue
        records.append(record)
        selected_offers.append(offer)
        timestamps_value = offer.get("field_timestamps")
        timestamps = timestamps_value if isinstance(timestamps_value, Mapping) else {}
        source_field_evidence.append({
            "supplier_product_id": record.supplier_product_id,
            "fields": {
                key: {
                    "provenance": provenance.get(key, "unavailable"),
                    "captured_at": _iso_timestamp(_numeric_timestamp(timestamps, key)),
                }
                for key in sorted(set(provenance) | set(timestamps))
            },
        })

    if not records:
        return {
            "status": "no_results",
            "candidate_id": candidate_id,
            "search_query": query,
            "destination_country_code": destination_country,
            "evidence_mode": "fixture",
            "provider_status": provider_result.status,
            "supplier_records": [],
            "supplier_report": None,
            "logistics_reports": [],
            "opportunity_synthesis": None,
            "blockers": [],
            "warnings": sorted(set(warnings + ["no_valid_supplier_offer"])),
            "shipping_quotes": [],
            "source_field_evidence": [],
            "attempted": False,
            "read_only": True,
            "network_calls": False,
            "mutated": False,
        }

    generated_at = _iso_timestamp(current)
    supplier_report = build_supplier_feasibility_report(records, evidence_mode="fixture")
    logistics_reports = _logistics_reports(
        candidate_id,
        records,
        selected_offers,
        generated_at=generated_at,
        now=current,
        stale_after_seconds=float(stale_after_seconds),
    )
    synthesis = build_product_opportunity_synthesis(None, supplier_report.to_dict(), None)
    safe_shipping_quotes = []
    for record, offer in zip(records, selected_offers):
        timestamps_value = offer.get("field_timestamps")
        timestamps = timestamps_value if isinstance(timestamps_value, Mapping) else {}
        quotes = []
        for raw_quote in offer.get("shipping_quotes", ()):
            if not isinstance(raw_quote, Mapping):
                continue
            quote = dict(raw_quote)
            quote_fields = quote.get("field_provenance")
            quote_fields = dict(quote_fields) if isinstance(quote_fields, Mapping) else {}
            captured = _numeric_timestamp(quote, "captured_at")
            if captured is not None and current - captured > stale_after_seconds:
                quote_fields = {
                    key: "stale" if value in {"fixture", "derived"} else value
                    for key, value in quote_fields.items()
                }
            quote["field_provenance"] = quote_fields
            quotes.append(quote)
        safe_shipping_quotes.append({
            "supplier_product_id": record.supplier_product_id,
            "variant_id": str(offer.get("variant_id") or ""),
            "quotes": quotes,
            "field_timestamps": {
                key: _iso_timestamp(_numeric_timestamp(timestamps, key))
                for key in ("shipping_cost", "shipping_currency", "delivery_min_days", "delivery_max_days")
            },
        })
    return {
        "status": "fixture",
        "candidate_id": candidate_id,
        "search_query": query,
        "destination_country_code": destination_country,
        "evidence_mode": "fixture",
        "provider_status": provider_result.status,
        "supplier_reliability_status": "unknown_until_fulfillment_outcomes",
        "supplier_records": [record.to_dict() for record in records],
        "supplier_report": supplier_report.to_dict(),
        "logistics_reports": logistics_reports,
        "opportunity_synthesis": synthesis.to_dict(),
        "shipping_quotes": safe_shipping_quotes,
        "source_field_evidence": source_field_evidence,
        "freshness_policy": {
            "stale_after_seconds": float(stale_after_seconds),
            "label": "configuration threshold; not a CJ guarantee",
        },
        "blockers": [],
        "warnings": sorted(set(warnings)),
        "captured_at": generated_at,
        "attempted": False,
        "read_only": True,
        "network_calls": False,
        "mutated": False,
    }

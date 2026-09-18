"""services.unit_economics.analyzer — run_unit_economics, the paid-service
entrypoint wrapping MarketOS's existing margin_calculator/ltv math. No new
margin logic lives here beyond break_even.py's derived formulas.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from backend.economics import MarketLane, Money, UnitEconomicsAssumptions
from backend.economics import calculate_scenarios, calculate_unit_economics as calculate_canonical_unit_economics
from backend.experiments.audit_log import log_transition
from backend.experiments.envelope import CommercialRunEnvelope
from backend.experiments.registry import get_experiment_registry
from backend.workspaces.artifact_store import ArtifactStore
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import get_workspace_registry

from .break_even import break_even_cac, required_roas, verdict_from_margin
from .schemas import UnitEconomicsResult

_log = logging.getLogger(__name__)

SERVICE_NAME = "unit_economics"


def _default_workspace() -> ClientWorkspace:
    return get_workspace_registry().register(ClientWorkspace(name="ephemeral", workspace_type="internal"))


def _canonical_economics(
    supplier_cost: float,
    retail_price: float,
    shipping_cost: float,
    category: str,
    *,
    monthly_ad_spend: float = 500.0,
    expected_monthly_revenue: float = 5000.0,
    lane: MarketLane | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build the typed result from the service's explicit legacy inputs."""
    from backend.validation.margin_calculator import CATEGORY_RETURN_RATES, _PAYMENT_FEE_FIXED, _PAYMENT_FEE_PCT, _PLATFORM_MONTHLY

    currency = lane.currency if lane else "USD"
    price = Money(max(0.0, retail_price), currency, source="unit_economics_input", provenance="assumed")
    cost = Money(max(0.0, supplier_cost), currency, source="unit_economics_input", provenance="assumed")
    shipping = Money(max(0.0, shipping_cost), currency, source="unit_economics_input", provenance="assumed")
    expected_orders = max(expected_monthly_revenue / retail_price, 1.0) if retail_price > 0 else 1.0
    assumptions = UnitEconomicsAssumptions(
        supplier_shipping=shipping,
        payment_fee_rate=None if lane and lane.payment_fee_rate is not None else Decimal(str(_PAYMENT_FEE_PCT)),
        payment_fee_fixed=None if lane and lane.payment_fee_fixed is not None else Money(_PAYMENT_FEE_FIXED, currency, source="platform_assumption", provenance="assumed"),
        platform_fee_fixed=Money(_PLATFORM_MONTHLY / expected_orders, currency, source="platform_assumption", provenance="assumed"),
        platform_fee_rate=None if lane and lane.platform_fee_rate is not None else Decimal("0"),
        return_rate=Decimal(str(CATEGORY_RETURN_RATES.get(category, CATEGORY_RETURN_RATES["general"]))),
        defect_rate=Decimal("0"),
        warranty_rate=Decimal("0"),
        support_reserve_rate=Decimal("0"),
        chargeback_rate=Decimal("0"),
        fx_reserve_rate=Decimal("0"),
        discount_rate=Decimal("0"),
        affiliate_fee_rate=Decimal("0"),
        marketplace_fee_rate=Decimal("0"),
        tax_rate=None if lane else Decimal("0"),
        duty_rate=None if lane else Decimal("0"),
        cac=Money(monthly_ad_spend / expected_orders, currency, source="ad_spend_assumption", provenance="assumed"),
    )
    result = calculate_canonical_unit_economics(price, cost, lane=lane, assumptions=assumptions)
    scenarios = calculate_scenarios(price, cost, lane=lane, assumptions=assumptions)
    return result.to_dict(), [item.to_dict() for item in scenarios.values()]


def run_unit_economics(
    product_name: str,
    supplier_cost: float,
    retail_price: float,
    *,
    shipping_cost: float = 0.0,
    category: str = "general",
    geo: str | None = None,
    workspace: ClientWorkspace | None = None,
    lane: MarketLane | None = None,
) -> tuple[UnitEconomicsResult, CommercialRunEnvelope]:
    """Never raises: calculate_margin/calculate_margin_geo/
    calculate_ltv_adjusted_margin/effective_cac are all already never-raise;
    this function wraps them anyway so a surprise failure degrades to a
    partial result instead of aborting."""
    workspace = workspace or _default_workspace()
    workspace = get_workspace_registry().register(workspace)
    registry = get_experiment_registry()
    store = ArtifactStore(workspace)

    envelope = CommercialRunEnvelope(
        service_name=SERVICE_NAME,
        workspace_id=workspace.workspace_id,
        mode="dry_run" if workspace.dry_run_default else workspace.mode,
        inputs={
            "product_name": product_name, "supplier_cost": supplier_cost, "retail_price": retail_price,
            "shipping_cost": shipping_cost, "category": category, "geo": geo,
            "lane": lane.to_dict() if lane else None,
        },
    )
    registry.register(envelope)
    log_transition(envelope, "experiment_created")
    envelope.mark_running()
    log_transition(envelope, "experiment_running")

    base_margin: dict[str, Any] = {}
    geo_margin: dict[str, Any] | None = None
    ltv_margin: dict[str, Any] = {}
    be_cac = 0.0
    roas = 0.0
    eff_cac = 0.0
    canonical_result: dict[str, Any] = {}
    canonical_scenarios: list[dict[str, Any]] = []

    try:
        canonical_result, canonical_scenarios = _canonical_economics(supplier_cost, retail_price, shipping_cost, category, lane=lane)
    except Exception as exc:  # noqa: BLE001 - legacy result remains the compatibility fallback
        _log.debug("unit_economics_canonical_calculation_failed product=%s error=%s", product_name, type(exc).__name__)

    try:
        from backend.validation.margin_calculator import calculate_margin
        base_margin = calculate_margin(
            supplier_cost=supplier_cost, retail_price=retail_price,
            shipping_cost=shipping_cost, category=category,
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("unit_economics_base_margin_failed product=%s error=%s", product_name, exc)

    if geo:
        try:
            from backend.validation.margin_calculator import calculate_margin_geo
            geo_margin = calculate_margin_geo(
                supplier_cost=supplier_cost, retail_price=retail_price,
                shipping_cost=shipping_cost, category=category, geo=geo,
            )
        except Exception as exc:  # noqa: BLE001
            _log.debug("unit_economics_geo_margin_failed product=%s geo=%s error=%s", product_name, geo, exc)

    try:
        from backend.validation.margin_calculator import calculate_ltv_adjusted_margin
        ltv_margin = calculate_ltv_adjusted_margin(
            supplier_cost=supplier_cost, retail_price=retail_price,
            shipping_cost=shipping_cost, category=category,
        )
    except Exception as exc:  # noqa: BLE001
        _log.debug("unit_economics_ltv_margin_failed product=%s error=%s", product_name, exc)

    try:
        be_cac = break_even_cac(supplier_cost, retail_price, shipping_cost, category=category)
        roas = required_roas(supplier_cost, retail_price, shipping_cost, category=category)
    except Exception as exc:  # noqa: BLE001
        _log.debug("unit_economics_break_even_failed product=%s error=%s", product_name, exc)

    try:
        from backend.economics.ltv import effective_cac
        base_cac = base_margin.get("cac", 0.0)
        eff_cac = round(effective_cac(base_cac, category=category), 2) if base_cac else 0.0
    except Exception as exc:  # noqa: BLE001
        _log.debug("unit_economics_effective_cac_failed product=%s error=%s", product_name, exc)

    from services.status import commercial_status
    status = commercial_status(workspace=workspace)  # pure math, no external credentials/live data needed

    result = UnitEconomicsResult(
        product_name=product_name,
        category=category,
        base_margin=base_margin,
        geo_margin=geo_margin,
        ltv_adjusted_margin=ltv_margin,
        break_even_cac=be_cac,
        required_roas=roas,
        effective_cac=eff_cac,
        verdict=verdict_from_margin(base_margin) if base_margin else "unknown",
        status=status,
        dry_run=workspace.dry_run_default,
        canonical_economics=canonical_result,
        scenarios=canonical_scenarios,
    )

    try:
        from services.reporting import save_report_artifacts
        from .report import render_unit_economics_markdown
        save_report_artifacts(store, envelope.experiment_id,
                               render_unit_economics_markdown(result), result.to_dict())
    except Exception as exc:  # noqa: BLE001 — the JSON result below is the durable fallback
        _log.debug("unit_economics_report_save_failed error=%s", exc)
        store.save(envelope.experiment_id, "result.json", result.to_dict())

    envelope.mark_completed(result.to_dict())
    log_transition(envelope, "experiment_completed")

    return result, envelope


def from_ledger(
    product_name: str,
    *,
    workspace: ClientWorkspace,
    supplier_cost: float,
    retail_price: float,
    shipping_cost: float = 0.0,
    category: str = "general",
    geo: str | None = None,
    lane: MarketLane | None = None,
) -> tuple[UnitEconomicsResult, CommercialRunEnvelope]:
    """Same result shape as run_unit_economics, but monthly_ad_spend and
    expected_monthly_revenue are derived from backend.ledger's replayed
    commerce events for this workspace instead of the caller supplying
    them directly. Additive: run_unit_economics's direct-input signature
    is unchanged, and callers with no ledger history yet should keep
    using it. Never raises — an empty/missing ledger degrades to
    calculate_margin's own defaults (monthly_ad_spend=500.0,
    expected_monthly_revenue=5000.0), not a failure.
    """
    monthly_ad_spend = 500.0
    expected_monthly_revenue = 5000.0
    try:
        from backend.ledger.projections import compute_projection
        snapshot = compute_projection(workspace.workspace_id)
        if snapshot.total_ad_spend > 0:
            monthly_ad_spend = snapshot.total_ad_spend
        if snapshot.recognized_revenue > 0:
            expected_monthly_revenue = snapshot.recognized_revenue
    except Exception as exc:  # noqa: BLE001
        _log.debug("unit_economics_from_ledger_projection_failed workspace=%s error=%s",
                   workspace.workspace_id, exc)

    result, envelope = run_unit_economics(
        product_name, supplier_cost, retail_price,
        shipping_cost=shipping_cost, category=category, geo=geo, workspace=workspace,
        lane=lane,
    )

    try:
        from backend.validation.margin_calculator import calculate_margin
        ledger_margin = calculate_margin(
            supplier_cost=supplier_cost, retail_price=retail_price,
            shipping_cost=shipping_cost, category=category,
            monthly_ad_spend=monthly_ad_spend, expected_monthly_revenue=expected_monthly_revenue,
        )
        result.base_margin = ledger_margin
        result.verdict = verdict_from_margin(ledger_margin)
        envelope.outputs["base_margin"] = ledger_margin

        result.canonical_economics, result.scenarios = _canonical_economics(
            supplier_cost, retail_price, shipping_cost, category,
            monthly_ad_spend=monthly_ad_spend, expected_monthly_revenue=expected_monthly_revenue,
            lane=lane,
        )

        store = ArtifactStore(workspace)
        try:
            from services.reporting import save_report_artifacts
            from .report import render_unit_economics_markdown
            save_report_artifacts(store, envelope.experiment_id,
                                   render_unit_economics_markdown(result), result.to_dict())
        except Exception as exc:  # noqa: BLE001
            _log.debug("unit_economics_from_ledger_report_save_failed error=%s", exc)
            store.save(envelope.experiment_id, "result.json", result.to_dict())
        log_transition(envelope, "experiment_updated_from_ledger")
    except Exception as exc:  # noqa: BLE001 — direct-input result above is the fallback
        _log.debug("unit_economics_from_ledger_margin_failed product=%s error=%s", product_name, exc)

    return result, envelope

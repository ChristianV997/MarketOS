"""Offline finance planning for CompanyOS.

This is a scenario planner, not a bank, tax, investment, or payment system.
All numeric values are assumptions unless a caller labels them otherwise.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

from .service_catalog import ServicePackage


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _money(value: Any) -> float:
    return round(max(0.0, _num(value)), 2)


@dataclass(frozen=True)
class RevenueForecast:
    stream: str
    monthly_units: float
    average_price: float
    monthly_revenue: float
    evidence_status: str
    assumption_note: str


@dataclass(frozen=True)
class ExpenseForecast:
    category: str
    monthly_cost: float
    fixed_or_variable: str
    department: str
    assumption_note: str


@dataclass(frozen=True)
class DepartmentBudget:
    department: str
    monthly_cap: float
    planned_amount: float
    remaining_amount: float
    cap_status: str
    rationale: str


@dataclass(frozen=True)
class ProductTestBudget:
    candidate_id: str
    test_budget_cap: float
    supplier_validation_budget: float
    creative_validation_budget: float
    status: str


@dataclass(frozen=True)
class AdSpendBudget:
    monthly_cap: float
    approval_required: bool
    kill_switch_required: bool
    note: str


@dataclass(frozen=True)
class ClientProjectMargin:
    package_id: str
    average_price: float
    variable_cost: float
    gross_profit: float
    gross_margin_percent: float
    hours: float
    effective_hourly_rate: float
    assumption_note: str


@dataclass(frozen=True)
class ProfitScenario:
    scenario_id: str
    monthly_revenue: float
    monthly_cost: float
    gross_profit: float
    operating_profit: float
    margin_percent: float
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class SpendCap:
    cap_id: str
    category: str
    amount: float
    period: str
    approval_required: bool
    kill_condition: str


@dataclass(frozen=True)
class ReinvestmentPlan:
    priority: str
    allocation_percent: float
    amount: float
    rationale: str
    gate: str


@dataclass(frozen=True)
class BudgetScenario:
    scenario_id: str
    label: str
    starting_cash: float
    revenue_forecasts: tuple[RevenueForecast, ...]
    expense_forecasts: tuple[ExpenseForecast, ...]
    operating_profit: float
    runway_months: float | None
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class CashRunwayForecast:
    starting_cash: float
    monthly_burn: float
    runway_months: float | None
    warning: str


@dataclass(frozen=True)
class CapitalAllocationPlan:
    allocations: tuple[ReinvestmentPlan, ...]
    total_allocated: float
    unallocated_cash: float


@dataclass(frozen=True)
class FinancePlan:
    report_version: str
    currency: str
    monthly_revenue_forecast: tuple[RevenueForecast, ...]
    monthly_cost_forecast: tuple[ExpenseForecast, ...]
    gross_margin_forecast: float
    operating_profit_forecast: float
    cash_runway: CashRunwayForecast
    department_budgets: tuple[DepartmentBudget, ...]
    product_test_budgets: tuple[ProductTestBudget, ...]
    ad_spend_budget: AdSpendBudget
    client_project_margins: tuple[ClientProjectMargin, ...]
    profit_scenarios: tuple[ProfitScenario, ...]
    spend_caps: tuple[SpendCap, ...]
    capital_allocation: CapitalAllocationPlan
    reinvestment_recommendations: tuple[ReinvestmentPlan, ...]
    assumptions: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _service_revenue(packages: Iterable[ServicePackage], context: Mapping[str, Any]) -> list[RevenueForecast]:
    package_units = context.get("monthly_service_units", {}) if isinstance(context.get("monthly_service_units", {}), Mapping) else {}
    result: list[RevenueForecast] = []
    for package in packages:
        units = max(0.0, _num(package_units.get(package.package_id, 0)))
        average = round((package.price_min + package.price_max) / 2.0, 2)
        result.append(RevenueForecast(package.package_id, units, average, round(units * average, 2), "assumed", "Units and prices are planning assumptions."))
    return result


def build_finance_plan(*, context: Mapping[str, Any] | None = None, packages: Iterable[ServicePackage] = (), candidate_ids: Iterable[str] = ()) -> FinancePlan:
    context = context or {}
    currency = str(context.get("currency") or "USD")[:8]
    revenue = _service_revenue(packages, context)
    for item in context.get("additional_revenue_streams", ()) or ():
        if not isinstance(item, Mapping):
            continue
        stream = str(item.get("stream") or "manual_revenue")
        units = max(0.0, _num(item.get("monthly_units")))
        price = _money(item.get("average_price"))
        revenue.append(RevenueForecast(stream, units, price, round(units * price, 2), "assumed", "Manual planning assumption."))
    fixed_costs = context.get("monthly_fixed_costs", {}) if isinstance(context.get("monthly_fixed_costs", {}), Mapping) else {}
    variable_costs = context.get("monthly_variable_costs", {}) if isinstance(context.get("monthly_variable_costs", {}), Mapping) else {}
    costs: list[ExpenseForecast] = []
    for category, amount in sorted(fixed_costs.items()):
        costs.append(ExpenseForecast(str(category), _money(amount), "fixed", str(context.get("cost_department") or "management"), "Manual fixed-cost assumption."))
    for category, amount in sorted(variable_costs.items()):
        costs.append(ExpenseForecast(str(category), _money(amount), "variable", str(context.get("cost_department") or "operations"), "Manual variable-cost assumption."))
    revenue_total = round(sum(item.monthly_revenue for item in revenue), 2)
    cost_total = round(sum(item.monthly_cost for item in costs), 2)
    gross_margin = round((revenue_total - sum(item.monthly_cost for item in costs if item.fixed_or_variable == "variable")) / revenue_total, 4) if revenue_total else 0.0
    profit = round(revenue_total - cost_total, 2)
    starting_cash = _money(context.get("starting_cash", 0))
    burn = max(0.0, -profit)
    runway = round(starting_cash / burn, 2) if burn else None
    runway_warning = "No modeled burn; runway is not a forecast of solvency." if burn == 0 else "Review runway before approving new spend." if runway is not None and runway < 3 else "Scenario only; validate cash position with an accountant."
    budgets = [DepartmentBudget(name, _money(context.get("department_budgets", {}).get(name, 0)) if isinstance(context.get("department_budgets", {}), Mapping) else 0.0, 0.0, 0.0, "not_configured", "No spend authority is granted by this plan.") for name in ("management", "finance", "accounting", "sales", "intelligence", "launch", "website_store_funnel", "operations")]
    budgets = [DepartmentBudget(item.department, item.monthly_cap, item.planned_amount, round(item.monthly_cap - item.planned_amount, 2), "within_cap" if item.planned_amount <= item.monthly_cap else "over_cap", item.rationale) for item in budgets]
    product_budgets = [ProductTestBudget(str(candidate), _money(context.get("product_test_budget", 0)), _money(context.get("supplier_validation_budget", 0)), _money(context.get("creative_validation_budget", 0)), "approval_required") for candidate in candidate_ids]
    ad_cap = _money(context.get("ad_spend_monthly_cap", 0))
    ad_budget = AdSpendBudget(ad_cap, True, True, "No ad spend is authorized; cap is planning-only.")
    margins: list[ClientProjectMargin] = []
    for package in packages:
        average = round((package.price_min + package.price_max) / 2.0, 2)
        variable = round(average * package.estimated_variable_cost_percent, 2)
        gross = round(average - variable, 2)
        margins.append(ClientProjectMargin(package.package_id, average, variable, gross, package.gross_margin_estimate, package.estimated_delivery_hours, round(gross / package.estimated_delivery_hours, 2) if package.estimated_delivery_hours else 0.0, "Offline service-package assumption."))
    scenario = ProfitScenario("base", revenue_total, cost_total, round(revenue_total - sum(item.monthly_cost for item in costs if item.fixed_or_variable == "variable"), 2), profit, round(profit / revenue_total, 4) if revenue_total else 0.0, ("Revenue units, service prices, and costs are assumptions.", "This is not tax or investment advice."))
    caps = (SpendCap("product-tests", "product_validation", _money(context.get("product_test_budget", 0)), "monthly", True, "pause if evidence quality or economics deteriorate"), SpendCap("ads", "ad_spend", ad_cap, "monthly", True, "pause when an approved kill threshold is reached"))
    reinvest_cash = max(0.0, starting_cash + profit)
    allocations = (ReinvestmentPlan("evidence", .40, round(reinvest_cash * .40, 2), "Fund the next highest-value validation only.", "approval and evidence gate"), ReinvestmentPlan("delivery", .35, round(reinvest_cash * .35, 2), "Protect client delivery capacity.", "manager review"), ReinvestmentPlan("reserve", .25, round(reinvest_cash * .25, 2), "Preserve operating flexibility.", "do not spend automatically"))
    warnings = ("All values are scenario assumptions.", "No payments, transfers, bank reads, or investment/tax recommendations are performed.")
    return FinancePlan("companyos-finance-v1", currency, tuple(revenue), tuple(costs), gross_margin, profit, CashRunwayForecast(starting_cash, burn, runway, runway_warning), tuple(budgets), tuple(product_budgets), ad_budget, tuple(margins), (scenario,), caps, CapitalAllocationPlan(allocations, round(sum(item.amount for item in allocations), 2), round(max(0.0, reinvest_cash - sum(item.amount for item in allocations)), 2)), allocations, ("Service catalog feeds the forecast; no revenue is guaranteed.",) + warnings, warnings)


__all__ = ["RevenueForecast", "ExpenseForecast", "DepartmentBudget", "ProductTestBudget", "AdSpendBudget", "ClientProjectMargin", "ProfitScenario", "SpendCap", "ReinvestmentPlan", "BudgetScenario", "CashRunwayForecast", "CapitalAllocationPlan", "FinancePlan", "build_finance_plan"]

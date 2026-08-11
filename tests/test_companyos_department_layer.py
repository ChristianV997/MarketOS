from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.companyos.accounting import ACCOUNT_GROUPS, TRANSACTION_CATEGORIES, build_accounting_ledger, default_chart_of_accounts, load_transactions_csv
from evaluation.companyos.department_layer import DEPARTMENT_TYPES, CompanyOSReport, build_companyos_report
from evaluation.companyos.finance import build_finance_plan
from evaluation.companyos.sales import build_sales_pipeline
from evaluation.companyos.service_catalog import default_service_catalog, load_service_catalog

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "companyos"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture()
def report() -> CompanyOSReport:
    return build_companyos_report(company_context=load("company_context.json"))


def test_report_serializes_to_json_safe_shape(report):
    value = report.to_dict()
    assert value["report_version"] == "companyos-department-layer-v1"
    assert value["company"]["name"] == "MarketOS Demo"
    assert isinstance(json.dumps(value), str)


@pytest.mark.parametrize("field", ["read_only", "network_calls", "mutated", "external_actions", "live_messages_sent", "payments_created", "ads_launched", "orders_created", "publishing_done"])
def test_safety_flags_are_fixed(report, field):
    expected = True if field == "read_only" else False
    assert report.to_dict()[field] is expected


def test_unsafe_report_cannot_be_constructed(report):
    with pytest.raises(ValueError):
        CompanyOSReport(**{**report.to_dict(), "mutated": True})


def test_department_vocabulary_is_complete():
    assert {"management", "finance", "accounting", "sales"}.issubset(DEPARTMENT_TYPES)
    assert len(DEPARTMENT_TYPES) >= 10


def test_department_registry_has_expected_operating_departments(report):
    departments = {item["department_type"] for item in report.to_dict()["departments"]}
    assert {"management", "finance", "accounting", "sales", "supplier", "launch", "website_store_funnel"}.issubset(departments)


@pytest.mark.parametrize("department", sorted(DEPARTMENT_TYPES))
def test_every_department_has_manager_roles_workstreams_and_scorecard(report, department):
    item = next(item for item in report.to_dict()["departments"] if item["department_type"] == department)
    assert item["manager"]["human_approval_required"] is True
    assert item["roles"] and item["workstreams"] and item["tasks"]
    assert item["scorecard"]["department"] == department


@pytest.mark.parametrize("field", ["department_id", "name", "department_type", "manager", "roles", "workstreams", "tasks", "scorecard", "risks", "approvals", "operating_status", "next_best_action"])
def test_department_shape(report, field):
    assert all(field in item for item in report.to_dict()["departments"])


def test_supplier_is_blocked_until_live_proof(report):
    supplier = next(item for item in report.departments if item.department_type == "supplier")
    assert supplier.operating_status == "blocked"
    assert any(item.category == "evidence" for item in supplier.risks)


def test_management_review_contains_priorities_blockers_and_approvals(report):
    review = report.management.weekly_operating_review
    assert review.priorities and review.blocked_workstreams and review.pending_approvals
    assert "offline planning mode" in review.ceo_summary


def test_management_has_manager_briefs_and_org_chart(report):
    assert len(report.management.manager_briefs) == 11
    assert len(report.management.org_chart["departments"]) == 11


def test_approval_queue_is_pending_and_forbids_authority(report):
    value = report.to_dict()["approval_queue"]
    assert value["pending_count"] >= 1
    assert any("publish" in item for request in value["requests"] for item in request["forbidden_without_approval"])


def test_risk_register_has_escalations(report):
    assert any(item.escalation_required for item in report.risk_register)
    assert any(item.category == "consent" for item in report.risk_register)


def test_company_scorecard_is_blocked_by_supplier_gate(report):
    scorecard = report.company_scorecard
    assert scorecard.company_status == "blocked"
    assert "supplier" in scorecard.blocked_departments
    assert scorecard.safety_status == "controlled"


def test_optional_commerce_reports_are_tracked():
    value = build_companyos_report(source_reports={"opportunity_synthesis": "available", "launch_draft_pack": "available", "site_draft_pack": "available"}).to_dict()
    assert value["source_reports"] == {"opportunity_synthesis": "available", "launch_draft_pack": "available", "site_draft_pack": "available"}
    assert "Sources: launch_draft_pack and opportunity_synthesis and site_draft_pack" in value["management"]["weekly_operating_review"]["ceo_summary"]


def test_empty_context_degrades_safely():
    value = build_companyos_report().to_dict()
    assert value["company"]["context_status"] == "defaulted"
    assert value["company_scorecard"]["company_status"] == "blocked"


def test_malformed_context_degrades_safely():
    value = build_companyos_report(company_context=load("malformed_companyos_input.json")).to_dict()
    assert value["company"]["name"] == "42"
    assert value["company_scorecard"]["company_status"] == "blocked"


def test_finance_plan_uses_service_catalog_units():
    context = load("finance_assumptions.json")
    plan = build_finance_plan(context=context, packages=default_service_catalog())
    assert sum(item.monthly_revenue for item in plan.monthly_revenue_forecast) > 0
    assert plan.client_project_margins
    assert plan.ad_spend_budget.approval_required is True


@pytest.mark.parametrize("field", ["monthly_revenue_forecast", "monthly_cost_forecast", "gross_margin_forecast", "operating_profit_forecast", "cash_runway", "department_budgets", "product_test_budgets", "ad_spend_budget", "client_project_margins", "profit_scenarios", "spend_caps", "capital_allocation", "reinvestment_recommendations", "assumptions", "warnings"])
def test_finance_plan_has_required_outputs(field):
    assert field in build_finance_plan(context=load("finance_assumptions.json"), packages=default_service_catalog()).to_dict()


def test_cash_runway_is_scenario_only():
    plan = build_finance_plan(context={"starting_cash": 1000, "monthly_fixed_costs": {"software": 100}}, packages=())
    assert plan.cash_runway.runway_months == 10.0
    assert any("assumption" in item.lower() for item in plan.warnings)


def test_zero_burn_has_no_fake_runway():
    plan = build_finance_plan(context={"starting_cash": 1000}, packages=())
    assert plan.cash_runway.runway_months is None


def test_department_budgets_never_grant_spend_authority():
    plan = build_finance_plan(context={"department_budgets": {"sales": 1000}}, packages=())
    assert all(item.rationale.startswith("No spend authority") for item in plan.department_budgets)


def test_product_test_budget_is_capped():
    plan = build_finance_plan(context={"product_test_budget": 250, "supplier_validation_budget": 100}, packages=(), candidate_ids=("candidate-a",))
    assert plan.product_test_budgets[0].test_budget_cap == 250
    assert plan.product_test_budgets[0].status == "approval_required"


def test_catalog_contains_requested_packages():
    packages = default_service_catalog()
    names = {item.name for item in packages}
    assert "Product Opportunity Report" in names
    assert "Full Revenue Operations OS" in names
    assert len(packages) == 11


@pytest.mark.parametrize("field", ["package_id", "name", "department_owner", "price_min", "price_max", "estimated_delivery_hours", "estimated_variable_cost_percent", "gross_margin_estimate", "required_inputs", "approval_requirements", "handoff_department"])
def test_service_package_has_required_field(field):
    assert all(field in item.to_dict() for item in default_service_catalog())


def test_catalog_seed_overrides_only_price_band():
    packages = load_service_catalog({"packages": [{"package_id": "product-opportunity-report", "price_min": 800, "price_max": 1400, "unknown": "ignored"}]})
    package = next(item for item in packages if item.package_id == "product-opportunity-report")
    assert (package.price_min, package.price_max) == (800, 1400)
    assert package.name == "Product Opportunity Report"


def test_chart_of_accounts_has_required_groups():
    chart = default_chart_of_accounts()
    assert {item.group for item in chart.accounts} >= set(ACCOUNT_GROUPS)


@pytest.mark.parametrize("category", TRANSACTION_CATEGORIES)
def test_chart_of_accounts_has_every_transaction_category(category):
    assert any(item.account_id == category for item in default_chart_of_accounts().accounts)


def test_accounting_csv_creates_ledger_seed():
    text = (FIXTURES / "accounting_transactions_seed.csv").read_text(encoding="utf-8")
    ledger = build_accounting_ledger(csv_text=text)
    assert len(ledger.transactions) == 3
    assert ledger.reconciliation.unreconciled_count == 2
    assert ledger.profit_and_loss.status == "draft"


def test_accounting_categories_are_normalized():
    rows = load_transactions_csv("transaction_id,amount,category\n1,4,consulting revenue\n2,5,unknown\n")
    assert rows[0].category == "consulting_revenue"
    assert rows[1].category == "transfer"


def test_accounting_rejects_private_columns():
    with pytest.raises(ValueError):
        load_transactions_csv("transaction_id,amount,api_key\n1,4,secret\n")


@pytest.mark.parametrize("field", ["chart_of_accounts", "transactions", "reconciliation", "period_summary", "profit_and_loss", "cash_flow", "warnings"])
def test_accounting_seed_has_required_outputs(field):
    ledger = build_accounting_ledger(csv_text="transaction_id,amount,category\n1,10,consulting_revenue\n")
    assert field in ledger.to_dict()


def test_sales_pipeline_is_draft_only():
    pipeline = build_sales_pipeline(context=load("sales_lead_context.json"), packages={item.package_id: item for item in default_service_catalog()})
    assert pipeline.leads[0].score.score >= 70
    assert all(item.status == "draft" and not item.send_authorized for item in pipeline.messages)
    assert all(item.booking_status == "not_booked" for item in pipeline.appointments)


def test_sales_tracks_consent_and_do_not_contact():
    pipeline = build_sales_pipeline(context={"lead": {"consent_status": "not_given", "do_not_contact": True}})
    assert pipeline.leads[0].do_not_contact is True
    assert pipeline.leads[0].score.score == 0
    assert pipeline.leads[0].score.next_action == "do not contact"


@pytest.mark.parametrize("field", ["icp", "leads", "accounts", "contacts", "deals", "stages", "brief", "messages", "call_script", "proposal", "handoffs", "objections", "appointments", "reminders", "warnings"])
def test_sales_pipeline_has_required_outputs(field):
    assert field in build_sales_pipeline().to_dict()


def test_sales_proposal_uses_catalog_price_band():
    package = next(item for item in default_service_catalog() if item.package_id == "launch-draft-pack")
    pipeline = build_sales_pipeline(context={"recommended_package_id": package.package_id}, packages={package.package_id: package})
    assert tuple(pipeline.proposal.price_band) == (package.price_min, package.price_max)


def test_sales_handoff_requires_approved_scope():
    assert build_sales_pipeline().handoffs[0].approved_scope_required is True


def test_cli_json_is_offline_and_safe():
    result = subprocess.run([sys.executable, "scripts/run_companyos_department_layer.py", "--company-context", "tests/fixtures/companyos/company_context.json", "--json"], cwd=ROOT, capture_output=True, text=True, check=True)
    value = json.loads(result.stdout)
    assert value["network_calls"] is False
    assert value["mutated"] is False
    assert "secret" not in result.stdout.lower()


def test_cli_markdown_has_operating_review():
    result = subprocess.run([sys.executable, "scripts/run_companyos_department_layer.py", "--company-context", "tests/fixtures/companyos/company_context.json", "--markdown"], cwd=ROOT, capture_output=True, text=True, check=True)
    assert "# CompanyOS Department Layer" in result.stdout
    assert "## Management Operating Review" in result.stdout
    assert "## Safety Boundaries" in result.stdout


def test_cli_service_catalog_and_sales_context():
    result = subprocess.run([sys.executable, "scripts/run_companyos_department_layer.py", "--service-catalog", "--sales-context", "tests/fixtures/companyos/sales_lead_context.json", "--json"], cwd=ROOT, capture_output=True, text=True, check=True)
    value = json.loads(result.stdout)
    assert len(value["service_catalog"]) == 11
    assert value["sales"]["leads"][0]["score"]["score"] >= 70


def test_cli_accepts_accounting_seed():
    result = subprocess.run([sys.executable, "scripts/run_companyos_department_layer.py", "--accounting-transactions", "tests/fixtures/companyos/accounting_transactions_seed.csv", "--json"], cwd=ROOT, capture_output=True, text=True, check=True)
    assert len(json.loads(result.stdout)["accounting"]["transactions"]) == 3


def test_cli_writes_requested_exports(tmp_path):
    output = tmp_path / "companyos"
    subprocess.run([sys.executable, "scripts/run_companyos_department_layer.py", "--output", str(output), "--markdown"], cwd=ROOT, capture_output=True, text=True, check=True)
    expected = {"companyos_report.json", "companyos_report.md", "department_registry.json", "management_operating_review.md", "finance_plan.json", "accounting_ledger_seed.json", "sales_pipeline_seed.json", "service_catalog.json", "approval_queue.json", "risk_register.json"}
    assert expected == {item.name for item in output.iterdir()}


def test_cli_rejects_path_traversal():
    result = subprocess.run([sys.executable, "scripts/run_companyos_department_layer.py", "--company-context", "../secret.json", "--json"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 2
    assert "traversal" in result.stderr


def test_cli_rejects_secret_like_context():
    result = subprocess.run([sys.executable, "scripts/run_companyos_department_layer.py", "--company-context", "tests/fixtures/companyos/secret_like_companyos_input_rejected.json", "--json"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 2
    assert "secret-like" in result.stderr


def test_cli_output_is_deterministic():
    command = [sys.executable, "scripts/run_companyos_department_layer.py", "--company-context", "tests/fixtures/companyos/company_context.json", "--json"]
    first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True).stdout
    second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert first == second


def test_report_source_flags_support_commerce_to_operations_handoff():
    report = build_companyos_report(source_reports={"opportunity_synthesis": "available", "launch_draft_pack": "available", "site_draft_pack": "available"})
    assert report.source_reports["site_draft_pack"] == "available"
    assert any("client/service scope" in item.required_evidence for item in report.approval_queue.requests)


@pytest.mark.parametrize("section", ["CEO Summary", "Department Registry", "Management Operating Review", "Finance Plan", "Accounting Ledger Seed", "Sales Pipeline Seed", "Service Catalog", "Approval Queue", "Risk Register", "Next Best Actions", "Safety Boundaries"])
def test_markdown_operating_review_has_required_section(report, section):
    assert f"## {section}" in report.to_markdown()


def test_management_next_actions_assign_manager_owners(report):
    assert len(report.management.next_actions) == len(report.departments)
    assert all(item.owner.startswith("manager-") for item in report.management.next_actions)


def test_finance_reinvestment_allocations_are_bounded():
    plan = build_finance_plan(context={"starting_cash": 1000}, packages=())
    assert round(sum(item.allocation_percent for item in plan.reinvestment_recommendations), 4) == 1.0


def test_finance_negative_profit_does_not_create_positive_burn():
    plan = build_finance_plan(context={"starting_cash": 100, "monthly_fixed_costs": {"cost": 200}}, packages=())
    assert plan.cash_runway.monthly_burn == 200


def test_accounting_source_is_manual_import():
    row = load_transactions_csv("transaction_id,amount,category\n1,10,consulting_revenue\n")[0]
    assert row.source == "manual_import" and row.evidence_mode == "manual_import"


def test_accounting_empty_seed_is_explicitly_empty():
    ledger = build_accounting_ledger()
    assert ledger.transactions == ()
    assert ledger.reconciliation.status == "reconciled"


def test_sales_unknown_intent_is_low_confidence():
    pipeline = build_sales_pipeline(context={"lead": {"buying_intent": "unknown", "consent_status": "unknown"}})
    assert pipeline.leads[0].score.grade == "C"


def test_sales_message_unsubscribe_language_is_present():
    pipeline = build_sales_pipeline()
    assert all("opt-out" in item.unsubscribe_note.lower() or "opt-in" in item.unsubscribe_note.lower() for item in pipeline.messages)


def test_service_catalog_margin_is_not_authority():
    assert all("assumption" in (item.margin_assumption.cost_basis.lower() if item.margin_assumption else "") for item in default_service_catalog())

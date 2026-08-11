"""Ledger-ready accounting seeds for CompanyOS; no accounting-platform writes."""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from io import StringIO
from typing import Any, Iterable, Mapping

ACCOUNT_GROUPS = ("assets", "liabilities", "equity", "revenue", "cost_of_goods_sold", "operating_expenses", "sales_marketing_expenses", "software_tools", "contractors_payroll", "taxes", "owner_draws")
TRANSACTION_CATEGORIES = ("consulting_revenue", "launch_pack_revenue", "website_project_revenue", "managed_marketing_revenue", "sales_bot_revenue", "saas_subscription_revenue", "api_platform_revenue", "ecommerce_sales_revenue", "supplier_cogs", "ad_spend", "software_subscription", "contractor_payment", "payment_processing_fee", "refund", "tax", "transfer", "owner_draw")


@dataclass(frozen=True)
class Account:
    account_id: str
    name: str
    group: str
    normal_balance: str
    tax_tag: str


@dataclass(frozen=True)
class ChartOfAccounts:
    accounts: tuple[Account, ...]
    version: str = "companyos-coa-v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Counterparty:
    counterparty_id: str
    name: str
    kind: str
    private_data_present: bool = False


@dataclass(frozen=True)
class Transaction:
    transaction_id: str
    date: str
    description: str
    amount: float
    currency: str
    category: str
    account_id: str
    department: str
    project_id: str
    counterparty: str
    reconciliation_status: str
    tax_tag: str
    source: str
    evidence_mode: str


@dataclass(frozen=True)
class InvoiceDraft:
    invoice_id: str
    client_or_account: str
    amount: float
    currency: str
    status: str = "draft"
    sent: bool = False


@dataclass(frozen=True)
class ReceiptRecord:
    receipt_id: str
    transaction_id: str
    receipt_status: str = "not_attached"
    raw_document_stored: bool = False


@dataclass(frozen=True)
class PaymentRecord:
    payment_id: str
    transaction_id: str
    status: str = "not_created"
    external_call_made: bool = False


@dataclass(frozen=True)
class TransferRecord:
    transfer_id: str
    from_account: str
    to_account: str
    amount: float
    status: str = "draft"


@dataclass(frozen=True)
class PayoutRecord:
    payout_id: str
    source: str
    amount: float
    status: str = "not_received"


@dataclass(frozen=True)
class COGSRecord:
    transaction_id: str
    candidate_id: str
    amount: float
    source_status: str


@dataclass(frozen=True)
class AdSpendRecord:
    transaction_id: str
    campaign_id: str
    amount: float
    approval_status: str = "approval_required"


@dataclass(frozen=True)
class SupplierCostRecord:
    transaction_id: str
    supplier: str
    candidate_id: str
    amount: float
    evidence_status: str


@dataclass(frozen=True)
class SoftwareSubscriptionRecord:
    transaction_id: str
    vendor: str
    amount: float
    active_status: str = "review_required"


@dataclass(frozen=True)
class ContractorPaymentRecord:
    transaction_id: str
    contractor: str
    amount: float
    payment_status: str = "not_sent"


@dataclass(frozen=True)
class ReconciliationStatus:
    reconciled_count: int
    unreconciled_count: int
    status: str
    note: str


@dataclass(frozen=True)
class AccountingPeriodSummary:
    period: str
    total_revenue: float
    total_expenses: float
    net_cash_movement: float
    unreconciled_count: int


@dataclass(frozen=True)
class ProfitAndLossDraft:
    revenue_by_category: dict[str, float]
    expenses_by_category: dict[str, float]
    gross_profit: float
    operating_profit: float
    status: str = "draft"


@dataclass(frozen=True)
class CashFlowDraft:
    inflows: float
    outflows: float
    net_cash_flow: float
    status: str = "draft"


@dataclass(frozen=True)
class AccountingLedgerSeed:
    chart_of_accounts: ChartOfAccounts
    transactions: tuple[Transaction, ...]
    reconciliation: ReconciliationStatus
    period_summary: AccountingPeriodSummary
    profit_and_loss: ProfitAndLossDraft
    cash_flow: CashFlowDraft
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_chart_of_accounts() -> ChartOfAccounts:
    definitions = [
        ("cash", "Cash", "assets", "debit", "not_applicable"), ("accounts_receivable", "Accounts receivable", "assets", "debit", "review_required"), ("accounts_payable", "Accounts payable", "liabilities", "credit", "review_required"), ("owner_equity", "Owner equity", "equity", "credit", "not_applicable"),
        ("consulting_revenue", "Consulting revenue", "revenue", "credit", "income_review"), ("launch_pack_revenue", "Launch Pack revenue", "revenue", "credit", "income_review"), ("website_project_revenue", "Website project revenue", "revenue", "credit", "income_review"), ("managed_marketing_revenue", "Managed marketing revenue", "revenue", "credit", "income_review"), ("sales_bot_revenue", "Sales bot revenue", "revenue", "credit", "income_review"), ("saas_subscription_revenue", "SaaS subscription revenue", "revenue", "credit", "income_review"), ("api_platform_revenue", "API platform revenue", "revenue", "credit", "income_review"), ("ecommerce_sales_revenue", "Ecommerce sales revenue", "revenue", "credit", "income_review"),
        ("supplier_cogs", "Supplier COGS", "cost_of_goods_sold", "debit", "cogs_review"), ("ad_spend", "Ad spend", "sales_marketing_expenses", "debit", "expense_review"), ("software_subscription", "Software subscription", "software_tools", "debit", "expense_review"), ("contractor_payment", "Contractor payment", "contractors_payroll", "debit", "payroll_review"), ("payment_processing_fee", "Payment processing fee", "operating_expenses", "debit", "expense_review"), ("refund", "Refund", "operating_expenses", "debit", "refund_review"), ("tax", "Tax", "taxes", "debit", "tax_review"), ("transfer", "Transfer", "assets", "debit", "not_applicable"), ("owner_draw", "Owner draw", "owner_draws", "debit", "owner_review"),
    ]
    return ChartOfAccounts(tuple(Account(*item) for item in definitions))


def _category(value: Any) -> str:
    value = str(value or "").strip().lower().replace(" ", "_")
    return value if value in TRANSACTION_CATEGORIES else "transfer"


def load_transactions_csv(text: str) -> list[Transaction]:
    """Parse only normalized CSV columns; reject secret-like fields and private data."""
    reader = csv.DictReader(StringIO(text))
    allowed = {"transaction_id", "date", "description", "amount", "currency", "category", "department", "project_id", "counterparty", "reconciliation_status", "tax_tag"}
    if any(key.lower() in {"password", "token", "secret", "api_key", "bank_account", "card_number"} for key in (reader.fieldnames or ())):
        raise ValueError("secret-like or private accounting columns are not accepted")
    result: list[Transaction] = []
    for index, row in enumerate(reader, 1):
        try:
            amount = round(float(row.get("amount") or 0), 2)
        except (TypeError, ValueError):
            amount = 0.0
        category = _category(row.get("category"))
        result.append(Transaction(str(row.get("transaction_id") or f"txn-{index}"), str(row.get("date") or "TBD"), " ".join(str(row.get("description") or "Ledger seed").split())[:160], amount, str(row.get("currency") or "USD")[:8], category, f"account-{category}", str(row.get("department") or "accounting"), str(row.get("project_id") or "TBD"), "[redacted]" if row.get("counterparty") else "TBD", str(row.get("reconciliation_status") or "unreconciled"), str(row.get("tax_tag") or "review_required"), "manual_import", "manual_import"))
    return result


def build_accounting_ledger(*, csv_text: str | None = None, transactions: Iterable[Transaction] = ()) -> AccountingLedgerSeed:
    records = list(transactions) or (load_transactions_csv(csv_text) if csv_text else [])
    revenue_by: dict[str, float] = {}
    expense_by: dict[str, float] = {}
    for item in records:
        target = revenue_by if item.category.endswith("revenue") or item.category == "ecommerce_sales_revenue" else expense_by
        target[item.category] = round(target.get(item.category, 0.0) + abs(item.amount), 2)
    revenue = round(sum(revenue_by.values()), 2)
    expenses = round(sum(expense_by.values()), 2)
    unreconciled = sum(item.reconciliation_status != "reconciled" for item in records)
    return AccountingLedgerSeed(default_chart_of_accounts(), tuple(records), ReconciliationStatus(len(records) - unreconciled, unreconciled, "reconciled" if unreconciled == 0 else "review_required", "Ledger seed only; reconcile with an accountant."), AccountingPeriodSummary("TBD", revenue, expenses, round(revenue - expenses, 2), unreconciled), ProfitAndLossDraft(revenue_by, expense_by, round(revenue - expense_by.get("supplier_cogs", 0.0), 2), round(revenue - expenses, 2)), CashFlowDraft(revenue, expenses, round(revenue - expenses, 2)), ("Ledger records are manual/import seeds and not posted to an accounting platform.", "No payments, transfers, tax filings, or bank reads are performed."))


__all__ = ["ACCOUNT_GROUPS", "TRANSACTION_CATEGORIES", "Account", "ChartOfAccounts", "Counterparty", "Transaction", "InvoiceDraft", "ReceiptRecord", "PaymentRecord", "TransferRecord", "PayoutRecord", "COGSRecord", "AdSpendRecord", "SupplierCostRecord", "SoftwareSubscriptionRecord", "ContractorPaymentRecord", "ReconciliationStatus", "AccountingPeriodSummary", "ProfitAndLossDraft", "CashFlowDraft", "AccountingLedgerSeed", "default_chart_of_accounts", "load_transactions_csv", "build_accounting_ledger"]

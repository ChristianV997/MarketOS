# CompanyOS Department Layer v1

CompanyOS is MarketOS' offline operating spine. It gives Management, Finance, Accounting, and Sales a shared vocabulary for departments, managers, workstreams, tasks, approvals, risks, budgets, ledger-ready records, leads, deals, and operating reviews.

## Learning Ledger relationship

Department reviews and scorecards can become sanitized learning events after a decision has an outcome. The event retains department ownership and evidence references so Management, Finance, Sales, and Operations can learn without creating a second event or approval system. All records remain offline planning metadata.

It is not a CRM, accounting platform, project-management product, bank integration, messaging system, or payment system. It creates deterministic planning records and draft outputs that a human can review.

## Run it

```powershell
python scripts/run_companyos_department_layer.py --json
python scripts/run_companyos_department_layer.py --markdown
python scripts/run_companyos_department_layer.py --company-context tests/fixtures/companyos/company_context.json --sales-context tests/fixtures/companyos/sales_lead_context.json --markdown
python scripts/run_companyos_department_layer.py --accounting-transactions tests/fixtures/companyos/accounting_transactions_seed.csv --output artifacts/companyos/latest --markdown
```

Optional commerce context can be linked with `--opportunity-synthesis-report`, `--launch-draft-pack`, and `--site-draft-pack`. The CLI records that source reports are available; it does not publish, mutate, send, or spend.

## Departments

- Management owns the weekly operating review, priorities, scorecards, escalations, and approval queue.
- Finance plans revenue, costs, runway, budgets, spend caps, and reinvestment scenarios.
- Accounting produces a chart of accounts, normalized ledger seeds, reconciliation status, P&L draft, and cash-flow draft.
- Sales models ICP/persona fit, lead scores, pipeline stages, draft messages, proposals, objections, and delivery handoffs.
- Intelligence, Supplier, Consumer Attention, Launch, Website / Store / Funnel, Operations, and Risk & Approval preserve the existing evidence-to-delivery chain.

The service catalog is shared by Finance and Sales. Price bands and margins are planning assumptions; they are not quotes, tax advice, or guaranteed profit.

## Governance boundaries

Every output is read-only, offline, advisory, and non-authoritative. Approval requests explicitly list forbidden actions. Sales messages remain drafts with consent and do-not-contact fields. Ledger rows are not posted. Budgets are caps for review, not spend authority. Publishing, ads, orders, payments, customer messages, platform mutations, and external calls are disabled.

This prepares Management v2, Finance v2, Accounting v2, and Sales v2 without committing to external SaaS integrations.

The Agent / Skill / Tool / Workflow Registry is the next control-plane layer. It defines the contracts and safety gates those future department modules must use before any external integration is considered.

The Approval Ledger is the next gate after the registry: department plans, sales drafts, budgets, and ledger seeds may be produced locally, while messaging, payments, accounting sync, publishing, orders, and external calls remain blocked or simulation-only.

The Provider / Credential / Subscription Registry extends this operating spine with safe ownership, secret-manager references, scopes, budgets, rotation, health placeholders, and activation gates. It stores metadata only and does not validate or activate credentials.
# Client workspace boundary

CompanyOS department outputs can be projected to a client workspace only through the offline Client Workspace Isolation Plan. Department internals and cross-client operating knowledge remain internal.

The Resource & Execution Governor coordinates department proposals with Finance budgets, Management priorities, TrustOS gates, Approval Ledger decisions, and learning requirements.

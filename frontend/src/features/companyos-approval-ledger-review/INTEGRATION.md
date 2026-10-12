# CompanyOS Approval Ledger review (frontend slice)

Status: implemented, fixture-backed, local-file review, contract-adapted,
focused-tested, routed. Offline planning review only.

## Data source (no invented API)

There is **no mounted read-only HTTP GET** for CompanyOS Approval Ledger on `main`.

Canonical producer:

```text
python scripts/run_companyos_approval_ledger.py \
  --approval-requests tests/fixtures/companyos_approval/approval_requests_seed.json \
  --simulate-action model_spend --requested-budget 0.20 \
  --output artifacts/companyos_approval/latest --json
```

Report contract: `ApprovalLedgerReport.to_dict()` with
`report_version: companyos-approval-ledger-v1`
(`evaluation/companyos/approval_ledger.py`).

This page can:

1. Show the built-in **demo fixture** (clearly labeled), or
2. Let an operator pick a **local JSON report** from that CLI via a browser file
   input. The file is validated (size, JSON object shape, `report_version`) then
   passed through `adaptApprovalLedger` (secret/safety fail-closed). Content stays
   **in memory only** — no upload, network request, local persistence, or
   arbitrary filesystem access.

It does **not** call `/api/cockpit/approvals` (execution-cockpit write/decide path).

## Route

Mounted under Shell in `frontend/src/main.tsx`:

```text
/operator/approval-ledger → <ApprovalLedgerReviewPage />
```

Sidebar / Shell chrome ownership is out of this lane. Direct URL navigation is
enough for the review vertical.

## What the UI shows

- Local report picker with demo-fixture vs local-import distinction
- Queue summary (blocked / pending / draft-or-simulated / approved records)
- Policy decision classes and blocked-in-current-mode distinctions
- Request status, risk, sanitized evidence references, conditions
- Simulation results with explicit “not live authority” copy
- Safety summary (`read_only`, no network, no external action)
- Loading / empty / invalid (error) / review (success) surface states
- Safe plain-text display of untrusted strings (no HTML interpretation)
- Malformed or secret-shaped input fails closed without echoing contents

## Authority boundary

Always: `execution_authorized === false` (forced even if the imported JSON claims
otherwise). Scorecards, drafts, simulations, and approved **records** never
authorize spend, publish, orders, payments, messaging, or provider calls on this
surface. No approve/deny, transition, spend, publish, payment, or provider
controls. `would_auto_allow_draft` is a descriptive simulation result only.

## Integration boundaries

Do **not** edit in this lane:

- `frontend/src/components/layout/Sidebar.tsx` / `Shell.tsx` / `sidebarDrawer.ts`
- Tailwind / PostCSS / `package.json`
- Backend ledger, CLI, or new API routes

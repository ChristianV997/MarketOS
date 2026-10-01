# Owner performance dashboard (frontend slice)

Status: implemented, presenter-tested, **not mounted**, **not a live route**.

Pinned contract: PR #368 `owner-performance-report-v1` at `17f0c6caa769ea13a3635b28dbb70313802da2fa`.

## What the UI shows
- Period, currency, evidence classes, confidence.
- Revenue, refunds, product cost, shipping, fees, ad spend, contribution, realized profit only from the report object.
- Unavailable amounts stay "Unavailable" and say they are not zero.
- Explicit zeros come only from `explicit_zeros`.
- Campaign table from `campaigns`. Lift text is always "not claimed".
- No time series: the contract has none.
- Optional Recharts bars repeat reported campaign amounts; the table is the accessible source.

## Integration
Do not edit `frontend/src/main.tsx` or Sidebar in this change (owned by PR #370). A later owner can render `OwnerPerformanceDashboard` inside an existing `<main>` and pass a report fetched elsewhere. There is no endpoint in #368.

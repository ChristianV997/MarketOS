# Owner performance dashboard (frontend slice)

Status: implemented, contract-tested, adapter-tested, fail-closed live client attached, **endpoint unmounted in backend**.

Pinned contract: PR #368 `owner-performance-report-v1` at `17f0c6caa769ea13a3635b28dbb70313802da2fa`.
Canonical endpoint: `GET /api/owner/performance` (consumed through `fetchOwnerPerformanceReport` and `useOwnerPerformance` without workspace selector).

## What the UI shows
- **Period, currency, evidence classes, confidence**: displayed strictly as reported by the canonical contract.
- **Amounts strictly from server**: Revenue, refunds, product cost, shipping, fees, ad spend, contribution, realized profit are shown only when provided by the contract. The frontend never calculates competing scores or recomputes profit.
- **Missing amounts vs. explicit zero**:
  - Unavailable amounts stay `"Unavailable"` with missing reasons and explicitly declare `"Not zero"`.
  - Explicit zeros come strictly from `report.explicit_zeros` where amount is `"0"`.
- **Campaign table & attribution safety**:
  - Campaign rows preserve incoming server order without client sorting or re-ranking.
  - Lift text is strictly `"Not claimed. Causal lift is unsupported."`.
  - Causal attribution is strictly `"not claimed"`.
  - No platform connection or ad spend authority is claimed.
- **Fixture evidence**:
  - If `evidence_classes` or any metric includes `"fixture"`, a prominent banner warns: `"Fixture evidence is present. Do not treat these amounts as live results."`.
- **States covered**:
  - `loading`: accessible loading status note.
  - `auth`: `role="alert"` notification when HTTP 401/403 is received, stating authentication is required.
  - `unavailable`: fail-closed message stating `"Backend route GET /api/owner/performance is not yet mounted. Contract dependency: owner-performance-report-v1 (PR #368)."`.
  - `empty`: accessible note `"No in-period lines. Empty is not zero revenue."`.
  - `stale`: cached report timestamp banner with note that data may be stale.
  - `error`: `role="alert"` for unrecoverable errors or contract rejection.
- **Charts and mobile accessibility**:
  - Recharts bar chart includes SVG pattern fills (`spend-stripes` and `revenue-dots`) with contrasting borders, ensuring metrics are distinguishable without color alone.
  - Full accessible table alternative is rendered with `<caption>`, `<th scope="col">`, `<th scope="row">`, and keyboard navigation (`ArrowDown`, `ArrowUp`, `Home`, `End`).
  - Mobile responsive down to 375px with single-column metric card grid and horizontal scroll container for table.

## Backend dependency
`GET /api/owner/performance` is not yet mounted in the backend. When called in production, the hook fails closed into the `unavailable` phase, referencing the exact backend contract from PR #368. No fake or mock backend route is invented in production code.

## Integration boundaries
Do not edit `frontend/src/main.tsx`, `frontend/src/components/layout/Shell.tsx`, or `Sidebar` in this lane (owned by PR #370 / shell lanes). The dashboard exports `<OwnerPerformanceDashboard />` ready for mounting inside any view.

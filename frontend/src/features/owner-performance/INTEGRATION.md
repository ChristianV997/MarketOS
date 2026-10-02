# Owner performance dashboard (frontend slice)

Status: implemented, contract-tested, adapter-tested, unavailable by default. The performance-report endpoint remains unmounted, and canonical events are not requested in the owner view until workspace access is server-bound.

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

## Canonical event activity
The dashboard now contains an activity/freshness panel and a pure adapter for the existing `GET /api/events` response. The adapter uses a bounded first page (`limit=10`, `offset=0`), preserves each `event_id`, server response order, event `source`, read-only/advisory/dry-run qualifiers, and `authority_flags`, and labels freshness as applying only to that returned page. The current query service defaults to ascending event order, so offset 0 is the oldest page, not the newest activity. It adds no route, store, cursor, sorting, or financial calculation.

The route is mounted, but `api/routes/canonical_events.py` accepts an optional `workspace_id` selector without a server-verified principal or owner-workspace check; `RequestContextMiddleware` only adds request correlation/read-only metadata. The owner dashboard therefore does not call `fetchEvents`/`useEventRecords` or send an unscoped request. Its panel honestly remains `unavailable` until the canonical route enforces caller-bound workspace access. The adapter distinguishes an empty configured page from source warnings/unavailability; source labels are never promoted to live validation, and fixture/manual labels remain explicit.

## Backend dependency
`GET /api/owner/performance` is not yet mounted in the backend. The dashboard does not probe this absent route by default and remains in the `unavailable` phase. The reusable hook and adapter retain an explicit opt-in for the future mounted route, where they fail closed on 404/503, authentication errors, network failures, and contract violations. No fake or mock backend route is invented in production code.

## Integration boundaries
Do not edit `frontend/src/main.tsx`, `frontend/src/components/layout/Shell.tsx`, or `Sidebar` in this lane (owned by PR #370 / shell lanes). The dashboard exports `<OwnerPerformanceDashboard />` ready for mounting inside any view.

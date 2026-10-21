# Canonical Event Read Views

## Purpose

MarketOS operators can inspect advisory canonical events, timelines, Commerce
MVP runs, and Shopify read-only imports without adding a dashboard or a write
path. The query service is read-only and summarizes payload/metadata keys by
default instead of returning raw payload values.

## Sources

- **JSONL:** local CLI mode; no credentials. Supply an explicit `--jsonl` path.
- **Supabase staging:** server-side only; supply `--supabase-staging`. It needs
  `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`, but not the staging write
  gate. It never writes.

The FastAPI routes use JSONL only when the operator configures
`MARKETOS_EVENT_READ_JSONL_PATH` to a file beneath `artifacts/`. This avoids an
arbitrary local-file read parameter. Supabase keys are never accepted from a
request or returned in a response.

## CLI

```powershell
python scripts/query_canonical_events.py --jsonl artifacts/commerce-mvp-shopify-events.jsonl --timeline --markdown
python scripts/query_canonical_events.py --jsonl artifacts/commerce-mvp-shopify-events.jsonl --commerce-runs --json
python scripts/query_canonical_events.py --jsonl artifacts/shopify-readonly-events.jsonl --shopify-imports --markdown
python scripts/query_canonical_events.py --supabase-staging --workspace-id demo --limit 50 --json
```

Filters include workspace, event type, aggregate type/ID, correlation ID,
source, offset, limit, and ascending/descending deterministic ordering.

## API

GET-only routes are mounted at `/api/events`, `/api/events/timeline`,
`/api/events/commerce-runs`, `/api/events/shopify-imports`, and
`/api/events/readiness`. They contain no POST/PUT/PATCH/DELETE endpoint.

### Access contract

Every `/api/events` route is operator-only and workspace-bound through
`backend.identity.http.require_workspace_permission` with
`canonical_event:read` (shared dependencies in `api/routes/event_access.py`).
The other routes that read or write canonical event data use the same gate:
`/api/evaluations*` (bound workspace only), `POST /api/commerce-mvp/public-run`
(`canonical_event:write`, bound workspace only), `/api/workflows*` (the workflow
registry, bound workspace only; a foreign workflow answers as missing), the
phase1 readers `/api/phase1/readiness`, `/api/phase1/benchmark-matrix` and
`/api/phase1/public-market-benchmark` (operator-only; artifact locations are
reduced to names), and `/orchestration/workflows*` (fail closed: every caller that
passes the gate is refused, because the log cannot be bound to a workspace). Identity comes only from the verified bearer token and
the principal's stored membership; the query, headers and body cannot grant
access.

- A missing or invalid bearer token is 401. No token verifier or workspace
  repository is wired into this repository, so every route answers 503
  `identity_provider_unavailable` until deployment wiring supplies them.
- The principal's sole `internal` membership must carry `internal_operator`.
  No membership, several memberships, or any other role (including
  `client_viewer`) is 403 `workspace_not_authorized` or its specific code.
- The workspace is that membership's workspace. A `workspace_id` query value
  may repeat it; any other value, including an empty one, is 403. Headers
  such as `X-MarketOS-Workspace` do not select a workspace.
- Denied requests never load the JSONL file or call Supabase. Denials (401,
  403, 503) carry only a fixed `{"detail": {"code": ...}}`.
- Every route on these surfaces is throttled before identity, so anonymous and
  denied requests count toward `MARKETOS_EVENT_READ_RATE_LIMIT`. A throttled request answers
  429 with `Retry-After` and `{"detail": {"status": "rate_limited", ...}}`.
- Validation errors (422) echo the caller's own input, as FastAPI does.
  Configuration errors keep their short messages. None includes a path,
  payload or secret.

The readiness routes on these surfaces were open before this change and are now
operator-only. `/orchestration/health` carries no event data and stays open.

The workflow log routes (`/orchestration/workflows`, `/orchestration/workflows/incomplete`,
`/orchestration/workflows/{workflow_id}`) were open to any operator before this change.
They now pass the identity gate and then answer 403 `workspace_not_authorized`, without
reading the store, so no workspace can see another workspace's events or probe for a
workflow id. A same-workspace read is refused too: the store cannot attribute a record
to a workspace.

Not yet wired: serving the workflow log again needs trustworthy workspace attribution and a
workspace-scoped query in `backend/orchestration/event_store.py`. Neither exists today.
Most workflow producers (`backend/orchestration/workflow.py`, `transaction.py`, `adapter.py`,
`agents/hierarchy.py`, the `backend/commerce` modules) write no workspace. The records that do
carry `data.workspace_id` take it from the `workspace` string an unauthenticated caller passes
to `/api/services/*`: every commerce-service transition (`backend/experiments/audit_log.py`) and
the live-approval check (`backend/workspaces/live_mode_checklist.py`). `_resolve_workspace` in
`api/routes/services.py` also registers unknown names. A caller can therefore attribute
workflow records to any workspace. `backend/ledger/events.py` stamps a workspace but has no
production caller. Fixing `/api/services/*` identity and attribution is the owner's decision.

Status: implemented and integration-tested with synthetic principals in
`tests/integration/test_canonical_events_workspace_authz.py`. Not
live-validated. The frontend viewer (`frontend/src/lib/canonicalEventsApi.ts`)
sends no bearer token, so it cannot read these routes until identity wiring
lands.

## Safety and privacy

The views preserve canonical replay hashes and authority flags while exposing
payload/metadata summaries only. Shopify events were redacted before writing
and no raw Shopify PII is returned by these views. The service never creates,
updates, publishes, launches, spends, sends, fulfills, or pays.

The routes are read-only and operator-only, and a denied request reads nothing.

Rollback: revert the commit that adds this contract. That restores the
previous open reads, which must not be exposed on a network-reachable
deployment.

## Deployment next step

Deploy the FastAPI process server-side, configure one allowed JSONL artifact
path or a server-only Supabase staging connection, then use the minimal
read-only frontend viewer at `/operator/events`.

See `docs/OPERATOR_EVENT_DASHBOARD.md` for operator and deployment guidance.

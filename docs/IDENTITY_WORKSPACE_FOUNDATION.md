# Identity / workspace / durable-state foundation

Status: **implemented and unit/integration-tested on fixtures (SQLite stands in for Postgres); not deployed, not live-validated.**
Package: `backend/identity/`. Tests: `tests/identity/`. Two route families use it: `/api/organization/client-profile` and the credential-setup writes under `/api/setup` (both below). With no verifier or database configured both answer 503. No provider is configured.

## What it provides

| Piece | File | Behavior |
| --- | --- | --- |
| Verified principal | `principal.py` | `VerifiedPrincipal(issuer, subject)` only comes from a `TokenVerifier`. `ClerkSessionTokenVerifier` applies claim policy (`iss`, required `exp`, `nbf`, mandatory `azp` allowlist, `sub`) to claims returned by an **injected** signature check. |
| Workspace resolution | `workspaces.py` | Memberships are looked up by `(issuer, subject)` from the verified token. A client-supplied workspace id is only a selector among those memberships; names never select. Unknown and unauthorized workspaces return the same 403. |
| FastAPI dependencies | `http.py` | `require_principal` (401), `resolve_workspace_access` (403; 400 if several memberships and none named). Default `get_token_verifier` / `get_workspace_repository` fail closed with 503. |
| Durable store | `repository.py`, `migrations/0001_*` | DB-API repository (Postgres-targeted, `%s`) for memberships, the owner portfolio (`internal` workspaces) and operator-managed client profiles (`client_service`). |

Error mapping: missing/invalid identity 401 · unauthorized workspace 403 · ambiguous workspace 400 · constraint violation 409 · verifier/storage unavailable 503. Bodies carry only a stable `code`; tokens, claims and driver messages are never returned or logged.

## Contract for route authors (read-model integration)

```python
from backend.identity.http import resolve_workspace_access, install_identity_error_handlers
def handler(access: WorkspaceAccess = Depends(resolve_workspace_access)): ...
```

* Take identity **only** from `require_principal` and workspace scope **only** from `resolve_workspace_access`. Do not read a workspace id, name or user id from the query, body or other headers.
* Repository data methods take the resolved `WorkspaceAccess` and re-verify membership and workspace type in the database.
* Call `install_identity_error_handlers(app)` once so `StorageUnavailable` etc. raised inside handlers map to HTTP.
* Deployment wiring (not done here) supplies a real verifier and repository through `app.dependency_overrides` or equivalent.

## Client-profile API (`api/routes/client_profile.py`)

`GET | POST | PATCH /api/organization/client-profile`, registered in `backend/api.py` next to the organization router.

* **Workspace** is the principal's *only* `client_service` membership (`resolve_sole_workspace`). The `X-MarketOS-Workspace` header, query strings and body values are never read for identity; a body naming a workspace (`workspace_id`, `tenant_id`, `user_id`, ...) is rejected `422 workspace_selector_rejected`. Several client memberships fail closed `403 workspace_ambiguous` rather than being selectable.
* **Roles** (`roles.py`, stored on `workspace_members.role`, migration `0002`): `internal_operator` read/create/update, `client_viewer` read. A NULL, unknown or non-string role grants nothing (403). The repository re-reads the stored role; the role on the `WorkspaceAccess` object is not trusted.
* **Status codes:** 401 missing/invalid identity (checked before the body is parsed) · 403 no client membership / ambiguous / role not allowed · 404 no profile (GET, PATCH) · 409 `profile_exists` (POST) · 413/415/422 bounded validation with stable `{code, field}` bodies that never echo input · 503 verifier or database unconfigured or down, and any unexpected storage failure · 500 `profile_export_rejected` if a stored value fails the output screen.
* **Persistence** is the existing `client_profiles` / `client_profile_entries` tables (the "workspace profile" store). Fields: `company_name` (<=200), `business_type`, `segments` / `target_markets` / `offerings` (<=25 each, <=120 chars, case-insensitive unique), `social_accounts` (<=25 `{platform, handle}`, fixed platform list, handle pattern). PATCH replaces each supplied list wholesale.
* **Social accounts are metadata.** They are returned as `connection_state: "not_connected"` (stored as `record_only`). Credential-shaped keys (`token`, `password`, `secret`, `api_key`, ...) and any caller connection claim (`connection_state`, `connected`, `status`, ...) are rejected.
* **TrustOS:** requests and responses pass `check_workspace_leakage` from `evaluation/trustos/client_workspace_isolation.py`. `export_client_evidence` is *not* used: it requires a registration in the JSON `WorkspaceRegistry` (a second catalog, see blocker 4) and a fixed field allow-list that does not describe a profile. **Known cost:** the screen is substring-based, so legitimate text containing words such as "strategy", "token", "formula" or a leading "/" in values is rejected (422 on write, 500 on read of a stored value).
* The database role column is checked with the application's `role_grants`; `0002` is nullable so existing memberships have no role until an operator assigns one. There is still no route to assign roles or memberships.

## Operator runtime and commerce gates (`backend/identity/operator_gates.py`)

Mutating routes that drive the runtime loop, the global kill-switch, or commerce execution depend on `runtime_control_gate` or `commerce_execution_gate`. Each is `require_workspace_permission(OWNER_TYPE, <permission>)`, so the caller's sole `internal` membership must have a role that grants the permission.

* `runtime_control:write`, granted to `internal_operator` only: `POST /cycle`, `POST /runner/pause`, `POST /runner/resume` (`api/routes/cycle_control.py`), and `POST /risk/killswitch/activate` and `/deactivate` (`api/routes/agents_risk.py`).
* `commerce_execution:write`, granted to `internal_operator` only: `POST /commerce/cycle`, `POST /commerce/provider-cycle`, `POST /commerce/publish`, and `POST /integrations/postiz/analytics/reconcile` (`backend/api.py`).
* A refused request runs no handler code, so it makes no side effect and no outbound call: anonymous is 401, `client_viewer` or any role without the permission is 403, and no configured verifier or repository is 503. `tests/identity/test_runtime_control_gates.py` checks each refusal with recorders on every side-effect seam, and checks one authorized operator call per route with the effect stubbed.
* Like the credential routes, these answer 503 in every deployment today, because no verifier or repository is wired. The frontend's command controls (`/cycle`, `/runner/*`, `/risk/killswitch/*`) send no identity and fail closed until a deployment wires one. The CI container smoke asserts that an anonymous `POST /commerce/cycle` gets 503.

## Credential-setup API (`api/credentials_setup.py`)

`POST /api/setup/credentials/set` and `POST /api/setup/test/{service}`, mounted by `backend/api.py` under `/api/setup`. The read-only `GET /api/setup/credentials/status` and `GET /api/setup/instructions[/{service}]` stay unauthenticated: they return booleans and static text only, and no value, path or exception text.

* **Who:** the principal's *only* `internal` (owner) workspace membership (`require_workspace_permission(OWNER_TYPE, ...)`) whose stored role is `internal_operator`. `roles.py` adds `setup_credential:write` and `setup_credential:test`, granted to `internal_operator` only. `client_viewer`, a NULL or unknown role, a membership in a `client_service` workspace only, no membership, and several internal memberships all fail closed 403. Nothing in the body, query or other headers is read for identity, and a body naming a caller, workspace or role (`actor`, `user_id`, `role`, `workspace_id`, ...) is rejected `422 identity_field_rejected`.
* **Order:** 401/403/503 are decided by the route dependencies before the handler reads the body, so a denied caller's body is never parsed and credential storage is never reached. The body is then read with the client-profile pattern (`application/json` only, else 415; at most 16 KiB, else 413; invalid JSON, 422). Every error body is a fixed `{code, field}` and never echoes the submitted key, value, field names, service name, exception text or a path.
* **Writes:** only provider credential keys (`backend.config._SERVICE_CREDENTIALS`) are accepted, never `*_DRY_RUN` flags or arbitrary environment names. A value is non-empty, at most 4096 characters, free of control characters, and has no leading or trailing whitespace. It is never logged or returned. `backend.config.set_credential` swallows write errors, so the route reads the credentials file back and answers `500 credential_store_failed` unless it holds the value (an environment variable of the same name cannot mask a failed write). Stable error bodies, like successful responses, carry `Cache-Control: no-store`; gate denials from the identity dependencies do not.
* **Provider test:** never calls a provider helper. A service in dry-run reports `dry_run`. A service in live mode reports `blocked`, because no server-side approval seam exists yet. Any future live verification must go through the Approval Ledger (`evaluation/companyos/approval_ledger.py`) under a new, separately reviewed permission.
* **Onboarding:** `api/onboarding.py`'s `verify-credential` route (no application mounts that router) uses the same gates and helpers, accepts a credential key only under its own service (`400 key_service_mismatch`), and counts a service as configured only when it is live-but-blocked. Its other write routes are *not* gated. `tests/identity/test_credentials_setup_gate.py` fails if any write operation under `/api/setup` or `/api/onboarding` that the production app publishes answers an anonymous caller with anything other than an identity denial, so mounting that router ungated is caught.
* **Provisioning:** an internal operator is an `internal` workspace membership with role `internal_operator`, created by `add_member` (an operator/bootstrap action; there is still no route). Until a verifier and repository are wired in, these two routes answer 503 for everyone, so credentials are set locally with `backend/cli_setup.py`.
* **Status: a fail-closed seam, not an operational login.** `backend/api.py` installs no token verifier and no workspace repository, so both POST routes answer 503 `identity_provider_unavailable` for every caller in every deployment today. `tests/identity/test_credentials_setup_gate.py` drives the *production* application object (its CORS and request-context middleware included) with the canonical `ClerkSessionTokenVerifier` claim policy, a real `PostgresWorkspaceRepository` over SQLite and the documented `app.dependency_overrides` seam. That proves the request path (401 for unverifiable, expired, wrong-issuer, wrong-party and revoked tokens; 503 for unavailable keys or store; 403 for every unauthorized membership, including a membership held under another issuer; role and membership changes effective on the next request; nothing sensitive in responses or logs). It is fixture-only: the signature check there verifies nothing cryptographically. The application lifespan is not run in tests (it starts background cycle threads and writes runtime state).
* **Blocker before these routes can work in a deployment** (nothing below was invented here): (1) a signature/JWKS check to inject into `ClerkSessionTokenVerifier`, with the issuer and authorized-party configuration it requires, since no JWT/crypto library is declared in any requirements file; (2) a DB-API connection factory and driver for `PostgresWorkspaceRepository` (no driver or DSN convention is declared, and nothing applies migrations `0001`/`0002`); (3) one reviewed wiring call that sets `app.dependency_overrides[get_token_verifier]` and `[get_workspace_repository]` (and calls `install_identity_error_handlers(app)`) only when that configuration is complete, leaving the 503 defaults otherwise; (4) a bootstrap path that creates the first `internal_operator` membership. Until all four exist, keep using `backend/cli_setup.py`.

## Schema (additive, `0001_identity_workspace_foundation`)

`workspace_identity`, `workspace_members`, `owner_portfolio_items`, `client_profiles`, `client_profile_entries`, plus `.down.sql` and a Postgres-only `.rls.sql` (RLS on, no policies, matching `deploy/supabase/schema.sql`).

**Operator note:** on a database with a public data API (e.g. Supabase `public` schema) the `.rls.sql` file **must** be applied right after `.up.sql`; the portable `.up.sql` alone leaves these tables, including `workspace_members`, readable through that API. Nothing in this repo applies either file automatically.

* **Prerequisite:** the existing `workspaces` table from `deploy/supabase/schema.sql`. The migration never creates, alters or drops it, so there is one workspace catalog in Postgres.
* Owner data can only attach to `internal` workspaces and client data only to `client_service` workspaces (composite FK + CHECK). `workspace_type` reuses `backend.workspaces.client_workspace.WORKSPACE_TYPES`.
* `evidence_label` has no live/measured value. Client social accounts are `connection_state = 'record_only'` by constraint. No `ON DELETE CASCADE`.

## Not done / blockers (do not treat as available)

1. **Signature verification is not implemented.** No JWT/RSA library is declared in `requirements*.txt` (the system PyJWT here cannot import its `cryptography` backend), and JWKS retrieval is an outbound HTTPS call to the Clerk frontend API that needs its own approval, caching and key-rotation design. Production must supply the `signature_verifier` callable.
2. **Clerk-specific facts are only partly verified.** Direct fetches of `clerk.com` were blocked by the egress proxy; the claim policy follows search-result summaries of Clerk's manual-verification guide (validate `exp`/`nbf`, validate `azp` against known origins, check algorithm and signature against the instance JWKS). **Unverified:** session-token lifetime, exact signing algorithm, `sid`, header-vs-cookie delivery for cross-origin calls, and whether every legitimate token carries `azp` (tokens without it are rejected by design).
3. **No Postgres driver is declared** (only stdlib `sqlite3` and the `supabase` client). The repository is DB-API and needs an operator-supplied `connect` factory. The SQL and migration were exercised on SQLite (`qmark`) and through a recording fake for the `%s` path; **they have not been run on a Postgres server**, nor has the RLS file.
4. **Two workspace catalogs still exist.** The JSON `WorkspaceRegistry` (`state/workspaces.json`, name-derived ids, `by_name`) is unchanged and is not written through. Deciding which catalog owns `workspace_id`s, and bridging consumers of `ClientWorkspace`, is a follow-up. New ids should be `new_workspace_id()` (random), never name-derived.
5. Membership provisioning (`create_workspace`, `add_member`) is an operator/bootstrap action with no route; there is deliberately no first-login auto-provisioning. Roles beyond the two profile roles, delete flows, role/membership management routes, webhooks and any client-facing login are out of scope.

## Rollback

Credential-setup gates: revert the commit that added `setup_credential:*` to `roles.py` together with `api/credentials_setup.py`, `api/onboarding.py` and `tests/identity/test_credentials_setup_gate.py`. That restores the previous unauthenticated routes, which must not be exposed on a network-reachable deployment.

Migration `0002` (member roles): run `0002_workspace_member_roles.down.sql` (drops only `workspace_members.role`; assigned roles are lost, memberships stay). It adds no table, so the RLS file needs no change. Then, to remove everything: delete the two `include_router` lines in `backend/api.py`, `api/routes/client_profile.py`, `backend/identity/`, `tests/identity/` and this file. If `0001` was applied (after `0002` down) to a database, run `0001_identity_workspace_foundation.down.sql` (drops only the five new tables; `workspaces` is untouched) after taking a backup, since their rows are lost.

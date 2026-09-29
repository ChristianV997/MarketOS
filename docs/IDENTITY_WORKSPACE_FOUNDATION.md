# Identity / workspace / durable-state foundation

Status: **implemented and unit/integration-tested on fixtures; not wired, not deployed, not live-validated.**
Package: `backend/identity/`. Tests: `tests/identity/`. No route is mounted; no provider is configured.

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

## Schema (additive, `0001_identity_workspace_foundation`)

`workspace_identity`, `workspace_members`, `owner_portfolio_items`, `client_profiles`, `client_profile_entries`, plus `.down.sql` and a Postgres-only `.rls.sql` (RLS on, no policies, matching `deploy/supabase/schema.sql`).

* **Prerequisite:** the existing `workspaces` table from `deploy/supabase/schema.sql`. The migration never creates, alters or drops it, so there is one workspace catalog in Postgres.
* Owner data can only attach to `internal` workspaces and client data only to `client_service` workspaces (composite FK + CHECK). `workspace_type` reuses `backend.workspaces.client_workspace.WORKSPACE_TYPES`.
* `evidence_label` has no live/measured value. Client social accounts are `connection_state = 'record_only'` by constraint. No `ON DELETE CASCADE`.

## Not done / blockers (do not treat as available)

1. **Signature verification is not implemented.** No JWT/RSA library is declared in `requirements*.txt` (the system PyJWT here cannot import its `cryptography` backend), and JWKS retrieval is an outbound HTTPS call to the Clerk frontend API that needs its own approval, caching and key-rotation design. Production must supply the `signature_verifier` callable.
2. **Clerk-specific facts are only partly verified.** Direct fetches of `clerk.com` were blocked by the egress proxy; the claim policy follows search-result summaries of Clerk's manual-verification guide (validate `exp`/`nbf`, validate `azp` against known origins, check algorithm and signature against the instance JWKS). **Unverified:** session-token lifetime, exact signing algorithm, `sid`, header-vs-cookie delivery for cross-origin calls, and whether every legitimate token carries `azp` (tokens without it are rejected by design).
3. **No Postgres driver is declared** (only stdlib `sqlite3` and the `supabase` client). The repository is DB-API and needs an operator-supplied `connect` factory. The SQL and migration were exercised on SQLite (`qmark`) and through a recording fake for the `%s` path; **they have not been run on a Postgres server**, nor has the RLS file.
4. **Two workspace catalogs still exist.** The JSON `WorkspaceRegistry` (`state/workspaces.json`, name-derived ids, `by_name`) is unchanged and is not written through. Deciding which catalog owns `workspace_id`s, and bridging consumers of `ClientWorkspace`, is a follow-up. New ids should be `new_workspace_id()` (random), never name-derived.
5. Membership provisioning (`create_workspace`, `add_member`) is an operator/bootstrap action with no route; there is deliberately no first-login auto-provisioning. Roles beyond membership, update/delete flows, webhooks and any client-facing login are out of scope.

## Rollback

Delete `backend/identity/`, `tests/identity/` and this file. If `0001` was applied to a database, run `0001_identity_workspace_foundation.down.sql` (drops only the five new tables; `workspaces` is untouched) after taking a backup, since their rows are lost.

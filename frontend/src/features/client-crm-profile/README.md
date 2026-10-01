# Client CRM profile onboarding (frontend slice)

Status: **wired to `/api/organization/client-profile` through a same-origin API
client, mocked-network tested and browser-checked in a throwaway harness. NOT
verified against a real backend: the endpoint and its schema are not in this
repository. Not live validated.**

A guided, client-facing company profile: company identity and business type
(service B2C, service B2B, product), categories / segments / target markets,
products or services (with inventory details for product businesses), and social
account **details** (plain handles and links), then a review step that lists
anything missing. It is separate from the owner dashboard: no owner navigation and
no shared state with the operator surfaces.

## Server contract (ASSUMED shape)

`ClientProfileOnboardingPage` (default source `"server"`) calls one same-origin
endpoint with `credentials: "same-origin"`:

| Method | When | Success |
|---|---|---|
| `GET` | on page load | `200` with the profile; `404` = no saved profile yet (create mode) |
| `POST` | first save, while GET returned 404 | `200`/`201` with the profile, or `204` |
| `PATCH` | every later save (and when GET returned a profile) | `200` with the profile, or `204` |

Request and response bodies use the `client-profile-draft-v0` shape in
`contracts/clientProfileDraft.ts`. **That shape is an assumption**: the backend
contract was not available. If it differs, change only `lib/clientProfileApi.ts`
and `lib/serverProfile.ts`. A 2xx reply whose body is not a valid profile
(including any account claiming a status other than `not_connected`) is treated as
`malformed_response`, never as success.

Failures are separate codes with separate wording, for both load and save:
`401` unauthenticated, `403` forbidden, `404` not_found (save), `409` conflict,
`503` unavailable, `400`/`422` validation, a 2xx that cannot be trusted
(`malformed_response`), a request that got no response (`network`), anything else
`unknown`. Raw server text is never shown. "Profile saved" appears only after a
trustworthy 2xx and only while the form still matches what was sent.

If the initial GET fails (anything but 404) the form is not shown at all, because
the page cannot tell whether a profile exists; it shows the failure and a retry.

## Demo vs server

`source="server"` is the default and what the routes mount. `source="demo"` shows
fictional sample data, makes no request and stores nothing; it is selected only by
the code that mounts the page. **No URL parameter, stored value or user-picked id
selects fixture vs live data or a tenant.** Demo is labelled "fictional demo data:
not observed, not saved and not connected".

## Identity and tenant safety

* The contract and the UI have **no workspace, tenant, client or owner id** field.
  A value the user types or selects must never decide whose profile this is; the
  server must derive it from the authenticated session.
* The server decides whose profile this is from the session cookie. The URL,
  headers and body contain no workspace, tenant or client identifier, and the page
  keeps no tenant state (`lib/clientProfileApi.ts` is the only network code; an AST
  test enforces that).
* `ClientProfileWizard` takes an `onSave` function; the container supplies the API
  client. "Saved" is shown only after it resolves and only while the form still
  equals what was saved.

## Saved profile vs connected account

Social accounts are details only. The payload's only representable link state is
`link_status: "not_connected"`, every account carries a "Details only. Not
connected." badge, and the review shows two separate panels ("Saved profile" and
"Connected external accounts: Nothing connected by this page"). The form rejects
credential-shaped text (passwords, tokens, API keys, secret query values,
credentials in URLs) instead of storing it. There is no connect, verify,
publish, message or billing code path.

## Business type behaviour

Switching type is non-destructive in the form: everything typed is kept. Only the
fields that apply are validated, shown in the review and sent (services need a
delivery mode; products need availability and may have SKU and self-reported,
unverified units; an empty quantity is `null`, never `0`).

## Files

`contracts/` draft schema and copy per type; `lib/` pure logic (validation, secret
detection, tags, payload, wizard reducer, save runner); `hooks/useProfileWizard.ts`;
`components/` fields, chip input, five steps; `ClientProfileOnboardingPage.tsx`
(default export); `fixtures/sampleProfile.ts` (fictional data).
Tests: `frontend/tests/client-crm-profile/` (with a test-only loader built on the
repo's own `typescript`; no new dependency).

## Remaining backend dependencies

1. The authenticated, tenant-scoped `/api/organization/client-profile` GET/POST/PATCH
   endpoint with a published schema; replace the assumed shape if it differs.
2. A sign-in path for the `unauthenticated` case (this page only reports it).
3. CSRF protection for cookie-authenticated POST/PATCH is the server's job.
4. Until 1 is integrated nothing here has run end to end.

# Client CRM profile onboarding (frontend slice)

Status: **implemented, unit/component tested, browser-checked in a throwaway
harness (not in CI), NOT mounted, NOT connected to any API, NOT live validated.**

A guided, client-facing company profile: company identity and business type
(service B2C, service B2B, product), categories / segments / target markets,
products or services (with inventory details for product businesses), and social
account **details** (plain handles and links), then a review step that lists
anything missing. It is separate from the owner dashboard: no owner navigation,
no shared state with the operator surfaces, and it loads nothing.

## Persistence: demo mode by default

Verified on main when this was written:

* there is no client-profile endpoint;
* there is no authentication or session identity in `api/` or `backend/api.py`;
* `api/onboarding.py` is an in-memory store-setup wizard keyed by a client-supplied
  session id (not a client profile, not tenant-scoped);
* `ClientWorkspace` has no profile fields and derives `workspace_id` from its name.

So the page runs in **demo mode**: it is labelled, stores nothing, sends nothing,
loads no real client information, and its confirm button says "demo, not saved".
`contracts/clientProfileDraft.ts` is therefore a *frontend-proposed draft*
(`client-profile-draft-v0`), not a canonical schema. When a backend contract
exists it replaces this file.

## Identity and tenant safety

* The contract and the UI have **no workspace, tenant, client or owner id** field.
  A value the user types or selects must never decide whose profile this is; the
  server must derive it from the authenticated session.
* `onSave` is the only persistence seam. A host passes it **only** when saving goes
  through authenticated, tenant-scoped storage. Passing it switches the page from
  demo to save wording; "saved" is shown only after the promise resolves and only
  while the form still equals what was saved.
* Save failures are shown as short codes (`ProfileSaveError`); raw error text is
  never displayed.

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

## Not mounted: integration dependencies

1. A **client** route group with its own layout that supplies a `<main>` landmark.
   Do not mount inside the owner `Shell`/Sidebar (owner navigation and operator
   state would appear next to client data).
2. Authenticated, tenant-scoped profile API (create/read/update) owned by the
   backend, with the schema above replaced by the canonical one.
3. A host that passes `onSave` mapping HTTP outcomes to `ProfileSaveError` codes,
   and a sign-in path for the `unauthenticated` case.
4. A load path (initial profile) with explicit loading and error states; not built
   because there is nothing to load from.

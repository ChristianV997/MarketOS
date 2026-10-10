# Client CRM profile onboarding (frontend slice)

Status: **the mounted routes (`/client/profile`, `/client/onboarding`, `/crm`) run
the offline demo and make no network request.** A live path exists in code, aligned
to the merged backend contract (`api/routes/client_profile.py`), but it is only
mocked-network tested: no code in this repository issues the bearer tokens it
needs, so it has never run against a real server. **Not live validated. Not
production CRM persistence.**

A guided, client-facing company profile: company identity and business type
(service B2C, service B2B, product, other), categories / segments / target markets,
products or services, and social account **details** (plain handles), then a
review step that lists anything missing. It is separate from the owner dashboard:
no owner navigation and no shared state with the operator surfaces.

## Demo vs live

`ClientProfileOnboardingPage` is the **offline demo unless the mounting code passes
`getAccessToken`**: fictional sample data, no request, nothing stored, a persistent
"Demo mode. Nothing is saved or sent" banner. `main.tsx` passes none, because
nothing in this repository signs a client in or issues a token. **No URL parameter,
stored value or user-typed value selects live vs demo, a token, or a workspace.**

With `getAccessToken` the page loads the profile (GET), and saves with POST while
none exists, PATCH after.

## Server contract (merged backend, `api/routes/client_profile.py`)

| Method | When | Success |
|---|---|---|
| `GET` | on page load | `200` profile; `404 profile_not_found` = no saved profile (create mode) |
| `POST` | first save | `201` with the stored profile |
| `PATCH` | later saves | `200` with the stored profile |

Auth is `Authorization: Bearer <token>` from the injected provider, read per request
and never stored, logged or typed in this feature; `credentials: "omit"` keeps
cookies out. With no provider, a blank token, or a provider that throws, **no
request is sent** and the result is `unauthenticated`. The workspace is resolved
server-side from the token's sole `client_service` membership and role; the URL,
headers and body carry no workspace, tenant, user or client identifier (the server
rejects a body that does).

The service **stores only**: company name, business type (`service_b2c`,
`service_b2b`, `product`, `other`), segments, target markets, offering **names**
(max 25, no duplicates) and social `{platform, handle}` (handles `A-Za-z0-9._`,
always reported `not_connected`). `lib/toServerBody.ts` sends exactly those keys.
**Stays in the browser tab only, never sent:** categories, offering descriptions,
delivery, availability, SKU and units on hand, social links and notes, and any
social account entered without a handle. The review step lists these under
"Stays in this tab only", and a loaded profile starts those fields empty. They
are optional because the service cannot keep them.

A 2xx whose body is not a valid stored profile (wrong types, over-limit lists, an
account claiming anything but `not_connected`, a 204/202) is `malformed_response`,
never success. Failures have separate codes and wording for load and save: `401`,
`403`, `404`, `409`, `503`, `400/413/415/422` validation, malformed, `network`,
`unknown`. Raw server text is never shown. "Profile saved" appears only after a
trustworthy `200/201` and only while the fields the service stores still match
what was sent. If the initial GET fails (anything but 404) the form is not shown.

## Saved profile vs connected account

Social accounts are details only. Every account carries a "Details only. Not
connected." badge and the review shows "Connected external accounts: Nothing
connected by this page". The form rejects credential-shaped text (passwords,
tokens, API keys, secret query values, credentials in URLs). There is no connect,
verify, publish, message or billing code path.

## Layout and accessibility

`ClientShell` provides the single `<main>`, makes no isolation claim (isolation is
the server's job), moves focus to `<main>` on client route changes and sets a
client document title. The wizard has one live region, an error summary that takes
focus, labelled fields with `aria-describedby`/`aria-invalid`, 44px targets and a
failed-save message next to Confirm.

## Files

`contracts/` form model and copy per type; `lib/` pure logic (validation, secret
detection, tags, local payload, `toServerBody`, `serverProfile` parser, API client,
session, wizard reducer, save runner); `hooks/`; `components/`;
`ClientProfileOnboardingPage.tsx` (default export); `fixtures/sampleProfile.ts`
(fictional data). Tests: `frontend/tests/client-crm-profile/` (test-only loader
built on the repo's own `typescript`; no new dependency).

## Remaining dependencies

1. A client sign-in that issues bearer tokens the profile service verifies
   (`get_token_verifier`), and a host that passes `getAccessToken`; until then the
   routes stay demo.
2. A deployed profile service with storage; until then nothing here has run end to
   end.
3. If the stored fields should grow (categories, offering details, links), that is
   a backend schema change; this client would then drop the matching "tab only" item.

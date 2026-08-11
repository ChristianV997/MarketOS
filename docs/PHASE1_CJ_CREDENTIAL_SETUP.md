# Phase 1 CJ Read-Only Credential Setup

This guide prepares an operator to validate the already-implemented CJ
catalog evidence path. It does not enable ordering, fulfillment, payment,
inventory writes, publishing, messaging, or any other provider mutation.

## Before you begin

Use an operator-owned CJ developer account and obtain the credentials required
by the current CJ API token flow. CJ's API v2 documentation lists a token
endpoint and separate product and stock GET endpoints; confirm current account
eligibility, terms, rate limits, and field availability in the official docs
before use. [CJ API v2](https://developers.cjdropshipping.com/en/api/api2/)
and [product API reference](https://developers.cjdropshipping.com/en/api/api2/api/product.html).

MarketOS requires only these server-side values:

| Variable | Purpose | Commit/browser policy |
|---|---|---|
| `MARKETOS_SUPPLIER_PROVIDER` | Selects the implemented provider; set to `cj`. | Safe server configuration; never browser-controlled. |
| `MARKETOS_SUPPLIER_AUTH_READONLY` | Explicitly enables the CJ read-only adapter; set to `1` only for a planned probe. | Safe server configuration; defaults to `0`. |
| `CJ_EMAIL` | CJ account email used by the existing token exchange. | Secret; never commit or expose to a browser. |
| `CJ_API_KEY` | CJ developer API key used by the existing token exchange. | Secret; never commit or expose to a browser. |

The adapter only permits catalog, product-detail, and stock GET endpoints. It
rejects order, payment, fulfillment, inventory mutation, publishing, and
customer-message paths before a request is made.

## Local Windows PowerShell

Do not paste real values into committed files. Set them only in the current
PowerShell session or a local ignored environment file:

```powershell
$env:MARKETOS_SUPPLIER_PROVIDER = "cj"
$env:MARKETOS_SUPPLIER_AUTH_READONLY = "1"
$env:CJ_EMAIL = "<operator-owned CJ account email>"
$env:CJ_API_KEY = "<operator-owned CJ API key>"

python scripts/check_phase1_supplier_readonly_access.py --provider cj --json
python scripts/check_phase1_supplier_readonly_access.py --provider cj --allow-network --json
```

The first command verifies configuration without network I/O. The second is a
single bounded, read-only catalog probe; run it only after confirming the
account and credentials are appropriate for this environment.

If this repository's `.env.example` convention is used locally, copy it to an
ignored `.env` file and populate values there. Do not load a real `.env` into a
frontend build, commit it, attach it to an issue, or paste it into terminal
output.

## Railway or other server runtime

Add the same four values through the platform's encrypted server-side
environment configuration. Do not set `CJ_EMAIL` or `CJ_API_KEY` as Vercel
`VITE_*` values and do not expose them in client-side configuration. Keep the
read-only gate at `0` except for an explicit operator validation window.

Vercel hosts the frontend and must never receive CJ credentials. If a Railway
backend runs the probe, only that backend receives the secrets.

## Run the full validation after a successful probe

```powershell
python scripts/run_phase1_live_validation.py `
  --supplier-source authenticated_readonly `
  --allow-authenticated-supplier `
  --query "portable espresso maker" `
  --allow-network `
  --markdown `
  --timestamp cj-auth-readonly-live
```

Add the documented competitor URLs only when intentionally measuring the
combined supplier/competition run. Public JS competitor rendering remains
separately optional and domain-allowlisted.

## Status interpretation

| Status | Meaning | Operator action |
|---|---|---|
| `credential_missing` | One or both CJ secrets are absent. | Set them only server-side, then rerun configuration preflight. |
| `live_flag_disabled` | Credentials exist but the adapter gate is off. | Set `MARKETOS_SUPPLIER_AUTH_READONLY=1` only for the approved read-only probe. |
| `network_gate_required` | Configuration is ready but `--allow-network` was omitted. | Review scope, then explicitly pass the flag. |
| `provider_mismatch` | The selected provider is not `cj`. | Set `MARKETOS_SUPPLIER_PROVIDER=cj`; Zendrop is not implemented here. |
| `provider_failed` | Auth, endpoint, response, or network request failed. | Record the redacted status and consult CJ docs/account access; do not retry aggressively. |
| `no_results` | The API responded but did not return a matching product. | Refine the query; no price or inventory is inferred. |
| `observed` | One or more catalog fields were normalized with provenance. | Run the evaluation report; observed evidence is advisory, not launch authority. |

## Safety boundary

Every output remains read-only, advisory, non-authoritative, and replayable.
Canonical events contain normalized evidence and provenance, never the raw CJ
authentication request, access token, API key, or full provider payload. A
successful read-only observation does not prove demand, supplier viability,
profitability, delivery performance, ROAS, or launch readiness.

# Phase 1 Authenticated Read-Only Supplier Evidence

## Decision

The selected implementation path is **Path A: CJ Dropshipping read-only API**.
Public CJ pages remain insufficient after the CPython 3.12 JS benchmark, while
the official CJ REST documentation exposes concrete catalog, product-detail,
variant, and stock GET endpoints. MarketOS reuses the existing
`backend.validation.suppliers.CJDropshippingClient` token boundary and adds a
small allowlisted evidence adapter; it does not create a second CJ client.

| Provider | Access method | Product fields | Inventory | Shipping | Variants/SKUs | Credential friction | Runtime fit | Safety | Phase 1 decision |
|---|---|---|---|---|---|---|---|---|---|
| CJ Dropshipping | Authenticated REST token, GET only | title, price, currency, SKU, weight, images when returned | documented stock GET | available in API family but not used by this slice | product/variant query and SKU fields | CJ account plus server env credentials | concrete existing Python client | endpoint allowlist, explicit flags, no mutation methods | **implement now** |
| Zendrop | MCP endpoint with token/OAuth and `catalog:read` | catalog/product detail, variants and price described | less concrete in repo-runtime docs | described, tool details less concrete | catalog variants described | token/OAuth2 PKCE and MCP host | external MCP-oriented fit | read-only scope is possible but runtime contract is less settled | evaluate next |

Sources: [CJ API v2.0](https://developers.cjdropshipping.com/en/api/api2/), [CJ Product API](https://developers.cjdropshipping.com/en/api/api2/api/product.html), and [Zendrop MCP developer documentation](https://support.zendrop.com/en/articles/14461568-zendrop-mcp-developer-documentation). Verify current endpoint behavior, account requirements, rate limits, and pricing before production use.

## Safety and configuration

The adapter is unavailable by default. A live call requires all of:

- `MARKETOS_SUPPLIER_PROVIDER=cj`;
- `MARKETOS_SUPPLIER_AUTH_READONLY=1`;
- `CJ_EMAIL` and `CJ_API_KEY` supplied server-side; and
- an explicit CLI/API `--allow-network` or equivalent operator gate.

Secrets are presence-tested only. They are never put into events, reports,
logs, browser configuration, or exception text. The adapter can only call
`/product/list`, `/product/query`, `/product/stock/queryByVid`, and
`/product/stock/queryBySku`.

Orders, payments, fulfillment, inventory mutation, publishing, and supplier
messages are outside the adapter. No authenticated probe is attempted by CI
or by default. `scripts/check_phase1_supplier_readonly_access.py` returns
`credential_missing`, `live_flag_disabled`, `network_gate_required`,
`provider_mismatch`, `provider_failed`, `no_results`, or `observed` without
turning missing configuration into an exception.

## Evidence contract and precedence

The adapter normalizes to the existing `CJProductEvidence` record. A field is
`observed` only when the provider payload supplies it. Missing price, stock,
shipping, dimensions, or SKU remain `unavailable`; no landed-cost estimate is
invented. Authenticated evidence is labeled `authenticated_readonly_api` and
has no-authority metadata on canonical events.

Commerce economics precedence is:

1. authenticated observed supplier evidence;
2. public observed supplier evidence;
3. explicit operator assumptions;
4. unknown/unavailable.

Only an observed authenticated price can replace the unit-cost assumption in
the existing economics path. Shipping remains an assumption unless the
selected adapter is later extended with a documented read-only freight
contract.

## Commands

Readiness only, no network:

```powershell
python scripts/check_phase1_supplier_readonly_access.py --json
```

Fixture-backed normalization is covered by tests. A credentialed operator
probe, when explicitly approved and configured, is:

```powershell
$env:MARKETOS_SUPPLIER_PROVIDER = "cj"
$env:MARKETOS_SUPPLIER_AUTH_READONLY = "1"
python scripts/check_phase1_supplier_readonly_access.py --provider cj --allow-network --json
```

The live validation harness can select the path without changing its default:

```powershell
python scripts/run_phase1_live_validation.py `
  --supplier-source authenticated_readonly `
  --allow-authenticated-supplier `
  --query "portable espresso maker" `
  --allow-network --markdown
```

The command intentionally reports `credential_missing` when credentials are
absent. It does not fall back to public CJ credentials, scrape a login page, or
attempt an order.

For an operator-safe first live check, use the
[CJ Live Validation Pack](PHASE1_CJ_LIVE_VALIDATION_PACK.md). Its default
mode is offline configuration preflight; its explicit live mode limits the
authenticated catalog search to one candidate, sanitizes all generated
artifacts, and evaluates the result against an optional public/JS baseline.

## Evaluation and operations

While credentials are unavailable, the offline Supplier Feasibility Intelligence
slice can consume sanitized CJ-style or manual supplier snapshots. It provides
cost, landed-cost, logistics, inventory, MOQ, and break-even scenarios without
claiming authenticated supplier proof. Run
`python scripts/run_supplier_feasibility_intelligence.py --markdown` before
requesting the one bounded credentialed validation.

Evaluation reports now separate `public_page_static`, `public_page_js`,
`authenticated_readonly_api`, `fixture`, and `unavailable` supplier sources.
They expose authenticated attempt/success counts, source distribution,
observed price/inventory/shipping/SKU/variant rates, credential-missing
counts, and disabled-gate counts. Compare a public run and an authenticated
run with the existing `scripts/evaluate_commerce_run.py` comparison command;
the result is evidence coverage, not a launch or profitability decision.

`GET /api/events/readiness` exposes redacted supplier-auth readiness. It does
not expose credentials. Canonical supplier events remain replayable and
advisory; JSONL remains the default persistence target and Supabase staging is
still separately opt-in.

For a single operator-facing readiness answer across supplier, competition,
evaluation, events, and safety, use the read-only
[Phase 1 Readiness Cockpit](PHASE1_READINESS_COCKPIT.md). It reports missing
credentials as a gate and never reads their values.

## Known limitations and next step

This PR is fixture-tested and configuration-tested, not live credential-
validated in this environment. Current field mapping intentionally covers
catalog/detail/variant/stock observations and leaves shipping/logistics
estimates unavailable. Confirm the official account, rate-limit, warehouse,
and endpoint requirements with an operator-owned CJ account before a single
read-only probe. If that probe fails or returns no product data, compare the
structured failure with Zendrop's documented `catalog:read` MCP path before
adding any further integration.

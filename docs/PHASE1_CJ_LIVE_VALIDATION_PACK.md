# Phase 1 CJ Read-Only Validation Pack

## Purpose

`scripts/run_phase1_cj_readonly_validation_pack.py` is the operator-facing,
credential-safe path for one bounded CJ catalog validation. It composes the
existing CJ read-only adapter, Phase 1 validation harness, canonical events,
and Commerce Evaluation Framework; it does not add a second client, parser,
event system, or scoring path.

The pack is advisory and read-only. It cannot create products or orders,
change inventory, capture a payment, publish, fulfill, message a customer,
or invoke Shopify. It never stores authentication headers, provider response
bodies, browser traces, or credential values.

## Offline-first workflow

The default command performs configuration inspection only. It does not call
CJ, competitor pages, or any other network source:

```powershell
python scripts/run_phase1_cj_readonly_validation_pack.py --json
```

It produces a redacted `preflight_report.json` and
`validation_pack_report.json` below
`artifacts/phase1_cj_readonly_validation/<timestamp>/`. Typical next actions
are deterministic:

| Status | Next action |
|---|---|
| `credential_missing` | `set_credentials` |
| `live_flag_disabled` | `enable_readonly_flag` |
| `network_gate_required` | `rerun_with_allow_network` |
| auth/provider failure | `fix_auth` or `check_cj_account_permissions` |
| observed normalized evidence | `record_live_supplier_success` or `ready_for_phase1_live_results` |

## One bounded live probe

Only run this after an operator has configured the server-side variables in
[PHASE1_CJ_CREDENTIAL_SETUP.md](PHASE1_CJ_CREDENTIAL_SETUP.md). The explicit
network flag is a second confirmation; the pack does not make a preliminary
live probe and then a second validation request. It delegates exactly one
bounded authenticated candidate search to the existing harness with
`--max-authenticated-supplier-candidates 1`.

```powershell
$env:MARKETOS_SUPPLIER_PROVIDER = "cj"
$env:MARKETOS_SUPPLIER_AUTH_READONLY = "1"
$env:CJ_EMAIL = "<set locally; never commit>"
$env:CJ_API_KEY = "<set locally; never commit>"

python scripts/check_phase1_supplier_readonly_access.py --provider cj --json
python scripts/run_phase1_cj_readonly_validation_pack.py `
  --provider cj `
  --query "portable espresso maker" `
  --allow-network `
  --markdown
```

The pack limits the catalog candidate count to one. The existing allowlisted
CJ adapter may make its documented GET detail/stock reads for that one result;
it cannot call an order, payment, inventory-write, fulfillment, or message
endpoint.

To include an intentionally chosen public competitor comparison in the same
Commerce MVP run, pass URLs explicitly. No competitor URL is built in or
fetched by default:

```powershell
python scripts/run_phase1_cj_readonly_validation_pack.py `
  --provider cj --query "portable espresso maker" --allow-network `
  --competitor-urls "https://example-store.invalid/products/example" `
  --markdown
```

For Railway or another server runtime, set the same values as encrypted
server-side secrets. Do not add `CJ_EMAIL` or `CJ_API_KEY` to Vercel or any
`VITE_*` configuration. Keep `MARKETOS_SUPPLIER_AUTH_READONLY=0` outside the
short operator validation window.

### Railway/server command

In Railway, add `CJ_EMAIL` and `CJ_API_KEY` through the service **Variables**
screen, then set the non-secret provider and read-only gate there for the
approved validation window. Run the command in a Railway shell or through the
CLI; the values stay in the platform secret store and are never supplied on
the command line:

```bash
railway run python scripts/run_phase1_cj_readonly_validation_pack.py \
  --provider cj --query "portable espresso maker" --allow-network --markdown
```

Turn `MARKETOS_SUPPLIER_AUTH_READONLY` back to `0` once the result is recorded.
Vercel hosts the frontend and must never receive CJ credentials.

## Sanitized artifacts

The following are the only generated artifact types:

- `preflight_report.json` — configuration booleans and redacted status;
- `validation_report.json` — normalized evidence and Commerce MVP result;
- `events.jsonl` — canonical, advisory, no-authority events;
- `evaluation_report.json` — deterministic evaluation metrics;
- `validation_pack_report.json` and optional `.md` — concise operator result.

Before persisting reports the pack strips configured secret values, sensitive
mapping keys, URL query strings/fragments, bearer-shaped values, and raw
provider content. The reports contain normalized observed fields/provenance
only. Generated files remain under ignored `artifacts/` and must not be
committed.

## Comparison against the public/JS baseline

Pass an existing Phase 1 artifact directory to produce an evaluation delta:

```powershell
python scripts/run_phase1_cj_readonly_validation_pack.py `
  --provider cj --query "portable espresso maker" --allow-network `
  --compare-against artifacts/phase1_live_validation/js-rendered-py312 `
  --markdown
```

`validation_pack_report.json` includes deltas for supplier observed fields,
coverage, confidence, price/inventory/shipping/SKU/variant observation rates,
overall confidence, evidence completeness, assumptions, run quality, and
ranking stability when a baseline is available. A missing baseline is a
warning-free optional condition, not a failure.

## Reading a result

An `observed` result only means CJ returned a field that MarketOS normalized
with `observed` provenance. It does not prove availability at checkout,
shipping performance, landed cost, profit, demand, conversion, ROAS, supplier
viability, or launch readiness. Commerce economics only replaces its unit-cost
assumption when the authenticated price field is genuinely observed; all other
unknown fields remain unknown or assumed.

If CJ returns an account, endpoint, or payload error, record the redacted
status and stop rather than retrying aggressively. If the API succeeds but a
genuinely present normalized field is absent, the next action is targeted
payload-mapping hardening with a sanitized fixture — not a new provider.

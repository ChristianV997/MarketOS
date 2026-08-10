# Shopify Read-only Import

## Purpose

This package converts an operator-provided Shopify-like JSON export into
PII-redacted, advisory MarketOS observations. It is a fixture/manual-file
boundary for the [Commerce MVP Vertical Slice](COMMERCE_MVP_VERTICAL_SLICE.md),
not a Shopify API client and not a store-management feature.

## Scope and safety

- Input is a local JSON file with `products`, `collections`, `orders`, and
  `customers`; products may contain variants and orders may contain line items.
- The importer makes no network request, reads no credential, and does not use
  `backend/integrations/shopify_client.py`.
- Customer email and phone values are deterministically hashed; customer names
  are redacted; addresses and raw customer notes are excluded from observations
  and canonical event payloads.
- Every resulting event is `dry_run`, `advisory`, `read_only`,
  `non_authoritative`, and declares that it cannot mutate a store, inventory,
  fulfillment, payment, refund, publication, or customer message.

Historical observed revenue and AOV are export-context summaries only. They do
not prove future demand, profitability, ROAS, supplier viability, conversion,
or launch readiness.

## Canonical events

The importer emits `shopify_import_batch_started`, product/variant/collection/
order/line-item/customer observed events, `shopify_store_context_built`, and
`shopify_import_batch_completed`. JSONL persistence is optional and uses the
existing `JsonlEventRepository`; Supabase is not selected by default.
The gated staging path is documented in
[Supabase Canonical Events Staging](SUPABASE_CANONICAL_EVENTS_STAGING.md).

## Usage

```powershell
python scripts/import_shopify_readonly.py --fixture tests/fixtures/shopify_readonly/shopify_sample.json --json
python scripts/import_shopify_readonly.py --fixture tests/fixtures/shopify_readonly/shopify_sample.json --write-jsonl artifacts/shopify-readonly-events.jsonl --json
python scripts/run_commerce_mvp_slice.py --fixture tests/fixtures/commerce_mvp/public_signals.json --shopify-fixture tests/fixtures/shopify_readonly/shopify_sample.json --query "portable espresso maker" --json
```

The final command enriches Commerce MVP metadata with context notes without
changing candidate selection or turning any packet into a launch recommendation.
When `--write-jsonl` is supplied, Shopify advisory events are appended first,
then Commerce MVP advisory events.

Inspect an explicit JSONL import artifact with
`python scripts/query_canonical_events.py --jsonl <artifact> --shopify-imports --markdown`.

## Router contract and future API

The SaaS router selects Shopify manual-file import as a use-now path for
ecommerce evidence/inventory context. Authenticated read-only Admin API work is
evaluate-next only. Shopify documents that Admin data access requires an
authorized app and least-privilege scopes (for example `read_products`,
`read_orders`, and `read_customers`); access and pricing/rate limits must be
reviewed before any production work. [Shopify API access scopes](https://shopify.dev/docs/api/usage/access-scopes)

Future work must add explicit authenticated scope review, fixtures, data
retention controls, canonical replay checks, and an operator rollback plan. It
must not add write scopes merely to support this importer.

## Rollback

Remove the CLI/package use or stop passing `--shopify-fixture`. No remote state
exists to reverse. Locally generated JSONL files can be retained as an audit
artifact or removed by the operator according to their retention policy.

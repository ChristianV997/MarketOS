# Supabase Canonical Events Staging

## Purpose

This is an operator-invoked staging persistence path for the canonical advisory
events emitted by Commerce MVP and Shopify read-only import. It uses the
existing `EventRepository` abstraction and `canonical_events` table; it does
not make Supabase the MarketOS decision engine or replace JSONL.

## Explicit configuration

All three server-only values are required for an actual write:

```text
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<server-only secret>
MARKETOS_SUPABASE_CANONICAL_EVENTS=1
```

The service-role key must never be placed in browser/Vite configuration or
source control. It bypasses RLS; the current schema enables RLS without
browser-facing policies. This is staging persistence, not the future
Auth/workspace tenancy implementation. [Supabase secure-data guidance](https://supabase.com/docs/guides/database/secure-data)

## CLI examples

```powershell
python scripts/supabase_staging_readiness.py --json
python scripts/run_commerce_mvp_slice.py --fixture tests/fixtures/commerce_mvp/public_signals.json --query "portable espresso maker" --supabase-dry-run --json
python scripts/import_shopify_readonly.py --fixture tests/fixtures/shopify_readonly/shopify_sample.json --supabase-dry-run --json
```

`--supabase-dry-run` validates the canonical event shape, authority metadata,
and Shopify PII redaction locally. It does not create a client or call the
network. `--write-supabase` is an additional explicit request and fails closed
unless all three configuration values are present. `--event-target both`
requires an explicit JSONL path as well; there is no silent fallback after a
Supabase failure.

## Privacy and advisory rules

Shopify events are rejected if their payload contains raw email, phone,
address, first/last name, or name fields. Commerce MVP events must retain
dry-run/advisory/non-authoritative/manual-approval metadata. Shopify events
must additionally retain read-only, PII-redacted, and no-mutation authority
metadata. Every event keeps canonical serialization and replay hashing.

## Schema and operations

Apply [schema.sql](../deploy/supabase/schema.sql) only to an operator-owned
staging project after review. The readiness command is local-only; mocked tests
cover PostgREST-style insert rows without a project. Keep JSONL as the local
default and use an operator-controlled staging environment for any smoke test.

[Canonical Event Read Views](CANONICAL_EVENT_READ_VIEWS.md) can inspect this
same staging table server-side; its read path does not enable or require the
staging write gate.

Rollback means unset `MARKETOS_SUPABASE_CANONICAL_EVENTS` or stop passing the
Supabase flags. No legacy writer is migrated and no remote commerce state is
created by these events.

## Deferred work

- Real staging project smoke test after operator configuration.
- API read views, Supabase Auth, workspace RLS policies, and an event viewer.
- Any approved persistence-default discussion only after replay, retention,
  tenancy, and rollback review.

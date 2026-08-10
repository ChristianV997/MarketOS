# Commerce MVP Vertical Slice

> The Commerce MVP can optionally enrich its advisory packet with a local,
> PII-redacted Shopify-like export. See [Shopify Read-only Import](SHOPIFY_READONLY_IMPORT.md).
> Optional canonical-event staging is documented in
> [Supabase Canonical Events Staging](SUPABASE_CANONICAL_EVENTS_STAGING.md).

## Purpose

This fixture-first workflow turns attributed public/no-auth signal records into
a reviewable commerce test packet:

```text
public signal fixture -> opportunity hypothesis -> assumption-based economics
-> safe creative draft -> landing-page export -> store-draft export
-> vendor plan -> manual approval -> canonical advisory events
```

It is the MVP Island's demoable workflow, not a live commerce pipeline. It
does not call providers, create Shopify products, order inventory, launch ads,
send messages, publish content, or capture payments.

## Packet contents

- Attributed `OpportunityCandidate` records, including confidence, unknowns,
  and explicit non-claims.
- `UnitEconomicsSummary` based on explicit price/cost/shipping/CAC/return
  assumptions—not actual profitability or ROAS.
- `CreativePacket` with cautious buyer/use-case drafts and claim-safety notes.
- `LandingPagePacket` for manual GemPages/PageFly/generic export.
- `StoreDraftPacket` for Shopify, WooCommerce, Medusa, or generic manual
  drafting. Shopify is an output target, never the core architecture.
- Router-derived vendor recommendations and `ManualApprovalPacket` gates.
- Canonical Event stream that can be written to JSONL only on explicit request.

Public signals do not prove demand, sales, customer intent, supplier quality,
margin, conversion, ROAS, profitability, or launch readiness. All copy and
economics must be verified by a human before any external action.

## Run locally

```powershell
python scripts/run_commerce_mvp_slice.py --fixture tests/fixtures/commerce_mvp/public_signals.json --query "portable espresso maker" --json
python scripts/run_commerce_mvp_slice.py --fixture tests/fixtures/commerce_mvp/public_signals.json --query "portable espresso maker" --markdown
python scripts/run_commerce_mvp_slice.py --fixture tests/fixtures/commerce_mvp/public_signals.json --query "portable espresso maker" --write-jsonl artifacts/commerce-mvp-events.jsonl --json
```

The runner also supports a manually gated public Google News RSS path. See
`docs/PUBLIC_COMMERCE_MVP_RUNS.md`; fixture mode remains the default.

## Event behavior

Events use `commerce_mvp_*` types and have dry-run, advisory,
non-authoritative, manual-approval-required, and no launch/spend/publish/store
mutation/payment/fulfillment authority metadata. JSONL remains the explicit
local output option; Supabase is a future, optional EventRepository target.

After generating an explicit JSONL event artifact, inspect it with
`python scripts/query_canonical_events.py --jsonl <artifact> --commerce-runs --json`.

## Manual approval policy

Before creating any external draft or action, an operator must corroborate
evidence, verify landed economics, review claims, select an approved target,
record approval/rollback ownership, and keep all real mutation paths behind
their existing human/live-mode gates.

## Implemented since this doc was first written

- Supabase staging persistence for canonical events
  (`docs/SUPABASE_CANONICAL_EVENTS_STAGING.md`).
- Shopify read-only import packet (`docs/SHOPIFY_READONLY_IMPORT.md`).
- A dashboard read view — the operator dashboard is available at
  `/operator/events`; its public-run control is acknowledgement-gated and
  uses the fixed Google News RSS source
  (`docs/OPERATOR_EVENT_DASHBOARD.md`).
- Real CJ public-page supplier evidence, grounding this slice's unit
  economics in an observed supplier cost when one is found (see
  `docs/CJ_PUBLIC_SUPPLIER_EVIDENCE.md`) — `attempt_supplier_evidence` on
  `/api/commerce-mvp/public-run` and
  `backend.mvp_commerce.public_run.run_commerce_mvp_from_public_rss`.

## Next integrations (not implemented)

1. Automatic CJ product discovery from a query (today: operator-supplied
   candidate URLs are the reliable path; discovery is best-effort/unverified
   — see `docs/CJ_PUBLIC_SUPPLIER_EVIDENCE.md`).
2. Creatify/HeyGen export/import results.
3. PageFly/GemPages export refinement.
4. Upstash-scheduled public signal collection with human review.
5. Authenticated CJ API supplier evidence once `CJ_EMAIL`/`CJ_API_KEY`
   credentials are configured (`backend.validation.suppliers.CJDropshippingClient`
   already implements the client; it just has no credentials yet).

# Commerce Operations Readiness Cycle v1

This is a thin offline composition layer. It connects existing MarketOS
consulting entrypoints into one deterministic readiness cycle. It is not a
live operator, a second orchestrator, a second scoring system, or a
publishing/spend path.

Product Opportunity Synthesis remains the scoring authority. This cycle calls
`evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis`
and does not recopy weights or grades.

## What it composes

1. Marketplace or research evidence (existing fixture importers + `build_report`)
2. Supplier feasibility (same)
3. Consumer-attention (same)
4. Product-opportunity synthesis (existing builder only)
5. Resource & Execution Governor decision (`evaluate_execution_request`)
6. TrustOS and Approval Ledger status (existing APIs, metadata only)
7. Launch and site draft **readiness** (plan-only; packs are not written unless `--output` is set, and even then only the cycle report is written)
8. Client-workspace-safe projection metadata (existing isolation plan; no tenant creation)
9. `next_best_action` plus explicit blockers

## Evidence classes

Every section is labeled with one of:

- `fixture_evidence`
- `plan_only`
- `dry_run`
- `blocked`
- `requires_approval`
- `unavailable`
- `client_safe_projection`
- `not_live_validated`

Fixture input cannot claim `A_live_validated` at the cycle layer. The nested
synthesis grade is whatever the existing synthesis module emits (fixture path
is `C_fixture_or_partial` or lower).

If a governor, TrustOS, approval, launch, site, or workspace surface cannot be
imported or raises, that section is `unavailable`. The cycle never fakes a go.

## Commands

```text
python scripts/run_commerce_operations_cycle.py --json
python scripts/run_commerce_operations_cycle.py --markdown
python scripts/run_commerce_operations_cycle.py --output /tmp/commerce-operations-cycle --json
```

`--json` and `--markdown` are mutually exclusive. Default stdout is JSON.
Nothing is written unless `--output` is supplied. Path traversal and non-JSON
inputs are rejected. Secret-like keys (`api_key`, `token`, …), raw HTML, and
`raw_payload` fail closed with exit `2` and are not echoed.

`--live` is accepted only so it can fail closed as `blocked`. Live commerce
operations are not implemented: no network, provider, ad, publish, order,
payment, or messaging calls.

Default inputs are the same sanitized fixtures used by
`scripts/run_product_opportunity_synthesis.py`.

## Safety

The cycle does not call models or providers, launch ads, publish sites, create
orders or payments, send messages, write to a database, create tenants, or
load credentials. `scripts/run_commerce_cycle.py` and
`backend/execution/loop.py` are not used. SerpApi and DataForSEO are not
combined here into dual-proof.

Rollback is revert of this composition vertical only.

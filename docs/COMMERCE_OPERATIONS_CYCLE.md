# Commerce Operations Readiness Cycle v1

This is a thin offline composition layer. It connects existing MarketOS
consulting entrypoints into one deterministic readiness cycle. It is not a
live operator, a second orchestrator, a second scoring system, or a
publishing/spend path.

Product Opportunity Synthesis remains the scoring and ranking authority. This
cycle calls
`evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis`
and does not recopy weights or grades. Ranking is the existing synthesis
candidate list (`last-wins` identity collapse, sort `(-combined, id)`). The
cycle does not re-rank and does not call `opportunity_scoring`. Ranking
`provenance` is the raw pillar `evidence_mode` string passed through
unchanged — not an `observed`/`derived` translation.

Governor `unit_economics_score` is taken from synthesis
`unit_economics_summary.gross_margin_percent` when present. Missing economics
are fail-closed as `0.0` with `unit_economics_unavailable`. Economics are never
derived from marketplace or attention signals.

Marketplace evidence is not supplier proof. Consumer-attention is not ad
performance or ad authority. Supplier feasibility is not fulfillment or order
proof. Those are named blockers on the ranking projection.

Product validation is a later stage. After synthesis and before launch-draft
readiness, the cycle calls
`evaluation.commerce.product_validation_report.generate` with the three pillar
reports plus the synthesis dict. It does not pass launch or site packs, does
not copy scoring, and projects only compact metadata. `generate()` is called
with truthy blocked stubs for benchmark, readiness, and deployment so the
Phase-1 CJ path builders do not run.

## What it composes

1. Marketplace or research evidence (existing fixture importers + `build_report`)
2. Supplier feasibility (same)
3. Consumer-attention (same)
4. Product-opportunity synthesis (existing builder only; canonical ranking)
5. Ranking projection of the synthesis candidate list (no second scorer)
6. Product validation (`generate`, compact projection only)
7. TrustOS status (`evaluate_action` / combined report, metadata only)
8. Resource & Execution Governor (`evaluate_execution_request`), with the
   existing TrustOS `evaluate_action` result passed through as
   `trustos_decision` (no cycle-local gate)
9. Approval Ledger status (`simulate_action` / `build_approval_ledger` with an
   empty `registry_report`, so this cycle does not call `build_provider_registry`)
10. Launch and site draft **readiness** (plan-only; packs are not written unless `--output` is set, and even then only the cycle report is written)
11. Client-workspace-safe projection metadata (existing isolation plan; no tenant creation)
12. `next_best_action` plus explicit blockers

## Uniform stage schema

Every stage is projected onto the same dict keys (plus stage-specific extras):

- `status`
- `evidence_references`
- `blocking_reasons` (aliased as `blockers` for the existing report shape)
- `next_action`
- `owner_department`
- `required_approval_or_gate`
- `client_visible_projection_state`

Top-level `stages` holds the compact form of marketplace, supplier,
consumer_attention, synthesis, ranking, product_validation, trustos, governor,
approval_ledger, launch_draft_readiness, site_draft_readiness, and
client_workspace. This mapping does not add a second scorer or a second
TrustOS gate.

Governor `ExecutionDecisionRequest.trustos_decision` is the existing
`evaluate_action` decision for the mapped TrustOS action
(`public_beta_launch`, `publish_site`, or `run_provider_readonly_call`).
If TrustOS is unavailable, the cycle passes `blocked` (fail closed) rather
than hardcoding `allow`.

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

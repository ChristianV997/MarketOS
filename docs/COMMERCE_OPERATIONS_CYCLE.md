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
unchanged — not an `observed`/`derived` translation. Ranking labels
(`source_type`, `source_url`, `observed_at`, `field_provenance`,
`supplier_product_id`, `sku`) are pillar pass-through; there is no alias
collapse and no fingerprint. Absent pillar keys are omitted; the cycle
does not invent `observed_at`.

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
python scripts/run_commerce_operations_cycle.py --manifest tests/fixtures/commerce_operations/cli_batch/valid_manifest.json --json
python scripts/run_commerce_operations_cycle.py --manifest path/to/jobs.json --output /tmp/commerce-operations-batch --json
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

## Operator batch input

`--manifest PATH.json` is bounded CLI I/O over the **existing** cycle. It does
not add a second runner, scorer, packet schema, fingerprint, `source_family`,
or alias matcher. Each job is one local triple of the same three report flags.
The cycle still multi-candidate-ranks inside a single triple.

`--manifest` cannot be combined with `--marketplace-trend-report`,
`--supplier-feasibility-report`, or `--consumer-attention-report`. The single
triple remains the default path when `--manifest` is absent.

The manifest is a local JSON object, `.json` only, with no path traversal:

```json
{
  "jobs": [
    {
      "id": "job-alpha",
      "marketplace_trend_report": "path/to/marketplace.json",
      "supplier_feasibility_report": "path/to/supplier.json",
      "consumer_attention_report": "path/to/consumer.json"
    }
  ]
}
```

Hard maximum: 8 jobs. Duplicate job ids fail closed (the whole manifest is
rejected). Missing files, malformed job JSON, secret-like keys, HTML, and
`raw_payload` are classified **per job** as `malformed`, `blocked`,
`unavailable`, or `failed` and do not abort the rest (partial results).
`--live` with a manifest still fail-closes live as `blocked` inside the existing
cycle; no providers are called.

Without `--output`, stdout is the batch summary only. With `--output`, the CLI
writes `batch_summary.json` plus one subdirectory per admitted job using the
existing three filenames (`commerce_operations_cycle_report.json`,
`commerce_operations_cycle_report.md`, `client_safe_projection.json`). No extra
packet type is written.

Per-job summary fields: `id`, `status`, `blockers`, `evidence_class`,
`overall_status` (the last two from existing `to_dict()` when the job is
admitted). Two identical runs are byte-equal for summary and stdout
(`generated_at` is already frozen on the cycle).

Exit codes:

- `0` — every job admitted (the cycle ran; `--live` may still be `blocked`)
- `1` — manifest was valid but at least one job was `malformed`, `blocked`,
  `unavailable`, or `failed` (partial results are still printed / written)
- `2` — manifest path, JSON, schema, secret-like content, traversal, duplicate
  ids, or over-max job count; also the existing single-triple error path

## Safety

The cycle does not call models or providers, launch ads, publish sites, create
orders or payments, send messages, write to a database, create tenants, or
load credentials. `scripts/run_commerce_cycle.py` and
`backend/execution/loop.py` are not used. SerpApi and DataForSEO are not
combined here into dual-proof.

The acceptance suite also rejects mixing marketplace, supplier, and attention
streams or adding a second scorer; treating economics assumptions or missing
economics as observed proof; inventing live evidence modes; authorizing launch
from fixture, partial, or simulated confidence; skipping Governor, TrustOS, or
the client-safe projection after an early blocked stage; and leaking candidate
ids across fixture packs in one process.

Rollback is revert of this composition vertical only.

## QA notes

Adversarial acceptance tests live in `tests/test_commerce_operations_cycle.py` plus
`tests/fixtures/commerce_operations/`. They are mutation locks, not a test-count
exercise. A developer reintroducing any of the following should fail that suite:

- live clients (`urllib` / `httpx` / `requests` / `openai` / `subprocess`) or
  CJ path builders (`build_from_paths`, `build_benchmark_from_paths`,
  `build_readiness`)
- a second scorer (`rank_opportunities`) or a second packet / fingerprint /
  `source_family` identity authority
- remapping `fixture` / `manual_import` / `simulated` / `live_readonly` to
  `observed`, or inventing `observed_at`
- treating marketplace as supplier proof, attention as ads, or supplier as
  fulfillment
- nested malformed candidate records producing fake scores
- `api_key` / `token` / `html` / `raw_payload` on `to_dict` or
  `client_safe_projection.json`
- `A_live_validated` or `live_go: true` at the cycle layer
- Approval Ledger live approval, registry load, or auto-allow
- dropping named terms/privacy blockers (`policies_present`,
  `privacy_terms_approved`, `lawyer_review`) on the dry-run path

The on-disk packet is the existing `to_dict()` plus
`client_safe_projection.json`. There is no second schema. Two identical calls
must be byte-equal. License is not a cycle-native field; unverified terms stay
blocked through TrustOS `policies_present` / `lawyer_review` and site-draft
`privacy_terms_approved`.

## Operator release packet

The cycle `to_dict()` **is** the operator/release packet. Operator-facing
mapping (manifest, provenance, freshness, limitations, client-safe export,
rollback) lives in `docs/commerce_operations/OPERATOR_RELEASE_PACKET.md`.
Do not invent a second packet schema or builder.

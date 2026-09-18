# Operator release packet spec (commerce-operations cycle)

Audience: Windows operators and humans who need a **decision/release artifact**
from the existing commerce-operations cycle. This page documents the keys that
already exist on `to_dict()` and `client_safe_projection`. It does not define a
new packet type.

## No-second-schema proof

| Claim | Existing source of truth |
| --- | --- |
| Packet | `CommerceOperationsCycleReport.to_dict()` in `evaluation/commerce/commerce_operations_cycle.py` |
| Builder | `build_commerce_operations_cycle(...)` only |
| Client-safe file | `to_dict()["client_safe_projection"]` (see `_client_safe_projection`) |
| CLI stdout | that same dict as JSON (`sort_keys=True`) or Markdown |
| `--output` files | `commerce_operations_cycle_report.json`, `commerce_operations_cycle_report.md`, `client_safe_projection.json` |
| Ranking / identity | Product Opportunity Synthesis candidate list; stable id is `candidate_id`; last-wins collapse already happens in synthesis |
| Provenance | raw pillar `evidence_mode` copied into ranking `mode` and `provenance` |
| Fingerprint / `source_family` / `rank_opportunities` | **absent** from the cycle and CLI |

There is no `docs/commerce_operations` builder, no cycle-local fingerprint, and
no second score. Contract tests in
`tests/test_commerce_operations_release_packet.py` import the existing cycle
and assert this shape.

CoderOS is a frozen black-box planning/evidence surface. This spec maps
MarketOS fields onto operator-facing release IA (manifest, provenance,
assumptions, freshness, limitations, rollback, client-safe projection). It
does not import CoderOS, clone a CoderOS schema, or treat CoderOS
`evidence-handoff.md` as an executable contract (that file is a title-only
stub on CoderOS main `b980e90b49ea7c0639094f3060ced5aaf772a571`).

## Authority and non-authority

This cycle is **planning output**. It never grants:

- launch / public-beta go-live
- ads or spend
- orders, inventory, or fulfillment
- payments
- site publish / CMS / hosting / domain
- provider mutation or credential use

`confidence_claim` is always `not_live_validated` at the cycle layer, even
when nested synthesis `confidence_grade` is `A_live_validated`.
`governor.live_go` is always `false`. `--live` fail-closes as `blocked`.

TrustOS, the Resource & Execution Governor, and the Approval Ledger appear as
**pass-through metadata**. This cycle does not rerun them as live authorities
and does not invent a cycle-local gate.

Rollback: **revert PR #225 only**. Do not roll back unrelated mainline work.

## Public patterns (information architecture only)

These systems are **not** implemented here. The labels map existing keys so
operators can read the packet the way they read other release artifacts. Do
not copy their payloads into MarketOS.

| Pattern | MarketOS analog (existing keys) |
| --- | --- |
| OpenLineage job / run | `report_version` = `commerce-operations-cycle-v1`; one offline job; `generated_at` = run clock |
| OpenLineage inputs vs outputs | Inputs = three pillar JSON reports. Outputs = the three `--output` files (or stdout). Facets = stage `evidence_class` + `evidence_references` (labeled evidence, **not** proof) |
| MLflow params vs metrics vs artifacts | Params = `cycle_mode`, `live_requested`, pillar `evidence_mode`. Metrics = synthesis scores / ranking `combined_opportunity` (never a go-live). Artifacts = the three `--output` filenames |
| Great Expectations | Named blockers (`blocking_reasons` / top-level `blockers`) are failed expectations. They block a live go; they are **not** live validation of commerce |
| Dagster asset metadata | `stages[*].status` + `stages[*]` / section `evidence_class` = materialization metadata analog |
| Reproducible-build / SLSA-style | Builder identity = this cycle module + CLI. Materials = sanitized pillar JSON. Digest analog = frozen `generated_at` (`offline-deterministic`) plus `json.dumps(..., sort_keys=True)` replay. **Do not add a cycle-local fingerprint**; identity stays `candidate_id` from synthesis |
| Commerce analytics | Marketplace / consumer-attention / funnel proxies are **not** ads, orders, or fulfillment proof (`marketplace_is_not_supplier_proof`, `consumer_attention_is_not_ad_performance`, `supplier_feasibility_is_not_fulfillment_proof`) |

## How to produce the packet (Windows)

From the repo root (PowerShell). Default stdout is JSON. `--json` and
`--markdown` are mutually exclusive.

```powershell
python scripts/run_commerce_operations_cycle.py --json
python scripts/run_commerce_operations_cycle.py --markdown
python scripts/run_commerce_operations_cycle.py --output $env:TEMP\commerce-operations-cycle --json
```

`--output` writes **only**:

1. `commerce_operations_cycle_report.json` — `to_dict()` with `sort_keys`
2. `commerce_operations_cycle_report.md` — the same report as Markdown
3. `client_safe_projection.json` — `to_dict()["client_safe_projection"]`

It never writes launch or site packs (`launch_draft_pack.json`,
`site_draft_pack.json`, or equivalent). Path traversal and non-JSON inputs
are rejected. Secret-like keys, nested secret-like objects/arrays, raw HTML,
and `raw_payload` fail closed with exit `2` and are **not echoed**.

`--live` is accepted only so it can fail closed as `blocked`. Live commerce
operations are not implemented: no network, provider, ad, publish, order,
payment, or messaging calls.

The commerce MVP cockpit and Windows runner consume
`scripts/run_commerce_mvp_slice.py`, **not** this cycle.

## Manifest (operator IA)

Treat the top-level `to_dict()` as the manifest.

| Key | Meaning |
| --- | --- |
| `report_version` | Always `commerce-operations-cycle-v1` |
| `generated_at` | Cycle clock: frozen `offline-deterministic`. Not pillar freshness |
| `cycle_mode` | `dry_run` (default) or `blocked` when `--live` / `live_requested` |
| `overall_status` | `plan_only` (default), `blocked` (live requested), or `unavailable` (synthesis missing and not live-requested) |
| `evidence_class` | Cycle-level class: `not_live_validated` by default, `blocked` when live requested |
| `confidence_claim` | **Always** `not_live_validated` (hard-coded in `to_dict`) |
| `live_requested` | Whether `--live` / `live_requested=True` was passed |
| `live_validated` | Always `false` |
| `read_only` / `network_calls` / `mutated` / `artifacts_written` | Safety flags. Artifact writes require `--output`; the in-memory `to_dict()` still reports `artifacts_written: false` until the CLI mutates the printed copy |
| `safety_summary` | Explicit zeros for ads, publish, orders, payments, messages, DB, tenants, credentials, models, providers |
| `next_best_action` | Single operator action string |
| `blockers` | Deduped named blockers from every composed stage plus workspace leakage/export blocks |
| `evidence_required` | Subset of blockers that name missing/proof/evidence/unavailable |
| `approvals_required` | Subset of blockers that name approval |
| `stages` | Compact uniform view of every stage (see below) |
| `client_safe_projection` | Secret-free projection of **this same dict** |

Required top-level keys (the packet):

`report_version`, `generated_at`, `cycle_mode`, `overall_status`,
`evidence_class`, `confidence_claim`, `live_requested`, `live_validated`,
`marketplace`, `supplier`, `consumer_attention`, `synthesis`, `ranking`,
`product_validation`, `trustos`, `governor`, `approval_ledger`,
`launch_draft_readiness`, `site_draft_readiness`, `client_workspace`,
`client_safe_projection`, `stages`, `blockers`, `evidence_required`,
`approvals_required`, `next_best_action`, `safety_summary`, `read_only`,
`network_calls`, `mutated`, `artifacts_written`.

## Uniform stage schema

Every stage dict (and every `stages[<name>]` compact row) includes:

- `status`
- `evidence_references`
- `blocking_reasons` (full stage dict also aliases `blockers`)
- `next_action`
- `owner_department`
- `required_approval_or_gate`
- `client_visible_projection_state`

`stages` order is fixed: marketplace, supplier, consumer_attention, synthesis,
ranking, product_validation, trustos, governor, approval_ledger,
launch_draft_readiness, site_draft_readiness, client_workspace.

Dagster analog: `status` + `evidence_class` on the full stage dict is
materialization metadata, not a live run.

## Market / consumer / supplier / economics pillars

### Pillar sections (`marketplace`, `supplier`, `consumer_attention`)

| Key | Meaning |
| --- | --- |
| `supplied` | Whether a pillar object was passed in |
| `candidate_count` | `len(candidates)` when the root is a mapping |
| `evidence_mode` | **Raw pass-through** of the pillar report `evidence_mode` (default `fixture_demo` if the report omitted it; `missing` if the pillar was `None`) |
| `status` / `evidence_class` | `fixture_evidence` when mode is not a live mode and candidates exist; `not_live_validated` when mode is `live_readonly` / `public_live` / `authenticated_live`; `unavailable` when missing or empty |
| `live_validated` | Always `false` on supplied pillars |

Marketplace evidence is **not** supplier proof. Consumer-attention is **not**
ad performance or ad authority. Supplier feasibility is **not** fulfillment
or order proof. Those facts are named on ranking as
`PROOF_SEPARATION_BLOCKERS` and copied into top-level `blockers`.

### Economics

Governor `unit_economics_score` is taken from synthesis
`unit_economics_summary.gross_margin_percent` when present (clamped to
`[0.0, 1.0]`). Missing economics fail closed as `0.0` with
`unit_economics_unavailable`. Economics are never derived from marketplace
or attention signals.

Compact economics keys (when present): `target_sell_price`,
`estimated_landed_cost`, `gross_margin_percent`,
`profit_per_order_before_ad_spend`, `break_even_cpa`, `break_even_roas`,
`assumptions`.

## Candidate ranking (no second score)

Ranking is a **projection** of the existing synthesis candidate list.

- Authority: `evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis`
- `re_ranked` is `false`
- `duplicate_collapse` is `last_wins` (synthesis identity collapse, not a
  cycle-local alias registry)
- `sort` is `(-combined_opportunity_score, candidate_id)`
- Stable identity is `candidate_id`. There is no fingerprint field
- Similar titles with distinct ids stay two rows
- `confidence_claim` on ranking is `not_live_validated`; `live_go` is `false`

Each ranking row includes: `rank`, `candidate_id`, `title`,
`combined_opportunity`, `combined_recommendation`, `next_best_action`,
`confidence_grade`, `unit_economics_summary`, `pillars`, `references`,
`blockers`, `reject_reason`.

Each pillar facet on a row:

| Key | Meaning |
| --- | --- |
| `status` | From synthesis `evidence_matrix` (or `supplied` / `missing`) |
| `mode` | Raw pillar/candidate/packet `evidence_mode` (last-wins). `live_readonly` stays `live_readonly`. Never remapped to `observed` |
| `provenance` | **Same string as `mode`** (raw `evidence_mode`) |
| `score` | Matrix score pass-through |
| `source_type`, `source_url`, `observed_at`, `field_provenance` | Copied only if the pillar/candidate/packet actually set them |
| `supplier_product_id`, `sku`, `supplier_sku` | Supplier pass-through only, when present |
| `source_family` | **Not a field.** Do not add it |

`references` are citations from `source_url` and `supplier_product_id` only.

## Provenance

`provenance = raw evidence_mode`. Examples: `fixture`, `fixture_demo`,
`stale`, `live_readonly`, `unavailable`.

Do **not** translate `live_readonly` → `observed`. Do **not** invent
`deterministic` when `observed_at` is absent. Omit absent pass-through keys.

## Freshness

| Clock | Key | Use |
| --- | --- | --- |
| Cycle / replay clock | top-level `generated_at` = `offline-deterministic` | Deterministic serialization; SLSA-style replay analog |
| Pillar freshness | ranking pillar `observed_at` | **Only copied** when the fixture/report set it |

Stale evidence: when a pillar's raw mode is `stale`, ranking adds
`stale_evidence:<pillar>` to the row and to cycle `blockers`.

Absent `observed_at`: omitted from the pillar facet. The cycle clock is not
used as a substitute freshness timestamp.

## Confidence, assumptions, blockers, next action

- Cycle `confidence_claim`: always `not_live_validated`
- Nested synthesis `confidence_grade`: whatever synthesis emitted (fixture
  path is typically `C_fixture_or_partial` or lower). Fixture input cannot
  claim `A_live_validated` **at the cycle layer**
- `live_validated` / `live_go`: false
- Assumptions: economics `assumptions` plus planning-only scores. CPA, CTR,
  budget, and scale figures remain planning assumptions
- Blockers: named strings (`*_missing`, `stale_evidence:*`,
  `trustos_*_hard_block`, `governor_*`, `approval_missing:*`, proof-separation
  names). Great Expectations analog: a failed expectation is a blocker, not
  live commerce proof
- Unavailable reasons: stage `status` / `evidence_class` = `unavailable` with
  a named reason (`*_unavailable`, `*_pillar_missing`,
  `*_candidates_missing`). The cycle never fakes a go
- `next_best_action`: live-requested → keep dry-run; missing pillars → supply
  sanitized evidence; reject recommendation → hold; else review fixture-backed
  synthesis and keep drafts plan-only

## TrustOS / Governor / Approval Ledger (pass-through)

| Section | What the packet shows | What it is not |
| --- | --- | --- |
| `trustos` | `evaluate_action` / combined report metadata: `gates`, `public_launch_decision`, `provider_activation_decision`, `professional_conclusion=false`, `metadata_only=true` | Not a rerun live control plane; not a professional conclusion |
| `governor` | `evaluate_execution_request` simulations; TrustOS decision **passed through**; `simulated_only=true`; `live_go=false`; `workspace_decision_authorizes_live=false` | `workspace_decision` (often `allow` in simulation) is **not** live authorization |
| `approval_ledger` | `simulate_action` / `build_approval_ledger` with empty `registry_report`; `live_approval_granted=false`; `registry_loaded=false` | Not a human-approved live policy |

Typical default: TrustOS public launch / ads / export are `hard_block`;
governor outcomes require approval or are blocked; approval simulations list
`missing_conditions`. Those blockers are **visible on the packet**.

## Vocabulary

| Term | Packet meaning |
| --- | --- |
| `blocked` | Explicit deny (e.g. `--live`, TrustOS hard_block, governor hard/soft/kill). Not a go |
| `unavailable` | Surface missing, empty, or raised; named reason; never a fake go |
| `plan_only` | Offline composition; drafts stay drafts |
| `dry_run` | `cycle_mode` when live was not requested |
| `fixture_evidence` | Sanitized fixture/manual pillar input |
| `client_safe_projection` | Secret-free subset suitable for a client-visible file; still not live proof |
| `not_live_validated` | Cycle confidence claim. Nested `A_live_validated` does **not** promote this |
| `requires_approval` | Approval Ledger / governor still needs a human policy |
| `live_readonly` | Raw evidence_mode from a pillar; **not** remapped to `observed`; **not** live go |

## Client-safe projection keys

`_client_safe_projection` copies a **subset** of the same `to_dict()`:

`report_version`, `generated_at`, `overall_status`, `cycle_mode`,
`evidence_class` (forced `client_safe_projection`), `confidence_claim`
(forced `not_live_validated`), `live_validated` (`false`),
`top_candidate_id`, `overall_recommendation`, `confidence_grade` (nested
synthesis values, still not a go-live), `blockers`, `evidence_required`,
`approvals_required`, `next_best_action`, `launch_authorized` (`false`),
`publishing_authorized` (`false`).

It omits secrets, raw payloads, HTML, credentials, launch/site pack bodies,
and internal formulas. Nested secret-like keys in **inputs** are rejected
before a packet is built (`reject_unsafe_input`); they are not echoed.

`--output` `client_safe_projection.json` is this object, not a second schema.

## Deterministic replay

Two `build_commerce_operations_cycle(...)` calls with the same inputs produce
identical `to_dict()` objects. CLI JSON uses `json.dumps(..., indent=2,
sort_keys=True)`. Frozen `generated_at` (`offline-deterministic`) is the
replay clock. That pair is the digest analog. Do **not** add a fingerprint
field.

Malformed or missing fields fail closed (`ValueError` / CLI exit `2`) without
inventing scores or a live grade.

## Other composed stages (still the same packet)

These are readiness/projection metadata on `to_dict()`, not extra artifacts:

- `product_validation` — `generate()` presentation only; `live_go` false;
  launch/site packs reported `missing` as inputs
- `launch_draft_readiness` / `site_draft_readiness` — plan-only; `packs_written`
  false; Shopify/Medusa payload status stays `draft`; `published` false
- `client_workspace` — isolation plan; `tenant_created` false; no DB writes

## Safety summary keys

`read_only`, `network_calls`, `model_calls`, `provider_calls`, `ads_launched`,
`sites_published`, `orders_created`, `payments_created`, `messages_sent`,
`database_writes`, `tenant_created`, `client_data_present`,
`credentials_loaded`, `artifacts_written`, `live_validated`.

Default in-memory packet: all side-effect flags false.

## Rollback

Revert **PR #225** (`grok/marketos-commerce-operations-composition-v1`) only.
This docs/tests addendum does not introduce a second production surface to
revert separately. Do not revert unrelated `main` commits.

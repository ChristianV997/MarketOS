# Category-mapping evidence (Shopify Product Taxonomy)

## What this is

`services.category_mapping` matches a caller-supplied, free-text product
category (the existing `category` field already accepted by
`services.product_research.audit.run_product_audit`, default `"general"`)
against a pinned, offline snapshot of the
[Shopify Product Taxonomy](https://github.com/Shopify/product-taxonomy),
producing zero or more candidate taxonomy categories with a deterministic
confidence score, for a **human to review**. The evidence status is
`"mapped"` only when one candidate remains, `"ambiguous"` when multiple
plausible candidates remain, and `"unmapped"` when no candidates are found.
An exact name match takes precedence over weaker token-overlap alternatives;
multiple exact matches remain `"ambiguous"`.

## What this is not

- **Not a ranker.** Candidates are not scored against each other's commercial
  merit, and nothing here decides which category is "correct" — it only
  surfaces textual matches. An `"ambiguous"` result is explicitly incomplete,
  not a selected category. `CategoryMappingEvidence.decision_authority` is
  always `"none"`; `human_review_required` is always `True`.
- **Not supplier proof.** No supplier, price, inventory, or fulfillment claim
  is made or implied by a category match.
- **Not live validation.** The match is a deterministic, offline string
  comparison against a static snapshot, never a live query against Shopify or
  any other provider.
- **Not a launch/decision gate.** Nothing in this vertical blocks, approves,
  or authorizes a launch, publish, order, payment, or provider action.
- **Not a full taxonomy mirror.** The bundled snapshot keeps the top
  3 of the upstream taxonomy's 8 hierarchy levels (26 verticals + their next
  two child levels) plus a curated slice of levels 4–5 matching real
  MarketOS candidate fixtures (1,875 of the upstream's 14,606 categories).
  A category string with no match in that partial snapshot is reported
  `"unmapped"`, never guessed at or silently widened.

## How it composes with existing MarketOS authorities

- **`evaluation.commerce.opportunity_synthesis`** remains the sole
  three-pillar (marketplace/supplier/consumer) decision layer. This vertical
  adds no fourth pillar and is not consumed by `opportunity_synthesis` at
  all — it is surfaced only as an additional, optional evidence field on
  `ProductAuditResult`, for a human reviewing that report.
- **`evaluation.trustos.client_workspace_isolation`** remains the sole
  internal-to-client export boundary. This vertical introduces no new export
  path of its own; wherever a `ProductAuditResult` (including its
  `category_mapping_evidence` field) is exported to a client, it goes through
  whatever boundary already governs that export, unmodified by this change.
- **No second category, catalog, scoring, or evidence-register authority is
  introduced.** `services/category_mapping/` is a self-contained leaf
  package under `services/`, matching the existing sibling convention
  (`services/product_research/`, `services/unit_economics/`, etc.).

## Data provenance

See `data/shopify_product_taxonomy/README.md` for the exact pinned tag,
commit SHA, license, and regeneration steps. In summary: tag `v2026-08`,
commit `2e9aa2e9b882383952c63d212add13eb80f46cf9`, license MIT, verified
during developer-time dataset curation against the public open-source Git
repository metadata at that exact commit SHA (an offline public source
retrieval step performed during artifact preparation, completely separate from
MarketOS runtime execution; not a runtime network or provider call, and not
taken from a cached or AI-summarized page render — an unrelated tag,
`v2026-08-patch`, was found during verification to resolve to a different
commit whose `VERSION` file read `2026-11-unstable`, and was deliberately
**not** used for exactly that reason).

## Safety

Offline and read-only throughout. Public source retrieval occurred strictly as a
developer-time artifact curation step from public open-source Git repository
data; MarketOS executes with zero runtime network access, zero provider API
calls, zero credentials read, and zero commerce, publication, ad, or ordering
mutation anywhere in this vertical. Matching failures degrade to
`category_mapping_evidence = None` on the audit result (logged at `debug`
level) rather than aborting `run_product_audit`, matching that function's
existing fail-silent-and-degrade contract for every other optional input.

## Missing-versus-explicit-zero

This vertical has no numeric economics fields of its own (categories are
text, not costs). Its `confidence` score is always a bounded float in
`(0.0, 1.0]` when a candidate exists at all — an unmatched category is
represented by `status="unmapped"` with an **empty** candidate tuple, never
by a `0.0`-confidence candidate, so "no match found" is never conflated with
"a match was found, with zero confidence."

# Product Identity Resolution

Updated: 2026-10-12

Canonical module: `evaluation/commerce/product_identity_resolution.py`

## Purpose

Connect marketplace listings, supplier offers, and consumer-attention observations
to stable, workspace-scoped product candidate keys so research can combine
evidence without merging different products or variants.

This lane is **identity linking only**. It does not score opportunities, authorize
launch/spend, or replace pillar evidence contracts.

## Reused contracts

| Concern | Canonical home |
|---|---|
| Product candidate summary | `evaluation.contracts.ProductCandidate` |
| Supplier offer identity (commerce packet) | `evaluation.commerce.canonical.SupplierOfferIdentity` |
| Marketplace / supplier / attention evidence | existing pillar modules (keyed by `candidate_id` after linking) |
| Client export boundary | `evaluation/trustos/client_workspace_isolation.py` |

Do not treat event IDs, observation IDs, or workspace IDs as product identity.

## Match states

| State | Meaning |
|---|---|
| `exact_match` | Linked by a strong, non-conflicting identifier within one workspace |
| `possible_match` | Name-compatible suggestion for human review; **not** auto-merged |
| `ambiguous` | Multiple distinct roots share a weak signal (e.g. title) |
| `conflict` | Identifiers or variant/brand attributes disagree |
| `unmatched` | No link and no review suggestion |

## Automatic link rules (fail-closed)

Automatic `exact_match` requires **one** of the following, within the same
`workspace_id`, with compatible brand/model/variant attributes:

1. Same normalized GTIN/UPC/EAN (UPC-12 padded to EAN-13)
2. Same ASIN
3. Same brand + MPN (normalized)
4. Same seller SKU **scoped to** `(source_system, seller_id)` — never global
5. Same `(source_kind, source_system, source_record_id)` duplicate observation

`candidate_id_hint` is **never** an exact-match basis. A shared hint with
compatible attributes may emit `possible_match` for review. A shared hint with
conflicting pack size, variant size/color, brand, or model emits `conflict`
(`candidate_id_hint_does_not_override_variant`) and keeps distinct candidate keys.

## Product-versus-variant contract

| Signal | Compatible variants | Conflicting pack/model/brand/variant |
|---|---|---|
| Strong ID (GTIN/ASIN/brand+MPN/scoped SKU/source record) | `exact_match` when attributes compatible | Split clusters → `conflict`, no shared exact key |
| `candidate_id_hint` alone | `possible_match` (review only) | `conflict`, never `exact_match` |
| Name/title alone | `possible_match` / `ambiguous` | `conflict` or separate keys; never `exact_match` |
| Missing identifiers | `unmatched` / name review only | n/a |

Empty variant fields are treated as unknown (compatible), not as zero/default.

## Safety limits

- Seller SKUs are **not** globally unique across sellers or source systems.
- Name-only / similarity-only matches may emit `possible_match` or `ambiguous`;
  they never produce `exact_match`.
- Pack-size / variant conflicts block auto-merge even when brand+MPN or GTIN align.
- Conflicting GTINs/ASINs/brand-MPN pairs never merge.
- Workspaces never share candidate keys.
- Evidence modes are preserved; fixture/manual are never upgraded to live.
- Consumer-attention links (even on GTIN) remain labeled
  `source_kind=consumer_attention` and are not supplier or price proof.
- Product identity is not attention evidence, marketplace price proof, or supplier proof.
- The resolver does not invent GTINs or manufacturer identifiers.
- Results are deterministic and idempotent under input reordering.

## Integration handoff for opportunity synthesis (#483)

Do **not** edit `evaluation/commerce/opportunity_synthesis.py` from this lane.
Consume the tested projection:

```python
from evaluation.commerce.product_identity_resolution import (
    resolve_product_identity,
    to_opportunity_synthesis_handoff,
)

report = resolve_product_identity(observations)
handoff = to_opportunity_synthesis_handoff(report)
# handoff["by_observation_id"][obs_id]["candidate_key" | "match_state" | ...]
# Auto-join only when match_state == "exact_match"
```

Contract version: `product-identity-synthesis-handoff-v1`

- `auto_merge_allowed_states`: `["exact_match"]`
- `never_auto_merge_states`: possible_match, ambiguous, conflict, unmatched
- `candidate_id_hint_is_not_exact_basis`: always true
- Pillar flags keep identity separate from attention / price / supplier proof

## OSS pattern review (search-first)

Evaluated public patterns before implementing:

| Pattern | Fit | Decision |
|---|---|---|
| GTIN-first cascade (retail feeds) | Strong for exact IDs | Adopted conceptually |
| Brand+MPN then review-only fuzzy (product-matcher / Gridscoot-style) | Strong | Adopted; no fuzzy auto-merge |
| `retailerapi/identifier` normalize/detect | Useful shape | Reimplemented minimally in-repo (no new dep) |
| pyJedAI full ER stack | Heavy research dependency | Not installed |

No third-party matching library was added. No upstream code was copied.

## Out of scope

- Opportunity synthesis / scoring changes (handoff only; #483 owns synthesis)
- Provider adapters, API routes, frontend mounts
- Event-ID collision work
- Shared schema redesign
- Live provider calls or credential reads

## Tests

`tests/test_product_identity_resolution.py` — synthetic fixtures only, including
adversarial JSON under `tests/fixtures/product_identity_resolution/`.

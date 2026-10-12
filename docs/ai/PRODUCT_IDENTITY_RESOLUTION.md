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

## Safety limits

- Seller SKUs are **not** globally unique across sellers or source systems.
- Name-only / similarity-only matches may emit `possible_match` or `ambiguous`;
  they never produce `exact_match`.
- Pack-size / variant conflicts block auto-merge even when brand+MPN align.
- Conflicting GTINs/ASINs/brand-MPN pairs never merge.
- Workspaces never share candidate keys.
- Evidence modes are preserved; fixture/manual are never upgraded to live.
- Consumer-attention links (even on GTIN) remain labeled
  `source_kind=consumer_attention` and are not supplier or price proof.
- The resolver does not invent GTINs or manufacturer identifiers.
- Results are deterministic and idempotent under input reordering.

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

- Opportunity synthesis / scoring changes
- Provider adapters, API routes, frontend mounts
- Event-ID collision work
- Shared schema redesign
- Live provider calls or credential reads

## Tests

`tests/test_product_identity_resolution.py` — synthetic fixtures only.
